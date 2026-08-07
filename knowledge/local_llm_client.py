"""LLM client for root-cause/judgment reasoning. Four backends: NVIDIA NIM
(Nemotron), OpenAI, Anthropic (Claude), and a locally-running Ollama server
(free, no auth, ultimate fallback). Each of the first three can be
configured either via .env (deployment-time, static) or via the Settings
page (backend/app/routers/settings.py — runtime, stored in Postgres, no
restart needed); a DB-stored value always wins over the matching .env var
when both are present.

Default behavior is automatic failover — Nemotron, then OpenAI, then
Anthropic are tried in that order among whichever are configured, and any
failure (timeout, auth error, rate limit, bad response) falls through to
the next one, ending with Ollama as the free local backup. LLM_PROVIDER
forces one exclusively ("nemotron" | "openai" | "anthropic" | "ollama")
when that's actually wanted, skipping failover entirely.

Chosen over knowledge/watsonx_client.py (removed) because that client's
fallback path unconditionally labeled synthesized template text as "IBM
watsonx.ai" output — a real fabrication, not just a stale claim. This
client never does that: status honestly reflects whether generation
actually happened (and which backend it came from), never a fabricated one.
"""

import os
import re
import time
from typing import Any, Dict, List, Optional

import httpx

# Providers a Settings-page key can be saved for, in fixed failover
# priority order (nemotron, openai, anthropic — Ollama is env-only, see
# module docstring). Shared by _generate_text's failover loop and
# backend/app/routers/settings.py's provider listing, so the two can never
# drift apart on what "all providers" means.
KEY_PROVIDERS = ("nemotron", "openai", "anthropic")


def mask_api_key(key: Optional[str]) -> Optional[str]:
    """Never return a full key to the frontend — first 4 / last 4 chars is
    enough for a human to recognize which key is saved without it being
    usable if the response leaks (browser devtools, a log, a screenshot)."""
    if not key:
        return None
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}...{key[-4:]}"


class LocalLLMClient:
    def __init__(self):
        # Ollama (local, free, no auth) — .env only, not part of the
        # Settings page's "add your API key" flow, since there's no key.
        self.base_url = os.environ.get("LOCAL_LLM_URL", "http://localhost:11434")
        self.model = os.environ.get("LOCAL_LLM_MODEL", "qwen3:4b")

        self._settings_cache: Dict[str, Any] = {}
        self._health_cache: Dict[str, Dict[str, Any]] = {}
        self._health_cache_ts: Dict[str, float] = {}

    # ------------------------------------------------------------------
    # Runtime settings resolution — DB (Settings page) over .env (deploy-
    # time default) over a hardcoded fallback.
    # ------------------------------------------------------------------

    def _db_settings(self) -> Dict[str, Any]:
        """Postgres-stored provider overrides — asyncpg has no sync query
        path, and this method (like get_api_key/get_model/is_configured
        below it) is called synchronously from deep inside agent code that
        already runs on a live event loop, so it can't itself await a
        query. Push-based instead of pull-based: hydrate_settings_cache()
        is the only writer, called by backend/app/routers/settings.py
        right after every save/delete (and once at startup, main.py's
        lifespan) — so this is always just an in-memory read, never I/O."""
        return self._settings_cache

    def hydrate_settings_cache(self, settings: Dict[str, Any]) -> None:
        """settings is {provider: {"apiKey": ..., "model": ...}}, one
        entry per row currently in llm_provider_settings — see
        backend/app/routers/settings.py's _load_all_provider_settings()."""
        self._settings_cache = settings

    def _cfg(self, provider: str, field: str, env_var: str, default: Optional[str] = None) -> Optional[str]:
        db_val = self._db_settings().get(provider, {}).get(field)
        if db_val:
            return db_val
        return os.environ.get(env_var, default)

    def get_api_key(self, provider: str) -> Optional[str]:
        env_var = {"nemotron": "NEMOTRON_API_KEY", "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}[provider]
        return self._cfg(provider, "apiKey", env_var)

    def get_model(self, provider: str) -> str:
        env_var, default = {
            "nemotron": ("NEMOTRON_MODEL", "nvidia/llama-3.3-nemotron-super-49b-v1"),
            "openai": ("OPENAI_MODEL", "gpt-4o-mini"),
            "anthropic": ("ANTHROPIC_MODEL", "claude-opus-5"),
        }[provider]
        return self._cfg(provider, "model", env_var, default)

    @property
    def nemotron_base_url(self) -> str:
        return os.environ.get("NEMOTRON_BASE_URL", "https://integrate.api.nvidia.com/v1")

    @property
    def provider_override(self) -> str:
        """"" (default/unset) = automatic failover across every configured
        provider in KEY_PROVIDERS order, Ollama last. A specific provider
        name forces that one exclusively, with no fallback — an explicit
        opt-out of failover, not the normal mode."""
        return os.environ.get("LLM_PROVIDER", "").strip().lower()

    def _configured(self, provider: str) -> bool:
        if provider == "ollama":
            return os.environ.get("LOCAL_LLM_ENABLED") == "true"
        return bool(self.get_api_key(provider))

    def is_configured(self) -> bool:
        override = self.provider_override
        if override in ("ollama", *KEY_PROVIDERS):
            return self._configured(override)
        return any(self._configured(p) for p in (*KEY_PROVIDERS, "ollama"))

    # ------------------------------------------------------------------
    # Status / health — one method per provider so the Integrations page
    # and the Settings page can show all of them side by side instead of
    # collapsing to "whichever is primary right now".
    # ------------------------------------------------------------------

    def list_provider_statuses(self) -> List[Dict[str, Any]]:
        """One row per KEY_PROVIDERS entry, for the Settings page — role,
        masked key, live-ish connectivity, current model."""
        return [self.get_provider_status(p) for p in KEY_PROVIDERS]

    def _role_for(self, provider: str) -> str:
        override = self.provider_override
        if override == provider:
            return f"primary (LLM_PROVIDER={provider} forces this one, no fallback)"
        if override and override != provider:
            return f"disabled (LLM_PROVIDER={override} forces a different provider)"
        # Automatic mode: role is this provider's rank among configured ones.
        chain = [p for p in KEY_PROVIDERS if self._configured(p)]
        if provider not in chain:
            return "not configured"
        idx = chain.index(provider)
        if idx == 0:
            return "primary"
        return f"backup #{idx} (used if {', '.join(chain[:idx])} fail{'s' if idx == 1 else ''})"

    def get_provider_status(self, provider: str) -> Dict[str, Any]:
        health = self._health_status(provider)
        return {
            "provider": provider,
            "configured": self._configured(provider),
            "model": self.get_model(provider),
            "masked_key": mask_api_key(self.get_api_key(provider)),
            "role": self._role_for(provider),
            **health,
        }

    def get_nemotron_status(self) -> Dict[str, Any]:
        return self.get_provider_status("nemotron")

    def get_openai_status(self) -> Dict[str, Any]:
        return self.get_provider_status("openai")

    def get_anthropic_status(self) -> Dict[str, Any]:
        return self.get_provider_status("anthropic")

    def get_ollama_status(self) -> Dict[str, Any]:
        chain = [p for p in KEY_PROVIDERS if self._configured(p)]
        if self.provider_override == "ollama":
            role = "primary (LLM_PROVIDER=ollama forces local only)"
        elif self.provider_override in KEY_PROVIDERS:
            role = f"disabled (LLM_PROVIDER={self.provider_override} forces cloud only, no fallback)"
        elif chain:
            role = f"backup #{len(chain)} (used automatically if {', '.join(chain)} all fail)"
        else:
            role = "primary (no cloud provider configured)"
        status = self._ollama_health_status()
        status["role"] = role
        return status

    def get_health_status(self) -> Dict[str, Any]:
        """Live-ish reachability check for whichever backend is actually
        primary right now. Kept for the Integrations page's single-row
        historical display; list_provider_statuses()/get_ollama_status()
        show every backend individually, which is more honest about what
        automatic failover actually does."""
        override = self.provider_override
        if override == "ollama":
            return self._ollama_health_status()
        chain = [p for p in KEY_PROVIDERS if self._configured(p)]
        primary = override if override in KEY_PROVIDERS else (chain[0] if chain else None)
        if primary:
            return self._health_status(primary)
        return self._ollama_health_status()

    def _health_status(self, provider: str) -> Dict[str, Any]:
        if provider == "nemotron":
            return self._nemotron_health_status()
        if provider == "openai":
            return self._openai_health_status()
        if provider == "anthropic":
            return self._anthropic_health_status()
        raise ValueError(f"unknown provider: {provider}")

    def _cached_health(self, provider: str, ttl_seconds: float, check) -> Dict[str, Any]:
        """Shared cache for the three metered cloud APIs — the Integrations
        and Settings pages poll every few seconds, and unlike Ollama's free
        local ping, a live call to each of these costs quota. `check` is a
        zero-arg callable that performs the real reachability probe."""
        now = time.time()
        cached = self._health_cache.get(provider)
        ts = self._health_cache_ts.get(provider, 0.0)
        if cached is not None and (now - ts) < ttl_seconds:
            return cached
        result = check()
        self._health_cache[provider] = result
        self._health_cache_ts[provider] = now
        return result

    def _ollama_health_status(self) -> Dict[str, Any]:
        """Actually pings Ollama rather than trusting the enabled flag
        alone, since a local process (unlike a cloud service) can silently
        be down even when LOCAL_LLM_ENABLED=true. Free and local, so a live
        check on every poll is fine — no caching needed."""
        base = {
            "name": "Local LLM (Ollama)",
            "auth": "None (local HTTP, no auth)",
            "description": f"Live root-cause reasoning generation via a self-hosted Ollama model ({self.model}) — used by the Reasoning stage instead of a managed cloud LLM.",
        }
        if not self._configured("ollama"):
            return {**base, "status": "Not Configured", "connected": False, "host": self.base_url}

        try:
            with httpx.Client(timeout=2.0) as client:
                resp = client.get(f"{self.base_url}/api/tags")
                if resp.status_code != 200:
                    return {**base, "status": f"Ollama returned {resp.status_code}", "connected": False, "host": self.base_url}
                models = [m.get("name") for m in resp.json().get("models", [])]
                if self.model not in models:
                    return {**base, "status": f"Ollama reachable, but '{self.model}' not pulled", "connected": False, "host": self.base_url}
                return {**base, "status": "Connected 🟢", "connected": True, "host": self.base_url}
        except Exception as exc:
            return {**base, "status": f"Unreachable: {exc}", "connected": False, "host": self.base_url}

    def _nemotron_health_status(self) -> Dict[str, Any]:
        base = {
            "name": "NVIDIA NIM (Nemotron)",
            "auth": "Bearer API key",
            "description": f"Cloud root-cause reasoning via NVIDIA NIM ({self.get_model('nemotron')}).",
            "host": self.nemotron_base_url,
        }
        api_key = self.get_api_key("nemotron")
        if not api_key:
            return {**base, "status": "Not Configured", "connected": False}

        def check() -> Dict[str, Any]:
            try:
                with httpx.Client(timeout=5.0) as client:
                    resp = client.get(f"{self.nemotron_base_url}/models", headers={"Authorization": f"Bearer {api_key}"})
                    if resp.status_code == 200:
                        return {"status": "Connected 🟢", "connected": True}
                    if resp.status_code == 401:
                        return {"status": "Unauthorized — check the saved API key", "connected": False}
                    return {"status": f"NVIDIA NIM returned {resp.status_code}", "connected": False}
            except Exception as exc:
                return {"status": f"Unreachable: {exc}", "connected": False}

        return {**base, **self._cached_health("nemotron", 60, check)}

    def _openai_health_status(self) -> Dict[str, Any]:
        base = {
            "name": "OpenAI",
            "auth": "Bearer API key",
            "description": f"Cloud root-cause reasoning via OpenAI ({self.get_model('openai')}).",
            "host": "https://api.openai.com/v1",
        }
        api_key = self.get_api_key("openai")
        if not api_key:
            return {**base, "status": "Not Configured", "connected": False}

        def check() -> Dict[str, Any]:
            try:
                with httpx.Client(timeout=5.0) as client:
                    resp = client.get("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {api_key}"})
                    if resp.status_code == 200:
                        return {"status": "Connected 🟢", "connected": True}
                    if resp.status_code == 401:
                        return {"status": "Unauthorized — check the saved API key", "connected": False}
                    return {"status": f"OpenAI returned {resp.status_code}", "connected": False}
            except Exception as exc:
                return {"status": f"Unreachable: {exc}", "connected": False}

        return {**base, **self._cached_health("openai", 60, check)}

    def _anthropic_health_status(self) -> Dict[str, Any]:
        base = {
            "name": "Anthropic (Claude)",
            "auth": "x-api-key",
            "description": f"Cloud root-cause reasoning via Anthropic ({self.get_model('anthropic')}).",
            "host": "https://api.anthropic.com/v1",
        }
        api_key = self.get_api_key("anthropic")
        if not api_key:
            return {**base, "status": "Not Configured", "connected": False}

        def check() -> Dict[str, Any]:
            try:
                with httpx.Client(timeout=5.0) as client:
                    resp = client.get(
                        "https://api.anthropic.com/v1/models",
                        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                    )
                    if resp.status_code == 200:
                        return {"status": "Connected 🟢", "connected": True}
                    if resp.status_code == 401:
                        return {"status": "Unauthorized — check the saved API key", "connected": False}
                    return {"status": f"Anthropic returned {resp.status_code}", "connected": False}
            except Exception as exc:
                return {"status": f"Unreachable: {exc}", "connected": False}

        return {**base, **self._cached_health("anthropic", 60, check)}

    # ------------------------------------------------------------------
    # Generation — provider-specific HTTP calls, routed through a shared
    # failover-aware dispatcher so every prompt-building method below stays
    # provider-agnostic.
    # ------------------------------------------------------------------

    def _generate_text(self, prompt: str, max_tokens: int, temperature: float) -> Dict[str, Any]:
        """Routes the request and normalizes the result to
        {"status", "model_used", "text", "error"?} so callers below don't
        need to know which provider actually served it. Default mode is
        automatic failover across KEY_PROVIDERS in order, then Ollama: any
        failure (timeout, auth error, rate limit, bad response — anything
        that isn't "live_llm_generated") falls through to the next
        configured one. LLM_PROVIDER can force one exclusively, skipping
        failover entirely."""
        override = self.provider_override
        if override in ("ollama", *KEY_PROVIDERS):
            if not self._configured(override):
                return {"status": "not_configured", "model_used": None, "text": None}
            return self._dispatch(override, prompt, max_tokens, temperature)

        last_result: Dict[str, Any] = {"status": "not_configured", "model_used": None, "text": None}
        tried: List[str] = []
        for provider in KEY_PROVIDERS:
            if not self._configured(provider):
                continue
            result = self._dispatch(provider, prompt, max_tokens, temperature)
            if result["status"] == "live_llm_generated":
                if tried:
                    result["fell_back_from"] = tried
                return result
            tried.append(provider)
            last_result = result

        if self._configured("ollama"):
            fallback = self._dispatch("ollama", prompt, max_tokens, temperature)
            if fallback["status"] == "live_llm_generated":
                if tried:
                    fallback["fell_back_from"] = tried
                    fallback["primary_error"] = last_result.get("error")
                return fallback
            tried.append("ollama")
            last_result = fallback

        # Nothing succeeded (or nothing was configured at all) — report the
        # last real failure, not a fabricated success.
        return last_result

    def _dispatch(self, provider: str, prompt: str, max_tokens: int, temperature: float) -> Dict[str, Any]:
        if provider == "ollama":
            return self._generate_text_ollama(prompt, max_tokens, temperature)
        if provider == "nemotron":
            return self._generate_text_nemotron(prompt, max_tokens, temperature)
        if provider == "openai":
            return self._generate_text_openai(prompt, max_tokens, temperature)
        if provider == "anthropic":
            return self._generate_text_anthropic(prompt, max_tokens)
        raise ValueError(f"unknown provider: {provider}")

    def _generate_text_ollama(self, prompt: str, max_tokens: int, temperature: float) -> Dict[str, Any]:
        try:
            with httpx.Client(timeout=90.0) as client:
                resp = client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        # qwen3 reasons into a separate "thinking" phase
                        # before it writes anything into "response", and
                        # thinking length varies run to run (~600-1500+
                        # tokens observed). max_tokens caps thinking+response
                        # combined, so it must clear the thinking phase with
                        # room to spare or Ollama hits done_reason "length"
                        # with an empty response - verified against this
                        # exact model.
                        "options": {"num_predict": max_tokens, "temperature": temperature},
                    },
                )
                if resp.status_code != 200:
                    return {"status": "error", "model_used": None, "text": None, "error": f"Ollama returned {resp.status_code}: {resp.text[:300]}"}
                text = (resp.json().get("response") or "").strip()
                if not text:
                    return {"status": "error", "model_used": None, "text": None, "error": "empty response"}
                return {"status": "live_llm_generated", "model_used": f"{self.model} (local via Ollama)", "text": text}
        except Exception as exc:
            return {"status": "error", "model_used": None, "text": None, "error": str(exc)}

    def _generate_text_nemotron(self, prompt: str, max_tokens: int, temperature: float) -> Dict[str, Any]:
        api_key = self.get_api_key("nemotron")
        model = self.get_model("nemotron")
        try:
            # Longer than a single-explanation prompt needs: comparing
            # multiple candidates measurably takes the model longer to think
            # through than explaining a single already-decided cause (~47s
            # observed for a 2-option comparison vs ~15s for one).
            with httpx.Client(timeout=90.0) as client:
                resp = client.post(
                    f"{self.nemotron_base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                        "stream": False,
                    },
                )
                if resp.status_code != 200:
                    return {"status": "error", "model_used": None, "text": None, "error": f"NVIDIA NIM returned {resp.status_code}: {resp.text[:300]}"}
                data = resp.json()
                choices = data.get("choices") or []
                text = (choices[0].get("message", {}).get("content") if choices else "") or ""
                text = text.strip()
                if not text:
                    return {"status": "error", "model_used": None, "text": None, "error": "empty response"}
                return {"status": "live_llm_generated", "model_used": f"{model} (NVIDIA NIM)", "text": text}
        except Exception as exc:
            return {"status": "error", "model_used": None, "text": None, "error": str(exc)}

    def _generate_text_openai(self, prompt: str, max_tokens: int, temperature: float) -> Dict[str, Any]:
        api_key = self.get_api_key("openai")
        model = self.get_model("openai")
        try:
            with httpx.Client(timeout=90.0) as client:
                resp = client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                    },
                )
                if resp.status_code != 200:
                    return {"status": "error", "model_used": None, "text": None, "error": f"OpenAI returned {resp.status_code}: {resp.text[:300]}"}
                data = resp.json()
                choices = data.get("choices") or []
                text = (choices[0].get("message", {}).get("content") if choices else "") or ""
                text = text.strip()
                if not text:
                    return {"status": "error", "model_used": None, "text": None, "error": "empty response"}
                return {"status": "live_llm_generated", "model_used": f"{model} (OpenAI)", "text": text}
        except Exception as exc:
            return {"status": "error", "model_used": None, "text": None, "error": str(exc)}

    def _generate_text_anthropic(self, prompt: str, max_tokens: int) -> Dict[str, Any]:
        # No temperature/top_p/top_k: Claude Opus 5 (and the 4.6+ family)
        # reject those with a 400 outright — sampling is steered by
        # prompting instead. Thinking is left unset deliberately (defaults
        # to adaptive on Opus 5), and we read the first *text* content
        # block rather than content[0], since a thinking block can precede
        # it in the response.
        api_key = self.get_api_key("anthropic")
        model = self.get_model("anthropic")
        try:
            with httpx.Client(timeout=90.0) as client:
                resp = client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": model,
                        "max_tokens": max_tokens,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                )
                if resp.status_code != 200:
                    return {"status": "error", "model_used": None, "text": None, "error": f"Anthropic returned {resp.status_code}: {resp.text[:300]}"}
                data = resp.json()
                if data.get("stop_reason") == "refusal":
                    return {"status": "error", "model_used": None, "text": None, "error": "Anthropic safety classifiers declined this request"}
                text = ""
                for block in data.get("content", []):
                    if block.get("type") == "text":
                        text = (block.get("text") or "").strip()
                        break
                if not text:
                    return {"status": "error", "model_used": None, "text": None, "error": "empty response"}
                return {"status": "live_llm_generated", "model_used": f"{model} (Anthropic)", "text": text}
        except Exception as exc:
            return {"status": "error", "model_used": None, "text": None, "error": str(exc)}

    # ------------------------------------------------------------------
    # Prompt-building methods used by the agents — unchanged surface, just
    # now backed by the multi-provider dispatcher above.
    # ------------------------------------------------------------------

    def generate_root_cause_explanation(
        self,
        defect_type: str,
        primary_cause: str,
        confidence: float,
        evidence_paths: List[str],
        part_number: str = "MH-8820",
    ) -> Dict[str, Any]:
        if not self.is_configured():
            return {"status": "not_configured", "model_used": None, "explanation": None}

        prompt = (
            "You are an Industrial AI Quality Engineer. Analyze this factory defect telemetry:\n"
            f"- Part Number: {part_number}\n"
            f"- Defect Anomaly: {defect_type}\n"
            f"- Identified Primary Cause: {primary_cause}\n"
            f"- Bayesian Causal Confidence: {confidence:.2f}\n"
            f"- Evidence Chain: {' -> '.join(evidence_paths)}\n\n"
            "Respond with ONLY a concise 2-sentence engineering root-cause summary "
            "and recommended containment strategy. No preamble, no reasoning trace."
        )

        result = self._generate_text(prompt, max_tokens=2000, temperature=0.3)
        if result["status"] != "live_llm_generated":
            out = {"status": result["status"], "model_used": result.get("model_used"), "explanation": None}
            if "error" in result:
                out["error"] = result["error"]
            return out
        return {"status": "live_llm_generated", "model_used": result["model_used"], "explanation": result["text"]}

    def _pick_and_justify(self, role: str, task: str, options_text: str) -> Dict[str, Any]:
        """Shared call path for agents that need the model to choose among
        real, already-computed candidates and justify the choice — never to
        invent the candidates or their numbers itself. Response is
        constrained to a strict PICK/REASON format so the caller can
        validate the pick against its own candidate list before trusting it
        (an unparseable or out-of-list pick must never silently drive an
        automated action)."""
        if not self.is_configured():
            return {"status": "not_configured", "model_used": None, "pick": None, "justification": None}

        prompt = (
            f"You are {role}.\n{task}\n\n{options_text}\n\n"
            "Pick the single best option above. Respond in EXACTLY this format, nothing else:\n"
            "PICK: <option id, copied exactly as shown above>\n"
            "REASON: <one sentence engineering justification>"
        )

        # 2000 max_tokens / generous timeout for the same reason as
        # generate_root_cause_explanation — comparing multiple candidates
        # measurably takes longer than explaining one already-decided cause
        # (~47s observed for a 2-option Ollama comparison vs ~15s for one).
        result = self._generate_text(prompt, max_tokens=2000, temperature=0.2)
        if result["status"] != "live_llm_generated":
            out = {"status": result["status"], "model_used": result.get("model_used"), "pick": None, "justification": None}
            if "error" in result:
                out["error"] = result["error"]
            return out

        text = result["text"]
        pick_match = re.search(r"PICK:\s*(\S+)", text)
        reason_match = re.search(r"REASON:\s*(.+)", text, re.DOTALL)
        if not pick_match:
            return {"status": "error", "model_used": None, "pick": None, "justification": None, "error": "could not parse PICK from model response"}
        return {
            "status": "live_llm_generated",
            "model_used": result["model_used"],
            "pick": pick_match.group(1).strip().rstrip(".,"),
            "justification": reason_match.group(1).strip() if reason_match else text,
        }

    def generate_substitution_reasoning(
        self, source_part_number: str, candidates: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Judges which approved substitute part is the best pick for a
        given incident, from the real candidates the Substitution Agent's
        knowledge-graph query already found (agents/substitution_agent.py)
        — the model never invents parts, only weighs the ones on offer."""
        if not candidates:
            return {"status": "no_candidates", "model_used": None, "pick": None, "justification": None}

        options_text = "\n".join(
            f"- {c['target_part_number']} ({c['name']}): stock={c['in_stock_quantity']} units, "
            f"cost_delta_usd={c['cost_delta_usd']}, quality_risk_score={c['quality_risk_score']}, "
            f"approval_status={c['approval_status']}"
            for c in candidates
        )
        return self._pick_and_justify(
            role="an Industrial AI Supply Chain Engineer",
            task=(
                f"A production incident needs a substitute for part {source_part_number}. "
                "Candidate substitutes (from the approved supplier/ERP catalog):"
            ),
            options_text=options_text,
        )

    def generate_policy_answer(self, question: str, context_chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Grounded Q&A over the governance policy documents
        (knowledge/policy_docs_qa.py supplies the already-retrieved
        chunks — this method never searches or invents context itself,
        only synthesizes an answer from what it's given). Powers the Novus
        Studio Copilot tab's policy questions."""
        if not self.is_configured():
            return {"status": "not_configured", "model_used": None, "answer": None}
        if not context_chunks:
            return {"status": "no_context", "model_used": None, "answer": None}

        context_text = "\n\n".join(
            f"[{c['doc']} — {c['heading']}]\n{c['text']}" for c in context_chunks
        )
        prompt = (
            "You are the ADOS Governance & Autonomy Copilot, answering a plant "
            "director's question inside the Novus Studio operational dashboard.\n\n"
            "Answer ONLY using the policy context below. If the context does not "
            "contain the answer, say so plainly rather than guessing. Cite which "
            "document backs your answer inline as PLAIN TEXT, e.g. (see "
            "08_Governance_Autonomy_Policy.md) — never as a markdown link "
            "(no [text](url) syntax); this reply is shown as raw text, not rendered. "
            "Be concise: 2-4 sentences, no preamble.\n\n"
            f"POLICY CONTEXT:\n{context_text}\n\n"
            f"QUESTION: {question}\n\nANSWER:"
        )

        result = self._generate_text(prompt, max_tokens=500, temperature=0.2)
        if result["status"] != "live_llm_generated":
            out = {"status": result["status"], "model_used": result.get("model_used"), "answer": None}
            if "error" in result:
                out["error"] = result["error"]
            return out
        return {"status": "live_llm_generated", "model_used": result["model_used"], "answer": result["text"]}

    def generate_impact_simulation_reasoning(self, options: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Judges which candidate recovery option is the best pick from the
        real, already cost/downtime/risk-scored options the Impact
        Simulation Agent computed (agents/impact_simulation_agent.py) — the
        model never invents cost or downtime figures, only weighs the
        precomputed ones against each other."""
        if not options:
            return {"status": "no_options", "model_used": None, "pick": None, "justification": None}

        options_text = "\n".join(
            f"- {o['option_id']} ({o['name']}): cost=${o['estimated_cost_usd']}, "
            f"downtime={o['downtime_minutes']}min, quality_risk_score={o['quality_risk_score']}, "
            f"composite_score={o['overall_score']}"
            for o in options
        )
        return self._pick_and_justify(
            role="an Industrial AI Operations Risk Analyst",
            task="Evaluate these candidate recovery options for a production line incident:",
            options_text=options_text,
        )


local_llm_client = LocalLLMClient()

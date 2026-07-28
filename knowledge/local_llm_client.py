"""Local LLM client — root-cause reasoning generation via a locally-running
Ollama server. Chosen over knowledge/watsonx_client.py (removed) because
that client's fallback path unconditionally labeled synthesized template
text as "IBM watsonx.ai" output — a real fabrication, not just a stale
claim. This client never does that: status honestly reflects whether
generation actually happened, and the model_used string always names the
real local model, never an IBM product it didn't call.
"""

import os
from typing import Any, Dict, List

import httpx


class LocalLLMClient:
    def __init__(self):
        self.base_url = os.environ.get("LOCAL_LLM_URL", "http://localhost:11434")
        self.model = os.environ.get("LOCAL_LLM_MODEL", "qwen3:4b")

    def is_configured(self) -> bool:
        return os.environ.get("LOCAL_LLM_ENABLED") == "true"

    def get_health_status(self) -> Dict[str, Any]:
        """Live reachability check for the Integrations page — unlike the
        other connectors' env-var-only status, this actually pings Ollama,
        since a local process (unlike a cloud service) can silently be
        down even when LOCAL_LLM_ENABLED=true."""
        if not self.is_configured():
            return {"status": "Not Configured", "connected": False, "host": self.base_url}

        try:
            with httpx.Client(timeout=2.0) as client:
                resp = client.get(f"{self.base_url}/api/tags")
                if resp.status_code != 200:
                    return {
                        "status": f"Ollama returned {resp.status_code}",
                        "connected": False,
                        "host": self.base_url,
                    }
                models = [m.get("name") for m in resp.json().get("models", [])]
                if self.model not in models:
                    return {
                        "status": f"Ollama reachable, but '{self.model}' not pulled",
                        "connected": False,
                        "host": self.base_url,
                    }
                return {"status": "Connected 🟢", "connected": True, "host": self.base_url}
        except Exception as exc:
            return {"status": f"Unreachable: {exc}", "connected": False, "host": self.base_url}

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

        try:
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        # qwen3 reasons into a separate "thinking" phase
                        # before it writes anything into "response", and
                        # thinking length varies run to run (~600-1500+
                        # tokens observed for this prompt shape at default
                        # temperature). num_predict caps thinking+response
                        # combined, so it must clear the thinking phase
                        # with room to spare or Ollama hits done_reason
                        # "length" with an empty response - verified
                        # against this exact model. Lower temperature
                        # keeps the thinking trace shorter and more
                        # consistent, both for latency and reliability.
                        "options": {"num_predict": 2000, "temperature": 0.3},
                    },
                )
                if resp.status_code != 200:
                    return {
                        "status": "error",
                        "model_used": None,
                        "explanation": None,
                        "error": f"Ollama returned {resp.status_code}: {resp.text[:300]}",
                    }
                text = (resp.json().get("response") or "").strip()
                if not text:
                    return {"status": "error", "model_used": None, "explanation": None, "error": "empty response"}
                return {
                    "status": "live_llm_generated",
                    "model_used": f"{self.model} (local via Ollama)",
                    "explanation": text,
                }
        except Exception as exc:
            return {"status": "error", "model_used": None, "explanation": None, "error": str(exc)}


local_llm_client = LocalLLMClient()

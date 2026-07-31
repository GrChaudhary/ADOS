"""
LLM provider settings — self-service replacement for hand-editing .env for
NEMOTRON_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY (knowledge/local_llm_client.py).
One shared key per provider for the whole deployment (not per-user),
admin-managed, stored in Cloudant so it survives restarts and takes effect
immediately (no server restart, no redeploy).

Endpoints:
    GET    /settings/llm-providers                → status for all 4 backends (masked keys)
    PUT    /settings/llm-providers/{provider}      → save/replace a key + optional model (admin)
    DELETE /settings/llm-providers/{provider}      → clear a saved key, revert to .env (admin)
    POST   /settings/llm-providers/{provider}/test → real generation call, not just a ping (admin)
"""

from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from knowledge.cloudant_client import cloudant_db
from knowledge.local_llm_client import KEY_PROVIDERS, local_llm_client
from ..auth import get_current_user
from ..rbac import Role, require_role

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(get_current_user)])


class SaveProviderKeyRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    api_key: str = Field(..., min_length=1, alias="apiKey")
    model: Optional[str] = None


class ProviderTestResponse(BaseModel):
    success: bool
    message: str
    model_used: Optional[str] = None
    latency_ms: Optional[float] = None


def _validate_provider(provider: str) -> None:
    if provider not in KEY_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown provider '{provider}'. Must be one of: {', '.join(KEY_PROVIDERS)}.",
        )


@router.get("/llm-providers")
async def list_llm_providers():
    """Status for every LLM backend, including the env-only Ollama backup.
    Keys are always masked (see knowledge/local_llm_client.py's
    mask_api_key) — the full key is never sent back to the browser once
    saved, only on the write that set it."""
    return {
        "providers": local_llm_client.list_provider_statuses(),
        "ollama": local_llm_client.get_ollama_status(),
    }


@router.put("/llm-providers/{provider}", dependencies=[Depends(require_role(Role.ADMIN))])
async def save_llm_provider(provider: str, body: SaveProviderKeyRequest):
    _validate_provider(provider)
    if not cloudant_db.is_configured():
        raise HTTPException(
            status_code=503,
            detail="Cloudant not configured — saved keys wouldn't survive a restart. Set CLOUDANT_URL/CLOUDANT_API_KEY first, or set the key directly in .env.",
        )
    fields = {"apiKey": body.api_key}
    if body.model:
        fields["model"] = body.model
    cloudant_db.save_llm_provider_setting(provider, fields)
    local_llm_client.refresh_settings_cache()
    return local_llm_client.get_provider_status(provider)


@router.delete("/llm-providers/{provider}", dependencies=[Depends(require_role(Role.ADMIN))])
async def delete_llm_provider(provider: str):
    _validate_provider(provider)
    cloudant_db.delete_llm_provider_setting(provider)
    local_llm_client.refresh_settings_cache()
    return local_llm_client.get_provider_status(provider)


@router.post("/llm-providers/{provider}/test", dependencies=[Depends(require_role(Role.ADMIN))], response_model=ProviderTestResponse)
async def test_llm_provider(provider: str):
    """Runs a real, minimal generation call against this provider — not
    just a reachability ping. A key can list /models fine and still 403 or
    404 on the actual completions endpoint (wrong entitlement, wrong model
    name for this account) — that gap is exactly what a "test" button
    needs to catch, so it has to actually generate, not just connect."""
    _validate_provider(provider)
    if not local_llm_client._configured(provider):
        return ProviderTestResponse(success=False, message="No API key saved for this provider yet.")

    started = time.time()
    result = local_llm_client._dispatch(provider, "Reply with the single word: OK", max_tokens=20, temperature=0.0)
    latency_ms = round((time.time() - started) * 1000, 1)

    if result["status"] == "live_llm_generated":
        return ProviderTestResponse(
            success=True,
            message=f"Real generation succeeded: \"{result['text'][:80]}\"",
            model_used=result.get("model_used"),
            latency_ms=latency_ms,
        )
    return ProviderTestResponse(
        success=False,
        message=result.get("error") or f"Provider returned status '{result['status']}'.",
        latency_ms=latency_ms,
    )

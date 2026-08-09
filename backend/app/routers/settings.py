"""
LLM provider settings — self-service replacement for hand-editing .env for
NEMOTRON_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY (knowledge/local_llm_client.py).
One shared key per provider for the whole deployment (not per-user),
admin-managed, stored in Postgres (db/models/llm_provider_setting.py) so
it survives restarts and takes effect immediately (no server restart, no
redeploy) — see knowledge/local_llm_client.py's hydrate_settings_cache()
for how a write here becomes visible to the (synchronous) generation
code path.

Endpoints:
    GET    /settings/llm-providers                → status for all 4 backends (masked keys)
    PUT    /settings/llm-providers/{provider}      → save/replace a key + optional model (admin)
    DELETE /settings/llm-providers/{provider}      → clear a saved key, revert to .env (admin)
    POST   /settings/llm-providers/{provider}/test → real generation call, not just a ping (admin)
"""

from __future__ import annotations

import time
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.llm_provider_setting import LLMProviderSettingRow
from db.session import get_db_session
from knowledge.local_llm_client import KEY_PROVIDERS, local_llm_client
from ..auth import get_current_user
from ..rbac import Role, require_role

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(get_current_user)])


async def load_all_provider_settings(session: AsyncSession) -> Dict[str, Dict[str, Any]]:
    """Shapes every persisted row into the {provider: {"apiKey":...,
    "model":..., "thinkingEnabled":...}} dict knowledge/local_llm_client.py's _cfg() expects —
    called after every save/delete below, and once at startup
    (backend/app/main.py's lifespan)."""
    rows = (await session.execute(select(LLMProviderSettingRow))).scalars().all()
    result: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        fields: Dict[str, Any] = {"apiKey": row.api_key}
        if row.model:
            fields["model"] = row.model
        if row.thinking_enabled is not None:
            fields["thinkingEnabled"] = row.thinking_enabled
        result[row.provider] = fields
    return result


class SaveProviderKeyRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    api_key: str = Field(..., min_length=1, alias="apiKey")
    model: Optional[str] = None


class ToggleThinkingRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    thinking_enabled: bool = Field(..., alias="thinkingEnabled")


class ProviderTestResponse(BaseModel):
    success: bool
    message: str
    model_used: Optional[str] = None
    latency_ms: Optional[float] = None


class SetPrimaryProviderRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    provider: str = Field(..., alias="provider")


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
    info = local_llm_client.active_provider_info
    return {
        "providers": local_llm_client.list_provider_statuses(),
        "ollama": local_llm_client.get_ollama_status(),
        "activeProvider": info["active_provider"],
        "activeProviderSource": info["active_provider_source"],
    }


@router.put("/active-provider", dependencies=[Depends(require_role(Role.ADMIN))])
@router.put("/llm-providers/active", dependencies=[Depends(require_role(Role.ADMIN))])
async def set_active_provider(body: SetPrimaryProviderRequest, session: AsyncSession = Depends(get_db_session)):
    target = body.provider.strip().lower()
    valid_targets = {"auto", "ollama", *KEY_PROVIDERS}
    if target not in valid_targets:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown active provider '{target}'. Must be one of: {', '.join(sorted(valid_targets))}.",
        )
    row = await session.get(LLMProviderSettingRow, "__active_provider__")
    if row is None:
        session.add(LLMProviderSettingRow(provider="__active_provider__", api_key="", model=target))
    else:
        row.model = target
    await session.flush()
    local_llm_client.hydrate_settings_cache(await load_all_provider_settings(session))
    info = local_llm_client.active_provider_info
    return {"activeProvider": info["active_provider"], "activeProviderSource": info["active_provider_source"]}



@router.put("/llm-providers/ollama/thinking", dependencies=[Depends(require_role(Role.ADMIN))])
async def toggle_ollama_thinking(body: ToggleThinkingRequest, session: AsyncSession = Depends(get_db_session)):
    row = await session.get(LLMProviderSettingRow, "ollama")
    if row is None:
        session.add(LLMProviderSettingRow(provider="ollama", api_key="", model=None, thinking_enabled=body.thinking_enabled))
    else:
        row.thinking_enabled = body.thinking_enabled
    await session.flush()
    local_llm_client.hydrate_settings_cache(await load_all_provider_settings(session))
    return local_llm_client.get_ollama_status()


@router.put("/llm-providers/{provider}", dependencies=[Depends(require_role(Role.ADMIN))])
async def save_llm_provider(provider: str, body: SaveProviderKeyRequest, session: AsyncSession = Depends(get_db_session)):
    _validate_provider(provider)
    row = await session.get(LLMProviderSettingRow, provider)
    if row is None:
        session.add(LLMProviderSettingRow(provider=provider, api_key=body.api_key, model=body.model))
    else:
        row.api_key = body.api_key
        if body.model:
            row.model = body.model
    await session.flush()
    local_llm_client.hydrate_settings_cache(await load_all_provider_settings(session))
    return local_llm_client.get_provider_status(provider)


@router.delete("/llm-providers/{provider}", dependencies=[Depends(require_role(Role.ADMIN))])
async def delete_llm_provider(provider: str, session: AsyncSession = Depends(get_db_session)):
    _validate_provider(provider)
    row = await session.get(LLMProviderSettingRow, provider)
    if row is not None:
        await session.delete(row)
        await session.flush()
    local_llm_client.hydrate_settings_cache(await load_all_provider_settings(session))
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

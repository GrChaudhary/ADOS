"""
ORM model for backend/app/routers/settings.py's LLM provider settings —
one row per provider (knowledge/local_llm_client.py's KEY_PROVIDERS:
nemotron, openai, anthropic), not a single JSONB blob, since every
existing read/write already addresses one provider at a time
(get_api_key/get_model, save/delete a single provider's key).
"""

from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class LLMProviderSettingRow(Base):
    __tablename__ = "llm_provider_settings"

    provider: Mapped[str] = mapped_column(primary_key=True)
    api_key: Mapped[str]
    model: Mapped[Optional[str]]
    thinking_enabled: Mapped[Optional[bool]] = mapped_column(default=False)

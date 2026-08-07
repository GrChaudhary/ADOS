"""
ORM model for backend/app/routers/agents_registry.py's custom agent
registry — see that router for the read/write logic this backs. Only
custom (non-built-in) agents are ever stored here: the 8 built-ins stay a
static Python list (BUILTIN_AGENTS) as before. is_built_in isn't a
column — every row here is, by construction, a custom agent, so it's
always False and reconstructed as a constant rather than stored.
"""

from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base


class CustomAgentRow(Base):
    __tablename__ = "custom_agents"

    id: Mapped[str] = mapped_column(primary_key=True)
    label: Mapped[str]
    icon: Mapped[str]
    color: Mapped[str]
    description: Mapped[str]
    model: Mapped[str]
    input_schema: Mapped[str]
    output_schema: Mapped[str]
    memory_rag: Mapped[bool]
    target_tier: Mapped[str]
    stage: Mapped[str]
    instructions: Mapped[str]
    created_at: Mapped[str]

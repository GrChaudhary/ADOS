"""Novus Studio Copilot — grounded Q&A over the governance policy documents
(documentation/08-12, knowledge/policy_docs_qa.py). Replaces the frontend's
previous one-line generic fallback for governance questions with an answer
actually retrieved from those documents, honestly labeled per
knowledge/local_llm_client.py's status convention (never a fabricated
"live" answer)."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from knowledge.policy_docs_qa import answer_question

from ..auth import get_current_user

router = APIRouter(prefix="/copilot", tags=["copilot"], dependencies=[Depends(get_current_user)])


class CopilotAskRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    question: str


@router.post("/ask")
def copilot_ask(body: CopilotAskRequest):
    return answer_question(body.question)

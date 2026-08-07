"""Live IBM Watson NLU + TTS endpoints. Thin pass-throughs to
knowledge/nlu_client.py and knowledge/tts_client.py — no simulated
fallback output; an unconfigured or failing service returns a 502 with the
real error, matching the honesty convention used for the ServiceNow
connector (integrations/connectors/servicenow.py).
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict

from knowledge.nlu_client import nlu_client
from knowledge.tts_client import tts_client

from ..auth import get_current_user

# Previously the only router with no auth dependency at all - closed now
# that every other endpoint requires a real login (backend/app/rbac.py).
router = APIRouter(prefix="/ai", tags=["ai-services"], dependencies=[Depends(get_current_user)])


class NLUAnalyzeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    text: str


class TTSSynthesizeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    text: str
    voice: Optional[str] = None


@router.get("/nlu/status")
def nlu_status() -> Dict[str, Any]:
    return {"configured": nlu_client.is_configured()}


@router.post("/nlu/analyze")
def nlu_analyze(body: NLUAnalyzeRequest) -> Dict[str, Any]:
    result = nlu_client.analyze_text(body.text)
    if result.get("status") != "live":
        raise HTTPException(status_code=502, detail=result.get("error", "NLU request failed"))
    return result


@router.get("/tts/status")
def tts_status() -> Dict[str, Any]:
    return {"configured": tts_client.is_configured()}


@router.post("/tts/synthesize")
def tts_synthesize(body: TTSSynthesizeRequest) -> Response:
    result = tts_client.synthesize(body.text, voice=body.voice)
    if result.get("status") != "live":
        raise HTTPException(status_code=502, detail=result.get("error", "TTS request failed"))
    return Response(content=result["audio_bytes"], media_type=result["content_type"])

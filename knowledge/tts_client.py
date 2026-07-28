"""IBM Watson Text to Speech client — live speech synthesis, authenticated
with IBM Cloud IAM OAuth 2.0 (knowledge/ibm_iam.py). Returns raw audio
bytes on success; an explicit error on failure, never synthesized silence
or placeholder audio.
"""

import os
from typing import Any, Dict, Optional

import httpx

from backend.app.config import settings

from .ibm_iam import IAMTokenCache

_DEFAULT_VOICE = "en-US_AllisonV3Voice"


class TTSClient:
    def __init__(self):
        self.api_key = os.environ.get("TTS_API_KEY") or settings.tts_api_key
        self.url = (os.environ.get("TTS_URL") or settings.tts_url).rstrip("/")
        self._iam = IAMTokenCache(self.api_key)

    def is_configured(self) -> bool:
        # See NLUClient.is_configured() — same os.environ-literal gate so
        # the pipeline's opt-in TTS briefing call stays inert in tests.
        if "TTS_API_KEY" not in os.environ or "TTS_URL" not in os.environ:
            return False
        key = os.environ.get("TTS_API_KEY") or settings.tts_api_key
        url = os.environ.get("TTS_URL") or settings.tts_url
        return bool(key and url)

    def synthesize(
        self, text: str, voice: Optional[str] = None, accept: str = "audio/mp3"
    ) -> Dict[str, Any]:
        if not self.is_configured():
            return {"status": "not_configured", "error": "TTS_API_KEY/TTS_URL not set"}

        token = self._iam.get_token()
        if not token:
            return {"status": "auth_failed", "error": "Could not obtain IAM bearer token"}

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(
                    f"{self.url}/v1/synthesize?voice={voice or _DEFAULT_VOICE}",
                    json={"text": text},
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                        "Accept": accept,
                    },
                )
                if resp.status_code == 200:
                    return {"status": "live", "audio_bytes": resp.content, "content_type": accept}
                return {"status": "error", "error": f"TTS API returned {resp.status_code}: {resp.text[:300]}"}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}


tts_client = TTSClient()

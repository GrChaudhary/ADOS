"""IBM Watson Natural Language Understanding client — live keyword, entity,
sentiment, and category extraction, authenticated with IBM Cloud IAM OAuth
2.0 (knowledge/ibm_iam.py). No fallback/synthesized results: when the
service isn't configured or the call fails, callers get an explicit error,
never fabricated analysis.
"""

import os
from typing import Any, Dict, Optional

import httpx

from backend.app.config import settings

from .ibm_iam import IAMTokenCache

_API_VERSION = "2022-04-07"
_DEFAULT_FEATURES: Dict[str, Any] = {
    "keywords": {"limit": 10},
    "entities": {"limit": 10},
    "sentiment": {},
    "categories": {"limit": 5},
}


class NLUClient:
    def __init__(self):
        self.api_key = os.environ.get("NLU_API_KEY") or settings.nlu_api_key
        self.url = (os.environ.get("NLU_URL") or settings.nlu_url).rstrip("/")
        self._iam = IAMTokenCache(self.api_key)

    def is_configured(self) -> bool:
        # Requires the literal env var, not just settings parsed from the
        # .env file on disk — matches knowledge/cloudant_client.py's
        # is_configured() convention, so pipeline calls stay off in the
        # pytest suite unless a test explicitly opts in via monkeypatch.
        if "NLU_API_KEY" not in os.environ or "NLU_URL" not in os.environ:
            return False
        key = os.environ.get("NLU_API_KEY") or settings.nlu_api_key
        url = os.environ.get("NLU_URL") or settings.nlu_url
        return bool(key and url)

    def analyze_text(self, text: str, features: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.is_configured():
            return {"status": "not_configured", "error": "NLU_API_KEY/NLU_URL not set"}

        token = self._iam.get_token()
        if not token:
            return {"status": "auth_failed", "error": "Could not obtain IAM bearer token"}

        payload = {"text": text, "features": features or _DEFAULT_FEATURES}
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(
                    f"{self.url}/v1/analyze?version={_API_VERSION}",
                    json=payload,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                )
                if resp.status_code == 200:
                    return {"status": "live", **resp.json()}
                return {"status": "error", "error": f"NLU API returned {resp.status_code}: {resp.text[:300]}"}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}


nlu_client = NLUClient()

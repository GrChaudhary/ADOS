"""Shared IBM Cloud IAM OAuth 2.0 API-key-to-bearer-token exchange, used by
the NLU and TTS clients (each service accepts the same IAM bearer token
pattern).
"""

import time
from typing import Optional

import httpx

_IAM_URL = "https://iam.cloud.ibm.com/identity/token"


class IAMTokenCache:
    """Caches a bearer token for one API key until shortly before it expires."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._access_token: Optional[str] = None
        self._expires_at: float = 0.0

    def get_token(self) -> Optional[str]:
        if not self.api_key:
            return None

        now = time.time()
        if self._access_token and now < self._expires_at - 60:
            return self._access_token

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    _IAM_URL,
                    data={
                        "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                        "apikey": self.api_key,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    self._access_token = data.get("access_token")
                    self._expires_at = now + data.get("expires_in", 3600)
                    return self._access_token
        except Exception:
            pass

        return None

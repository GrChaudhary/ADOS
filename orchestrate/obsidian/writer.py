"""
Asynchronous, non-blocking, SHA-256 deduplicated note writer for Obsidian Vault.
Supports atomic local disk replacement and optional Obsidian Local REST API HTTPS push.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from typing import Dict, Optional
import httpx


class ObsidianVaultWriter:
    """Atomic, deduplicated vault note writer with local disk & optional REST API sync."""

    def __init__(self, target_dir: Optional[Path | str] = None, rest_api_url: Optional[str] = None, rest_api_token: Optional[str] = None):
        if target_dir:
            self.target_dir = Path(target_dir).resolve()
        else:
            root_dir = Path(__file__).resolve().parent.parent.parent
            self.target_dir = (root_dir / "ADOS_OBSIDIAN" / "Platform_Graph").resolve()

        self.rest_api_url = rest_api_url or os.getenv("OBSIDIAN_REST_API_URL")
        self.rest_api_token = rest_api_token or os.getenv("OBSIDIAN_REST_API_TOKEN")

        # In-memory SHA-256 cache to eliminate redundant disk/network I/O
        self._hash_cache: Dict[str, str] = {}
        self._lock = asyncio.Lock()

    def get_content_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    async def write_note(self, rel_path: str | Path, content: str) -> bool:
        """Writes a note to disk and/or REST API if content has changed. Returns True if written."""
        rel_str = str(rel_path)
        content_hash = self.get_content_hash(content)

        async with self._lock:
            if self._hash_cache.get(rel_str) == content_hash:
                return False  # Deduplicated — no write needed

            # 1. Atomic disk write
            dest_path = self.target_dir / rel_path
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            temp_path = dest_path.with_suffix(dest_path.suffix + ".tmp")
            temp_path.write_text(content, encoding="utf-8")
            os.replace(temp_path, dest_path)

            self._hash_cache[rel_str] = content_hash

            # 2. Optional Obsidian Local REST API Push
            if self.rest_api_url:
                asyncio.create_task(self._push_to_rest_api(rel_str, content))

            return True

    async def _push_to_rest_api(self, rel_path: str, content: str) -> None:
        """Pushes note content over HTTPS to Obsidian Local REST API plugin."""
        if not self.rest_api_url:
            return
        headers = {"Content-Type": "text/markdown"}
        if self.rest_api_token:
            headers["Authorization"] = f"Bearer {self.rest_api_token}"

        url = f"{self.rest_api_url.rstrip('/')}/vault/{rel_path}"
        try:
            async with httpx.AsyncClient(verify=False, timeout=3.0) as client:
                await client.put(url, content=content.encode("utf-8"), headers=headers)
        except Exception:
            pass  # Non-blocking graceful fallback

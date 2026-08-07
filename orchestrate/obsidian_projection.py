"""
Obsidian Architecture Graph & Live Projection Facade — orchestration-platform-vision.md §9.

Generates an on-demand and event-driven bidirectional markdown projection inside the ADOS_OBSIDIAN/ vault.
Delegates to the new `orchestrate.obsidian` package engine (renderer, writer, listener, reconciler).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional

from orchestrate.obsidian.reconciler import ObsidianReconciler
from orchestrate.obsidian.writer import ObsidianVaultWriter


class ObsidianGraphGenerator:
    """On-demand Obsidian Vault architecture note generator."""

    def __init__(self, target_dir: Optional[Path | str] = None):
        self.writer = ObsidianVaultWriter(target_dir=target_dir)
        self.reconciler = ObsidianReconciler(writer=self.writer)

    def generate(self) -> Dict[str, Any]:
        """Generates all markdown notes synchronously for backward compatibility."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # Running inside an active event loop (e.g. FastAPI)
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(lambda: asyncio.run(self.reconciler.reconcile_full_vault())).result()
        else:
            return asyncio.run(self.reconciler.reconcile_full_vault())


def generate_obsidian_projection(target_dir: Optional[Path | str] = None) -> Dict[str, Any]:
    """Helper function to run the projection generator on demand."""
    generator = ObsidianGraphGenerator(target_dir)
    return generator.generate()

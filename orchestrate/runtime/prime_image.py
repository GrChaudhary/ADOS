"""
Builds the ADOS Prime Agent runtime image.

The image needs source from two repositories that must NOT be merged:

    ../prime-agent                              the runtime (Node + Python kernel shim)
    ADOS/infrastructure/prime-runtime/ados_skill  the ADOS capability bridge

Docker cannot COPY from outside its build context, so this stages a minimal
context containing exactly those two trees and nothing else. Staging is the
answer rather than "just build from the ADOS repo root" because that would drag
the entire ADOS source — connectors, credentials handling, the database layer —
into an image whose whole purpose is to hold none of it.

What lands in the context, and nothing more:

    package.json, package-lock.json, tsconfig*, biome.json   build inputs
    packages/                                                the runtime itself
    prime-agent-runtime/                                     the kernel shim
    ados_skill/                                              the ADOS bridge

Explicitly excluded: the ADOS repo, .env files, .git histories, node_modules
(rebuilt in-image so the lockfile is authoritative).
"""

import asyncio
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger("ados.runtime.prime_image")

IMAGE_TAG = "ados-prime-runtime:0.7.1"

_ADOS_ROOT = Path(__file__).resolve().parents[2]
_DOCKERFILE = _ADOS_ROOT / "infrastructure" / "prime-runtime" / "Dockerfile"
_ADOS_SKILL = _ADOS_ROOT / "infrastructure" / "prime-runtime" / "ados_skill"

# Sibling checkout, matching how the repositories sit on disk today. Override
# with an explicit path if that ever stops being true.
DEFAULT_PRIME_SOURCE = _ADOS_ROOT.parent / "prime-agent"

# Copied verbatim into the staged context. Deliberately a allow-list: an
# exclude-list would silently start shipping whatever the upstream repo adds.
_PRIME_INCLUDES = (
    "package.json",
    "package-lock.json",
    "tsconfig.base.json",
    "tsconfig.json",
    "biome.json",
    "packages",
    "prime-agent-runtime",
)

_IGNORE = shutil.ignore_patterns("node_modules", ".git", "dist", "__pycache__", "*.pyc", ".env*")


def prime_source_dir(explicit: Optional[Path] = None) -> Path:
    src = explicit or DEFAULT_PRIME_SOURCE
    if not (src / "packages" / "coding-agent").is_dir():
        raise FileNotFoundError(
            f"Prime Agent source not found at {src}. Pass an explicit path — the image "
            "is built from source because the published npm versions diverge from "
            "prime-agent's own (0.7.1 is not on the registry)."
        )
    return src


def stage_build_context(dest: Path, prime_src: Path) -> Path:
    """Assembles the two-repo context under `dest`."""
    for name in _PRIME_INCLUDES:
        source = prime_src / name
        if not source.exists():
            raise FileNotFoundError(f"expected {source} in the Prime Agent source tree")
        target = dest / name
        if source.is_dir():
            shutil.copytree(source, target, ignore=_IGNORE, symlinks=True)
        else:
            shutil.copy2(source, target)

    shutil.copytree(_ADOS_SKILL, dest / "ados_skill", ignore=_IGNORE)
    return dest


async def build_image(
    *, prime_src: Optional[Path] = None, tag: str = IMAGE_TAG, timeout_seconds: float = 1800.0
) -> Tuple[bool, str]:
    """Builds the runtime image. Returns (ok, combined output tail)."""
    src = prime_source_dir(prime_src)

    with tempfile.TemporaryDirectory(prefix="ados-prime-ctx-") as tmp:
        context = stage_build_context(Path(tmp), src)
        logger.info("Staged Prime Agent build context", extra={"context": str(context), "tag": tag})

        proc = await asyncio.create_subprocess_exec(
            "docker", "build", "-f", str(_DOCKERFILE), "-t", tag, str(context),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return False, f"docker build timed out after {timeout_seconds}s"

    output = stdout.decode(errors="replace")
    return proc.returncode == 0, output[-6000:]


async def image_exists(tag: str = IMAGE_TAG) -> bool:
    proc = await asyncio.create_subprocess_exec(
        "docker", "images", "-q", tag, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    stdout, _ = await proc.communicate()
    return bool(stdout.strip())


if __name__ == "__main__":  # manual build: python -m orchestrate.runtime.prime_image
    logging.basicConfig(level=logging.INFO)
    ok, out = asyncio.run(build_image())
    print(out)
    print("BUILD OK" if ok else "BUILD FAILED")
    raise SystemExit(0 if ok else 1)

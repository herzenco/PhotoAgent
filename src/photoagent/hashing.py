"""File hashing module (MD5 + perceptual).

Provides MD5 content hashing for exact-duplicate detection and
perceptual hashing for near-duplicate / visually-similar detection.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_HASH_CHUNK_SIZE = 8192  # 8 KB read buffer


# ---------------------------------------------------------------------------
# Optional dependency imports
# ---------------------------------------------------------------------------

try:
    from PIL import Image
    import imagehash
except ImportError:
    Image = None  # type: ignore[assignment,misc]
    imagehash = None  # type: ignore[assignment]
    logger.warning(
        "Pillow or imagehash not installed — perceptual hashing unavailable"
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _compute_md5(file_path: Path) -> str | None:
    """Compute MD5 hex digest of file contents, reading in chunks."""
    try:
        md5 = hashlib.md5()
        with open(file_path, "rb") as fh:
            while True:
                chunk = fh.read(_HASH_CHUNK_SIZE)
                if not chunk:
                    break
                md5.update(chunk)
        return md5.hexdigest()
    except (OSError, IOError) as exc:
        logger.debug("Failed to compute MD5 for %s: %s", file_path, exc)
        return None


def _compute_phash(file_path: Path) -> str | None:
    """Compute perceptual hash (pHash) using imagehash + Pillow."""
    if Image is None or imagehash is None:
        return None
    try:
        with Image.open(file_path) as img:
            phash = imagehash.phash(img)
        return str(phash)
    except Exception as exc:
        logger.debug(
            "Failed to compute perceptual hash for %s: %s", file_path, exc
        )
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_hashes(file_path: Path) -> dict[str, Any]:
    """Compute file hashes for duplicate detection.

    Returns a dict with keys:

        ``file_md5``         — hex MD5 digest of file contents (or ``None``)
        ``perceptual_hash``  — pHash hex string (or ``None``)

    This function never raises.
    """
    return {
        "file_md5": _compute_md5(file_path),
        "perceptual_hash": _compute_phash(file_path),
    }

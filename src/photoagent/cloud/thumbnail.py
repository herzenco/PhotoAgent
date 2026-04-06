"""Thumbnail generation for cloud vision analysis."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageOps

# File extensions that are unsupported (RAW formats)
_RAW_EXTENSIONS: frozenset[str] = frozenset({
    ".raw", ".cr2", ".cr3", ".nef", ".arw",
    ".raf", ".dng", ".orf", ".rw2",
})

# File extensions that are supported for thumbnailing
_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({
    ".jpg", ".jpeg", ".png", ".gif", ".webp",
    ".heic", ".heif", ".tiff", ".tif", ".bmp",
})


def make_thumbnail(
    image_path: Path,
    max_size: int = 256,
    quality: int = 65,
) -> tuple[bytes, dict[str, int]] | tuple[None, None]:
    """Create a JPEG thumbnail from an image file.

    Parameters
    ----------
    image_path:
        Path to the source image.
    max_size:
        Maximum dimension (width or height) of the thumbnail in pixels.
    quality:
        JPEG quality (1-100).

    Returns
    -------
    A tuple of (jpeg_bytes, info_dict) on success, or (None, None) if
    the file is unsupported or an error occurs. info_dict contains:
    original_width, original_height, thumb_width, thumb_height, thumb_byte_size.
    """
    # Skip macOS resource forks (safety net if already in catalog)
    if image_path.name.startswith("._"):
        return None, None

    ext = Path(image_path).suffix.lower()

    if ext in _RAW_EXTENSIONS or ext not in _SUPPORTED_EXTENSIONS:
        return None, None

    try:
        with Image.open(image_path) as img:
            # Fix rotation from EXIF before resizing
            img = ImageOps.exif_transpose(img)

            original_width, original_height = img.size

            # Convert to RGB if needed (handles RGBA, P, CMYK, LA, etc.)
            if img.mode not in ("RGB",):
                img = img.convert("RGB")

            # Resize in-place, preserving aspect ratio
            img.thumbnail((max_size, max_size), Image.LANCZOS)

            thumb_width, thumb_height = img.size

            # Save to bytes buffer
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            jpeg_bytes = buf.getvalue()

            info = {
                "original_width": original_width,
                "original_height": original_height,
                "thumb_width": thumb_width,
                "thumb_height": thumb_height,
                "thumb_byte_size": len(jpeg_bytes),
            }

            return jpeg_bytes, info

    except Exception:
        return None, None

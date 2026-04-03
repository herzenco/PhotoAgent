"""Tests for photoagent.cloud.thumbnail.make_thumbnail."""

from __future__ import annotations

import io
import struct
from pathlib import Path

import pytest
from PIL import Image

from photoagent.cloud.thumbnail import make_thumbnail


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

REQUIRED_INFO_KEYS = {
    "original_width",
    "original_height",
    "thumb_width",
    "thumb_height",
    "thumb_byte_size",
}


def _save_image(
    path: Path,
    size: tuple[int, int] = (100, 100),
    mode: str = "RGB",
    fmt: str = "JPEG",
    color: str | tuple = "red",
    **kwargs,
) -> Path:
    """Helper to create and save a test image."""
    img = Image.new(mode, size, color=color)
    img.save(str(path), format=fmt, **kwargs)
    return path


def _jpeg_bytes_valid(data: bytes) -> bool:
    """Return True if *data* starts with the JPEG SOI marker FF D8."""
    return len(data) >= 2 and data[0] == 0xFF and data[1] == 0xD8


def _open_jpeg_bytes(data: bytes) -> Image.Image:
    """Open a JPEG from raw bytes."""
    return Image.open(io.BytesIO(data))


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def img_dir(tmp_path: Path) -> Path:
    """Return a temporary directory for test images."""
    return tmp_path


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


class TestMakeThumbnail:
    """Unit tests for make_thumbnail."""

    def test_thumbnail_basic_jpeg(self, img_dir: Path) -> None:
        """A 1000x800 JPEG produces a valid thumbnail with correct info keys."""
        path = img_dir / "big.jpg"
        _save_image(path, size=(1000, 800), fmt="JPEG", quality=85)

        result = make_thumbnail(path)
        assert result != (None, None), "Expected (bytes, dict), got (None, None)"

        jpeg_bytes, info = result
        assert isinstance(jpeg_bytes, bytes)
        assert isinstance(info, dict)

        # Valid JPEG marker
        assert _jpeg_bytes_valid(jpeg_bytes), "Thumbnail bytes must start with FF D8"

        # All required keys present
        assert REQUIRED_INFO_KEYS == set(info.keys())

        # Thumbnail dimensions within bounds
        thumb = _open_jpeg_bytes(jpeg_bytes)
        assert thumb.size[0] <= 256
        assert thumb.size[1] <= 256
        assert info["thumb_width"] == thumb.size[0]
        assert info["thumb_height"] == thumb.size[1]

        # Original dimensions recorded
        assert info["original_width"] == 1000
        assert info["original_height"] == 800

        # Byte size matches
        assert info["thumb_byte_size"] == len(jpeg_bytes)

    def test_thumbnail_preserves_aspect_ratio(self, img_dir: Path) -> None:
        """A 1000x500 image should produce a ~256x128 thumbnail (2:1 ratio)."""
        path = img_dir / "wide.jpg"
        _save_image(path, size=(1000, 500), fmt="JPEG", quality=85)

        jpeg_bytes, info = make_thumbnail(path)
        assert jpeg_bytes is not None

        tw, th = info["thumb_width"], info["thumb_height"]
        # The longer dimension should be exactly max_size (256)
        assert tw == 256
        # Aspect ratio preserved: 1000/500 == 2.0, so 256/th ~= 2.0
        original_ratio = 1000 / 500
        thumb_ratio = tw / th
        assert abs(original_ratio - thumb_ratio) < 0.05, (
            f"Aspect ratio not preserved: original={original_ratio:.2f}, "
            f"thumb={thumb_ratio:.2f}"
        )

    def test_thumbnail_rgba_conversion(self, img_dir: Path) -> None:
        """An RGBA PNG should produce a valid RGB JPEG thumbnail."""
        path = img_dir / "rgba.png"
        img = Image.new("RGBA", (400, 400), color=(255, 0, 0, 128))
        img.save(str(path), format="PNG")

        jpeg_bytes, info = make_thumbnail(path)
        assert jpeg_bytes is not None
        assert _jpeg_bytes_valid(jpeg_bytes)

        thumb = _open_jpeg_bytes(jpeg_bytes)
        assert thumb.mode == "RGB", "Thumbnail should be RGB, not RGBA"

    def test_thumbnail_exif_rotation(self, img_dir: Path) -> None:
        """An image with EXIF orientation=6 (90 CW) should have swapped dims.

        We create a 400x200 JPEG (landscape), set EXIF orientation to 6
        (rotate 90 CW), so after correction it should appear as 200x400
        (portrait). The thumbnail should reflect the corrected orientation.
        """
        path = img_dir / "rotated.jpg"
        img = Image.new("RGB", (400, 200), color="green")

        # Build EXIF with orientation tag = 6 using piexif if available,
        # otherwise use Pillow's Exif API.
        try:
            import piexif

            exif_dict = {"0th": {piexif.ImageIFD.Orientation: 6}}
            exif_bytes = piexif.dump(exif_dict)
            img.save(str(path), "JPEG", exif=exif_bytes, quality=90)
        except ImportError:
            # Fallback: use Pillow Exif
            from PIL.ExifTags import Base as ExifBase

            exif = img.getexif()
            exif[ExifBase.Orientation] = 6
            img.save(str(path), "JPEG", exif=exif.tobytes(), quality=90)

        jpeg_bytes, info = make_thumbnail(path)
        assert jpeg_bytes is not None

        # After 90 CW rotation correction, original should be 200x400
        assert info["original_width"] == 200, (
            f"Expected corrected width=200, got {info['original_width']}"
        )
        assert info["original_height"] == 400, (
            f"Expected corrected height=400, got {info['original_height']}"
        )

        # Thumbnail should be portrait
        assert info["thumb_height"] > info["thumb_width"]

    def test_thumbnail_unsupported_raw(self, img_dir: Path) -> None:
        """A .cr2 file should return (None, None)."""
        path = img_dir / "photo.cr2"
        path.write_bytes(b"\x00" * 128)

        result_bytes, result_info = make_thumbnail(path)
        assert result_bytes is None
        assert result_info is None

    def test_thumbnail_unsupported_nef(self, img_dir: Path) -> None:
        """A .nef file should return (None, None)."""
        path = img_dir / "photo.nef"
        path.write_bytes(b"\x00" * 128)

        result_bytes, result_info = make_thumbnail(path)
        assert result_bytes is None
        assert result_info is None

    def test_thumbnail_corrupt_file(self, img_dir: Path) -> None:
        """A .jpg with garbage bytes should return (None, None)."""
        path = img_dir / "garbage.jpg"
        path.write_bytes(b"NOT_A_JPEG_AT_ALL" * 20)

        result_bytes, result_info = make_thumbnail(path)
        assert result_bytes is None
        assert result_info is None

    def test_thumbnail_nonexistent(self, img_dir: Path) -> None:
        """A nonexistent path should return (None, None)."""
        path = img_dir / "does_not_exist.jpg"
        assert not path.exists()

        result_bytes, result_info = make_thumbnail(path)
        assert result_bytes is None
        assert result_info is None

    def test_thumbnail_small_image(self, img_dir: Path) -> None:
        """A 50x50 image should not be upscaled beyond 50x50."""
        path = img_dir / "tiny.jpg"
        _save_image(path, size=(50, 50), fmt="JPEG", quality=85)

        jpeg_bytes, info = make_thumbnail(path)
        assert jpeg_bytes is not None

        assert info["thumb_width"] <= 50
        assert info["thumb_height"] <= 50

    def test_thumbnail_custom_quality(self, img_dir: Path) -> None:
        """quality=20 should produce smaller output than quality=95."""
        path = img_dir / "quality_test.jpg"
        _save_image(path, size=(800, 600), fmt="JPEG", quality=90)

        low_bytes, low_info = make_thumbnail(path, quality=20)
        high_bytes, high_info = make_thumbnail(path, quality=95)

        assert low_bytes is not None
        assert high_bytes is not None
        assert low_info["thumb_byte_size"] < high_info["thumb_byte_size"], (
            f"quality=20 ({low_info['thumb_byte_size']}B) should be smaller "
            f"than quality=95 ({high_info['thumb_byte_size']}B)"
        )

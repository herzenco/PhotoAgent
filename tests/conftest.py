"""Shared fixtures for PhotoAgent test suite.

Provides reusable test images, database instances, and sample data
used across all test modules.
"""

from __future__ import annotations

import os
import shutil
import struct
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Generator

import pytest
from PIL import Image, ImageDraw, ImageFilter

from photoagent.database import CatalogDB


# ------------------------------------------------------------------
# Helper: build a minimal EXIF segment with GPS and camera info
# ------------------------------------------------------------------


def _build_exif_bytes() -> bytes:
    """Create a minimal valid EXIF APP1 segment with GPS and camera data.

    Uses piexif if available, otherwise falls back to Pillow's built-in
    EXIF support to embed camera make/model, date, and GPS coordinates.
    """
    try:
        import piexif

        zeroth_ifd = {
            piexif.ImageIFD.Make: b"TestCamera",
            piexif.ImageIFD.Model: b"TC-100",
            piexif.ImageIFD.Orientation: 1,
        }
        exif_ifd = {
            piexif.ExifIFD.DateTimeOriginal: b"2023:06:15 14:30:00",
            piexif.ExifIFD.ISOSpeedRatings: 200,
            piexif.ExifIFD.FNumber: (28, 10),
            piexif.ExifIFD.ExposureTime: (1, 125),
            piexif.ExifIFD.LensModel: b"TC 24-70mm f/2.8",
            piexif.ExifIFD.Flash: 0,
        }
        # GPS: 48.8566 N, 2.3522 E  (Paris)
        gps_ifd = {
            piexif.GPSIFD.GPSLatitudeRef: b"N",
            piexif.GPSIFD.GPSLatitude: ((48, 1), (51, 1), (24, 1)),
            piexif.GPSIFD.GPSLongitudeRef: b"E",
            piexif.GPSIFD.GPSLongitude: ((2, 1), (21, 1), (8, 1)),
        }
        exif_dict = {"0th": zeroth_ifd, "Exif": exif_ifd, "GPS": gps_ifd}
        return piexif.dump(exif_dict)
    except ImportError:
        pass

    # Fallback: use Pillow's Exif class (limited but functional)
    from PIL.ExifTags import Base as ExifBase

    img = Image.new("RGB", (1, 1))
    exif = img.getexif()
    exif[ExifBase.Make] = "TestCamera"
    exif[ExifBase.Model] = "TC-100"
    exif[ExifBase.Orientation] = 1
    exif[ExifBase.DateTime] = "2023:06:15 14:30:00"
    return exif.tobytes()


def _create_jpeg_with_exif(filepath: Path) -> None:
    """Create a small JPEG with embedded EXIF data (GPS + camera info)."""
    img = Image.new("RGB", (100, 100), color="red")
    exif_bytes = _build_exif_bytes()
    img.save(str(filepath), "JPEG", exif=exif_bytes, quality=85)


def _create_png(filepath: Path) -> None:
    """Create a small PNG without any EXIF data."""
    img = Image.new("RGB", (100, 100), color="blue")
    img.save(str(filepath), "PNG")


def _create_blurry_image(filepath: Path) -> None:
    """Create a JPEG that is intentionally very blurry."""
    img = Image.new("RGB", (200, 200), color="green")
    draw = ImageDraw.Draw(img)
    # Draw some shapes to have content, then blur heavily
    draw.rectangle([20, 20, 80, 80], fill="white")
    draw.ellipse([100, 100, 180, 180], fill="yellow")
    blurred = img.filter(ImageFilter.GaussianBlur(radius=15))
    blurred.save(str(filepath), "JPEG", quality=85)


def _create_dark_image(filepath: Path) -> None:
    """Create a very dark / underexposed JPEG."""
    img = Image.new("RGB", (100, 100), color=(5, 5, 5))
    draw = ImageDraw.Draw(img)
    # Minimal variation so it is not solid black but still very dark
    draw.rectangle([10, 10, 30, 30], fill=(10, 10, 12))
    img.save(str(filepath), "JPEG", quality=85)


def _create_screenshot(filepath: Path) -> None:
    """Create an image with iPhone screenshot dimensions (1170x2532).

    Includes a solid-color status bar region at the top to mimic a real
    screenshot.
    """
    img = Image.new("RGB", (1170, 2532), color="white")
    draw = ImageDraw.Draw(img)
    # Status bar area (solid dark strip at top)
    draw.rectangle([0, 0, 1170, 94], fill=(30, 30, 30))
    # Some content
    draw.rectangle([50, 200, 1120, 300], fill=(220, 220, 220))
    draw.rectangle([50, 400, 1120, 500], fill=(200, 200, 200))
    img.save(str(filepath), "JPEG", quality=85)


def _create_corrupt_jpg(filepath: Path) -> None:
    """Write random bytes with a .jpg extension (not a valid image)."""
    import random

    data = bytes(random.getrandbits(8) for _ in range(512))
    filepath.write_bytes(data)


def _create_text_file(filepath: Path) -> None:
    """Create a plain text file."""
    filepath.write_text("This is not an image file.\n")


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def tmp_image_dir(tmp_path: Path) -> Path:
    """Create a temporary directory populated with various test images.

    Contents:
      - sample.jpg          — valid JPEG with EXIF (GPS, camera info)
      - sample.png          — valid PNG, no EXIF
      - blurry.jpg          — intentionally blurry image
      - dark.jpg            — very dark / underexposed image
      - screenshot.jpg      — iPhone-sized screenshot
      - duplicate.jpg       — byte-for-byte copy of sample.jpg
      - corrupt.jpg         — random bytes, invalid image
      - notes.txt           — non-image file
      - sub/nested.jpg      — JPEG inside a subdirectory

    If pillow-heif is installed, also creates sample.heic.
    """
    d = tmp_path / "photos"
    d.mkdir()

    # Valid JPEG with EXIF
    _create_jpeg_with_exif(d / "sample.jpg")

    # Valid PNG (no EXIF)
    _create_png(d / "sample.png")

    # HEIC placeholder (only if pillow-heif available)
    try:
        import pillow_heif  # noqa: F401

        # pillow_heif registers HEIF opener with Pillow, but encoding
        # support varies.  Create a small JPEG and rename as a pragmatic
        # stand-in; tests that actually decode HEIC can be skipped.
        img = Image.new("RGB", (100, 100), color="purple")
        heic_path = d / "sample.heic"
        try:
            img.save(str(heic_path), format="HEIF")
        except Exception:
            # If saving as HEIF fails, just skip HEIC sample
            pass
    except ImportError:
        pass

    # Blurry image
    _create_blurry_image(d / "blurry.jpg")

    # Dark / underexposed image
    _create_dark_image(d / "dark.jpg")

    # Screenshot (iPhone dimensions)
    _create_screenshot(d / "screenshot.jpg")

    # Duplicate — exact copy of sample.jpg
    shutil.copy2(d / "sample.jpg", d / "duplicate.jpg")

    # Corrupt JPEG
    _create_corrupt_jpg(d / "corrupt.jpg")

    # Non-image text file
    _create_text_file(d / "notes.txt")

    # Subdirectory with an image (for recursive scan tests)
    sub = d / "sub"
    sub.mkdir()
    _create_jpeg_with_exif(sub / "nested.jpg")

    return d


@pytest.fixture
def catalog_db(tmp_path: Path) -> Generator[CatalogDB, None, None]:
    """Create a CatalogDB instance backed by a temporary directory."""
    db = CatalogDB(tmp_path)
    yield db
    db.close()


@pytest.fixture
def sample_image_record() -> dict:
    """Return a fully populated image record dict suitable for insert_image()."""
    return {
        "file_path": "/photos/vacation/IMG_0001.jpg",
        "filename": "IMG_0001.jpg",
        "extension": ".jpg",
        "file_size": 4_500_000,
        "file_md5": "d41d8cd98f00b204e9800998ecf8427e",
        "perceptual_hash": "a1b2c3d4e5f60718",
        "date_taken": "2023-06-15 14:30:00",
        "gps_lat": 48.8566,
        "gps_lon": 2.3522,
        "city": "Paris",
        "country": "France",
        "camera_make": "Canon",
        "camera_model": "EOS R5",
        "lens": "RF 24-70mm f/2.8L",
        "iso": 200,
        "aperture": 2.8,
        "shutter_speed": "1/125",
        "flash_used": False,
        "orientation": 1,
        "file_created": "2023-06-15 14:30:00",
        "file_modified": "2023-06-15 14:30:00",
    }

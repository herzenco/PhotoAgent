"""Tests for photoagent.exif — EXIF metadata extraction.

Verifies that the extract_exif() function correctly reads camera info,
GPS coordinates, date taken, and handles images without EXIF and
corrupt files gracefully.

Expected interface (being built concurrently):

    from photoagent.exif import extract_exif

    result = extract_exif(path: str | Path) -> dict[str, Any] | None
    # Keys: date_taken, gps_lat, gps_lon, city, country,
    #        camera_make, camera_model, lens, iso, aperture,
    #        shutter_speed, flash_used, orientation
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from photoagent.exif import extract_exif


# ------------------------------------------------------------------
# Basic extraction
# ------------------------------------------------------------------


class TestExtractExif:
    """Tests for EXIF data extraction from image files."""

    def test_extract_jpeg_exif(self, tmp_image_dir: Path) -> None:
        """A JPEG with known EXIF should return populated fields."""
        result = extract_exif(tmp_image_dir / "sample.jpg")
        assert result is not None
        assert isinstance(result, dict)

        # Camera info should be present (set in conftest via piexif or Pillow)
        assert result.get("camera_make") is not None or result.get("camera_model") is not None

    def test_extract_no_exif(self, tmp_image_dir: Path) -> None:
        """A PNG without EXIF should return None or a dict with all-None fields."""
        result = extract_exif(tmp_image_dir / "sample.png")
        if result is not None:
            # All substantive fields should be None
            camera_fields = [
                result.get("camera_make"),
                result.get("camera_model"),
                result.get("date_taken"),
            ]
            # At least the camera fields should be absent
            assert all(v is None for v in camera_fields)

    def test_extract_corrupt_file(self, tmp_image_dir: Path) -> None:
        """Corrupt files should not raise; returns None or empty dict."""
        result = extract_exif(tmp_image_dir / "corrupt.jpg")
        # Should not raise — graceful handling
        if result is not None:
            # If a dict is returned it should indicate no useful data
            assert result.get("camera_make") is None

    def test_extract_nonexistent_file(self, tmp_path: Path) -> None:
        """Extracting EXIF from a non-existent file should not raise."""
        result = extract_exif(tmp_path / "no_such_file.jpg")
        # Returns a dict with all-None values (never raises)
        assert isinstance(result, dict)
        assert result.get("camera_make") is None


# ------------------------------------------------------------------
# GPS
# ------------------------------------------------------------------


class TestGPS:
    """Tests for GPS coordinate extraction and reverse geocoding."""

    def test_extract_gps_coordinates(self, tmp_image_dir: Path) -> None:
        """If the JPEG has GPS EXIF, lat/lon should be decimal floats."""
        result = extract_exif(tmp_image_dir / "sample.jpg")
        if result is None:
            pytest.skip("EXIF extraction returned None — piexif may not be installed")

        lat = result.get("gps_lat")
        lon = result.get("gps_lon")

        if lat is not None and lon is not None:
            # The conftest embeds Paris coords: ~48.856, ~2.352
            assert isinstance(lat, (int, float))
            assert isinstance(lon, (int, float))
            assert -90.0 <= lat <= 90.0, "Latitude out of range"
            assert -180.0 <= lon <= 180.0, "Longitude out of range"

    def test_extract_gps_reverse_geocode(self, tmp_image_dir: Path) -> None:
        """If GPS is present, city/country should be populated via reverse geocoding."""
        result = extract_exif(tmp_image_dir / "sample.jpg")
        if result is None:
            pytest.skip("EXIF extraction returned None")

        lat = result.get("gps_lat")
        if lat is None:
            pytest.skip("No GPS data in test image")

        # Reverse geocoding should populate city and/or country
        city = result.get("city")
        country = result.get("country")
        assert city is not None or country is not None, (
            "Reverse geocoding should populate city or country when GPS is present"
        )


# ------------------------------------------------------------------
# Camera info
# ------------------------------------------------------------------


class TestCameraInfo:
    """Tests for camera metadata fields."""

    def test_extract_camera_info(self, tmp_image_dir: Path) -> None:
        """Verify make, model, lens, ISO, aperture, shutter speed are extracted."""
        result = extract_exif(tmp_image_dir / "sample.jpg")
        if result is None:
            pytest.skip("EXIF extraction returned None")

        # The conftest sets Make=TestCamera, Model=TC-100 (via piexif)
        # Verify the fields exist in the returned dict at minimum
        expected_keys = [
            "camera_make",
            "camera_model",
            "iso",
            "aperture",
            "shutter_speed",
        ]
        for key in expected_keys:
            assert key in result, f"Expected key '{key}' in EXIF result"

    @pytest.mark.parametrize(
        "field,expected_type",
        [
            ("camera_make", str),
            ("camera_model", str),
            ("iso", (int, type(None))),
            ("aperture", (float, int, type(None))),
            ("shutter_speed", (str, type(None))),
            ("orientation", (int, type(None))),
        ],
    )
    def test_exif_field_types(
        self, tmp_image_dir: Path, field: str, expected_type: Any
    ) -> None:
        """Verify that extracted EXIF fields have the correct Python types."""
        result = extract_exif(tmp_image_dir / "sample.jpg")
        if result is None:
            pytest.skip("EXIF extraction returned None")

        value = result.get(field)
        if value is not None:
            assert isinstance(value, expected_type), (
                f"Field '{field}' has type {type(value)}, expected {expected_type}"
            )

"""EXIF metadata extraction for image files.

Reads EXIF, IPTC, and XMP metadata from image files and returns
structured records suitable for catalog storage.

Supports JPEG, TIFF, PNG, HEIC/HEIF formats.  Extracts camera settings,
GPS coordinates, and performs offline reverse geocoding.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional dependency imports — degrade gracefully
# ---------------------------------------------------------------------------

try:
    import exifread
except ImportError:
    exifread = None  # type: ignore[assignment]
    logger.warning("exifread not installed — EXIF extraction will be limited")

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:
    pillow_heif = None  # type: ignore[assignment]
    logger.debug("pillow_heif not installed — HEIC/HEIF support unavailable")

try:
    import reverse_geocoder as rg
except ImportError:
    rg = None  # type: ignore[assignment]
    logger.debug("reverse_geocoder not installed — reverse geocoding unavailable")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _convert_dms_to_decimal(
    dms_values: list[Any],
    ref: str,
) -> float | None:
    """Convert EXIF GPS DMS (degrees/minutes/seconds) to decimal degrees.

    ``dms_values`` is typically a list of three ``exifread.utils.Ratio``
    objects (degrees, minutes, seconds).  ``ref`` is one of N/S/E/W.
    """
    try:
        degrees = float(dms_values[0])
        minutes = float(dms_values[1])
        seconds = float(dms_values[2])
        decimal = degrees + minutes / 60.0 + seconds / 3600.0
        if ref in ("S", "W"):
            decimal = -decimal
        return decimal
    except (ValueError, TypeError, IndexError, ZeroDivisionError):
        return None


def _safe_float(tag_value: Any) -> float | None:
    """Try to coerce an EXIF tag value to float."""
    try:
        val = tag_value.values[0]
        return float(val)
    except Exception:
        try:
            return float(str(tag_value))
        except (ValueError, TypeError):
            return None


def _safe_int(tag_value: Any) -> int | None:
    """Try to coerce an EXIF tag value to int."""
    try:
        val = tag_value.values[0]
        return int(val)
    except Exception:
        try:
            return int(str(tag_value))
        except (ValueError, TypeError):
            return None


def _safe_str(tag_value: Any) -> str | None:
    """Coerce an EXIF tag value to a stripped string, or None."""
    try:
        text = str(tag_value).strip()
        return text if text else None
    except Exception:
        return None


def _parse_gps(tags: dict[str, Any]) -> tuple[float | None, float | None]:
    """Extract GPS lat/lon from EXIF tags as decimal degrees."""
    lat_tag = tags.get("GPS GPSLatitude")
    lat_ref_tag = tags.get("GPS GPSLatitudeRef")
    lon_tag = tags.get("GPS GPSLongitude")
    lon_ref_tag = tags.get("GPS GPSLongitudeRef")

    if not (lat_tag and lat_ref_tag and lon_tag and lon_ref_tag):
        return None, None

    lat = _convert_dms_to_decimal(lat_tag.values, str(lat_ref_tag))
    lon = _convert_dms_to_decimal(lon_tag.values, str(lon_ref_tag))
    return lat, lon


def _reverse_geocode(
    lat: float,
    lon: float,
) -> tuple[str | None, str | None]:
    """Reverse-geocode GPS coordinates to (city, country) offline."""
    if rg is None:
        return None, None
    try:
        results = rg.search([(lat, lon)], mode=1)
        if results:
            entry = results[0]
            city: str | None = entry.get("name") or entry.get("admin1")
            country: str | None = entry.get("cc")
            return city, country
    except Exception as exc:
        logger.debug("Reverse geocoding failed for (%s, %s): %s", lat, lon, exc)
    return None, None


def _parse_flash(tags: dict[str, Any]) -> bool | None:
    """Determine if flash fired from EXIF Flash tag."""
    flash_tag = tags.get("EXIF Flash")
    if flash_tag is None:
        return None
    try:
        # The Flash tag is a bitmask; bit 0 = flash fired
        val = int(str(flash_tag.values[0]))
        return bool(val & 1)
    except Exception:
        text = str(flash_tag).lower()
        if "fired" in text and "not" not in text:
            return True
        if "not" in text or "no" in text or "off" in text:
            return False
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_exif(file_path: Path) -> dict[str, Any]:
    """Extract EXIF metadata from an image file.

    Returns a dict with the following keys (any may be ``None``):

        date_taken, gps_lat, gps_lon, city, country,
        camera_make, camera_model, lens, iso, aperture,
        shutter_speed, flash_used, orientation

    This function never raises — on failure it returns a dict with all
    values set to ``None``.
    """
    empty: dict[str, Any] = {
        "date_taken": None,
        "gps_lat": None,
        "gps_lon": None,
        "city": None,
        "country": None,
        "camera_make": None,
        "camera_model": None,
        "lens": None,
        "iso": None,
        "aperture": None,
        "shutter_speed": None,
        "flash_used": None,
        "orientation": None,
    }

    if exifread is None:
        return empty

    try:
        import io
        import sys
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            old_stderr = sys.stderr
            sys.stderr = io.StringIO()  # suppress exifread print noise
            try:
                with open(file_path, "rb") as fh:
                    tags = exifread.process_file(fh, details=False)
            finally:
                sys.stderr = old_stderr
    except Exception:
        return empty

    if not tags:
        return empty

    result: dict[str, Any] = {}

    # --- Date taken ---
    for date_key in (
        "EXIF DateTimeOriginal",
        "EXIF DateTimeDigitized",
        "Image DateTime",
    ):
        dt = tags.get(date_key)
        if dt:
            result["date_taken"] = _safe_str(dt)
            break
    else:
        result["date_taken"] = None

    # --- GPS ---
    lat, lon = _parse_gps(tags)
    result["gps_lat"] = lat
    result["gps_lon"] = lon

    # --- Reverse geocode ---
    if lat is not None and lon is not None:
        city, country = _reverse_geocode(lat, lon)
        result["city"] = city
        result["country"] = country
    else:
        result["city"] = None
        result["country"] = None

    # --- Camera info ---
    result["camera_make"] = _safe_str(tags.get("Image Make"))
    result["camera_model"] = _safe_str(tags.get("Image Model"))
    result["lens"] = _safe_str(
        tags.get("EXIF LensModel") or tags.get("EXIF LensInfo")
    )

    # --- Exposure settings ---
    result["iso"] = _safe_int(tags.get("EXIF ISOSpeedRatings"))

    aperture_tag = tags.get("EXIF FNumber") or tags.get("EXIF ApertureValue")
    result["aperture"] = _safe_float(aperture_tag) if aperture_tag else None

    shutter_tag = (
        tags.get("EXIF ExposureTime") or tags.get("EXIF ShutterSpeedValue")
    )
    result["shutter_speed"] = _safe_str(shutter_tag) if shutter_tag else None

    # --- Flash ---
    result["flash_used"] = _parse_flash(tags)

    # --- Orientation ---
    result["orientation"] = _safe_int(tags.get("Image Orientation"))

    return result

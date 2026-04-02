"""Privacy audit integration tests for PhotoAgent.

These are the most critical tests in the suite. They enforce the core
principle that NO image pixel data, binary content, or base64-encoded
images ever leave the machine through the API payload pipeline.

The tests exercise the full pipeline: real images on disk -> CatalogDB ->
CatalogSummarizer -> JSON payload, then audit every byte of the output.
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any, Generator

import pytest
from PIL import Image
from unittest.mock import MagicMock, patch

from photoagent.database import CatalogDB
from photoagent.summarizer import CatalogSummarizer


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

# Allowed scalar types for manifest field values
_ALLOWED_SCALAR_TYPES = (str, int, float, bool, type(None))


def _create_test_jpeg(path: Path, color: str = "red", size: tuple[int, int] = (100, 100)) -> None:
    """Create a small JPEG file at the given path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", size, color=color)
    img.save(str(path), "JPEG", quality=85)


def _insert_test_image(
    db: CatalogDB,
    file_path: str,
    filename: str,
    *,
    date_taken: str = "2023-06-15 14:30:00",
    city: str = "Paris",
    country: str = "France",
    ai_tags: str | None = None,
    ai_caption: str = "A test photo",
    ai_quality_score: float = 0.8,
    is_screenshot: bool = False,
) -> int:
    """Insert a test image record and return its ID."""
    return db.insert_image({
        "file_path": file_path,
        "filename": filename,
        "extension": Path(filename).suffix,
        "file_size": 50_000,
        "date_taken": date_taken,
        "city": city,
        "country": country,
        "ai_caption": ai_caption,
        "ai_tags": ai_tags or json.dumps([
            {"label": "nature", "score": 0.8},
            {"label": "landscape", "score": 0.6},
        ]),
        "ai_quality_score": ai_quality_score,
        "is_screenshot": is_screenshot,
    })


def _assert_value_is_text_only(value: Any, context: str) -> None:
    """Recursively assert that a value contains only text-safe types.

    Raises AssertionError with a descriptive message if binary or
    unsafe types are found.
    """
    if isinstance(value, _ALLOWED_SCALAR_TYPES):
        return
    if isinstance(value, list):
        for i, item in enumerate(value):
            _assert_value_is_text_only(item, f"{context}[{i}]")
        return
    if isinstance(value, dict):
        for k, v in value.items():
            _assert_value_is_text_only(v, f"{context}.{k}")
        return

    # Reject everything else: bytes, bytearray, memoryview, numpy arrays, etc.
    raise AssertionError(
        f"Non-text type found at {context}: {type(value).__name__} = {repr(value)[:200]}"
    )


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def privacy_test_dir(tmp_path: Path) -> Path:
    """Create a temp directory with real JPEG files for privacy tests."""
    photo_dir = tmp_path / "photos"
    photo_dir.mkdir()

    # Create several real JPEG files
    for i in range(5):
        _create_test_jpeg(photo_dir / f"photo_{i:03d}.jpg", color="blue")
    _create_test_jpeg(photo_dir / "screenshot.jpg", color="white", size=(1170, 2532))
    _create_test_jpeg(photo_dir / "sub" / "nested.jpg", color="green")

    return tmp_path


@pytest.fixture
def privacy_db(privacy_test_dir: Path) -> Generator[CatalogDB, None, None]:
    """Create a CatalogDB populated with records pointing to real image files."""
    db = CatalogDB(privacy_test_dir)

    photo_dir = privacy_test_dir / "photos"

    for i in range(5):
        fname = f"photo_{i:03d}.jpg"
        _insert_test_image(
            db,
            str(photo_dir / fname),
            fname,
            date_taken=f"2023-{i+1:02d}-15 10:00:00",
            ai_caption=f"Photo number {i} in the test suite",
        )

    _insert_test_image(
        db,
        str(photo_dir / "screenshot.jpg"),
        "screenshot.jpg",
        is_screenshot=True,
        ai_caption="A mobile screenshot",
    )

    _insert_test_image(
        db,
        str(photo_dir / "sub" / "nested.jpg"),
        "nested.jpg",
        city="Tokyo",
        country="Japan",
        ai_caption="Nested photo in subdirectory",
    )

    yield db
    db.close()


@pytest.fixture
def privacy_summarizer(privacy_db: CatalogDB) -> CatalogSummarizer:
    """Create a CatalogSummarizer from the privacy test database."""
    return CatalogSummarizer(privacy_db)


# ------------------------------------------------------------------
# Test: Full pipeline -- no image bytes
# ------------------------------------------------------------------


class TestFullPipelineNoImageBytes:
    """End-to-end test that the full summarizer pipeline produces no image data."""

    def test_full_pipeline_no_image_bytes(
        self, privacy_summarizer: CatalogSummarizer
    ) -> None:
        """Build summary + manifest from real files and audit the JSON payload.

        This test:
        1. Creates real JPEG files on disk
        2. Populates CatalogDB with records pointing to those files
        3. Builds summary and manifest via CatalogSummarizer
        4. Serializes everything to a JSON string (simulating the API payload)
        5. Asserts: no base64, no binary, no file:// URLs, valid JSON, under 10MB
        """
        summary = privacy_summarizer.build_summary()
        chunks = privacy_summarizer.build_manifest()

        # Build the payload as it would be sent to the API
        payload_dict = {
            "summary": summary,
            "manifest": chunks,
        }
        payload = json.dumps(payload_dict, default=str)

        # 1. No base64 patterns (100+ chars of base64 alphabet)
        base64_match = re.search(r"[A-Za-z0-9+/=]{100,}", payload)
        assert base64_match is None, (
            f"Payload contains base64-like data at position {base64_match.start()}: "
            f"'{base64_match.group()[:80]}...'"
        )

        # 2. No bytes/binary object indicators
        assert "\\x" not in payload, "Payload contains hex-escaped bytes"
        assert "b'" not in payload, "Payload contains Python bytes literal b'"
        assert 'b"' not in payload, "Payload contains Python bytes literal b\""

        # 3. No file:// URLs pointing to actual image files
        file_urls = re.findall(r"file://[^\s\"']+", payload)
        for url in file_urls:
            assert not any(
                url.endswith(ext)
                for ext in (".jpg", ".jpeg", ".png", ".heic", ".tiff", ".bmp")
            ), f"Payload contains file:// URL pointing to an image: {url}"

        # 4. Payload is valid JSON text only
        parsed = json.loads(payload)
        assert isinstance(parsed, dict)

        # 5. Payload size is under 10MB
        payload_bytes = len(payload.encode("utf-8"))
        max_bytes = 10 * 1024 * 1024
        assert payload_bytes < max_bytes, (
            f"Payload is {payload_bytes / 1024 / 1024:.1f}MB, exceeds 10MB limit"
        )


# ------------------------------------------------------------------
# Test: All manifest fields are text only
# ------------------------------------------------------------------


class TestManifestFieldsTextOnly:
    """Verify that every field of every manifest entry is a safe text type."""

    def test_manifest_fields_are_text_only(
        self, privacy_summarizer: CatalogSummarizer
    ) -> None:
        """Iterate every field of every image in the manifest.

        Assert each value is str, int, float, bool, None, or a list of those types.
        No bytes, no memoryview, no numpy arrays, no binary data of any kind.
        """
        chunks = privacy_summarizer.build_manifest()

        for chunk_idx, chunk in enumerate(chunks):
            for entry_idx, entry in enumerate(chunk):
                context = f"chunk[{chunk_idx}][{entry_idx}]"
                assert isinstance(entry, dict), (
                    f"{context} is not a dict: {type(entry)}"
                )
                for key, value in entry.items():
                    _assert_value_is_text_only(value, f"{context}.{key}")

    def test_summary_fields_are_text_only(
        self, privacy_summarizer: CatalogSummarizer
    ) -> None:
        """Verify the summary dict also contains only text-safe types."""
        summary = privacy_summarizer.build_summary()
        _assert_value_is_text_only(summary, "summary")


# ------------------------------------------------------------------
# Test: Privacy guard catches injection
# ------------------------------------------------------------------


class TestPrivacyGuardCatchesInjection:
    """Test that the privacy guard detects injected image data."""

    @patch("photoagent.planner.anthropic")
    def test_privacy_guard_catches_injection(self, mock_anth: MagicMock) -> None:
        """Manually inject base64 image data into a manifest caption field."""
        from photoagent.planner import OrganizationPlanner, PrivacyViolationError

        mock_anth.Anthropic.return_value = MagicMock()
        planner = OrganizationPlanner(api_key="test-key")

        import io
        img = Image.new("RGB", (50, 50), color="red")
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        fake_image_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        assert len(fake_image_b64) > 100

        poisoned_payload = json.dumps({
            "summary": {"total_images": 1},
            "manifest": [[{
                "id": 1, "filename": "photo.jpg",
                "caption": f"Here is the image: {fake_image_b64}",
            }]],
        })

        with pytest.raises(PrivacyViolationError):
            planner._validate_payload(poisoned_payload)

    @patch("photoagent.planner.anthropic")
    def test_privacy_guard_catches_data_uri(self, mock_anth: MagicMock) -> None:
        """A data:image/jpeg;base64 URI in the payload should be caught."""
        from photoagent.planner import OrganizationPlanner, PrivacyViolationError

        mock_anth.Anthropic.return_value = MagicMock()
        planner = OrganizationPlanner(api_key="test-key")

        fake_b64 = "A" * 200
        data_uri = f"data:image/jpeg;base64,{fake_b64}"

        payload = json.dumps({
            "summary": {"total_images": 1},
            "manifest": [[{"id": 1, "filename": "photo.jpg", "caption": data_uri}]],
        })

        with pytest.raises(PrivacyViolationError):
            planner._validate_payload(payload)

    @patch("photoagent.planner.anthropic")
    def test_clean_manifest_passes_guard(
        self, mock_anth: MagicMock, privacy_summarizer: CatalogSummarizer
    ) -> None:
        """A manifest built from the real pipeline should pass the privacy guard."""
        from photoagent.planner import OrganizationPlanner

        mock_anth.Anthropic.return_value = MagicMock()
        planner = OrganizationPlanner(api_key="test-key")

        summary = privacy_summarizer.build_summary()
        chunks = privacy_summarizer.build_manifest()

        payload = json.dumps({
            "summary": summary,
            "manifest": chunks,
        }, default=str)

        # Should not raise
        planner._validate_payload(payload)


# ------------------------------------------------------------------
# Test: No image file contents leak through any path
# ------------------------------------------------------------------


class TestNoImageContentLeaks:
    """Additional paranoia checks for image content leakage."""

    def test_no_jpeg_magic_bytes_in_payload(
        self, privacy_summarizer: CatalogSummarizer
    ) -> None:
        """The JPEG magic bytes (FFD8FF) should never appear in the payload."""
        summary = privacy_summarizer.build_summary()
        chunks = privacy_summarizer.build_manifest()

        payload = json.dumps({"summary": summary, "manifest": chunks}, default=str)

        # JPEG starts with FF D8 FF -- check both hex representations
        assert "\\xff\\xd8\\xff" not in payload.lower()
        assert "ffd8ff" not in payload.lower()

    def test_no_png_magic_bytes_in_payload(
        self, privacy_summarizer: CatalogSummarizer
    ) -> None:
        """The PNG signature should never appear in the payload."""
        summary = privacy_summarizer.build_summary()
        chunks = privacy_summarizer.build_manifest()

        payload = json.dumps({"summary": summary, "manifest": chunks}, default=str)

        # PNG starts with 89 50 4E 47 (\x89PNG)
        assert "\\x89png" not in payload.lower()
        assert "89504e47" not in payload.lower()

    def test_payload_is_pure_ascii_json(
        self, privacy_summarizer: CatalogSummarizer
    ) -> None:
        """The payload should be representable as ASCII-safe JSON
        (no high bytes that could indicate embedded binary)."""
        summary = privacy_summarizer.build_summary()
        chunks = privacy_summarizer.build_manifest()

        payload = json.dumps(
            {"summary": summary, "manifest": chunks},
            default=str,
            ensure_ascii=True,
        )

        # Every character should be in the printable ASCII + whitespace range
        for i, ch in enumerate(payload):
            assert ord(ch) < 128, (
                f"Non-ASCII character at position {i}: "
                f"U+{ord(ch):04X} ({repr(ch)})"
            )

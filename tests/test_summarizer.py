"""Tests for photoagent.summarizer.CatalogSummarizer.

Verifies catalog summary generation, manifest building, chunking,
relative path computation, face mapping, and the critical guarantee
that no binary/image data appears in any output.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Generator

import pytest

from photoagent.database import CatalogDB
from photoagent.summarizer import CatalogSummarizer


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_image_record(
    base_path: str,
    filename: str,
    *,
    date_taken: str | None = "2023-06-15 14:30:00",
    city: str | None = "Paris",
    country: str | None = "France",
    ai_tags: str | None = None,
    ai_quality_score: float | None = 0.8,
    is_screenshot: bool = False,
    is_duplicate_of: int | None = None,
    camera_make: str | None = "Canon",
    camera_model: str | None = "EOS R5",
    ai_caption: str | None = "A photo",
) -> dict[str, Any]:
    """Build a minimal image record dict for insert_image()."""
    file_path = f"{base_path}/{filename}"
    return {
        "file_path": file_path,
        "filename": filename,
        "extension": Path(filename).suffix,
        "file_size": 4_000_000,
        "date_taken": date_taken,
        "city": city,
        "country": country,
        "camera_make": camera_make,
        "camera_model": camera_model,
        "ai_tags": ai_tags,
        "ai_quality_score": ai_quality_score,
        "is_screenshot": is_screenshot,
        "is_duplicate_of": is_duplicate_of,
        "ai_caption": ai_caption,
    }


def _insert_face(db: CatalogDB, image_id: int, cluster_label: str) -> None:
    """Insert a face record into the faces table."""
    db._conn.execute(
        "INSERT INTO faces (image_id, embedding, cluster_label) VALUES (?, ?, ?)",
        (image_id, b"\x00" * 16, cluster_label),
    )
    db._conn.commit()


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def summarizer_db(tmp_path: Path) -> Generator[CatalogDB, None, None]:
    """Create a CatalogDB for summarizer tests."""
    db = CatalogDB(tmp_path)
    yield db
    db.close()


@pytest.fixture
def summarizer(summarizer_db: CatalogDB) -> CatalogSummarizer:
    """Create a CatalogSummarizer backed by the test database."""
    return CatalogSummarizer(summarizer_db)


@pytest.fixture
def base_path(summarizer_db: CatalogDB) -> str:
    """Return the base_path as a string for building file paths."""
    return str(summarizer_db._base_path)


# ------------------------------------------------------------------
# Tests: build_summary
# ------------------------------------------------------------------


class TestBuildSummary:
    """Tests for CatalogSummarizer.build_summary()."""

    def test_build_summary_empty(self, summarizer: CatalogSummarizer) -> None:
        """An empty database produces a summary with zero counts and empty lists."""
        summary = summarizer.build_summary()

        assert summary["total_images"] == 0
        assert summary["date_range"] == "unknown"
        assert summary["locations"] == []
        assert summary["tag_distribution"] == {}
        assert summary["yearly_breakdown"] == {}
        assert summary["screenshot_count"] == 0
        assert summary["quality_issues"] == {}

    def test_build_summary_with_data(
        self,
        summarizer: CatalogSummarizer,
        summarizer_db: CatalogDB,
        base_path: str,
    ) -> None:
        """Insert ~10 varied images and verify all summary fields are correct."""
        tags_beach = json.dumps([
            {"label": "beach", "score": 0.9},
            {"label": "sunset", "score": 0.7},
        ])
        tags_city = json.dumps([
            {"label": "city", "score": 0.85},
            {"label": "architecture", "score": 0.6},
        ])
        tags_blurry = json.dumps([
            {"label": "blurry", "score": 0.95},
        ])

        records = [
            # 4 Paris photos in 2023
            _make_image_record(base_path, "paris_1.jpg", date_taken="2023-01-10 10:00:00", ai_tags=tags_beach),
            _make_image_record(base_path, "paris_2.jpg", date_taken="2023-03-15 12:00:00", ai_tags=tags_city),
            _make_image_record(base_path, "paris_3.jpg", date_taken="2023-06-20 14:00:00", ai_tags=tags_beach),
            _make_image_record(base_path, "paris_4.jpg", date_taken="2023-11-01 09:00:00"),
            # 2 Tokyo photos in 2022
            _make_image_record(base_path, "tokyo_1.jpg", date_taken="2022-05-01 08:00:00", city="Tokyo", country="Japan", ai_tags=tags_city),
            _make_image_record(base_path, "tokyo_2.jpg", date_taken="2022-08-15 16:00:00", city="Tokyo", country="Japan"),
            # 1 screenshot
            _make_image_record(base_path, "screen_1.jpg", is_screenshot=True, date_taken="2023-09-01 10:00:00", city=None, country=None),
            # 2 low-quality images
            _make_image_record(base_path, "bad_1.jpg", ai_quality_score=0.1, date_taken="2023-02-01 11:00:00", ai_tags=tags_blurry),
            _make_image_record(base_path, "bad_2.jpg", ai_quality_score=0.2, date_taken="2023-04-01 13:00:00"),
            # 1 image with no date
            _make_image_record(base_path, "nodate.jpg", date_taken=None, city=None, country=None),
        ]

        for rec in records:
            summarizer_db.insert_image(rec)

        summary = summarizer.build_summary()

        # Total images
        assert summary["total_images"] == 10

        # Date range spans 2022-05-01 to 2023-11-01
        assert "2022-05-01" in summary["date_range"]
        assert "2023-11-01" in summary["date_range"]

        # Locations: Paris (4 + 2 low quality that have Paris) and Tokyo (2)
        location_names = {loc["name"] for loc in summary["locations"]}
        assert "Paris, France" in location_names
        assert "Tokyo, Japan" in location_names

        # Find Paris count: paris_1..4 + bad_1 + bad_2 = 6 (all default to Paris)
        paris_loc = [loc for loc in summary["locations"] if loc["name"] == "Paris, France"][0]
        assert paris_loc["count"] == 6

        # Tag distribution
        assert "beach" in summary["tag_distribution"]
        assert "city" in summary["tag_distribution"]

        # Yearly breakdown
        assert "2023" in summary["yearly_breakdown"]
        assert "2022" in summary["yearly_breakdown"]
        assert summary["yearly_breakdown"]["2022"] == 2
        # 2023: paris_1..4, screen_1, bad_1, bad_2 = 7
        assert summary["yearly_breakdown"]["2023"] == 7

        # Screenshot count
        assert summary["screenshot_count"] == 1

        # Quality issues
        assert summary["quality_issues"].get("low_quality", 0) == 2
        assert summary["quality_issues"].get("blurry", 0) == 1

    def test_build_summary_tag_distribution(
        self,
        summarizer: CatalogSummarizer,
        summarizer_db: CatalogDB,
        base_path: str,
    ) -> None:
        """Verify that tag counts are aggregated correctly across multiple images."""
        tags_a = json.dumps([
            {"label": "beach", "score": 0.9},
            {"label": "sunset", "score": 0.7},
        ])
        tags_b = json.dumps([
            {"label": "beach", "score": 0.85},
            {"label": "ocean", "score": 0.6},
        ])
        tags_c = json.dumps([
            {"label": "sunset", "score": 0.95},
            {"label": "ocean", "score": 0.8},
            {"label": "beach", "score": 0.5},
        ])

        for i, tags in enumerate([tags_a, tags_b, tags_c]):
            rec = _make_image_record(base_path, f"tag_test_{i}.jpg", ai_tags=tags)
            summarizer_db.insert_image(rec)

        summary = summarizer.build_summary()
        td = summary["tag_distribution"]

        # beach appears in all 3
        assert td["beach"] == 3
        # sunset appears in tags_a and tags_c
        assert td["sunset"] == 2
        # ocean appears in tags_b and tags_c
        assert td["ocean"] == 2


# ------------------------------------------------------------------
# Tests: build_manifest
# ------------------------------------------------------------------


class TestBuildManifest:
    """Tests for CatalogSummarizer.build_manifest()."""

    def test_build_manifest_structure(
        self,
        summarizer: CatalogSummarizer,
        summarizer_db: CatalogDB,
        base_path: str,
    ) -> None:
        """Each manifest entry has all required keys with correct types."""
        rec = _make_image_record(
            base_path, "struct_test.jpg",
            ai_tags=json.dumps([{"label": "nature", "score": 0.9}]),
        )
        summarizer_db.insert_image(rec)

        chunks = summarizer.build_manifest()
        assert len(chunks) >= 1
        entry = chunks[0][0]

        required_keys = {
            "id", "filename", "current_path", "date", "location",
            "tags", "caption", "quality", "is_screenshot", "is_duplicate", "faces",
        }
        assert required_keys.issubset(entry.keys()), (
            f"Missing keys: {required_keys - entry.keys()}"
        )

        # Type checks
        assert isinstance(entry["id"], int)
        assert isinstance(entry["filename"], str)
        assert isinstance(entry["current_path"], str)
        assert isinstance(entry["tags"], list)
        assert isinstance(entry["is_screenshot"], bool)
        assert isinstance(entry["is_duplicate"], bool)
        assert isinstance(entry["faces"], list)

    def test_build_manifest_relative_paths(
        self,
        summarizer: CatalogSummarizer,
        summarizer_db: CatalogDB,
        base_path: str,
    ) -> None:
        """Manifest current_path should be relative to the base_path, not absolute."""
        rec = _make_image_record(base_path, "subdir/photo.jpg")
        summarizer_db.insert_image(rec)

        chunks = summarizer.build_manifest()
        entry = chunks[0][0]

        # Should be relative
        assert not entry["current_path"].startswith("/"), (
            f"Path should be relative, got: {entry['current_path']}"
        )
        assert entry["current_path"] == "subdir/photo.jpg"

    def test_build_manifest_chunking(
        self,
        summarizer: CatalogSummarizer,
        summarizer_db: CatalogDB,
        base_path: str,
    ) -> None:
        """Insert 15 images, chunk with size 5. Should get exactly 3 chunks."""
        for i in range(15):
            rec = _make_image_record(base_path, f"chunk_{i:03d}.jpg")
            summarizer_db.insert_image(rec)

        chunks = summarizer.build_manifest(chunk_size=5)

        assert len(chunks) == 3
        assert all(len(chunk) == 5 for chunk in chunks)

        # All 15 images accounted for
        total_entries = sum(len(c) for c in chunks)
        assert total_entries == 15

    def test_build_manifest_no_binary_data(
        self,
        summarizer: CatalogSummarizer,
        summarizer_db: CatalogDB,
        base_path: str,
    ) -> None:
        """Manifest must contain no bytes objects, no base64 strings -- only plain text/numbers/bools."""
        rec = _make_image_record(
            base_path, "binary_check.jpg",
            ai_tags=json.dumps([{"label": "test", "score": 0.5}]),
        )
        summarizer_db.insert_image(rec)

        chunks = summarizer.build_manifest()

        for chunk in chunks:
            for entry in chunk:
                for key, value in entry.items():
                    assert not isinstance(value, (bytes, bytearray, memoryview)), (
                        f"Field '{key}' contains binary data: {type(value)}"
                    )
                    if isinstance(value, str):
                        # No long base64-like strings
                        import re
                        assert not re.search(r"[A-Za-z0-9+/=]{100,}", value), (
                            f"Field '{key}' contains suspicious base64-like string"
                        )
                    if isinstance(value, list):
                        for item in value:
                            assert not isinstance(item, (bytes, bytearray, memoryview)), (
                                f"List item in '{key}' contains binary data"
                            )

    def test_build_manifest_faces(
        self,
        summarizer: CatalogSummarizer,
        summarizer_db: CatalogDB,
        base_path: str,
    ) -> None:
        """Manifest entries include face cluster labels from the faces table."""
        rec = _make_image_record(base_path, "face_test.jpg")
        image_id = summarizer_db.insert_image(rec)

        _insert_face(summarizer_db, image_id, "Alice")
        _insert_face(summarizer_db, image_id, "Bob")
        # Duplicate label should be deduplicated
        _insert_face(summarizer_db, image_id, "Alice")

        chunks = summarizer.build_manifest()
        entry = chunks[0][0]

        assert sorted(entry["faces"]) == ["Alice", "Bob"]

    def test_build_manifest_empty_db(
        self,
        summarizer: CatalogSummarizer,
    ) -> None:
        """An empty DB should return a list with one empty chunk."""
        chunks = summarizer.build_manifest()
        assert chunks == [[]]

"""Tests for photoagent.export — catalog export as JSON and CSV.

These tests validate that export_catalog produces correct JSON and CSV
files with proper structure, filtering, and edge-case handling.
"""

from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path
from typing import Any, Generator

import pytest

from photoagent.database import CatalogDB


# ------------------------------------------------------------------
# Helper
# ------------------------------------------------------------------

def _make_record(
    *,
    file_path: str,
    filename: str,
    extension: str = ".jpg",
    date_taken: str | None = None,
    city: str | None = None,
    country: str | None = None,
    camera_model: str | None = None,
    ai_tags: str | None = None,
    ai_caption: str | None = None,
    ai_quality_score: float | None = None,
    is_screenshot: bool = False,
) -> dict[str, Any]:
    return {
        "file_path": file_path,
        "filename": filename,
        "extension": extension,
        "date_taken": date_taken,
        "city": city,
        "country": country,
        "camera_model": camera_model,
        "ai_tags": ai_tags,
        "ai_caption": ai_caption,
        "ai_quality_score": ai_quality_score,
        "is_screenshot": is_screenshot,
        "analyzed_at": "2024-01-01 00:00:00",
    }


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def export_db(tmp_path: Path) -> Generator[CatalogDB, None, None]:
    """CatalogDB with 5 images for export tests."""
    db = CatalogDB(tmp_path)

    records = [
        _make_record(
            file_path="/photos/beach.jpg",
            filename="beach.jpg",
            date_taken="2023-07-15 10:00:00",
            city="Nice",
            country="France",
            camera_model="EOS R5",
            ai_tags=json.dumps([{"label": "beach", "score": 0.9}, {"label": "ocean", "score": 0.8}]),
            ai_caption="A sandy beach with blue water",
            ai_quality_score=0.9,
        ),
        _make_record(
            file_path="/photos/city.jpg",
            filename="city.jpg",
            date_taken="2023-08-20 19:30:00",
            city="Paris",
            country="France",
            camera_model="EOS R5",
            ai_tags=json.dumps([{"label": "city", "score": 0.85}]),
            ai_caption="Paris skyline at dusk",
            ai_quality_score=0.85,
        ),
        _make_record(
            file_path="/photos/cat.jpg",
            filename="cat.jpg",
            date_taken="2022-01-10 11:00:00",
            city="London",
            country="UK",
            camera_model="iPhone 15 Pro",
            ai_tags=json.dumps([{"label": "cat", "score": 0.95}]),
            ai_caption="An orange tabby cat",
            ai_quality_score=0.75,
        ),
        _make_record(
            file_path="/photos/mountain.jpg",
            filename="mountain.jpg",
            date_taken="2022-09-05 08:00:00",
            city="Chamonix",
            country="France",
            camera_model="A7IV",
            ai_tags=json.dumps([{"label": "mountain", "score": 0.95}]),
            ai_caption="Alpine mountain trail",
            ai_quality_score=0.92,
        ),
        _make_record(
            file_path="/photos/screenshot.png",
            filename="screenshot.png",
            extension=".png",
            date_taken="2023-05-20 09:00:00",
            ai_tags=json.dumps([{"label": "text", "score": 0.8}]),
            ai_caption="Chat screenshot",
            ai_quality_score=0.4,
            is_screenshot=True,
        ),
    ]

    for rec in records:
        db.insert_image(rec)

    yield db
    db.close()


@pytest.fixture
def empty_db(tmp_path: Path) -> Generator[CatalogDB, None, None]:
    """CatalogDB with no images."""
    db_path = tmp_path / "empty"
    db_path.mkdir()
    db = CatalogDB(db_path)
    yield db
    db.close()


# ------------------------------------------------------------------
# Lazy import
# ------------------------------------------------------------------

def _get_export_func():
    try:
        from photoagent.export import export_catalog
        return export_catalog
    except ImportError:
        pytest.skip("photoagent.export not yet implemented")


# ==================================================================
# TestExportJSON
# ==================================================================

class TestExportJSON:
    """Verify JSON export produces valid files with correct structure."""

    def test_export_json(self, export_db: CatalogDB, tmp_path: Path) -> None:
        export_catalog = _get_export_func()
        out_path = tmp_path / "export.json"
        export_catalog(export_db, tmp_path, out_path, format="json")

        assert out_path.exists()
        data = json.loads(out_path.read_text())
        assert isinstance(data, list)
        assert len(data) == 5

    def test_export_json_structure(self, export_db: CatalogDB, tmp_path: Path) -> None:
        export_catalog = _get_export_func()
        out_path = tmp_path / "export.json"
        export_catalog(export_db, tmp_path, out_path, format="json")

        data = json.loads(out_path.read_text())
        expected_fields = {"file_path", "filename", "date_taken", "ai_caption", "ai_tags"}

        for item in data:
            missing = expected_fields - set(item.keys())
            assert not missing, f"JSON item missing fields: {missing}"

    def test_export_json_with_filter(self, export_db: CatalogDB, tmp_path: Path) -> None:
        export_catalog = _get_export_func()
        out_path = tmp_path / "filtered.json"
        export_catalog(export_db, tmp_path, out_path, format="json", filters={"year": 2023})

        data = json.loads(out_path.read_text())
        # Only 2023 images: beach (2023-07), city (2023-08), screenshot (2023-05)
        assert len(data) == 3
        for item in data:
            assert "2023" in item.get("date_taken", ""), \
                f"Non-2023 image in filtered export: {item.get('file_path')}"


# ==================================================================
# TestExportCSV
# ==================================================================

class TestExportCSV:
    """Verify CSV export produces valid files with correct structure."""

    def test_export_csv(self, export_db: CatalogDB, tmp_path: Path) -> None:
        export_catalog = _get_export_func()
        out_path = tmp_path / "export.csv"
        export_catalog(export_db, tmp_path, out_path, format="csv")

        assert out_path.exists()
        text = out_path.read_text()
        reader = csv.reader(StringIO(text))
        rows = list(reader)

        # Header + 5 data rows
        assert len(rows) == 6, f"Expected 6 rows (1 header + 5 data), got {len(rows)}"
        # Header row should have column names
        header = rows[0]
        assert "file_path" in header
        assert "filename" in header

    def test_export_csv_tags_flattened(self, export_db: CatalogDB, tmp_path: Path) -> None:
        export_catalog = _get_export_func()
        out_path = tmp_path / "export.csv"
        export_catalog(export_db, tmp_path, out_path, format="csv")

        text = out_path.read_text()
        reader = csv.DictReader(StringIO(text))
        rows = list(reader)

        for row in rows:
            tags_value = row.get("ai_tags", row.get("tags", ""))
            if tags_value:
                # Tags should be comma-separated strings, NOT raw JSON
                # e.g., "beach, ocean" instead of '[{"label":"beach","score":0.9}]'
                assert "[{" not in tags_value, \
                    f"Tags appear to be raw JSON instead of flattened: {tags_value}"


# ==================================================================
# TestExportGeneral
# ==================================================================

class TestExportGeneral:
    """Verify return values and edge cases for export."""

    def test_export_returns_count(self, export_db: CatalogDB, tmp_path: Path) -> None:
        export_catalog = _get_export_func()
        out_dir = tmp_path / "export_out"
        out_dir.mkdir()
        out_path = out_dir / "export.json"
        count = export_catalog(export_db, tmp_path, out_path, format="json")

        assert count == 5

    def test_export_empty_db(self, empty_db: CatalogDB, tmp_path: Path) -> None:
        export_catalog = _get_export_func()

        # JSON: empty list
        json_path = tmp_path / "empty.json"
        count = export_catalog(empty_db, tmp_path, json_path, format="json")
        assert count == 0
        data = json.loads(json_path.read_text())
        assert data == []

        # CSV: header only
        csv_path = tmp_path / "empty.csv"
        count = export_catalog(empty_db, tmp_path, csv_path, format="csv")
        assert count == 0
        text = csv_path.read_text()
        reader = csv.reader(StringIO(text))
        rows = list(reader)
        # Should have header row but no data rows
        assert len(rows) <= 1

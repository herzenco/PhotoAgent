"""Tests for photoagent.search — ImageSearcher text search and filters.

These tests validate text-based search across tags, captions, locations,
and filenames, as well as filtering by year, location, quality, type,
camera, and combined criteria.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Generator

import pytest

from photoagent.database import CatalogDB


# ------------------------------------------------------------------
# Helper: insert a fully-specified image record
# ------------------------------------------------------------------

def _make_record(
    *,
    file_path: str,
    filename: str,
    extension: str = ".jpg",
    date_taken: str | None = None,
    city: str | None = None,
    country: str | None = None,
    camera_make: str | None = None,
    camera_model: str | None = None,
    ai_tags: str | None = None,
    ai_caption: str | None = None,
    ai_quality_score: float | None = None,
    ai_scene_type: str | None = None,
    is_screenshot: bool = False,
    is_duplicate_of: int | None = None,
    face_count: int = 0,
) -> dict[str, Any]:
    return {
        "file_path": file_path,
        "filename": filename,
        "extension": extension,
        "date_taken": date_taken,
        "city": city,
        "country": country,
        "camera_make": camera_make,
        "camera_model": camera_model,
        "ai_tags": ai_tags,
        "ai_caption": ai_caption,
        "ai_quality_score": ai_quality_score,
        "ai_scene_type": ai_scene_type,
        "is_screenshot": is_screenshot,
        "is_duplicate_of": is_duplicate_of,
        "face_count": face_count,
        "analyzed_at": "2024-01-01 00:00:00",
    }


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def search_db(tmp_path: Path) -> Generator[CatalogDB, None, None]:
    """CatalogDB pre-populated with ~10 varied images for search tests."""
    db = CatalogDB(tmp_path)

    records = [
        _make_record(
            file_path="/photos/beach_day.jpg",
            filename="beach_day.jpg",
            date_taken="2023-07-15 10:00:00",
            city="Nice",
            country="France",
            camera_make="Canon",
            camera_model="EOS R5",
            ai_tags=json.dumps([{"label": "beach", "score": 0.95}, {"label": "ocean", "score": 0.8}]),
            ai_caption="A beautiful sandy beach with clear blue water",
            ai_quality_score=0.9,
            ai_scene_type="outdoor",
        ),
        _make_record(
            file_path="/photos/sunset_paris.jpg",
            filename="sunset_paris.jpg",
            date_taken="2023-08-20 19:30:00",
            city="Paris",
            country="France",
            camera_make="Canon",
            camera_model="EOS R5",
            ai_tags=json.dumps([{"label": "sunset", "score": 0.9}, {"label": "city", "score": 0.7}]),
            ai_caption="Stunning sunset over the Eiffel Tower in Paris",
            ai_quality_score=0.85,
            ai_scene_type="outdoor",
        ),
        _make_record(
            file_path="/photos/birthday_party.jpg",
            filename="birthday_party.jpg",
            date_taken="2023-03-10 15:00:00",
            city="London",
            country="UK",
            camera_make="Apple",
            camera_model="iPhone 15 Pro",
            ai_tags=json.dumps([{"label": "party", "score": 0.85}, {"label": "people", "score": 0.9}]),
            ai_caption="A group of friends celebrating a birthday",
            ai_quality_score=0.7,
            ai_scene_type="indoor",
        ),
        _make_record(
            file_path="/photos/mountain_hike.jpg",
            filename="mountain_hike.jpg",
            date_taken="2022-09-05 08:00:00",
            city="Chamonix",
            country="France",
            camera_make="Sony",
            camera_model="A7IV",
            ai_tags=json.dumps([{"label": "mountain", "score": 0.95}, {"label": "hiking", "score": 0.8}]),
            ai_caption="Mountain trail with stunning alpine views",
            ai_quality_score=0.92,
            ai_scene_type="outdoor",
        ),
        _make_record(
            file_path="/photos/bad_photo.jpg",
            filename="bad_photo.jpg",
            date_taken="2022-11-01 12:00:00",
            city="Berlin",
            country="Germany",
            camera_make="Apple",
            camera_model="iPhone 12",
            ai_tags=json.dumps([{"label": "blurry", "score": 0.6}]),
            ai_caption="An out of focus photo of a street",
            ai_quality_score=0.2,
            ai_scene_type="outdoor",
        ),
        _make_record(
            file_path="/photos/screenshot_chat.png",
            filename="screenshot_chat.png",
            extension=".png",
            date_taken="2023-05-20 09:00:00",
            camera_make="Apple",
            camera_model="iPhone 15 Pro",
            ai_tags=json.dumps([{"label": "text", "score": 0.9}]),
            ai_caption="Screenshot of a chat conversation",
            ai_quality_score=0.5,
            is_screenshot=True,
        ),
        _make_record(
            file_path="/photos/paris_cafe.jpg",
            filename="paris_cafe.jpg",
            date_taken="2023-06-01 13:00:00",
            city="Paris",
            country="France",
            camera_make="Sony",
            camera_model="A7IV",
            ai_tags=json.dumps([{"label": "cafe", "score": 0.85}, {"label": "food", "score": 0.7}]),
            ai_caption="A cozy Parisian cafe with fresh croissants",
            ai_quality_score=0.8,
            ai_scene_type="indoor",
        ),
        _make_record(
            file_path="/photos/beach_sunset.jpg",
            filename="beach_sunset.jpg",
            date_taken="2022-06-20 18:30:00",
            city="Malibu",
            country="USA",
            camera_make="Canon",
            camera_model="EOS R5",
            ai_tags=json.dumps([{"label": "beach", "score": 0.9}, {"label": "sunset", "score": 0.85}]),
            ai_caption="Sunset at a California beach with surfers",
            ai_quality_score=0.88,
            ai_scene_type="outdoor",
        ),
        _make_record(
            file_path="/photos/cat_portrait.jpg",
            filename="cat_portrait.jpg",
            date_taken="2023-01-15 11:00:00",
            city="London",
            country="UK",
            camera_make="Apple",
            camera_model="iPhone 15 Pro",
            ai_tags=json.dumps([{"label": "cat", "score": 0.95}, {"label": "pet", "score": 0.9}]),
            ai_caption="A fluffy orange cat sitting on a windowsill",
            ai_quality_score=0.75,
            ai_scene_type="indoor",
        ),
        _make_record(
            file_path="/photos/screenshot_map.png",
            filename="screenshot_map.png",
            extension=".png",
            date_taken="2022-12-10 16:00:00",
            camera_make="Apple",
            camera_model="iPhone 12",
            ai_tags=json.dumps([{"label": "map", "score": 0.8}]),
            ai_caption="Screenshot of a Google Maps route",
            ai_quality_score=0.4,
            is_screenshot=True,
        ),
    ]

    for rec in records:
        db.insert_image(rec)

    yield db
    db.close()


# ------------------------------------------------------------------
# Lazy import of ImageSearcher (module may not exist yet)
# ------------------------------------------------------------------

def _get_searcher_class():
    """Import ImageSearcher; skip test if module not available."""
    try:
        from photoagent.search import ImageSearcher
        return ImageSearcher
    except ImportError:
        pytest.skip("photoagent.search not yet implemented")


# ==================================================================
# TestTextSearch
# ==================================================================

class TestTextSearch:
    """Verify text-based search across tags, captions, locations, filenames."""

    def test_search_by_tag(self, search_db: CatalogDB, tmp_path: Path) -> None:
        ImageSearcher = _get_searcher_class()
        searcher = ImageSearcher(search_db, tmp_path)
        results = searcher.search("beach")

        assert len(results) >= 2
        paths = [r["file_path"] for r in results]
        assert "/photos/beach_day.jpg" in paths
        assert "/photos/beach_sunset.jpg" in paths
        # Beach images should be ranked first (highest relevance)
        top_paths = [r["file_path"] for r in results[:2]]
        assert "/photos/beach_day.jpg" in top_paths or "/photos/beach_sunset.jpg" in top_paths

    def test_search_by_caption(self, search_db: CatalogDB, tmp_path: Path) -> None:
        ImageSearcher = _get_searcher_class()
        searcher = ImageSearcher(search_db, tmp_path)
        results = searcher.search("sunset")

        assert len(results) >= 2
        paths = [r["file_path"] for r in results]
        assert "/photos/sunset_paris.jpg" in paths
        assert "/photos/beach_sunset.jpg" in paths

    def test_search_by_location(self, search_db: CatalogDB, tmp_path: Path) -> None:
        ImageSearcher = _get_searcher_class()
        searcher = ImageSearcher(search_db, tmp_path)
        results = searcher.search("Paris")

        assert len(results) >= 2
        paths = [r["file_path"] for r in results]
        assert "/photos/sunset_paris.jpg" in paths
        assert "/photos/paris_cafe.jpg" in paths

    def test_search_by_filename(self, search_db: CatalogDB, tmp_path: Path) -> None:
        ImageSearcher = _get_searcher_class()
        searcher = ImageSearcher(search_db, tmp_path)
        results = searcher.search("birthday")

        assert len(results) >= 1
        paths = [r["file_path"] for r in results]
        assert "/photos/birthday_party.jpg" in paths

    def test_search_no_results(self, search_db: CatalogDB, tmp_path: Path) -> None:
        ImageSearcher = _get_searcher_class()
        searcher = ImageSearcher(search_db, tmp_path)
        results = searcher.search("xyznonexistent")

        assert results == []

    def test_search_returns_required_fields(self, search_db: CatalogDB, tmp_path: Path) -> None:
        ImageSearcher = _get_searcher_class()
        searcher = ImageSearcher(search_db, tmp_path)
        results = searcher.search("beach")

        assert len(results) > 0
        required = {"id", "file_path", "filename", "score", "caption", "tags", "match_reason"}
        for result in results:
            missing = required - set(result.keys())
            assert not missing, f"Result missing fields: {missing}"


# ==================================================================
# TestSearchFilters
# ==================================================================

class TestSearchFilters:
    """Verify filtering by year, location, quality, type, camera, and combos."""

    def test_filter_by_year(self, search_db: CatalogDB, tmp_path: Path) -> None:
        ImageSearcher = _get_searcher_class()
        searcher = ImageSearcher(search_db, tmp_path)
        results = searcher.search("", filters={"year": 2023})

        assert len(results) > 0
        for r in results:
            # All returned images must be from 2023
            img = search_db.get_image_by_path(r["file_path"])
            assert img is not None
            assert img["date_taken"].startswith("2023")

        # Ensure no 2022 images sneaked in
        paths = [r["file_path"] for r in results]
        assert "/photos/mountain_hike.jpg" not in paths
        assert "/photos/bad_photo.jpg" not in paths

    def test_filter_by_location(self, search_db: CatalogDB, tmp_path: Path) -> None:
        ImageSearcher = _get_searcher_class()
        searcher = ImageSearcher(search_db, tmp_path)
        results = searcher.search("", filters={"location": "Paris"})

        assert len(results) >= 2
        paths = [r["file_path"] for r in results]
        assert "/photos/sunset_paris.jpg" in paths
        assert "/photos/paris_cafe.jpg" in paths
        # Non-Paris images excluded
        assert "/photos/birthday_party.jpg" not in paths

    def test_filter_by_min_quality(self, search_db: CatalogDB, tmp_path: Path) -> None:
        ImageSearcher = _get_searcher_class()
        searcher = ImageSearcher(search_db, tmp_path)
        results = searcher.search("", filters={"min_quality": 0.5})

        paths = [r["file_path"] for r in results]
        # Low quality (0.2) must be excluded
        assert "/photos/bad_photo.jpg" not in paths
        # High quality should be present
        assert "/photos/beach_day.jpg" in paths

    def test_filter_by_type_screenshot(self, search_db: CatalogDB, tmp_path: Path) -> None:
        ImageSearcher = _get_searcher_class()
        searcher = ImageSearcher(search_db, tmp_path)
        results = searcher.search("", filters={"type": "screenshot"})

        assert len(results) == 2
        paths = [r["file_path"] for r in results]
        assert "/photos/screenshot_chat.png" in paths
        assert "/photos/screenshot_map.png" in paths

    def test_filter_by_type_photo(self, search_db: CatalogDB, tmp_path: Path) -> None:
        ImageSearcher = _get_searcher_class()
        searcher = ImageSearcher(search_db, tmp_path)
        results = searcher.search("", filters={"type": "photo"})

        paths = [r["file_path"] for r in results]
        # No screenshots should appear
        assert "/photos/screenshot_chat.png" not in paths
        assert "/photos/screenshot_map.png" not in paths
        # Regular photos should be present
        assert len(results) >= 5

    def test_filter_by_camera(self, search_db: CatalogDB, tmp_path: Path) -> None:
        ImageSearcher = _get_searcher_class()
        searcher = ImageSearcher(search_db, tmp_path)
        results = searcher.search("", filters={"camera": "iPhone"})

        assert len(results) >= 3
        for r in results:
            img = search_db.get_image_by_path(r["file_path"])
            assert img is not None
            assert "iPhone" in (img["camera_model"] or "")

    def test_combined_filters(self, search_db: CatalogDB, tmp_path: Path) -> None:
        ImageSearcher = _get_searcher_class()
        searcher = ImageSearcher(search_db, tmp_path)
        results = searcher.search("", filters={"year": 2023, "location": "Paris"})

        assert len(results) >= 2
        paths = [r["file_path"] for r in results]
        assert "/photos/sunset_paris.jpg" in paths
        assert "/photos/paris_cafe.jpg" in paths
        # 2022 images and non-Paris images excluded
        assert "/photos/mountain_hike.jpg" not in paths
        assert "/photos/birthday_party.jpg" not in paths

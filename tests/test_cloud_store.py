"""Tests for photoagent.cloud.store — SQLite persistence layer."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

import pytest

from photoagent.cloud.models import CloudAnalysisResult
from photoagent.cloud.store import (
    ensure_table,
    get_analyzed_paths,
    get_db_path,
    get_stats,
    save_result,
    search_cloud,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_result(
    image_path: str = "/photos/IMG_0001.jpg",
    category: str = "landscape",
    subcategory: str = "general",
    subject: str = "test subject",
    mood: str = "neutral",
    tags: list[str] | None = None,
    quality_note: str | None = None,
    model: str = "claude-haiku-4-5-20251001",
    input_tokens: int = 150,
    output_tokens: int = 60,
    thumb_byte_size: int = 8192,
    analyzed_at: str | None = None,
) -> CloudAnalysisResult:
    """Build a CloudAnalysisResult with sensible defaults."""
    return CloudAnalysisResult(
        image_path=image_path,
        category=category,
        subcategory=subcategory,
        subject=subject,
        mood=mood,
        tags=tags or ["mountain", "snow"],
        quality_note=quality_note,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        thumb_byte_size=thumb_byte_size,
        analyzed_at=analyzed_at or datetime.now(timezone.utc).isoformat(),
    )


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def db() -> sqlite3.Connection:
    """Return an in-memory SQLite connection with the cloud_analysis table."""
    conn = sqlite3.connect(":memory:")
    ensure_table(conn)
    return conn


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


class TestEnsureTable:
    """Tests for ensure_table."""

    def test_ensure_table_creates(self) -> None:
        """ensure_table should create the cloud_analysis table."""
        conn = sqlite3.connect(":memory:")
        ensure_table(conn)

        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='cloud_analysis'"
        ).fetchall()
        assert len(tables) == 1
        assert tables[0][0] == "cloud_analysis"
        conn.close()

    def test_ensure_table_idempotent(self) -> None:
        """Calling ensure_table twice should not raise."""
        conn = sqlite3.connect(":memory:")
        ensure_table(conn)
        ensure_table(conn)  # second call — should not raise

        count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='cloud_analysis'"
        ).fetchone()[0]
        assert count == 1
        conn.close()


class TestSaveAndRetrieve:
    """Tests for save_result and direct SELECT verification."""

    def test_save_and_retrieve(self, db: sqlite3.Connection) -> None:
        """A saved result can be retrieved with matching fields."""
        result = _make_result(
            image_path="/photos/sunset.jpg",
            category="landscape",
            subcategory="beach",
            subject="sunset over ocean",
            mood="calm",
            tags=["sunset", "ocean", "beach"],
            quality_note="slightly overexposed",
            input_tokens=200,
            output_tokens=80,
        )
        save_result(db, result)

        row = db.execute(
            "SELECT * FROM cloud_analysis WHERE image_path = ?",
            (result.image_path,),
        ).fetchone()

        assert row is not None
        # Columns: image_path, category, subcategory, subject, mood, tags,
        #          quality_note, model, input_tokens, output_tokens,
        #          thumb_byte_size, analyzed_at
        assert row[0] == "/photos/sunset.jpg"
        assert row[1] == "landscape"
        assert row[2] == "beach"
        assert row[3] == "sunset over ocean"
        assert row[4] == "calm"
        assert json.loads(row[5]) == ["sunset", "ocean", "beach"]
        assert row[6] == "slightly overexposed"
        assert row[7] == result.model
        assert row[8] == 200
        assert row[9] == 80

    def test_save_replaces_existing(self, db: sqlite3.Connection) -> None:
        """Saving a result for the same path replaces the old row."""
        path = "/photos/IMG_0001.jpg"

        original = _make_result(image_path=path, category="portrait")
        save_result(db, original)

        updated = _make_result(image_path=path, category="landscape")
        save_result(db, updated)

        count = db.execute(
            "SELECT COUNT(*) FROM cloud_analysis WHERE image_path = ?", (path,)
        ).fetchone()[0]
        assert count == 1

        row = db.execute(
            "SELECT category FROM cloud_analysis WHERE image_path = ?", (path,)
        ).fetchone()
        assert row[0] == "landscape"


class TestGetAnalyzedPaths:
    """Tests for get_analyzed_paths."""

    def test_get_analyzed_paths(self, db: sqlite3.Connection) -> None:
        """Returns the set of all analyzed image paths."""
        paths = ["/a.jpg", "/b.jpg", "/c.jpg"]
        for p in paths:
            save_result(db, _make_result(image_path=p))

        result = get_analyzed_paths(db)
        assert result == set(paths)

    def test_get_analyzed_paths_empty(self, db: sqlite3.Connection) -> None:
        """Empty table returns an empty set."""
        result = get_analyzed_paths(db)
        assert result == set()


class TestSearchCloud:
    """Tests for search_cloud."""

    def test_search_by_category(self, db: sqlite3.Connection) -> None:
        """Search by category returns only matching rows."""
        save_result(db, _make_result(image_path="/land.jpg", category="landscape"))
        save_result(db, _make_result(image_path="/port.jpg", category="portrait"))

        results = search_cloud(db, "landscape")
        assert len(results) == 1
        assert results[0]["image_path"] == "/land.jpg"
        assert results[0]["category"] == "landscape"

    def test_search_by_tags(self, db: sqlite3.Connection) -> None:
        """Search matches against JSON-encoded tags column."""
        save_result(
            db,
            _make_result(
                image_path="/mountain.jpg",
                tags=["mountain", "snow"],
                category="landscape",
                subcategory="alpine",
                subject="rocky peak",
                mood="serene",
            ),
        )
        save_result(
            db,
            _make_result(
                image_path="/city.jpg",
                tags=["urban", "night"],
                category="cityscape",
                subcategory="skyline",
                subject="city lights",
                mood="vibrant",
            ),
        )

        results = search_cloud(db, "mountain")
        assert len(results) == 1
        assert results[0]["image_path"] == "/mountain.jpg"

    def test_search_by_subject(self, db: sqlite3.Connection) -> None:
        """Search matches against the subject column."""
        save_result(
            db,
            _make_result(
                image_path="/bridge.jpg",
                subject="golden gate bridge",
            ),
        )

        results = search_cloud(db, "bridge")
        assert len(results) == 1
        assert results[0]["image_path"] == "/bridge.jpg"

    def test_search_no_results(self, db: sqlite3.Connection) -> None:
        """A query with no matches returns an empty list."""
        save_result(db, _make_result(image_path="/a.jpg"))

        results = search_cloud(db, "xyznonexistent")
        assert results == []


class TestGetStats:
    """Tests for get_stats."""

    def test_get_stats(self, db: sqlite3.Connection) -> None:
        """Stats reflect correct totals, token sums, and category breakdown."""
        # 3 landscapes, 2 portraits — 5 total
        for i in range(3):
            save_result(
                db,
                _make_result(
                    image_path=f"/land_{i}.jpg",
                    category="landscape",
                    input_tokens=100,
                    output_tokens=40,
                ),
            )
        for i in range(2):
            save_result(
                db,
                _make_result(
                    image_path=f"/port_{i}.jpg",
                    category="portrait",
                    input_tokens=200,
                    output_tokens=60,
                ),
            )

        stats = get_stats(db)

        assert stats["total_analyzed"] == 5
        # 3*100 + 2*200 = 700
        assert stats["total_input_tokens"] == 700
        # 3*40 + 2*60 = 240
        assert stats["total_output_tokens"] == 240
        assert stats["category_breakdown"]["landscape"] == 3
        assert stats["category_breakdown"]["portrait"] == 2


class TestGetDbPath:
    """Tests for get_db_path."""

    def test_get_db_path(self) -> None:
        """get_db_path returns <photo_path>/.photoagent/catalog.db."""
        from pathlib import Path

        result = get_db_path("/home/user/photos")
        assert result == Path("/home/user/photos/.photoagent/catalog.db")

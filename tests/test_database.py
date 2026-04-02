"""Tests for photoagent.database.CatalogDB.

Verifies schema creation, CRUD operations, statistics aggregation,
incremental rescan logic, and SQLite configuration (WAL mode).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from photoagent.database import CatalogDB


# ------------------------------------------------------------------
# Schema / initialization
# ------------------------------------------------------------------


class TestCatalogDBSchema:
    """Tests that focus on database initialization and schema."""

    def test_create_tables(self, catalog_db: CatalogDB) -> None:
        """Verify that all four required tables exist after CatalogDB init."""
        rows = catalog_db._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = sorted(row["name"] for row in rows)
        for expected in ("duplicates", "faces", "images", "operations"):
            assert expected in table_names, f"Table '{expected}' not found"

    def test_wal_mode(self, catalog_db: CatalogDB) -> None:
        """Verify that WAL journal mode is enabled for concurrent-read performance."""
        mode = catalog_db._conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"

    def test_catalog_directory_creation(self, tmp_path: Path) -> None:
        """Verify that CatalogDB creates the .photoagent directory automatically."""
        data_dir = tmp_path / ".photoagent"
        assert not data_dir.exists()
        db = CatalogDB(tmp_path)
        assert data_dir.exists()
        assert (data_dir / "catalog.db").exists()
        db.close()

    def test_context_manager(self, tmp_path: Path) -> None:
        """Verify __enter__ returns the db and __exit__ closes the connection."""
        with CatalogDB(tmp_path) as db:
            assert isinstance(db, CatalogDB)
            # Connection should be usable inside the context
            db._conn.execute("SELECT 1")
        # After exiting, the connection should be closed
        with pytest.raises(Exception):
            db._conn.execute("SELECT 1")


# ------------------------------------------------------------------
# Image CRUD
# ------------------------------------------------------------------


class TestImageCRUD:
    """Tests for inserting, updating, and querying image records."""

    def test_insert_image(
        self, catalog_db: CatalogDB, sample_image_record: dict
    ) -> None:
        """Insert a record and verify it is retrievable by path."""
        row_id = catalog_db.insert_image(sample_image_record)
        assert isinstance(row_id, int)
        assert row_id > 0

        result = catalog_db.get_image_by_path(sample_image_record["file_path"])
        assert result is not None
        assert result["filename"] == "IMG_0001.jpg"
        assert result["camera_model"] == "EOS R5"
        assert result["gps_lat"] == pytest.approx(48.8566)

    def test_insert_duplicate_path(
        self, catalog_db: CatalogDB, sample_image_record: dict
    ) -> None:
        """Inserting the same file_path a second time should raise IntegrityError.

        file_path has a UNIQUE constraint.
        """
        catalog_db.insert_image(sample_image_record)
        with pytest.raises(sqlite3.IntegrityError):
            catalog_db.insert_image(sample_image_record)

    def test_update_image(
        self, catalog_db: CatalogDB, sample_image_record: dict
    ) -> None:
        """Insert then update fields, verify updated values are persisted."""
        row_id = catalog_db.insert_image(sample_image_record)

        catalog_db.update_image(
            row_id,
            ai_caption="A sunset over the Eiffel Tower",
            ai_quality_score=0.92,
            analyzed_at="2023-07-01 10:00:00",
        )

        result = catalog_db.get_image_by_path(sample_image_record["file_path"])
        assert result is not None
        assert result["ai_caption"] == "A sunset over the Eiffel Tower"
        assert result["ai_quality_score"] == pytest.approx(0.92)
        assert result["analyzed_at"] == "2023-07-01 10:00:00"

    def test_update_image_no_fields(self, catalog_db: CatalogDB) -> None:
        """Calling update_image with no fields should be a no-op (no error)."""
        catalog_db.update_image(999)  # non-existent id, no fields

    def test_get_image_by_path_found(
        self, catalog_db: CatalogDB, sample_image_record: dict
    ) -> None:
        """Verify get_image_by_path returns the record when it exists."""
        catalog_db.insert_image(sample_image_record)
        result = catalog_db.get_image_by_path(sample_image_record["file_path"])
        assert result is not None
        assert result["file_path"] == sample_image_record["file_path"]

    def test_get_image_by_path_not_found(self, catalog_db: CatalogDB) -> None:
        """Verify get_image_by_path returns None for a non-existent path."""
        result = catalog_db.get_image_by_path("/no/such/file.jpg")
        assert result is None


# ------------------------------------------------------------------
# Filtering / querying
# ------------------------------------------------------------------


class TestImageQueries:
    """Tests for filtered queries (unanalyzed, get_all, etc.)."""

    def test_get_unanalyzed(
        self, catalog_db: CatalogDB, sample_image_record: dict
    ) -> None:
        """Insert images with and without analyzed_at; verify filtering."""
        # Image 1: not analyzed
        rec1 = {**sample_image_record, "file_path": "/photos/a.jpg"}
        id1 = catalog_db.insert_image(rec1)

        # Image 2: analyzed
        rec2 = {**sample_image_record, "file_path": "/photos/b.jpg"}
        id2 = catalog_db.insert_image(rec2)
        catalog_db.update_image(id2, analyzed_at="2023-07-01 10:00:00")

        # Image 3: not analyzed
        rec3 = {**sample_image_record, "file_path": "/photos/c.jpg"}
        catalog_db.insert_image(rec3)

        unanalyzed = catalog_db.get_unanalyzed()
        unanalyzed_paths = {r["file_path"] for r in unanalyzed}
        assert "/photos/a.jpg" in unanalyzed_paths
        assert "/photos/c.jpg" in unanalyzed_paths
        assert "/photos/b.jpg" not in unanalyzed_paths

    def test_get_all_images(
        self, catalog_db: CatalogDB, sample_image_record: dict
    ) -> None:
        """Insert multiple images and verify get_all_images returns all of them."""
        for i in range(5):
            rec = {**sample_image_record, "file_path": f"/photos/img_{i}.jpg"}
            catalog_db.insert_image(rec)

        all_images = catalog_db.get_all_images()
        assert len(all_images) == 5


# ------------------------------------------------------------------
# Statistics
# ------------------------------------------------------------------


class TestStatistics:
    """Tests for get_stats() aggregation."""

    def test_get_stats_empty(self, catalog_db: CatalogDB) -> None:
        """Stats on an empty catalog should return all zeros / empty dicts."""
        stats = catalog_db.get_stats()
        assert stats["total_images"] == 0
        assert stats["analyzed_count"] == 0
        assert stats["duplicate_count"] == 0
        assert stats["screenshot_count"] == 0
        assert stats["total_disk_usage"] == 0
        assert stats["by_year"] == {}
        assert stats["by_camera"] == {}
        assert stats["by_location"] == {}

    def test_get_stats_with_data(
        self, catalog_db: CatalogDB, sample_image_record: dict
    ) -> None:
        """Verify stats calculations with varied data."""
        # Image 1: Paris, 2023, Canon EOS R5
        rec1 = {**sample_image_record, "file_path": "/a.jpg", "file_size": 1000}
        id1 = catalog_db.insert_image(rec1)
        catalog_db.update_image(id1, analyzed_at="2023-07-01 10:00:00")

        # Image 2: same camera, different year
        rec2 = {
            **sample_image_record,
            "file_path": "/b.jpg",
            "file_size": 2000,
            "date_taken": "2022-01-01 12:00:00",
        }
        catalog_db.insert_image(rec2)

        # Image 3: screenshot
        rec3 = {
            **sample_image_record,
            "file_path": "/c.jpg",
            "file_size": 500,
            "is_screenshot": True,
            "camera_model": None,
            "city": None,
            "country": None,
            "date_taken": None,
        }
        catalog_db.insert_image(rec3)

        # Image 4: duplicate
        rec4 = {
            **sample_image_record,
            "file_path": "/d.jpg",
            "file_size": 1000,
            "is_duplicate_of": id1,
        }
        catalog_db.insert_image(rec4)

        stats = catalog_db.get_stats()
        assert stats["total_images"] == 4
        assert stats["analyzed_count"] == 1
        assert stats["duplicate_count"] == 1
        assert stats["screenshot_count"] == 1
        assert stats["total_disk_usage"] == 4500

        # Year breakdown
        assert "2023" in stats["by_year"]
        assert "2022" in stats["by_year"]

        # Camera breakdown
        assert "EOS R5" in stats["by_camera"]

        # Location breakdown
        assert any("Paris" in loc for loc in stats["by_location"])


# ------------------------------------------------------------------
# Rescan logic
# ------------------------------------------------------------------


class TestRescan:
    """Tests for image_needs_rescan()."""

    def test_image_needs_rescan_new_file(self, catalog_db: CatalogDB) -> None:
        """A file not in the catalog always needs scanning."""
        assert catalog_db.image_needs_rescan("/photos/new.jpg", 1234567890.0) is True

    def test_image_needs_rescan_same_mtime(
        self, catalog_db: CatalogDB, sample_image_record: dict
    ) -> None:
        """A file with the same modification time should NOT need rescanning."""
        mtime = 1700000000.0
        rec = {**sample_image_record, "file_modified": str(mtime)}
        catalog_db.insert_image(rec)

        needs = catalog_db.image_needs_rescan(rec["file_path"], mtime)
        assert needs is False

    def test_image_needs_rescan_different_mtime(
        self, catalog_db: CatalogDB, sample_image_record: dict
    ) -> None:
        """A file whose modification time has changed SHOULD need rescanning."""
        old_mtime = 1700000000.0
        rec = {**sample_image_record, "file_modified": str(old_mtime)}
        catalog_db.insert_image(rec)

        new_mtime = 1700099999.0
        needs = catalog_db.image_needs_rescan(rec["file_path"], new_mtime)
        assert needs is True

    def test_image_needs_rescan_null_mtime(
        self, catalog_db: CatalogDB, sample_image_record: dict
    ) -> None:
        """If stored file_modified is NULL, the file needs rescanning."""
        rec = {**sample_image_record}
        rec.pop("file_modified", None)
        catalog_db.insert_image(rec)

        needs = catalog_db.image_needs_rescan(rec["file_path"], 1700000000.0)
        assert needs is True

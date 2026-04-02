"""Catalog database layer for PhotoAgent.

Manages the SQLite database that stores image metadata, face embeddings,
duplicate groups, and operation history.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Optional


class CatalogDB:
    """SQLite-backed catalog for image metadata and analysis results."""

    def __init__(self, base_path: Path) -> None:
        self._base_path = Path(base_path)
        self._data_dir = self._base_path / ".photoagent"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._data_dir / "catalog.db"
        self._conn: sqlite3.Connection = sqlite3.connect(
            str(self._db_path),
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "CatalogDB":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _create_tables(self) -> None:
        cur = self._conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS images (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path       TEXT UNIQUE NOT NULL,
                filename        TEXT NOT NULL,
                extension       TEXT NOT NULL,
                file_size       INTEGER,
                file_md5        TEXT,
                perceptual_hash TEXT,
                date_taken      DATETIME,
                gps_lat         REAL,
                gps_lon         REAL,
                city            TEXT,
                country         TEXT,
                camera_make     TEXT,
                camera_model    TEXT,
                lens            TEXT,
                iso             INTEGER,
                aperture        REAL,
                shutter_speed   TEXT,
                flash_used      BOOLEAN,
                orientation     INTEGER,
                file_created    DATETIME,
                file_modified   DATETIME,
                ai_caption      TEXT,
                ai_tags         TEXT,
                ai_scene_type   TEXT,
                ai_quality_score REAL,
                is_screenshot   BOOLEAN DEFAULT FALSE,
                is_duplicate_of INTEGER REFERENCES images(id),
                face_count      INTEGER DEFAULT 0,
                organization_status TEXT DEFAULT 'pending',
                scanned_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
                analyzed_at     DATETIME
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS faces (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                image_id      INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
                embedding     BLOB NOT NULL,
                bbox_x        REAL,
                bbox_y        REAL,
                bbox_w        REAL,
                bbox_h        REAL,
                cluster_id    INTEGER,
                cluster_label TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS duplicates (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id   INTEGER NOT NULL,
                image_id   INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
                is_primary BOOLEAN NOT NULL DEFAULT FALSE
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS operations (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp     DATETIME DEFAULT CURRENT_TIMESTAMP,
                instruction   TEXT,
                manifest_json TEXT,
                status        TEXT DEFAULT 'pending',
                completed_at  DATETIME
            )
        """)

        self._conn.commit()

    # ------------------------------------------------------------------
    # Image CRUD
    # ------------------------------------------------------------------

    def insert_image(self, record: dict[str, Any]) -> int:
        """Insert a new image record and return its id."""
        columns = ", ".join(record.keys())
        placeholders = ", ".join(["?"] * len(record))
        cur = self._conn.execute(
            f"INSERT INTO images ({columns}) VALUES ({placeholders})",
            list(record.values()),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def update_image(self, image_id: int, **fields: Any) -> None:
        """Update arbitrary fields on an image row."""
        if not fields:
            return
        set_clause = ", ".join(f"{col} = ?" for col in fields)
        self._conn.execute(
            f"UPDATE images SET {set_clause} WHERE id = ?",
            [*fields.values(), image_id],
        )
        self._conn.commit()

    def get_image_by_path(self, path: str) -> Optional[dict[str, Any]]:
        """Return an image record by its file_path, or None."""
        row = self._conn.execute(
            "SELECT * FROM images WHERE file_path = ?", (path,)
        ).fetchone()
        return dict(row) if row else None

    def get_unanalyzed(self) -> list[dict[str, Any]]:
        """Return all images that have not been analyzed yet."""
        rows = self._conn.execute(
            "SELECT * FROM images WHERE analyzed_at IS NULL"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_images(self) -> list[dict[str, Any]]:
        """Return every image record."""
        rows = self._conn.execute("SELECT * FROM images").fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Aggregate statistics for the catalog."""
        cur = self._conn.cursor()

        total_images: int = cur.execute(
            "SELECT COUNT(*) FROM images"
        ).fetchone()[0]

        analyzed_count: int = cur.execute(
            "SELECT COUNT(*) FROM images WHERE analyzed_at IS NOT NULL"
        ).fetchone()[0]

        by_year: dict[str, int] = {}
        for row in cur.execute(
            "SELECT strftime('%Y', date_taken) AS yr, COUNT(*) AS cnt "
            "FROM images WHERE date_taken IS NOT NULL GROUP BY yr ORDER BY yr"
        ).fetchall():
            by_year[row["yr"]] = row["cnt"]

        by_camera: dict[str, int] = {}
        for row in cur.execute(
            "SELECT camera_model, COUNT(*) AS cnt FROM images "
            "WHERE camera_model IS NOT NULL GROUP BY camera_model ORDER BY cnt DESC"
        ).fetchall():
            by_camera[row["camera_model"]] = row["cnt"]

        by_location: dict[str, int] = {}
        for row in cur.execute(
            "SELECT city || ', ' || country AS loc, COUNT(*) AS cnt FROM images "
            "WHERE city IS NOT NULL AND country IS NOT NULL "
            "GROUP BY loc ORDER BY cnt DESC"
        ).fetchall():
            by_location[row["loc"]] = row["cnt"]

        duplicate_count: int = cur.execute(
            "SELECT COUNT(*) FROM images WHERE is_duplicate_of IS NOT NULL"
        ).fetchone()[0]

        screenshot_count: int = cur.execute(
            "SELECT COUNT(*) FROM images WHERE is_screenshot = TRUE"
        ).fetchone()[0]

        total_disk_usage: int = cur.execute(
            "SELECT COALESCE(SUM(file_size), 0) FROM images"
        ).fetchone()[0]

        return {
            "total_images": total_images,
            "analyzed_count": analyzed_count,
            "by_year": by_year,
            "by_camera": by_camera,
            "by_location": by_location,
            "duplicate_count": duplicate_count,
            "screenshot_count": screenshot_count,
            "total_disk_usage": total_disk_usage,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def image_needs_rescan(self, file_path: str, current_modified: float) -> bool:
        """Return True if the file is not in the catalog or has been modified."""
        row = self._conn.execute(
            "SELECT file_modified FROM images WHERE file_path = ?", (file_path,)
        ).fetchone()
        if row is None:
            return True
        stored = row["file_modified"]
        if stored is None:
            return True
        return float(stored) != current_modified

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

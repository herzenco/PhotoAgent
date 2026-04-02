"""Tests for photoagent.face_manager — FaceManager list/rename face clusters.

These tests validate listing face clusters with counts, renaming by ID
or label, and retrieving photos for a given person.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Generator

import pytest

from photoagent.database import CatalogDB


# ------------------------------------------------------------------
# Helper
# ------------------------------------------------------------------

def _insert_image(db: CatalogDB, file_path: str, filename: str) -> int:
    """Insert a minimal image record and return its id."""
    return db.insert_image({
        "file_path": file_path,
        "filename": filename,
        "extension": ".jpg",
        "analyzed_at": "2024-01-01 00:00:00",
    })


def _insert_face(
    db: CatalogDB,
    image_id: int,
    cluster_id: int,
    cluster_label: str | None = None,
) -> int:
    """Insert a face record directly via the DB connection."""
    # Use a dummy embedding (16 bytes of zeros)
    dummy_embedding = b"\x00" * 128
    cur = db._conn.execute(
        """INSERT INTO faces (image_id, embedding, bbox_x, bbox_y, bbox_w, bbox_h,
                              cluster_id, cluster_label)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (image_id, dummy_embedding, 0.1, 0.1, 0.3, 0.3, cluster_id, cluster_label),
    )
    db._conn.commit()
    return cur.lastrowid


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def face_db(tmp_path: Path) -> Generator[CatalogDB, None, None]:
    """CatalogDB with images and face records for face manager tests."""
    db = CatalogDB(tmp_path)

    # Create 5 images
    img1 = _insert_image(db, "/photos/family1.jpg", "family1.jpg")
    img2 = _insert_image(db, "/photos/family2.jpg", "family2.jpg")
    img3 = _insert_image(db, "/photos/group.jpg", "group.jpg")
    img4 = _insert_image(db, "/photos/portrait1.jpg", "portrait1.jpg")
    img5 = _insert_image(db, "/photos/portrait2.jpg", "portrait2.jpg")

    # Cluster 1: appears in 3 images (img1, img2, img3)
    _insert_face(db, img1, cluster_id=1, cluster_label="Person 1")
    _insert_face(db, img2, cluster_id=1, cluster_label="Person 1")
    _insert_face(db, img3, cluster_id=1, cluster_label="Person 1")

    # Cluster 2: appears in 2 images (img3, img4)
    _insert_face(db, img3, cluster_id=2, cluster_label="Person 2")
    _insert_face(db, img4, cluster_id=2, cluster_label="Person 2")

    # Cluster 3: appears in 1 image (img5)
    _insert_face(db, img5, cluster_id=3, cluster_label=None)

    yield db
    db.close()


@pytest.fixture
def empty_face_db(tmp_path: Path) -> Generator[CatalogDB, None, None]:
    """CatalogDB with images but no face records."""
    db_path = tmp_path / "empty_faces"
    db_path.mkdir()
    db = CatalogDB(db_path)
    _insert_image(db, "/photos/noface.jpg", "noface.jpg")
    yield db
    db.close()


# ------------------------------------------------------------------
# Lazy import
# ------------------------------------------------------------------

def _get_face_manager():
    try:
        from photoagent.face_manager import FaceManager
        return FaceManager
    except ImportError:
        pytest.skip("photoagent.face_manager not yet implemented")


# ==================================================================
# Tests
# ==================================================================

class TestFaceManager:
    """Verify face cluster listing, renaming, and photo retrieval."""

    def test_list_people_empty(self, empty_face_db: CatalogDB) -> None:
        FaceManager = _get_face_manager()
        fm = FaceManager(empty_face_db)
        people = fm.list_people()

        assert isinstance(people, list)
        assert len(people) == 0

    def test_list_people(self, face_db: CatalogDB) -> None:
        FaceManager = _get_face_manager()
        fm = FaceManager(face_db)
        people = fm.list_people()

        assert isinstance(people, list)
        assert len(people) == 3  # 3 clusters

        # Build a lookup by cluster_id
        by_id = {p["cluster_id"]: p for p in people}

        assert by_id[1]["photo_count"] == 3  # cluster 1: 3 face records
        assert by_id[2]["photo_count"] == 2  # cluster 2: 2 face records
        assert by_id[3]["photo_count"] == 1  # cluster 3: 1 face record

    def test_rename_person_by_id(self, face_db: CatalogDB) -> None:
        FaceManager = _get_face_manager()
        fm = FaceManager(face_db)

        fm.rename_person("1", "Alice")

        # Verify label updated in DB
        rows = face_db._conn.execute(
            "SELECT cluster_label FROM faces WHERE cluster_id = 1"
        ).fetchall()
        for row in rows:
            assert row["cluster_label"] == "Alice"

    def test_rename_person_by_label(self, face_db: CatalogDB) -> None:
        FaceManager = _get_face_manager()
        fm = FaceManager(face_db)

        # Rename "Person 1" to "Bob"
        fm.rename_person("Person 1", "Bob")

        rows = face_db._conn.execute(
            "SELECT cluster_label FROM faces WHERE cluster_id = 1"
        ).fetchall()
        for row in rows:
            assert row["cluster_label"] == "Bob"

    def test_rename_person_returns_count(self, face_db: CatalogDB) -> None:
        FaceManager = _get_face_manager()
        fm = FaceManager(face_db)

        count = fm.rename_person("1", "Carol")

        # Cluster 1 has 3 face records
        assert count == 3

    def test_get_person_photos(self, face_db: CatalogDB) -> None:
        FaceManager = _get_face_manager()
        fm = FaceManager(face_db)

        photos = fm.get_person_photos("1")

        assert isinstance(photos, list)
        # Cluster 1 appears in images: family1, family2, group
        paths = [p["file_path"] for p in photos]
        assert len(paths) == 3
        assert "/photos/family1.jpg" in paths
        assert "/photos/family2.jpg" in paths
        assert "/photos/group.jpg" in paths

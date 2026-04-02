"""Tests for photoagent.undo.UndoManager.

Verifies that executed file moves can be reversed, manifests are tracked,
operations table is updated, and history queries work correctly.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from photoagent.database import CatalogDB
from photoagent.models import ExecutionResult


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _md5(path: Path) -> str:
    """Compute MD5 hex digest of a file."""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _create_test_image(filepath: Path, color: str = "red", size: tuple[int, int] = (100, 100)) -> None:
    """Create a small JPEG image at the given path."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", size, color=color)
    img.save(str(filepath), "JPEG", quality=85)


def _build_plan(moves: list[dict[str, Any]], folders: list[str] | None = None) -> dict[str, Any]:
    """Build a plan dict in the expected format."""
    if folders is None:
        folders = sorted({str(Path(m["to"]).parent) for m in moves if str(Path(m["to"]).parent) != "."})
    return {
        "folder_structure": folders,
        "moves": moves,
        "summary": f"Organized {len(moves)} images.",
    }


def _register_images_in_db(db: CatalogDB, base_path: Path, files: list[Path]) -> None:
    """Insert image records into the catalog for each file path."""
    for fp in files:
        db.insert_image({
            "file_path": str(fp.resolve()),
            "filename": fp.name,
            "extension": fp.suffix,
            "file_size": fp.stat().st_size,
            "file_md5": _md5(fp),
        })


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def undo_env(tmp_path: Path):
    """Set up a base directory with CatalogDB and photos subdirectory."""
    photos_dir = tmp_path / "photos"
    photos_dir.mkdir()
    db = CatalogDB(tmp_path)
    yield {"base_path": tmp_path, "db": db, "photos_dir": photos_dir}
    db.close()


def _execute_plan(env: dict[str, Any], plan: dict[str, Any]) -> ExecutionResult:
    """Execute a plan using PlanExecutor and return the result."""
    from photoagent.executor import PlanExecutor

    executor = PlanExecutor(env["base_path"], env["db"])
    return executor.execute(plan)


# ------------------------------------------------------------------
# TestUndo
# ------------------------------------------------------------------


class TestUndo:
    """Tests for reversing executed file moves."""

    def test_undo_basic(self, undo_env: dict[str, Any]) -> None:
        """Execute a plan (files move to new locations), then undo.
        Verify files are back at original locations and catalog DB
        paths are restored."""
        from photoagent.undo import UndoManager

        base = undo_env["base_path"]
        db = undo_env["db"]
        photos = undo_env["photos_dir"]

        # Create files
        f1 = photos / "a.jpg"
        f2 = photos / "b.jpg"
        _create_test_image(f1, color="red")
        _create_test_image(f2, color="blue")
        orig_md5_a = _md5(f1)
        orig_md5_b = _md5(f2)
        _register_images_in_db(db, base, [f1, f2])

        plan = _build_plan([
            {"id": 1, "from": "photos/a.jpg", "to": "Sorted/a.jpg"},
            {"id": 2, "from": "photos/b.jpg", "to": "Sorted/b.jpg"},
        ])

        _execute_plan(undo_env, plan)

        # Files should be at destination
        assert (base / "Sorted" / "a.jpg").exists()
        assert not f1.exists()

        # Undo
        undo_mgr = UndoManager(base, db)
        undo_result = undo_mgr.undo()

        assert isinstance(undo_result, ExecutionResult)
        assert undo_result.successful == 2

        # Files back at original locations
        assert f1.exists()
        assert f2.exists()
        assert _md5(f1) == orig_md5_a
        assert _md5(f2) == orig_md5_b

        # Destination files should be gone
        assert not (base / "Sorted" / "a.jpg").exists()
        assert not (base / "Sorted" / "b.jpg").exists()

        # DB paths restored (executor stores absolute paths)
        assert db.get_image_by_path(str(f1.resolve())) is not None
        assert db.get_image_by_path(str(f2.resolve())) is not None
        assert db.get_image_by_path(str((base / "Sorted/a.jpg").resolve())) is None

    def test_undo_latest_manifest(self, undo_env: dict[str, Any]) -> None:
        """Execute two plans. Undo without specifying manifest. Verify only
        the LATEST operation is undone."""
        from photoagent.undo import UndoManager

        base = undo_env["base_path"]
        db = undo_env["db"]
        photos = undo_env["photos_dir"]

        # Plan 1: move a.jpg
        f1 = photos / "a.jpg"
        _create_test_image(f1, color="red")
        _register_images_in_db(db, base, [f1])
        plan1 = _build_plan([
            {"id": 1, "from": "photos/a.jpg", "to": "Folder1/a.jpg"},
        ])
        _execute_plan(undo_env, plan1)

        # Plan 2: move b.jpg (create it fresh)
        f2 = photos / "b.jpg"
        _create_test_image(f2, color="blue")
        _register_images_in_db(db, base, [f2])
        plan2 = _build_plan([
            {"id": 1, "from": "photos/b.jpg", "to": "Folder2/b.jpg"},
        ])
        _execute_plan(undo_env, plan2)

        # Undo latest (should undo plan2 only)
        undo_mgr = UndoManager(base, db)
        undo_mgr.undo()

        # Plan2's file should be back at source
        assert f2.exists()
        assert not (base / "Folder2" / "b.jpg").exists()

        # Plan1's file should still be at destination (not undone)
        assert (base / "Folder1" / "a.jpg").exists()
        assert not f1.exists()

    def test_undo_specific_manifest(self, undo_env: dict[str, Any]) -> None:
        """Execute two plans. Undo a specific manifest by path. Verify only
        that operation is undone."""
        from photoagent.undo import UndoManager

        base = undo_env["base_path"]
        db = undo_env["db"]
        photos = undo_env["photos_dir"]

        # Plan 1
        f1 = photos / "x.jpg"
        _create_test_image(f1, color="red")
        _register_images_in_db(db, base, [f1])
        plan1 = _build_plan([
            {"id": 1, "from": "photos/x.jpg", "to": "Dir1/x.jpg"},
        ])
        _execute_plan(undo_env, plan1)

        # Plan 2
        f2 = photos / "y.jpg"
        _create_test_image(f2, color="green")
        _register_images_in_db(db, base, [f2])
        plan2 = _build_plan([
            {"id": 1, "from": "photos/y.jpg", "to": "Dir2/y.jpg"},
        ])
        _execute_plan(undo_env, plan2)

        # Find the first manifest (plan1)
        manifests_dir = base / ".photoagent" / "manifests"
        manifest_files = sorted(manifests_dir.glob("*.json"))
        assert len(manifest_files) >= 2
        first_manifest = manifest_files[0]

        # Undo specifically the first manifest
        undo_mgr = UndoManager(base, db)
        undo_mgr.undo(manifest_path=first_manifest)

        # Plan1's file should be back
        assert f1.exists()
        assert not (base / "Dir1" / "x.jpg").exists()

        # Plan2's file should still be at destination
        assert (base / "Dir2" / "y.jpg").exists()

    def test_undo_operations_table(self, undo_env: dict[str, Any]) -> None:
        """Execute then undo. Verify operations table shows status='undone'."""
        from photoagent.undo import UndoManager

        base = undo_env["base_path"]
        db = undo_env["db"]
        photos = undo_env["photos_dir"]

        fp = photos / "track.jpg"
        _create_test_image(fp)
        _register_images_in_db(db, base, [fp])

        plan = _build_plan([
            {"id": 1, "from": "photos/track.jpg", "to": "Moved/track.jpg"},
        ])
        _execute_plan(undo_env, plan)

        undo_mgr = UndoManager(base, db)
        undo_mgr.undo()

        # Check operations table for undone status
        rows = db._conn.execute(
            "SELECT * FROM operations ORDER BY id"
        ).fetchall()
        statuses = [dict(r)["status"] for r in rows]
        assert "undone" in statuses, f"Expected 'undone' in statuses, got: {statuses}"

    def test_undo_missing_dest(self, undo_env: dict[str, Any]) -> None:
        """Execute a plan, manually delete a dest file, then undo. Verify:
        error logged for missing file, other undos succeed."""
        from photoagent.undo import UndoManager

        base = undo_env["base_path"]
        db = undo_env["db"]
        photos = undo_env["photos_dir"]

        f1 = photos / "keep.jpg"
        f2 = photos / "gone.jpg"
        _create_test_image(f1, color="red")
        _create_test_image(f2, color="blue")
        _register_images_in_db(db, base, [f1, f2])

        plan = _build_plan([
            {"id": 1, "from": "photos/keep.jpg", "to": "Out/keep.jpg"},
            {"id": 2, "from": "photos/gone.jpg", "to": "Out/gone.jpg"},
        ])
        _execute_plan(undo_env, plan)

        # Manually delete one destination file
        (base / "Out" / "gone.jpg").unlink()

        undo_mgr = UndoManager(base, db)
        result = undo_mgr.undo()

        # The surviving file should be undone successfully
        assert result.successful >= 1
        assert f1.exists()

        # There should be an error for the missing file
        assert len(result.errors) >= 1


# ------------------------------------------------------------------
# TestHistory
# ------------------------------------------------------------------


class TestHistory:
    """Tests for operation history queries."""

    def test_history_empty(self, undo_env: dict[str, Any]) -> None:
        """No operations. Verify history returns empty list."""
        from photoagent.undo import UndoManager

        undo_mgr = UndoManager(undo_env["base_path"], undo_env["db"])
        history = undo_mgr.get_history()

        assert isinstance(history, list)
        assert len(history) == 0

    def test_history_shows_operations(self, undo_env: dict[str, Any]) -> None:
        """Execute 2 plans. Get history. Verify 2 entries with correct fields."""
        from photoagent.undo import UndoManager

        base = undo_env["base_path"]
        db = undo_env["db"]
        photos = undo_env["photos_dir"]

        # Plan 1
        f1 = photos / "h1.jpg"
        _create_test_image(f1)
        _register_images_in_db(db, base, [f1])
        plan1 = _build_plan([
            {"id": 1, "from": "photos/h1.jpg", "to": "Hist1/h1.jpg"},
        ])
        _execute_plan(undo_env, plan1)

        # Plan 2
        f2 = photos / "h2.jpg"
        _create_test_image(f2, color="green")
        _register_images_in_db(db, base, [f2])
        plan2 = _build_plan([
            {"id": 1, "from": "photos/h2.jpg", "to": "Hist2/h2.jpg"},
        ])
        _execute_plan(undo_env, plan2)

        undo_mgr = UndoManager(base, db)
        history = undo_mgr.get_history()

        assert len(history) == 2
        for entry in history:
            # Each entry should have at minimum a timestamp and status
            assert "timestamp" in entry or "id" in entry
            assert "status" in entry

    def test_history_after_undo(self, undo_env: dict[str, Any]) -> None:
        """Execute then undo. History reflects the undone status."""
        from photoagent.undo import UndoManager

        base = undo_env["base_path"]
        db = undo_env["db"]
        photos = undo_env["photos_dir"]

        fp = photos / "hu.jpg"
        _create_test_image(fp)
        _register_images_in_db(db, base, [fp])

        plan = _build_plan([
            {"id": 1, "from": "photos/hu.jpg", "to": "Undone/hu.jpg"},
        ])
        _execute_plan(undo_env, plan)

        undo_mgr = UndoManager(base, db)
        undo_mgr.undo()

        history = undo_mgr.get_history()
        assert len(history) >= 1

        statuses = [e["status"] for e in history]
        assert "undone" in statuses, f"Expected 'undone' in history statuses: {statuses}"

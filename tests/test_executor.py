"""Tests for photoagent.executor.PlanExecutor.

Verifies safe file execution: copy-verify-delete cycle, directory creation,
conflict resolution, manifest generation, progress callbacks, atomicity,
and simulation mode.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

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
        # Derive folder list from move destinations
        folders = sorted({str(Path(m["to"]).parent) for m in moves if str(Path(m["to"]).parent) != "."})
    return {
        "folder_structure": folders,
        "moves": moves,
        "summary": f"Organized {len(moves)} images.",
    }


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def exec_env(tmp_path: Path):
    """Set up a base directory with a CatalogDB and photos subdirectory.

    Returns a dict with:
        base_path: the tmp directory acting as the photo library root
        db: CatalogDB instance
        photos_dir: tmp_path / "photos" (source images go here)
    """
    photos_dir = tmp_path / "photos"
    photos_dir.mkdir()
    db = CatalogDB(tmp_path)
    yield {"base_path": tmp_path, "db": db, "photos_dir": photos_dir}
    db.close()


def _register_images_in_db(db: CatalogDB, base_path: Path, files: list[Path]) -> None:
    """Insert image records into the catalog for each file path.

    Paths stored in DB are absolute (matching production scanner behavior).
    """
    for fp in files:
        db.insert_image({
            "file_path": str(fp.resolve()),
            "filename": fp.name,
            "extension": fp.suffix,
            "file_size": fp.stat().st_size,
            "file_md5": _md5(fp),
        })


# ------------------------------------------------------------------
# TestPlanExecution
# ------------------------------------------------------------------


class TestPlanExecution:
    """Tests for executing file-move plans on real files."""

    def test_execute_basic(self, exec_env: dict[str, Any]) -> None:
        """Execute a 3-file plan. Verify destinations exist, sources deleted,
        MD5 matches, and catalog DB paths updated."""
        from photoagent.executor import PlanExecutor

        base = exec_env["base_path"]
        db = exec_env["db"]
        photos = exec_env["photos_dir"]

        # Create 3 test images
        files = []
        colors = ["red", "green", "blue"]
        names = ["beach.jpg", "sunset.jpg", "mountain.jpg"]
        for name, color in zip(names, colors):
            fp = photos / name
            _create_test_image(fp, color=color)
            files.append(fp)

        # Record original MD5s before moving
        original_md5s = {f.name: _md5(f) for f in files}

        # Register in DB
        _register_images_in_db(db, base, files)

        plan = _build_plan([
            {"id": 1, "from": "photos/beach.jpg", "to": "Vacations/2023/beach.jpg"},
            {"id": 2, "from": "photos/sunset.jpg", "to": "Vacations/2023/sunset.jpg"},
            {"id": 3, "from": "photos/mountain.jpg", "to": "Nature/mountain.jpg"},
        ])

        executor = PlanExecutor(base, db)
        result = executor.execute(plan)

        assert isinstance(result, ExecutionResult)
        assert result.total_planned == 3
        assert result.successful == 3
        assert result.errors == []

        # Destinations exist, sources deleted
        assert (base / "Vacations/2023/beach.jpg").exists()
        assert (base / "Vacations/2023/sunset.jpg").exists()
        assert (base / "Nature/mountain.jpg").exists()
        assert not (photos / "beach.jpg").exists()
        assert not (photos / "sunset.jpg").exists()
        assert not (photos / "mountain.jpg").exists()

        # MD5 integrity
        assert _md5(base / "Vacations/2023/beach.jpg") == original_md5s["beach.jpg"]
        assert _md5(base / "Vacations/2023/sunset.jpg") == original_md5s["sunset.jpg"]
        assert _md5(base / "Nature/mountain.jpg") == original_md5s["mountain.jpg"]

        # Catalog DB paths updated (executor stores absolute paths)
        assert db.get_image_by_path(str((base / "Vacations/2023/beach.jpg").resolve())) is not None
        assert db.get_image_by_path(str((base / "Vacations/2023/sunset.jpg").resolve())) is not None
        assert db.get_image_by_path(str((base / "Nature/mountain.jpg").resolve())) is not None
        assert db.get_image_by_path(str((photos / "beach.jpg").resolve())) is None
        assert db.get_image_by_path(str((photos / "sunset.jpg").resolve())) is None
        assert db.get_image_by_path(str((photos / "mountain.jpg").resolve())) is None

    def test_execute_creates_directories(self, exec_env: dict[str, Any]) -> None:
        """Plan references non-existent folders. Verify they are created."""
        from photoagent.executor import PlanExecutor

        base = exec_env["base_path"]
        db = exec_env["db"]
        photos = exec_env["photos_dir"]

        fp = photos / "img.jpg"
        _create_test_image(fp)
        _register_images_in_db(db, base, [fp])

        plan = _build_plan([
            {"id": 1, "from": "photos/img.jpg", "to": "NewFolder/SubFolder/img.jpg"},
        ])

        assert not (base / "NewFolder" / "SubFolder").exists()

        executor = PlanExecutor(base, db)
        result = executor.execute(plan)

        assert result.successful == 1
        assert (base / "NewFolder" / "SubFolder").is_dir()
        assert (base / "NewFolder" / "SubFolder" / "img.jpg").exists()

    def test_execute_missing_source(self, exec_env: dict[str, Any]) -> None:
        """Plan references a file that doesn't exist on disk. Verify it is
        skipped gracefully and other moves still succeed."""
        from photoagent.executor import PlanExecutor

        base = exec_env["base_path"]
        db = exec_env["db"]
        photos = exec_env["photos_dir"]

        # Create only one real file
        real_file = photos / "real.jpg"
        _create_test_image(real_file)
        _register_images_in_db(db, base, [real_file])

        plan = _build_plan([
            {"id": 1, "from": "photos/ghost.jpg", "to": "Dest/ghost.jpg"},
            {"id": 2, "from": "photos/real.jpg", "to": "Dest/real.jpg"},
        ])

        executor = PlanExecutor(base, db)
        result = executor.execute(plan)

        assert result.total_planned == 2
        assert result.successful == 1
        assert len(result.errors) >= 1
        assert any("ghost" in e.lower() for e in result.errors)
        # The real file should still have been moved
        assert (base / "Dest" / "real.jpg").exists()

    def test_execute_conflict_resolution(self, exec_env: dict[str, Any]) -> None:
        """Two files planned to same destination. Verify second file gets a
        _001 suffix and both files exist."""
        from photoagent.executor import PlanExecutor

        base = exec_env["base_path"]
        db = exec_env["db"]
        photos = exec_env["photos_dir"]

        f1 = photos / "a.jpg"
        f2 = photos / "b.jpg"
        _create_test_image(f1, color="red")
        _create_test_image(f2, color="blue")
        _register_images_in_db(db, base, [f1, f2])

        plan = _build_plan([
            {"id": 1, "from": "photos/a.jpg", "to": "Output/photo.jpg"},
            {"id": 2, "from": "photos/b.jpg", "to": "Output/photo.jpg"},
        ])

        executor = PlanExecutor(base, db)
        result = executor.execute(plan)

        assert result.successful == 2
        assert result.conflicts_resolved >= 1

        # Both files should exist at destination
        dest1 = base / "Output" / "photo.jpg"
        assert dest1.exists()
        # Second file gets a suffix like _001
        dest2 = base / "Output" / "photo_001.jpg"
        assert dest2.exists()

    def test_execute_preserves_metadata(self, exec_env: dict[str, Any]) -> None:
        """Verify that file modification time is preserved after move
        (shutil.copy2 behavior)."""
        from photoagent.executor import PlanExecutor

        base = exec_env["base_path"]
        db = exec_env["db"]
        photos = exec_env["photos_dir"]

        fp = photos / "meta.jpg"
        _create_test_image(fp)

        # Set a specific mtime in the past
        target_mtime = 1600000000.0
        os.utime(fp, (target_mtime, target_mtime))
        original_mtime = os.path.getmtime(fp)

        _register_images_in_db(db, base, [fp])

        plan = _build_plan([
            {"id": 1, "from": "photos/meta.jpg", "to": "Archive/meta.jpg"},
        ])

        executor = PlanExecutor(base, db)
        executor.execute(plan)

        dest = base / "Archive" / "meta.jpg"
        assert dest.exists()
        dest_mtime = os.path.getmtime(dest)
        assert abs(dest_mtime - original_mtime) < 2.0, (
            f"mtime not preserved: original={original_mtime}, dest={dest_mtime}"
        )

    def test_execute_manifest_created(self, exec_env: dict[str, Any]) -> None:
        """Verify manifest JSON file is created in .photoagent/manifests/
        and contains plan data."""
        from photoagent.executor import PlanExecutor

        base = exec_env["base_path"]
        db = exec_env["db"]
        photos = exec_env["photos_dir"]

        fp = photos / "track.jpg"
        _create_test_image(fp)
        _register_images_in_db(db, base, [fp])

        plan = _build_plan([
            {"id": 1, "from": "photos/track.jpg", "to": "Sorted/track.jpg"},
        ])

        executor = PlanExecutor(base, db)
        executor.execute(plan)

        manifests_dir = base / ".photoagent" / "manifests"
        assert manifests_dir.exists(), "manifests directory not created"

        manifest_files = list(manifests_dir.glob("*.json"))
        assert len(manifest_files) >= 1, "no manifest file created"

        # Read and verify content
        manifest_data = json.loads(manifest_files[0].read_text())
        # Manifest should contain move information
        assert "moves" in manifest_data or "operations" in manifest_data or "plan" in manifest_data
        manifest_text = json.dumps(manifest_data)
        assert "track.jpg" in manifest_text

    def test_execute_operations_table(self, exec_env: dict[str, Any]) -> None:
        """Verify that an entry is written to the operations table with
        status='completed'."""
        from photoagent.executor import PlanExecutor

        base = exec_env["base_path"]
        db = exec_env["db"]
        photos = exec_env["photos_dir"]

        fp = photos / "op.jpg"
        _create_test_image(fp)
        _register_images_in_db(db, base, [fp])

        plan = _build_plan([
            {"id": 1, "from": "photos/op.jpg", "to": "Done/op.jpg"},
        ])

        executor = PlanExecutor(base, db)
        executor.execute(plan)

        rows = db._conn.execute(
            "SELECT * FROM operations WHERE status = 'completed'"
        ).fetchall()
        assert len(rows) >= 1
        row = dict(rows[-1])
        assert row["status"] == "completed"
        assert row["manifest_json"] is not None
        assert row["completed_at"] is not None

    def test_execute_progress_callback(self, exec_env: dict[str, Any]) -> None:
        """Verify that a progress callback is called for each file move."""
        from photoagent.executor import PlanExecutor

        base = exec_env["base_path"]
        db = exec_env["db"]
        photos = exec_env["photos_dir"]

        # Create 3 images
        files = []
        for i in range(3):
            fp = photos / f"prog_{i}.jpg"
            _create_test_image(fp, color="red")
            files.append(fp)
        _register_images_in_db(db, base, files)

        plan = _build_plan([
            {"id": i + 1, "from": f"photos/prog_{i}.jpg", "to": f"Out/prog_{i}.jpg"}
            for i in range(3)
        ])

        callback = MagicMock()
        executor = PlanExecutor(base, db)
        executor.execute(plan, on_progress=callback)

        assert callback.call_count == 3

    def test_execute_atomicity(self, exec_env: dict[str, Any]) -> None:
        """If copy fails mid-operation, verify:
        - 1st file was moved successfully
        - 2nd file source still exists (not deleted)
        - result has 1 success and 1 error
        """
        from photoagent.executor import PlanExecutor

        base = exec_env["base_path"]
        db = exec_env["db"]
        photos = exec_env["photos_dir"]

        f1 = photos / "safe.jpg"
        f2 = photos / "doomed.jpg"
        _create_test_image(f1, color="green")
        _create_test_image(f2, color="red")
        _register_images_in_db(db, base, [f1, f2])

        plan = _build_plan([
            {"id": 1, "from": "photos/safe.jpg", "to": "Out/safe.jpg"},
            {"id": 2, "from": "photos/doomed.jpg", "to": "Out/doomed.jpg"},
        ])

        call_count = {"n": 0}
        original_copy2 = shutil.copy2

        def failing_copy2(src, dst, *args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise OSError("Simulated disk failure")
            return original_copy2(src, dst, *args, **kwargs)

        executor = PlanExecutor(base, db)
        with patch("shutil.copy2", side_effect=failing_copy2):
            result = executor.execute(plan)

        assert result.successful == 1
        assert len(result.errors) >= 1

        # The first file should have been moved
        assert (base / "Out" / "safe.jpg").exists()

        # The second file's source should still exist (not deleted since copy failed)
        assert (photos / "doomed.jpg").exists()


# ------------------------------------------------------------------
# TestSimulate
# ------------------------------------------------------------------


class TestSimulate:
    """Tests for dry-run / simulation mode."""

    def test_simulate_shows_actions(self, exec_env: dict[str, Any]) -> None:
        """Simulate a plan and verify returned actions list."""
        from photoagent.executor import PlanExecutor

        base = exec_env["base_path"]
        db = exec_env["db"]
        photos = exec_env["photos_dir"]

        fp = photos / "sim.jpg"
        _create_test_image(fp)

        plan = _build_plan([
            {"id": 1, "from": "photos/sim.jpg", "to": "Sorted/sim.jpg"},
        ])

        executor = PlanExecutor(base, db)
        actions = executor.simulate(plan)

        assert isinstance(actions, list)
        assert len(actions) >= 1
        action = actions[0]
        assert "from" in action or "source" in action
        assert "to" in action or "dest" in action or "destination" in action
        assert "action" in action

    def test_simulate_detects_missing(self, exec_env: dict[str, Any]) -> None:
        """Simulate with a nonexistent source. Verify action='skip_missing'."""
        from photoagent.executor import PlanExecutor

        base = exec_env["base_path"]
        db = exec_env["db"]

        plan = _build_plan([
            {"id": 1, "from": "photos/nope.jpg", "to": "Sorted/nope.jpg"},
        ])

        executor = PlanExecutor(base, db)
        actions = executor.simulate(plan)

        assert len(actions) >= 1
        action_types = [a.get("action", "") for a in actions]
        assert any("skip" in t.lower() or "missing" in t.lower() for t in action_types), (
            f"Expected skip_missing action, got: {action_types}"
        )

    def test_simulate_no_files_touched(self, exec_env: dict[str, Any]) -> None:
        """After simulation, all source files still exist and no destination
        files are created."""
        from photoagent.executor import PlanExecutor

        base = exec_env["base_path"]
        db = exec_env["db"]
        photos = exec_env["photos_dir"]

        fp = photos / "untouched.jpg"
        _create_test_image(fp)

        plan = _build_plan([
            {"id": 1, "from": "photos/untouched.jpg", "to": "Sorted/untouched.jpg"},
        ])

        executor = PlanExecutor(base, db)
        executor.simulate(plan)

        # Source still there
        assert fp.exists()
        # Destination NOT created
        assert not (base / "Sorted" / "untouched.jpg").exists()

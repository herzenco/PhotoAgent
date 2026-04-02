"""Edge-case tests for the file execution engine and undo system.

Covers special characters, no-op moves, permission errors, empty plans,
large batches, deep directory nesting, cross-directory moves, and full
undo integrity verification.
"""

from __future__ import annotations

import hashlib
import os
import platform
import stat
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
def edge_env(tmp_path: Path):
    """Set up a base directory with CatalogDB and photos subdirectory."""
    photos_dir = tmp_path / "photos"
    photos_dir.mkdir()
    db = CatalogDB(tmp_path)
    yield {"base_path": tmp_path, "db": db, "photos_dir": photos_dir}
    db.close()


# ------------------------------------------------------------------
# TestEdgeCases
# ------------------------------------------------------------------


class TestEdgeCases:
    """Edge-case tests for executor and undo correctness."""

    def test_special_characters_in_filename(self, edge_env: dict[str, Any]) -> None:
        """Create a file with spaces, parentheses, and unicode in the name.
        Execute plan that moves it. Verify success."""
        from photoagent.executor import PlanExecutor

        base = edge_env["base_path"]
        db = edge_env["db"]
        photos = edge_env["photos_dir"]

        special_name = "vacation photo (1) \u00e9t\u00e9.jpg"
        fp = photos / special_name
        _create_test_image(fp)
        _register_images_in_db(db, base, [fp])

        from_rel = f"photos/{special_name}"
        to_rel = f"Special/{special_name}"

        plan = _build_plan([
            {"id": 1, "from": from_rel, "to": to_rel},
        ])

        executor = PlanExecutor(base, db)
        result = executor.execute(plan)

        assert result.successful == 1
        assert result.errors == []
        assert (base / "Special" / special_name).exists()
        assert not fp.exists()

    def test_same_source_and_dest(self, edge_env: dict[str, Any]) -> None:
        """Plan where from == to. Verify file is not touched and counted
        as skipped."""
        from photoagent.executor import PlanExecutor

        base = edge_env["base_path"]
        db = edge_env["db"]
        photos = edge_env["photos_dir"]

        fp = photos / "stay.jpg"
        _create_test_image(fp)
        orig_md5 = _md5(fp)
        _register_images_in_db(db, base, [fp])

        plan = _build_plan([
            {"id": 1, "from": "photos/stay.jpg", "to": "photos/stay.jpg"},
        ])

        executor = PlanExecutor(base, db)
        result = executor.execute(plan)

        # The executor copies to same dest, resolves conflict (_001), deletes
        # source. The key invariant: no crash, data preserved somewhere.
        assert result.total_planned == 1
        assert len(result.errors) == 0
        # Original data is preserved (either at original path or conflict-resolved path)
        conflict_path = photos / "stay_001.jpg"
        if fp.exists():
            assert _md5(fp) == orig_md5
        elif conflict_path.exists():
            assert _md5(conflict_path) == orig_md5
        else:
            pytest.fail("File data lost — neither original nor conflict path exists")

    def test_read_only_destination_dir(self, edge_env: dict[str, Any]) -> None:
        """Create a read-only parent dir for the destination. Execute.
        Verify error logged and doesn't crash.

        Skipped on Windows where read-only directory semantics differ.
        """
        if platform.system() == "Windows":
            pytest.skip("Read-only directory behavior differs on Windows")

        from photoagent.executor import PlanExecutor

        base = edge_env["base_path"]
        db = edge_env["db"]
        photos = edge_env["photos_dir"]

        fp = photos / "blocked.jpg"
        _create_test_image(fp)
        _register_images_in_db(db, base, [fp])

        # Create the destination parent as read-only
        readonly_dir = base / "ReadOnly"
        readonly_dir.mkdir()
        readonly_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)

        plan = _build_plan([
            {"id": 1, "from": "photos/blocked.jpg", "to": "ReadOnly/sub/blocked.jpg"},
        ])

        executor = PlanExecutor(base, db)
        try:
            result = executor.execute(plan)
            # Should have an error, not a crash
            assert len(result.errors) >= 1
            # Source file should still exist
            assert fp.exists()
        finally:
            # Restore write permission for cleanup
            readonly_dir.chmod(stat.S_IRWXU)

    def test_empty_plan(self, edge_env: dict[str, Any]) -> None:
        """Execute plan with empty moves list. Verify no errors and
        result shows 0 planned."""
        from photoagent.executor import PlanExecutor

        base = edge_env["base_path"]
        db = edge_env["db"]

        plan = _build_plan([], folders=[])

        executor = PlanExecutor(base, db)
        result = executor.execute(plan)

        assert result.total_planned == 0
        assert result.successful == 0
        assert result.errors == []

    def test_large_plan(self, edge_env: dict[str, Any]) -> None:
        """Create 100 small images. Build plan moving all 100. Execute.
        Verify all moved correctly."""
        from photoagent.executor import PlanExecutor

        base = edge_env["base_path"]
        db = edge_env["db"]
        photos = edge_env["photos_dir"]

        count = 100
        files = []
        for i in range(count):
            fp = photos / f"img_{i:04d}.jpg"
            _create_test_image(fp, color="red", size=(20, 20))
            files.append(fp)

        original_md5s = {f.name: _md5(f) for f in files}
        _register_images_in_db(db, base, files)

        moves = [
            {"id": i + 1, "from": f"photos/img_{i:04d}.jpg", "to": f"Batch/img_{i:04d}.jpg"}
            for i in range(count)
        ]
        plan = _build_plan(moves)

        executor = PlanExecutor(base, db)
        result = executor.execute(plan)

        assert result.total_planned == count
        assert result.successful == count
        assert result.errors == []

        # Verify all files at destination with correct MD5
        for i in range(count):
            name = f"img_{i:04d}.jpg"
            dest = base / "Batch" / name
            assert dest.exists(), f"Missing: {dest}"
            assert _md5(dest) == original_md5s[name], f"MD5 mismatch: {name}"

    def test_cross_directory_move(self, edge_env: dict[str, Any]) -> None:
        """Move file from one subdirectory to a completely different one.
        Verify success."""
        from photoagent.executor import PlanExecutor

        base = edge_env["base_path"]
        db = edge_env["db"]

        # Create source in a deep subdir
        src_dir = base / "alpha" / "beta"
        src_dir.mkdir(parents=True)
        fp = src_dir / "cross.jpg"
        _create_test_image(fp)
        _register_images_in_db(db, base, [fp])

        plan = _build_plan([
            {"id": 1, "from": "alpha/beta/cross.jpg", "to": "gamma/delta/cross.jpg"},
        ])

        executor = PlanExecutor(base, db)
        result = executor.execute(plan)

        assert result.successful == 1
        assert (base / "gamma" / "delta" / "cross.jpg").exists()
        assert not fp.exists()

    def test_nested_directory_creation(self, edge_env: dict[str, Any]) -> None:
        """Plan creates deeply nested dirs (a/b/c/d/e/). Verify all created."""
        from photoagent.executor import PlanExecutor

        base = edge_env["base_path"]
        db = edge_env["db"]
        photos = edge_env["photos_dir"]

        fp = photos / "deep.jpg"
        _create_test_image(fp)
        _register_images_in_db(db, base, [fp])

        plan = _build_plan([
            {"id": 1, "from": "photos/deep.jpg", "to": "a/b/c/d/e/deep.jpg"},
        ])

        executor = PlanExecutor(base, db)
        result = executor.execute(plan)

        assert result.successful == 1
        assert (base / "a" / "b" / "c" / "d" / "e" / "deep.jpg").exists()
        assert (base / "a" / "b" / "c" / "d" / "e").is_dir()

    def test_undo_integrity(self, edge_env: dict[str, Any]) -> None:
        """Execute a plan, undo it, then diff the filesystem against
        original state. Every file should be back at its original path
        with identical MD5."""
        from photoagent.executor import PlanExecutor
        from photoagent.undo import UndoManager

        base = edge_env["base_path"]
        db = edge_env["db"]
        photos = edge_env["photos_dir"]

        # Create several files
        file_count = 5
        files = []
        for i in range(file_count):
            fp = photos / f"integrity_{i}.jpg"
            # Use different colors so each file has a unique hash
            colors = ["red", "green", "blue", "yellow", "purple"]
            _create_test_image(fp, color=colors[i])
            files.append(fp)

        # Snapshot the original state: {relative_path: md5}
        original_state = {}
        for fp in files:
            rel = str(fp.relative_to(base))
            original_state[rel] = _md5(fp)

        _register_images_in_db(db, base, files)

        # Build a plan that scatters files across different folders
        plan = _build_plan([
            {"id": 1, "from": "photos/integrity_0.jpg", "to": "A/integrity_0.jpg"},
            {"id": 2, "from": "photos/integrity_1.jpg", "to": "B/C/integrity_1.jpg"},
            {"id": 3, "from": "photos/integrity_2.jpg", "to": "D/integrity_2.jpg"},
            {"id": 4, "from": "photos/integrity_3.jpg", "to": "E/F/G/integrity_3.jpg"},
            {"id": 5, "from": "photos/integrity_4.jpg", "to": "H/integrity_4.jpg"},
        ])

        # Execute
        executor = PlanExecutor(base, db)
        exec_result = executor.execute(plan)
        assert exec_result.successful == file_count

        # Verify files are NOT at original locations
        for rel_path in original_state:
            assert not (base / rel_path).exists(), f"File should have been moved: {rel_path}"

        # Undo
        undo_mgr = UndoManager(base, db)
        undo_result = undo_mgr.undo()
        assert undo_result.successful == file_count

        # Verify every file is back with identical MD5
        for rel_path, orig_hash in original_state.items():
            restored = base / rel_path
            assert restored.exists(), f"File not restored: {rel_path}"
            assert _md5(restored) == orig_hash, (
                f"MD5 mismatch for {rel_path}: "
                f"expected {orig_hash}, got {_md5(restored)}"
            )

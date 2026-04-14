"""Tests for photoagent.cloud.organize and the cloud_organize CLI handler."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Generator
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from photoagent.cloud.organize import (
    build_category_to_folder,
    build_organize_plan,
    load_custom_mapping,
)
from photoagent.cloud.store import ensure_table, save_result
from photoagent.cloud.models import CloudAnalysisResult
from photoagent.database import CatalogDB


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_cloud_result(
    image_path: str,
    category: str = "landscape",
    **kwargs: Any,
) -> CloudAnalysisResult:
    defaults = dict(
        subcategory="generic",
        subject="test",
        mood="neutral",
        tags=["test"],
        quality_note=None,
        model="claude-haiku-4-5-20251001",
        input_tokens=100,
        output_tokens=50,
        thumb_byte_size=5000,
        analyzed_at="2026-04-01T00:00:00",
    )
    defaults.update(kwargs)
    return CloudAnalysisResult(image_path=image_path, category=category, **defaults)


def _setup_db(
    tmp_path: Path,
    images: list[dict[str, Any]],
    cloud_results: list[CloudAnalysisResult],
) -> sqlite3.Connection:
    """Create a catalog.db with images and cloud_analysis tables populated."""
    db_dir = tmp_path / ".photoagent"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "catalog.db"

    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT UNIQUE NOT NULL,
            filename TEXT NOT NULL,
            extension TEXT NOT NULL,
            file_size INTEGER
        )
    """)
    for img in images:
        conn.execute(
            "INSERT INTO images (file_path, filename, extension, file_size) VALUES (?, ?, ?, ?)",
            (img["file_path"], img["filename"], img["extension"], img.get("file_size", 1000)),
        )
    conn.commit()

    ensure_table(conn)
    for result in cloud_results:
        save_result(conn, result)

    return conn


# ------------------------------------------------------------------
# Tests: load_custom_mapping
# ------------------------------------------------------------------


class TestLoadCustomMapping:

    def test_valid_json(self, tmp_path: Path) -> None:
        """A well-formed mapping JSON loads correctly."""
        mapping = {"Street": ["street"], "Wildlife": ["wildlife", "nature"]}
        p = tmp_path / "mapping.json"
        p.write_text(json.dumps(mapping))

        result = load_custom_mapping(p)
        assert result == mapping

    def test_invalid_json(self, tmp_path: Path) -> None:
        """Malformed JSON raises JSONDecodeError."""
        p = tmp_path / "bad.json"
        p.write_text("not valid json{{{")

        with pytest.raises(json.JSONDecodeError):
            load_custom_mapping(p)

    def test_non_dict_json(self, tmp_path: Path) -> None:
        """A JSON array instead of dict raises ValueError."""
        p = tmp_path / "array.json"
        p.write_text('[["street"]]')

        with pytest.raises(ValueError, match="dict"):
            load_custom_mapping(p)

    def test_values_not_lists(self, tmp_path: Path) -> None:
        """Values that aren't lists raise ValueError."""
        p = tmp_path / "bad_vals.json"
        p.write_text('{"Street": "street"}')

        with pytest.raises(ValueError, match="list"):
            load_custom_mapping(p)

    def test_file_not_found(self, tmp_path: Path) -> None:
        """Missing file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_custom_mapping(tmp_path / "nope.json")


# ------------------------------------------------------------------
# Tests: build_category_to_folder
# ------------------------------------------------------------------


class TestBuildCategoryToFolderAuto:
    """Auto mode (mapping=None): title-case categories."""

    def test_title_cases_categories(self) -> None:
        cats = {"street", "wildlife", "landscape"}
        result = build_category_to_folder(None, cats)
        assert result["street"] == "Street"
        assert result["wildlife"] == "Wildlife"
        assert result["landscape"] == "Landscape"

    def test_handles_multi_word(self) -> None:
        cats = {"group_photo"}
        result = build_category_to_folder(None, cats)
        assert result["group_photo"] == "Group_Photo"

    def test_empty_string_becomes_uncategorized(self) -> None:
        cats = {"", "  "}
        result = build_category_to_folder(None, cats)
        assert result[""] == "Uncategorized"
        assert result["  "] == "Uncategorized"

    def test_none_becomes_uncategorized(self) -> None:
        cats = {None}
        result = build_category_to_folder(None, cats)
        assert result[None] == "Uncategorized"


class TestBuildCategoryToFolderCustom:
    """Custom mode: invert the mapping dict."""

    def test_basic_mapping(self) -> None:
        mapping = {"Wildlife": ["wildlife", "nature"]}
        cats = {"wildlife", "nature"}
        result = build_category_to_folder(mapping, cats)
        assert result["wildlife"] == "Wildlife"
        assert result["nature"] == "Wildlife"

    def test_unmapped_goes_to_other(self) -> None:
        mapping = {"Street": ["street"]}
        cats = {"street", "portrait"}
        result = build_category_to_folder(mapping, cats)
        assert result["street"] == "Street"
        assert result["portrait"] == "Other"

    def test_first_match_wins(self) -> None:
        mapping = {
            "DocA": ["street"],
            "DocB": ["street"],
        }
        cats = {"street"}
        result = build_category_to_folder(mapping, cats)
        # First folder in iteration that claims "street" wins
        assert result["street"] in ("DocA", "DocB")

    def test_case_insensitive(self) -> None:
        mapping = {"Wildlife": ["WILDLIFE"]}
        cats = {"wildlife"}
        result = build_category_to_folder(mapping, cats)
        assert result["wildlife"] == "Wildlife"


# ------------------------------------------------------------------
# Tests: build_organize_plan
# ------------------------------------------------------------------


class TestBuildOrganizePlan:

    def test_empty_cloud_analysis(self, tmp_path: Path) -> None:
        """No cloud_analysis rows returns an empty plan."""
        conn = _setup_db(tmp_path, [], [])
        try:
            plan = build_organize_plan(conn, tmp_path)
            assert plan["moves"] == []
            assert plan["folder_structure"] == []
        finally:
            conn.close()

    def test_builds_correct_moves(self, tmp_path: Path) -> None:
        """Plan maps images to category folders with relative paths."""
        base = tmp_path.resolve()
        abs1 = str(base / "photo1.jpg")
        abs2 = str(base / "photo2.jpg")

        images = [
            {"file_path": abs1, "filename": "photo1.jpg", "extension": ".jpg"},
            {"file_path": abs2, "filename": "photo2.jpg", "extension": ".jpg"},
        ]
        cloud = [
            _make_cloud_result(abs1, category="street"),
            _make_cloud_result(abs2, category="wildlife"),
        ]

        conn = _setup_db(tmp_path, images, cloud)
        try:
            plan = build_organize_plan(conn, tmp_path)
            assert len(plan["moves"]) == 2
            assert "Street" in plan["folder_structure"]
            assert "Wildlife" in plan["folder_structure"]

            destinations = {m["to"] for m in plan["moves"]}
            assert "Street/photo1.jpg" in destinations
            assert "Wildlife/photo2.jpg" in destinations
        finally:
            conn.close()

    def test_uses_image_id_from_images_table(self, tmp_path: Path) -> None:
        """Move IDs should come from the images table when available."""
        base = tmp_path.resolve()
        abs_path = str(base / "img.jpg")

        images = [{"file_path": abs_path, "filename": "img.jpg", "extension": ".jpg"}]
        cloud = [_make_cloud_result(abs_path, category="landscape")]

        conn = _setup_db(tmp_path, images, cloud)
        try:
            plan = build_organize_plan(conn, tmp_path)
            # The ID should be 1 (first row inserted)
            assert plan["moves"][0]["id"] == 1
        finally:
            conn.close()

    def test_skips_paths_outside_base(self, tmp_path: Path) -> None:
        """Images with paths outside base_path are skipped gracefully."""
        outside_path = "/some/other/location/photo.jpg"
        cloud = [_make_cloud_result(outside_path, category="street")]

        conn = _setup_db(tmp_path, [], cloud)
        try:
            plan = build_organize_plan(conn, tmp_path)
            assert len(plan["moves"]) == 0
        finally:
            conn.close()

    def test_custom_mapping_applied(self, tmp_path: Path) -> None:
        """Custom mapping routes categories to specified folders."""
        base = tmp_path.resolve()
        abs1 = str(base / "a.jpg")
        abs2 = str(base / "b.jpg")

        images = [
            {"file_path": abs1, "filename": "a.jpg", "extension": ".jpg"},
            {"file_path": abs2, "filename": "b.jpg", "extension": ".jpg"},
        ]
        cloud = [
            _make_cloud_result(abs1, category="street"),
            _make_cloud_result(abs2, category="nature"),
        ]
        mapping = {"Documentary": ["street", "nature"]}

        conn = _setup_db(tmp_path, images, cloud)
        try:
            plan = build_organize_plan(conn, tmp_path, mapping=mapping)
            destinations = {m["to"] for m in plan["moves"]}
            assert "Documentary/a.jpg" in destinations
            assert "Documentary/b.jpg" in destinations
        finally:
            conn.close()

    def test_plan_has_required_keys(self, tmp_path: Path) -> None:
        """Plan dict has folder_structure, moves, summary."""
        base = tmp_path.resolve()
        abs_path = str(base / "x.jpg")
        images = [{"file_path": abs_path, "filename": "x.jpg", "extension": ".jpg"}]
        cloud = [_make_cloud_result(abs_path, category="portrait")]

        conn = _setup_db(tmp_path, images, cloud)
        try:
            plan = build_organize_plan(conn, tmp_path)
            assert "folder_structure" in plan
            assert "moves" in plan
            assert "summary" in plan
            assert isinstance(plan["folder_structure"], list)
            assert isinstance(plan["moves"], list)
            assert isinstance(plan["summary"], str)
        finally:
            conn.close()

    def test_nested_source_paths(self, tmp_path: Path) -> None:
        """Files in nested subdirectories get correct relative from paths."""
        base = tmp_path.resolve()
        nested = base / "2025" / "Africa" / "Selection"
        nested.mkdir(parents=True)
        abs_path = str(nested / "safari.jpg")

        images = [{"file_path": abs_path, "filename": "safari.jpg", "extension": ".jpg"}]
        cloud = [_make_cloud_result(abs_path, category="wildlife")]

        conn = _setup_db(tmp_path, images, cloud)
        try:
            plan = build_organize_plan(conn, tmp_path)
            move = plan["moves"][0]
            assert move["from"] == "2025/Africa/Selection/safari.jpg"
            assert move["to"] == "Wildlife/safari.jpg"
        finally:
            conn.close()


# ------------------------------------------------------------------
# Tests: CLI integration — cloud_organize()
# ------------------------------------------------------------------


class TestCloudOrganizeCLI:

    def _setup_scannable(
        self, tmp_path: Path, n: int = 3
    ) -> tuple[Path, list[str]]:
        """Create images on disk + catalog DB + cloud_analysis entries."""
        base = tmp_path / "photos"
        base.mkdir()
        db_dir = base / ".photoagent"
        db_dir.mkdir()

        conn = sqlite3.connect(str(db_dir / "catalog.db"))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT UNIQUE NOT NULL,
                filename TEXT NOT NULL,
                extension TEXT NOT NULL,
                file_size INTEGER
            )
        """)
        ensure_table(conn)

        categories = ["street", "wildlife", "landscape"]
        abs_paths = []
        for i in range(n):
            img_path = base / f"img_{i:03d}.jpg"
            Image.new("RGB", (100, 100), "blue").save(str(img_path), "JPEG")
            abs_path = str(img_path.resolve())
            abs_paths.append(abs_path)
            conn.execute(
                "INSERT INTO images (file_path, filename, extension, file_size) VALUES (?,?,?,?)",
                (abs_path, img_path.name, ".jpg", 1000),
            )
            save_result(conn, _make_cloud_result(abs_path, category=categories[i % len(categories)]))

        conn.commit()
        conn.close()
        return base, abs_paths

    def test_dry_run_does_not_move(self, tmp_path: Path) -> None:
        """--dry-run shows plan but files stay in place."""
        base, abs_paths = self._setup_scannable(tmp_path)

        from photoagent.cloud.cli import cloud_organize
        cloud_organize(str(base), mapping_path=None, copy=False, dry_run=True)

        # All files still in original location
        for p in abs_paths:
            assert Path(p).exists()
        # No category folders created
        assert not (base / "Street").exists()

    @patch("photoagent.plan_display.get_user_approval", return_value="approve")
    @patch("photoagent.plan_display.display_plan")
    def test_execute_moves_files(self, mock_display: MagicMock, mock_approval: MagicMock, tmp_path: Path) -> None:
        """Execute mode moves files into category folders."""
        base, abs_paths = self._setup_scannable(tmp_path)

        from photoagent.cloud.cli import cloud_organize
        cloud_organize(str(base), mapping_path=None, copy=False, dry_run=False)

        # Category folders should exist
        assert (base / "Street").exists() or (base / "Wildlife").exists() or (base / "Landscape").exists()

    @patch("photoagent.plan_display.get_user_approval", return_value="approve")
    @patch("photoagent.plan_display.display_plan")
    def test_copy_keeps_originals(self, mock_display: MagicMock, mock_approval: MagicMock, tmp_path: Path) -> None:
        """--copy flag copies files but keeps originals in place."""
        base, abs_paths = self._setup_scannable(tmp_path)

        from photoagent.cloud.cli import cloud_organize
        cloud_organize(str(base), mapping_path=None, copy=True, dry_run=False)

        # Originals still exist
        for p in abs_paths:
            assert Path(p).exists(), f"Original should still exist: {p}"

    @patch("photoagent.plan_display.get_user_approval", return_value="approve")
    @patch("photoagent.plan_display.display_plan")
    def test_custom_mapping(self, mock_display: MagicMock, mock_approval: MagicMock, tmp_path: Path) -> None:
        """--mapping applies a custom category mapping."""
        base, abs_paths = self._setup_scannable(tmp_path)

        mapping_file = tmp_path / "map.json"
        mapping_file.write_text(json.dumps({
            "Documentary": ["street", "wildlife", "landscape"],
        }))

        from photoagent.cloud.cli import cloud_organize
        cloud_organize(str(base), mapping_path=str(mapping_file), copy=True, dry_run=False)

        # All files should be in Documentary/
        assert (base / "Documentary").exists()

    def test_no_cloud_results_message(self, tmp_path: Path, capsys) -> None:
        """When no cloud_analysis results, prints helpful message."""
        base = tmp_path / "empty"
        base.mkdir()
        db_dir = base / ".photoagent"
        db_dir.mkdir()

        conn = sqlite3.connect(str(db_dir / "catalog.db"))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT UNIQUE NOT NULL,
                filename TEXT NOT NULL,
                extension TEXT NOT NULL
            )
        """)
        ensure_table(conn)
        conn.commit()
        conn.close()

        from photoagent.cloud.cli import cloud_organize
        cloud_organize(str(base), mapping_path=None, copy=False, dry_run=True)
        # Should not crash — it prints a message about running cloud-analyze first

    def test_no_catalog_message(self, tmp_path: Path) -> None:
        """When no catalog.db exists, prints helpful message."""
        base = tmp_path / "nocat"
        base.mkdir()

        from photoagent.cloud.cli import cloud_organize
        cloud_organize(str(base), mapping_path=None, copy=False, dry_run=True)
        # Should not crash — it prints a message about running scan first

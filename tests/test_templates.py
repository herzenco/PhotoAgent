"""Tests for photoagent.templates — TemplateEngine built-in and custom templates.

These tests validate organization templates that produce move plans
based on image metadata: date, location, camera, type, and quality.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any, Generator

import pytest

from photoagent.database import CatalogDB


# ------------------------------------------------------------------
# Helper: insert image records
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
def template_db(tmp_path: Path) -> Generator[CatalogDB, None, None]:
    """CatalogDB with ~10 images having varied metadata for template tests."""
    db = CatalogDB(tmp_path)

    records = [
        _make_record(
            file_path="/photos/IMG_0001.jpg",
            filename="IMG_0001.jpg",
            date_taken="2023-07-15 10:00:00",
            city="Paris",
            country="France",
            camera_make="Canon",
            camera_model="EOS R5",
            ai_quality_score=0.9,
        ),
        _make_record(
            file_path="/photos/IMG_0002.jpg",
            filename="IMG_0002.jpg",
            date_taken="2023-07-16 14:00:00",
            city="Paris",
            country="France",
            camera_make="Canon",
            camera_model="EOS R5",
            ai_quality_score=0.85,
        ),
        _make_record(
            file_path="/photos/IMG_0003.jpg",
            filename="IMG_0003.jpg",
            date_taken="2023-12-25 09:00:00",
            city="London",
            country="UK",
            camera_make="Apple",
            camera_model="iPhone 15 Pro",
            ai_quality_score=0.7,
        ),
        _make_record(
            file_path="/photos/IMG_0004.jpg",
            filename="IMG_0004.jpg",
            date_taken="2022-03-10 08:00:00",
            city="Berlin",
            country="Germany",
            camera_make="Sony",
            camera_model="A7IV",
            ai_quality_score=0.92,
        ),
        _make_record(
            file_path="/photos/IMG_0005.jpg",
            filename="IMG_0005.jpg",
            date_taken="2022-06-20 18:30:00",
            city="New York",
            country="USA",
            camera_make="Sony",
            camera_model="A7IV",
            ai_quality_score=0.15,
        ),
        _make_record(
            file_path="/photos/screenshot1.png",
            filename="screenshot1.png",
            extension=".png",
            date_taken="2023-05-20 09:00:00",
            camera_make="Apple",
            camera_model="iPhone 15 Pro",
            ai_quality_score=0.5,
            is_screenshot=True,
        ),
        _make_record(
            file_path="/photos/screenshot2.png",
            filename="screenshot2.png",
            extension=".png",
            date_taken="2023-10-01 12:00:00",
            camera_make="Apple",
            camera_model="iPhone 15 Pro",
            ai_quality_score=0.45,
            is_screenshot=True,
        ),
        _make_record(
            file_path="/photos/IMG_0006.jpg",
            filename="IMG_0006.jpg",
            date_taken="2023-01-05 11:00:00",
            city="Tokyo",
            country="Japan",
            camera_make="Canon",
            camera_model="EOS R5",
            ai_quality_score=0.88,
        ),
        _make_record(
            file_path="/photos/blurry.jpg",
            filename="blurry.jpg",
            date_taken="2023-04-15 16:00:00",
            city="London",
            country="UK",
            camera_make="Apple",
            camera_model="iPhone 12",
            ai_quality_score=0.1,
        ),
    ]

    # Insert all, then mark one as duplicate
    ids = []
    for rec in records:
        ids.append(db.insert_image(rec))

    # Mark blurry.jpg as low quality (already 0.1)
    # Mark IMG_0005 as duplicate of IMG_0004
    db.update_image(ids[4], is_duplicate_of=ids[3])

    yield db
    db.close()


# ------------------------------------------------------------------
# Lazy import
# ------------------------------------------------------------------

def _get_template_engine():
    try:
        from photoagent.templates import TemplateEngine
        return TemplateEngine
    except ImportError:
        pytest.skip("photoagent.templates not yet implemented")


# ==================================================================
# TestBuiltinTemplates
# ==================================================================

class TestBuiltinTemplates:
    """Verify built-in organization templates produce correct plans."""

    def test_by_date_template(self, template_db: CatalogDB, tmp_path: Path) -> None:
        TemplateEngine = _get_template_engine()
        engine = TemplateEngine(template_db, tmp_path)
        plan = engine.apply_template("by-date")

        moves = plan["moves"]
        assert len(moves) > 0

        # Check that moves produce date-based paths like "2023/07/filename.jpg"
        for move in moves:
            dest = move["to"]
            # Should contain year/month pattern
            parts = Path(dest).parts
            # At minimum, there should be a year component
            year_parts = [p for p in parts if p.isdigit() and len(p) == 4]
            assert len(year_parts) >= 1, f"Expected year in path: {dest}"

    def test_by_date_location_template(self, template_db: CatalogDB, tmp_path: Path) -> None:
        TemplateEngine = _get_template_engine()
        engine = TemplateEngine(template_db, tmp_path)
        plan = engine.apply_template("by-date-location")

        moves = plan["moves"]
        assert len(moves) > 0

        # Find the Paris image moves
        paris_moves = [m for m in moves if "IMG_0001" in m.get("from", "")]
        assert len(paris_moves) >= 1
        dest = paris_moves[0]["to"]
        # Should include location info (Paris or France)
        assert "Paris" in dest or "France" in dest, f"Expected location in path: {dest}"

    def test_by_camera_template(self, template_db: CatalogDB, tmp_path: Path) -> None:
        TemplateEngine = _get_template_engine()
        engine = TemplateEngine(template_db, tmp_path)
        plan = engine.apply_template("by-camera")

        moves = plan["moves"]
        assert len(moves) > 0

        # Find Canon image moves
        canon_moves = [m for m in moves if "IMG_0001" in m.get("from", "")]
        assert len(canon_moves) >= 1
        dest = canon_moves[0]["to"]
        assert "EOS R5" in dest or "Canon" in dest, f"Expected camera in path: {dest}"

    def test_by_type_template(self, template_db: CatalogDB, tmp_path: Path) -> None:
        TemplateEngine = _get_template_engine()
        engine = TemplateEngine(template_db, tmp_path)
        plan = engine.apply_template("by-type")

        moves = plan["moves"]
        assert len(moves) > 0

        screenshot_dests = []
        photo_dests = []
        for move in moves:
            src = move.get("from", "")
            dest = move["to"]
            if "screenshot" in src.lower():
                screenshot_dests.append(dest)
            else:
                photo_dests.append(dest)

        # Screenshots should go to Screenshots/ folder
        for d in screenshot_dests:
            assert "Screenshot" in d or "screenshot" in d.lower(), f"Screenshot not in expected folder: {d}"

        # Non-screenshot images should go to Photos/, Duplicates/, or Low Quality/
        valid_folders = {"photos", "duplicates", "low quality"}
        for d in photo_dests:
            folder = Path(d).parts[0].lower() if Path(d).parts else ""
            assert folder in valid_folders, f"Photo not in expected folder: {d}"

    def test_cleanup_template(self, template_db: CatalogDB, tmp_path: Path) -> None:
        TemplateEngine = _get_template_engine()
        engine = TemplateEngine(template_db, tmp_path)
        plan = engine.apply_template("cleanup")

        moves = plan["moves"]

        # Low quality images should go to a review/low quality folder
        low_quality_moves = [
            m for m in moves
            if "blurry" in m.get("from", "").lower()
        ]
        assert len(low_quality_moves) >= 1
        dest = low_quality_moves[0]["to"]
        dest_lower = dest.lower()
        assert "review" in dest_lower or "low" in dest_lower or "quality" in dest_lower, \
            f"Low quality not in review folder: {dest}"

        # Duplicate images should go to review/duplicates folder
        dup_moves = [
            m for m in moves
            if "IMG_0005" in m.get("from", "")
        ]
        assert len(dup_moves) >= 1
        dup_dest = dup_moves[0]["to"]
        dup_lower = dup_dest.lower()
        assert "review" in dup_lower or "duplicate" in dup_lower, \
            f"Duplicate not in review folder: {dup_dest}"

    def test_template_returns_valid_plan(self, template_db: CatalogDB, tmp_path: Path) -> None:
        TemplateEngine = _get_template_engine()
        engine = TemplateEngine(template_db, tmp_path)
        plan = engine.apply_template("by-date")

        # Plan must have required top-level keys
        assert "folder_structure" in plan, "Plan missing 'folder_structure'"
        assert "moves" in plan, "Plan missing 'moves'"
        assert "summary" in plan, "Plan missing 'summary'"

        # moves is a list
        assert isinstance(plan["moves"], list)
        # folder_structure is a list or dict
        assert isinstance(plan["folder_structure"], (list, dict))
        # summary is a dict or string
        assert isinstance(plan["summary"], (dict, str))

    def test_get_builtin_templates(self, template_db: CatalogDB, tmp_path: Path) -> None:
        TemplateEngine = _get_template_engine()
        engine = TemplateEngine(template_db, tmp_path)
        templates = engine.get_builtin_templates()

        assert isinstance(templates, list)
        assert len(templates) >= 5

        expected = {"by-date", "by-date-location", "by-camera", "by-type", "cleanup"}
        template_set = set(templates) if isinstance(templates[0], str) else {t["name"] for t in templates}
        assert expected.issubset(template_set), f"Missing templates: {expected - template_set}"


# ==================================================================
# TestCustomTemplate
# ==================================================================

class TestCustomTemplate:
    """Verify user-defined YAML templates are parsed and applied correctly."""

    def test_custom_yaml_template(self, template_db: CatalogDB, tmp_path: Path) -> None:
        TemplateEngine = _get_template_engine()
        engine = TemplateEngine(template_db, tmp_path)

        yaml_content = textwrap.dedent("""\
            name: custom-test
            rules:
              - match:
                  location_country: France
                destination: "Europe/France/{filename}"
              - match:
                  location_country: UK
                destination: "Europe/UK/{filename}"
              - default:
                  destination: "Other/{filename}"
        """)
        yaml_path = tmp_path / "custom.yaml"
        yaml_path.write_text(yaml_content)

        plan = engine.apply_custom_template(yaml_path)
        moves = plan["moves"]

        # France images should match the first rule
        france_moves = [
            m for m in moves
            if "IMG_0001" in m.get("from", "")
        ]
        assert len(france_moves) >= 1
        assert "Europe/France" in france_moves[0]["to"]

    def test_custom_template_default_rule(self, template_db: CatalogDB, tmp_path: Path) -> None:
        TemplateEngine = _get_template_engine()
        engine = TemplateEngine(template_db, tmp_path)

        # Rule only matches Japan; everything else goes to default
        yaml_content = textwrap.dedent("""\
            name: narrow-rule
            rules:
              - match:
                  location_country: Japan
                destination: "Japan/{filename}"
              - default:
                  destination: "Unsorted/{filename}"
        """)
        yaml_path = tmp_path / "narrow.yaml"
        yaml_path.write_text(yaml_content)

        plan = engine.apply_custom_template(yaml_path)
        moves = plan["moves"]

        # The Tokyo image should go to Japan/
        japan_moves = [
            m for m in moves
            if "IMG_0006" in m.get("from", "")
        ]
        assert len(japan_moves) >= 1
        assert "Japan" in japan_moves[0]["to"]

        # A non-Japan image (e.g. Paris) should go to Unsorted/
        paris_moves = [
            m for m in moves
            if "IMG_0001" in m.get("from", "")
        ]
        assert len(paris_moves) >= 1
        assert "Unsorted" in paris_moves[0]["to"]

    def test_custom_template_variables(self, template_db: CatalogDB, tmp_path: Path) -> None:
        TemplateEngine = _get_template_engine()
        engine = TemplateEngine(template_db, tmp_path)

        yaml_content = textwrap.dedent("""\
            name: variable-test
            rules:
              - match: {}
                destination: "{year}/{month}/{filename}"
        """)
        yaml_path = tmp_path / "vars.yaml"
        yaml_path.write_text(yaml_content)

        plan = engine.apply_custom_template(yaml_path)
        moves = plan["moves"]

        # Find the 2023-07-15 image (IMG_0001)
        img1_moves = [
            m for m in moves
            if "IMG_0001" in m.get("from", "")
        ]
        assert len(img1_moves) >= 1
        dest = img1_moves[0]["to"]
        assert "2023" in dest, f"Expected year 2023 in {dest}"
        assert "07" in dest, f"Expected month 07 in {dest}"
        assert "IMG_0001.jpg" in dest, f"Expected filename in {dest}"

    def test_custom_template_missing_file(self, template_db: CatalogDB, tmp_path: Path) -> None:
        TemplateEngine = _get_template_engine()
        engine = TemplateEngine(template_db, tmp_path)

        with pytest.raises(FileNotFoundError):
            engine.apply_custom_template(Path("/nonexistent/path/to/template.yaml"))

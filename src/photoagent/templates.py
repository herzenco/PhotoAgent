"""Offline organization templates for PhotoAgent.

Provides built-in and custom YAML-based templates that generate
organization plans without any network access.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from photoagent.database import CatalogDB

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _sanitize_filename(text: str, max_len: int = 60) -> str:
    """Remove characters unsafe for filenames and truncate."""
    cleaned = _UNSAFE_CHARS.sub("_", text).strip(" ._")
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len].rstrip(" ._")
    return cleaned or "untitled"


def _safe_json_loads(raw: str | None) -> list[dict[str, Any]]:
    """Parse a JSON string into a list of dicts, returning [] on failure."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _parse_date(date_str: str | None) -> datetime | None:
    """Parse a date_taken string into a datetime object."""
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt)
        except (ValueError, TypeError):
            continue
    return None


def _image_date_parts(img: dict[str, Any]) -> dict[str, str]:
    """Extract year, month, day, date string from an image record."""
    dt = _parse_date(str(img.get("date_taken") or ""))
    if dt:
        return {
            "year": str(dt.year),
            "month": f"{dt.month:02d}",
            "day": f"{dt.day:02d}",
            "date": dt.strftime("%Y-%m-%d"),
        }
    return {"year": "Unknown", "month": "00", "day": "00", "date": "unknown"}


def _image_location(img: dict[str, Any]) -> str:
    """Return a location string like 'City' or 'Country' or 'Unknown'."""
    city = img.get("city") or ""
    country = img.get("country") or ""
    if city:
        return _sanitize_filename(city)
    if country:
        return _sanitize_filename(country)
    return "Unknown"


def _image_camera(img: dict[str, Any]) -> str:
    """Return camera model or 'Unknown Camera'."""
    model = img.get("camera_model") or ""
    if model:
        return _sanitize_filename(model)
    return "Unknown Camera"


def _caption_short(img: dict[str, Any], max_len: int = 30) -> str:
    """First max_len chars of caption, sanitized for filenames."""
    caption = img.get("ai_caption") or ""
    return _sanitize_filename(caption[:max_len]) if caption else "untitled"


# ------------------------------------------------------------------
# Template variables expansion
# ------------------------------------------------------------------


def _expand_template_vars(
    template: str, img: dict[str, Any]
) -> str:
    """Expand {var} placeholders in a template string using image metadata."""
    parts = _image_date_parts(img)

    replacements = {
        "{year}": parts["year"],
        "{month}": parts["month"],
        "{day}": parts["day"],
        "{date}": parts["date"],
        "{filename}": img.get("filename") or "unknown",
        "{caption_short}": _caption_short(img),
        "{location}": _image_location(img),
        "{camera}": _image_camera(img),
        "{ext}": img.get("extension") or "",
    }

    result = template
    for var, value in replacements.items():
        result = result.replace(var, value)
    return result


# ------------------------------------------------------------------
# TemplateEngine
# ------------------------------------------------------------------


class TemplateEngine:
    """Generate organization plans from built-in or custom YAML templates."""

    def __init__(self, db: CatalogDB, base_path: Path) -> None:
        self._db = db
        self._base_path = Path(base_path)

    # ------------------------------------------------------------------
    # Built-in template list
    # ------------------------------------------------------------------

    @staticmethod
    def get_builtin_templates() -> list[str]:
        """Return names of all built-in templates."""
        return [
            "by-date",
            "by-date-location",
            "by-camera",
            "by-type",
            "cleanup",
        ]

    # ------------------------------------------------------------------
    # Apply built-in template
    # ------------------------------------------------------------------

    def apply_template(self, template_name: str) -> dict[str, Any]:
        """Apply a built-in template and return a plan dict.

        Parameters
        ----------
        template_name:
            One of the names returned by get_builtin_templates().

        Returns
        -------
        Plan dict with keys: folder_structure, moves, summary.
        """
        handlers = {
            "by-date": self._template_by_date,
            "by-date-location": self._template_by_date_location,
            "by-camera": self._template_by_camera,
            "by-type": self._template_by_type,
            "cleanup": self._template_cleanup,
        }

        handler = handlers.get(template_name)
        if handler is None:
            available = ", ".join(self.get_builtin_templates())
            raise ValueError(
                f"Unknown template '{template_name}'. "
                f"Available: {available}"
            )

        images = self._db.get_all_images()
        moves = handler(images)
        return self._build_plan_from_moves(moves, template_name)

    # ------------------------------------------------------------------
    # Built-in template implementations
    # ------------------------------------------------------------------

    def _template_by_date(
        self, images: list[dict[str, Any]]
    ) -> list[tuple[int, str, str]]:
        """Organize by {year}/{month:02d}/{filename}."""
        moves: list[tuple[int, str, str]] = []
        for img in images:
            parts = _image_date_parts(img)
            dest = f"{parts['year']}/{parts['month']}/{img['filename']}"
            moves.append((img["id"], img["file_path"], dest))
        return moves

    def _template_by_date_location(
        self, images: list[dict[str, Any]]
    ) -> list[tuple[int, str, str]]:
        """Organize by {year}/{month:02d}/{location}/{filename}."""
        moves: list[tuple[int, str, str]] = []
        for img in images:
            parts = _image_date_parts(img)
            location = _image_location(img)
            dest = (
                f"{parts['year']}/{parts['month']}/"
                f"{location}/{img['filename']}"
            )
            moves.append((img["id"], img["file_path"], dest))
        return moves

    def _template_by_camera(
        self, images: list[dict[str, Any]]
    ) -> list[tuple[int, str, str]]:
        """Organize by {camera_model}/{filename}."""
        moves: list[tuple[int, str, str]] = []
        for img in images:
            camera = _image_camera(img)
            dest = f"{camera}/{img['filename']}"
            moves.append((img["id"], img["file_path"], dest))
        return moves

    def _template_by_type(
        self, images: list[dict[str, Any]]
    ) -> list[tuple[int, str, str]]:
        """Sort into Photos/, Screenshots/, Duplicates/, Low Quality/."""
        moves: list[tuple[int, str, str]] = []
        for img in images:
            quality = img.get("ai_quality_score")
            if img.get("is_duplicate_of"):
                folder = "Duplicates"
            elif img.get("is_screenshot"):
                folder = "Screenshots"
            elif quality is not None and quality < 0.3:
                folder = "Low Quality"
            else:
                folder = "Photos"
            dest = f"{folder}/{img['filename']}"
            moves.append((img["id"], img["file_path"], dest))
        return moves

    def _template_cleanup(
        self, images: list[dict[str, Any]]
    ) -> list[tuple[int, str, str]]:
        """Move duplicates, low quality, and screenshots to review folders.

        Only moves files that match a cleanup criteria; leaves others in place.
        """
        moves: list[tuple[int, str, str]] = []
        for img in images:
            quality = img.get("ai_quality_score")
            if img.get("is_duplicate_of"):
                dest = f"Review/Duplicates/{img['filename']}"
            elif quality is not None and quality < 0.3:
                dest = f"Review/Low Quality/{img['filename']}"
            elif img.get("is_screenshot"):
                dest = f"Screenshots/{img['filename']}"
            else:
                # Leave in place
                continue
            moves.append((img["id"], img["file_path"], dest))
        return moves

    # ------------------------------------------------------------------
    # Custom YAML template
    # ------------------------------------------------------------------

    def apply_custom_template(self, yaml_path: Path) -> dict[str, Any]:
        """Apply a custom YAML template file and return a plan dict.

        Parameters
        ----------
        yaml_path:
            Path to a YAML file defining organization rules.

        Returns
        -------
        Plan dict with keys: folder_structure, moves, summary.
        """
        try:
            import yaml
        except ImportError:
            raise ImportError(
                "PyYAML is required for custom templates. "
                "Install it with: pip install pyyaml"
            )

        yaml_path = Path(yaml_path)
        if not yaml_path.exists():
            raise FileNotFoundError(f"Template file not found: {yaml_path}")

        with open(yaml_path, "r", encoding="utf-8") as f:
            template = yaml.safe_load(f)

        if not isinstance(template, dict) or "rules" not in template:
            raise ValueError(
                "Invalid template format. Must contain a 'rules' key."
            )

        template_name = template.get("name", yaml_path.stem)
        rules = template["rules"]
        images = self._db.get_all_images()
        moves = self._apply_rules(images, rules)
        return self._build_plan_from_moves(moves, template_name)

    def _apply_rules(
        self,
        images: list[dict[str, Any]],
        rules: list[dict[str, Any]],
    ) -> list[tuple[int, str, str]]:
        """Apply YAML rules to images and return move tuples."""
        moves: list[tuple[int, str, str]] = []
        # Preload face cluster labels per image for person matching
        face_labels = self._get_face_labels_by_image()

        for img in images:
            matched = False
            for rule in rules:
                if "default" in rule:
                    # Default rule: applies to all unmatched images
                    dest_template = rule["default"].get("destination", "Unsorted")
                    rename_template = rule["default"].get("rename")
                    dest = self._resolve_destination(
                        img, dest_template, rename_template
                    )
                    moves.append((img["id"], img["file_path"], dest))
                    matched = True
                    break

                match_spec = rule.get("match", {})
                if self._matches_rule(img, match_spec, face_labels):
                    dest_template = rule.get("destination", "Matched")
                    rename_template = rule.get("rename")
                    dest = self._resolve_destination(
                        img, dest_template, rename_template
                    )
                    moves.append((img["id"], img["file_path"], dest))
                    matched = True
                    break

            # If no rule matched and no default rule, skip the image
        return moves

    def _matches_rule(
        self,
        img: dict[str, Any],
        match_spec: dict[str, Any],
        face_labels: dict[int, list[str]],
    ) -> bool:
        """Check whether an image matches all conditions in a rule."""
        for condition, value in match_spec.items():
            if not self._check_condition(img, condition, value, face_labels):
                return False
        return True

    def _check_condition(
        self,
        img: dict[str, Any],
        condition: str,
        value: Any,
        face_labels: dict[int, list[str]],
    ) -> bool:
        """Evaluate a single match condition."""
        if condition == "tags_contain":
            tags = _safe_json_loads(img.get("ai_tags"))
            tag_labels = [t.get("label", "").lower() for t in tags]
            return str(value).lower() in tag_labels

        if condition == "location_country":
            return (img.get("country") or "").lower() == str(value).lower()

        if condition == "location_city":
            return (img.get("city") or "").lower() == str(value).lower()

        if condition == "camera_model":
            return (img.get("camera_model") or "").lower() == str(value).lower()

        if condition == "is_screenshot":
            return bool(img.get("is_screenshot")) == bool(value)

        if condition == "is_duplicate":
            is_dup = img.get("is_duplicate_of") is not None
            return is_dup == bool(value)

        if condition == "quality_below":
            score = img.get("ai_quality_score")
            if score is None:
                return False
            return float(score) < float(value)

        if condition == "quality_above":
            score = img.get("ai_quality_score")
            if score is None:
                return False
            return float(score) > float(value)

        if condition == "year":
            dt = _parse_date(str(img.get("date_taken") or ""))
            if dt is None:
                return False
            return dt.year == int(value)

        if condition == "date_before":
            dt = _parse_date(str(img.get("date_taken") or ""))
            if dt is None:
                return False
            cutoff = _parse_date(str(value))
            if cutoff is None:
                return False
            return dt < cutoff

        if condition == "date_after":
            dt = _parse_date(str(img.get("date_taken") or ""))
            if dt is None:
                return False
            cutoff = _parse_date(str(value))
            if cutoff is None:
                return False
            return dt > cutoff

        if condition == "person":
            img_labels = face_labels.get(img["id"], [])
            return str(value).lower() in [l.lower() for l in img_labels]

        logger.warning("Unknown match condition: %s", condition)
        return False

    def _resolve_destination(
        self,
        img: dict[str, Any],
        dest_template: str,
        rename_template: str | None = None,
    ) -> str:
        """Expand template variables and build the final destination path."""
        folder = _expand_template_vars(dest_template, img)
        if rename_template:
            new_name = _expand_template_vars(rename_template, img)
            # Ensure extension is preserved
            ext = img.get("extension") or ""
            if ext and not new_name.endswith(f".{ext}"):
                new_name = f"{new_name}.{ext}"
            return f"{folder}/{_sanitize_filename(new_name, max_len=200)}"
        return f"{folder}/{img['filename']}"

    def _get_face_labels_by_image(self) -> dict[int, list[str]]:
        """Return a mapping of image_id -> list of face cluster labels."""
        result: dict[int, list[str]] = {}
        try:
            rows = self._db._conn.execute(
                "SELECT image_id, cluster_label FROM faces "
                "WHERE cluster_label IS NOT NULL"
            ).fetchall()
            for row in rows:
                img_id = row["image_id"]
                label = row["cluster_label"]
                if img_id not in result:
                    result[img_id] = []
                result[img_id].append(label)
        except Exception:
            pass
        return result

    # ------------------------------------------------------------------
    # Plan builder
    # ------------------------------------------------------------------

    def _build_plan_from_moves(
        self,
        moves: list[tuple[int, str, str]],
        template_name: str,
    ) -> dict[str, Any]:
        """Convert (id, from, to) tuples into the standard plan dict format.

        Parameters
        ----------
        moves:
            List of (image_id, source_path, destination_path) tuples.
        template_name:
            Name of the template applied (for the summary).

        Returns
        -------
        Plan dict with keys: folder_structure, moves, summary.
        """
        # Collect unique folders
        folders: set[str] = set()
        plan_moves: list[dict[str, Any]] = []

        for img_id, from_path, to_path in moves:
            # Extract folder from destination
            dest_folder = str(Path(to_path).parent)
            if dest_folder and dest_folder != ".":
                # Add the folder and all parent folders
                parts = Path(dest_folder).parts
                for i in range(len(parts)):
                    folders.add("/".join(parts[: i + 1]))

            plan_moves.append({
                "id": img_id,
                "from": from_path,
                "to": to_path,
            })

        folder_list = sorted(folders)
        total = len(plan_moves)
        summary = (
            f"Template '{template_name}': organizing {total} "
            f"file{'s' if total != 1 else ''} into "
            f"{len(folder_list)} folder{'s' if len(folder_list) != 1 else ''}."
        )

        return {
            "folder_structure": folder_list,
            "moves": plan_moves,
            "summary": summary,
        }

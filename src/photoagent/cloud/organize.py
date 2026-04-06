"""Cloud-based organization: group images by cloud analysis category."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def load_custom_mapping(mapping_path: Path) -> dict[str, list[str]]:
    """Load a JSON mapping file: folder_name -> [category, ...].

    Example JSON::

        {
            "Street": ["street"],
            "Wildlife": ["wildlife", "nature"],
            "Documentary": ["event", "street"]
        }

    Raises ``FileNotFoundError`` or ``json.JSONDecodeError`` on bad input.
    """
    text = mapping_path.read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Mapping JSON must be a dict of folder -> [categories]")
    for key, val in data.items():
        if not isinstance(val, list):
            raise ValueError(f"Mapping value for '{key}' must be a list of category strings")
    return data


def build_category_to_folder(
    mapping: dict[str, list[str]] | None,
    categories: set[str],
) -> dict[str, str]:
    """Build a category -> folder name lookup.

    Auto mode (mapping=None): title-case the category.
    Custom mode: invert the mapping. First folder claiming a category wins.
    Unmapped categories go to "Other".
    """
    if mapping is None:
        result: dict[str, str] = {}
        for cat in categories:
            if cat and cat.strip():
                result[cat] = cat.strip().title()
            else:
                result[cat] = "Uncategorized"
        return result

    # Invert: folder -> [cats] becomes cat -> folder (first match wins)
    cat_to_folder: dict[str, str] = {}
    for folder, cats in mapping.items():
        for cat in cats:
            cat_lower = cat.lower().strip()
            if cat_lower not in cat_to_folder:
                cat_to_folder[cat_lower] = folder
            else:
                logger.warning(
                    "Category '%s' already mapped to '%s', ignoring mapping to '%s'",
                    cat, cat_to_folder[cat_lower], folder,
                )

    # Map all actual categories, defaulting unmapped to "Other"
    result = {}
    for cat in categories:
        cat_lower = (cat or "").lower().strip()
        result[cat] = cat_to_folder.get(cat_lower, "Other")
    return result


def build_organize_plan(
    conn: sqlite3.Connection,
    base_path: Path,
    mapping: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Build an organization plan from cloud analysis results.

    Parameters
    ----------
    conn:
        SQLite connection to catalog.db.
    base_path:
        Root photo directory (for making paths relative).
    mapping:
        Optional custom folder mapping, or None for auto mode.

    Returns
    -------
    Standard plan dict with folder_structure, moves, summary.
    """
    rows = conn.execute(
        "SELECT image_path, category FROM cloud_analysis"
    ).fetchall()

    if not rows:
        return {
            "folder_structure": [],
            "moves": [],
            "summary": "No cloud analysis results found.",
        }

    # Collect unique categories
    categories = {row[1] for row in rows}

    # Build category -> folder mapping
    cat_to_folder = build_category_to_folder(mapping, categories)

    # Build moves
    base_resolved = base_path.resolve()
    moves: list[tuple[int, str, str]] = []

    for idx, (abs_path, category) in enumerate(rows, start=1):
        # Convert absolute path to relative
        try:
            rel_path = str(Path(abs_path).relative_to(base_resolved))
        except ValueError:
            logger.warning("Path %s not under %s, skipping", abs_path, base_resolved)
            continue

        folder = cat_to_folder.get(category, "Other")
        filename = Path(abs_path).name
        dest_rel = f"{folder}/{filename}"

        # Look up image ID from main images table
        row = conn.execute(
            "SELECT id FROM images WHERE file_path = ?", (abs_path,)
        ).fetchone()
        img_id = row[0] if row else idx

        moves.append((img_id, rel_path, dest_rel))

    return _build_plan_from_moves(moves, mapping)


def _build_plan_from_moves(
    moves: list[tuple[int, str, str]],
    mapping: dict[str, list[str]] | None,
) -> dict[str, Any]:
    """Convert move tuples into the standard plan dict."""
    folders: set[str] = set()
    plan_moves: list[dict[str, Any]] = []

    for img_id, from_path, to_path in moves:
        dest_folder = str(Path(to_path).parent)
        if dest_folder and dest_folder != ".":
            # Add all parent paths for nested folders
            parts = Path(dest_folder).parts
            for i in range(len(parts)):
                folders.add("/".join(parts[: i + 1]))
        plan_moves.append({"id": img_id, "from": from_path, "to": to_path})

    folder_list = sorted(folders)
    total = len(plan_moves)
    mode = "custom mapping" if mapping else "auto (by category)"
    summary = (
        f"Cloud organize ({mode}): organizing {total} "
        f"file{'s' if total != 1 else ''} into "
        f"{len(folder_list)} folder{'s' if len(folder_list) != 1 else ''}."
    )

    return {
        "folder_structure": folder_list,
        "moves": plan_moves,
        "summary": summary,
    }

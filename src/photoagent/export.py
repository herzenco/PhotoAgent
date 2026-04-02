"""Catalog export for PhotoAgent.

Exports image catalog data to JSON or CSV format with optional filtering.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from photoagent.database import CatalogDB


def _safe_json_loads(raw: str | None) -> list[Any]:
    """Parse a JSON string, returning [] on failure."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def _flatten_tags(raw: str | None) -> str:
    """Flatten a JSON tag array to a comma-separated string of labels."""
    tags = _safe_json_loads(raw)
    return ", ".join(t.get("label", "") for t in tags if isinstance(t, dict))


def _fetch_faces_by_image(db: CatalogDB) -> dict[int, list[dict[str, Any]]]:
    """Return a mapping of image_id -> list of face dicts."""
    result: dict[int, list[dict[str, Any]]] = {}
    try:
        rows = db._conn.execute(
            "SELECT image_id, cluster_id, cluster_label, "
            "bbox_x, bbox_y, bbox_w, bbox_h FROM faces"
        ).fetchall()
        for row in rows:
            img_id = row["image_id"]
            face = {
                "cluster_id": row["cluster_id"],
                "cluster_label": row["cluster_label"],
                "bbox": {
                    "x": row["bbox_x"],
                    "y": row["bbox_y"],
                    "w": row["bbox_w"],
                    "h": row["bbox_h"],
                },
            }
            if img_id not in result:
                result[img_id] = []
            result[img_id].append(face)
    except Exception:
        pass
    return result


def _apply_filters(
    db: CatalogDB, filters: dict[str, Any]
) -> list[dict[str, Any]]:
    """Fetch images from DB with SQL-level filters applied."""
    clauses: list[str] = []
    params: list[Any] = []

    if "year" in filters:
        clauses.append("strftime('%Y', date_taken) = ?")
        params.append(str(filters["year"]))

    if "location" in filters:
        loc = f"%{filters['location']}%"
        clauses.append("(city LIKE ? OR country LIKE ?)")
        params.extend([loc, loc])

    if "min_quality" in filters:
        clauses.append("ai_quality_score >= ?")
        params.append(float(filters["min_quality"]))

    if "type" in filters:
        type_val = filters["type"].lower()
        if type_val == "screenshot":
            clauses.append("is_screenshot = 1")
        elif type_val == "photo":
            clauses.append("(is_screenshot = 0 OR is_screenshot IS NULL)")

    if "camera" in filters:
        clauses.append("camera_model LIKE ?")
        params.append(f"%{filters['camera']}%")

    where = ""
    if clauses:
        where = "WHERE " + " AND ".join(clauses)

    sql = f"SELECT * FROM images {where}"
    rows = db._conn.execute(sql, params).fetchall()
    images = [dict(r) for r in rows]

    # Person filter requires face table join
    if "person" in filters:
        person_val = filters["person"]
        person_ids: set[int] = set()
        try:
            cid = int(person_val)
            rows2 = db._conn.execute(
                "SELECT DISTINCT image_id FROM faces WHERE cluster_id = ?",
                (cid,),
            ).fetchall()
            person_ids.update(r["image_id"] for r in rows2)
        except (ValueError, TypeError):
            pass
        rows3 = db._conn.execute(
            "SELECT DISTINCT image_id FROM faces WHERE cluster_label LIKE ?",
            (f"%{person_val}%",),
        ).fetchall()
        person_ids.update(r["image_id"] for r in rows3)
        images = [img for img in images if img["id"] in person_ids]

    return images


def export_catalog(
    db: CatalogDB,
    base_path: Path,
    output_path: Path,
    format: str = "json",
    filters: dict[str, Any] | None = None,
) -> int:
    """Export the catalog to JSON or CSV.

    Parameters
    ----------
    db:
        Open CatalogDB instance.
    base_path:
        Root directory of the photo catalog.
    output_path:
        Destination file path for the export.
    format:
        Export format: "json" or "csv".
    filters:
        Optional filter dict. Supported keys: year, location,
        min_quality, type, camera, person.

    Returns
    -------
    Count of exported records.
    """
    filters = filters or {}

    if filters:
        images = _apply_filters(db, filters)
    else:
        images = db.get_all_images()

    if not images:
        # Write empty file
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if format == "csv":
            output_path.write_text("", encoding="utf-8")
        else:
            output_path.write_text("[]", encoding="utf-8")
        return 0

    faces_by_image = _fetch_faces_by_image(db)

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if format == "csv":
        return _export_csv(images, faces_by_image, output_path)
    else:
        return _export_json(images, faces_by_image, output_path)


def _export_json(
    images: list[dict[str, Any]],
    faces_by_image: dict[int, list[dict[str, Any]]],
    output_path: Path,
) -> int:
    """Export images as structured JSON."""
    records: list[dict[str, Any]] = []

    for img in images:
        record = dict(img)

        # Parse JSON fields into proper structures
        record["ai_tags"] = _safe_json_loads(img.get("ai_tags"))

        # Add face data
        record["faces"] = faces_by_image.get(img["id"], [])

        # Convert booleans for cleaner JSON
        for bool_field in ("is_screenshot", "flash_used"):
            if bool_field in record:
                record[bool_field] = bool(record[bool_field])

        records.append(record)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False, default=str)

    return len(records)


def _export_csv(
    images: list[dict[str, Any]],
    faces_by_image: dict[int, list[dict[str, Any]]],
    output_path: Path,
) -> int:
    """Export images as CSV with flattened fields."""
    if not images:
        return 0

    # Define column order
    columns = [
        "id", "file_path", "filename", "extension", "file_size",
        "date_taken", "gps_lat", "gps_lon", "city", "country",
        "camera_make", "camera_model", "lens", "iso", "aperture",
        "shutter_speed", "ai_caption", "ai_tags", "ai_scene_type",
        "ai_quality_score", "is_screenshot", "is_duplicate_of",
        "face_count", "face_labels", "analyzed_at",
    ]

    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()

        for img in images:
            row = dict(img)

            # Flatten tags to comma-separated string
            row["ai_tags"] = _flatten_tags(img.get("ai_tags"))

            # Flatten face labels
            faces = faces_by_image.get(img["id"], [])
            row["face_labels"] = ", ".join(
                f.get("cluster_label", "") or ""
                for f in faces
            )

            writer.writerow(row)

    return len(images)

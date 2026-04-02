"""Catalog summarizer for PhotoAgent.

Builds high-level summaries and per-image manifests from the catalog database.
All outputs are text/metadata only -- never includes pixel data, thumbnails,
or binary content.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from photoagent.database import CatalogDB


class CatalogSummarizer:
    """Produces catalog summaries and chunked manifests for the planner."""

    def __init__(self, db: CatalogDB) -> None:
        self._db = db
        self._base_path: Path = db._base_path

    # ------------------------------------------------------------------
    # High-level summary
    # ------------------------------------------------------------------

    def build_summary(self) -> dict[str, Any]:
        """Return a high-level summary of the entire catalog.

        The summary is designed to give an LLM planner enough context to
        propose an organization scheme without seeing any actual image data.
        """
        images = self._db.get_all_images()
        stats = self._db.get_stats()

        # Date range ---------------------------------------------------
        dates: list[str] = sorted(
            img["date_taken"]
            for img in images
            if img.get("date_taken")
        )
        date_range = (
            f"{dates[0][:10]} to {dates[-1][:10]}" if dates else "unknown"
        )

        # Locations (top 30) -------------------------------------------
        location_counter: Counter[str] = Counter()
        for img in images:
            city = img.get("city")
            country = img.get("country")
            if city and country:
                location_counter[f"{city}, {country}"] += 1
        locations = [
            {"name": name, "count": count}
            for name, count in location_counter.most_common(30)
        ]

        # Tag distribution (top 50) ------------------------------------
        tag_counter: Counter[str] = Counter()
        for img in images:
            raw_tags = img.get("ai_tags")
            if raw_tags:
                try:
                    tags = json.loads(raw_tags) if isinstance(raw_tags, str) else raw_tags
                    for tag in tags:
                        label = tag.get("label") if isinstance(tag, dict) else str(tag)
                        if label:
                            tag_counter[label] += 1
                except (json.JSONDecodeError, TypeError):
                    pass
        tag_distribution = dict(tag_counter.most_common(50))

        # Cameras ------------------------------------------------------
        camera_counter: Counter[str] = Counter()
        for img in images:
            make = img.get("camera_make") or ""
            model = img.get("camera_model") or ""
            name = (f"{make} {model}").strip() if (make or model) else None
            if name:
                camera_counter[name] += 1
        cameras = [
            {"name": name, "count": count}
            for name, count in camera_counter.most_common()
        ]

        # Yearly breakdown ---------------------------------------------
        yearly_breakdown: dict[str, int] = stats.get("by_year", {})

        # Screenshot count ---------------------------------------------
        screenshot_count: int = stats.get("screenshot_count", 0)

        # Duplicate groups ---------------------------------------------
        duplicate_ids: set[int] = set()
        for img in images:
            dup_of = img.get("is_duplicate_of")
            if dup_of is not None:
                duplicate_ids.add(dup_of)
        duplicate_groups = len(duplicate_ids)

        # Quality issues -----------------------------------------------
        quality_issues = self._compute_quality_issues(images)

        # Face clusters ------------------------------------------------
        face_clusters, face_cluster_count = self._compute_face_clusters()

        return {
            "total_images": stats.get("total_images", len(images)),
            "date_range": date_range,
            "locations": locations,
            "tag_distribution": tag_distribution,
            "cameras": cameras,
            "yearly_breakdown": yearly_breakdown,
            "screenshot_count": screenshot_count,
            "duplicate_groups": duplicate_groups,
            "quality_issues": quality_issues,
            "face_clusters": face_clusters,
            "face_cluster_count": face_cluster_count,
        }

    # ------------------------------------------------------------------
    # Per-image manifest (chunked)
    # ------------------------------------------------------------------

    def build_manifest(self, chunk_size: int = 5000) -> list[list[dict[str, Any]]]:
        """Return chunked per-image manifests.

        Each image dict contains only textual metadata -- no pixel data,
        base64, thumbnails, or binary content is ever included.
        """
        images = self._db.get_all_images()
        face_map = self._build_face_map()

        manifest: list[dict[str, Any]] = []
        for img in images:
            manifest.append(self._image_to_manifest_entry(img, face_map))

        # Chunk into sublists ------------------------------------------
        chunks: list[list[dict[str, Any]]] = []
        for i in range(0, len(manifest), chunk_size):
            chunks.append(manifest[i : i + chunk_size])

        return chunks if chunks else [[]]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _image_to_manifest_entry(
        self,
        img: dict[str, Any],
        face_map: dict[int, list[str]],
    ) -> dict[str, Any]:
        """Convert a raw DB image row to a compact manifest entry."""
        # Relative path ------------------------------------------------
        file_path = img.get("file_path", "")
        try:
            current_path = str(
                Path(file_path).relative_to(self._base_path)
            )
        except ValueError:
            current_path = file_path

        # Top 5 tag labels ---------------------------------------------
        tags: list[str] = []
        raw_tags = img.get("ai_tags")
        if raw_tags:
            try:
                parsed = json.loads(raw_tags) if isinstance(raw_tags, str) else raw_tags
                # Sort by score descending and take top 5
                if parsed and isinstance(parsed, list):
                    sorted_tags = sorted(
                        parsed,
                        key=lambda t: t.get("score", 0) if isinstance(t, dict) else 0,
                        reverse=True,
                    )
                    tags = [
                        t.get("label", "") if isinstance(t, dict) else str(t)
                        for t in sorted_tags[:5]
                    ]
                    tags = [t for t in tags if t]  # drop empty strings
            except (json.JSONDecodeError, TypeError):
                pass

        # Date (date portion only) -------------------------------------
        date_taken = img.get("date_taken")
        date_str = str(date_taken)[:10] if date_taken else None

        # Location -----------------------------------------------------
        city = img.get("city")
        country = img.get("country")
        location: str | None = None
        if city and country:
            location = f"{city}, {country}"
        elif city:
            location = city
        elif country:
            location = country

        # Face cluster labels ------------------------------------------
        image_id = img.get("id")
        faces = face_map.get(image_id, []) if image_id else []

        return {
            "id": image_id,
            "filename": img.get("filename", ""),
            "current_path": current_path,
            "date": date_str,
            "location": location,
            "tags": tags,
            "caption": img.get("ai_caption"),
            "quality": img.get("ai_quality_score"),
            "is_screenshot": bool(img.get("is_screenshot")),
            "is_duplicate": img.get("is_duplicate_of") is not None,
            "faces": faces,
        }

    def _build_face_map(self) -> dict[int, list[str]]:
        """Query the faces table and build a map of image_id -> [cluster labels]."""
        face_map: dict[int, list[str]] = defaultdict(list)
        try:
            conn = self._db._conn
            rows = conn.execute(
                "SELECT image_id, cluster_label FROM faces "
                "WHERE cluster_label IS NOT NULL"
            ).fetchall()
            for row in rows:
                face_map[row["image_id"]].append(row["cluster_label"])
        except Exception:
            # faces table may be empty or not populated
            pass
        # Deduplicate labels per image
        return {k: sorted(set(v)) for k, v in face_map.items()}

    def _compute_quality_issues(
        self, images: list[dict[str, Any]]
    ) -> dict[str, int]:
        """Estimate quality issue counts from ai_quality_score and ai_tags."""
        issues: Counter[str] = Counter()
        for img in images:
            score = img.get("ai_quality_score")
            if score is not None and score < 0.3:
                issues["low_quality"] += 1

            raw_tags = img.get("ai_tags")
            if raw_tags:
                try:
                    parsed = (
                        json.loads(raw_tags) if isinstance(raw_tags, str) else raw_tags
                    )
                    labels = {
                        (t.get("label", "") if isinstance(t, dict) else str(t)).lower()
                        for t in (parsed or [])
                    }
                    if "blurry" in labels or "blur" in labels:
                        issues["blurry"] += 1
                    if "dark" in labels or "underexposed" in labels:
                        issues["dark"] += 1
                    if "low_resolution" in labels or "low resolution" in labels:
                        issues["low_resolution"] += 1
                except (json.JSONDecodeError, TypeError):
                    pass
        return dict(issues)

    def _compute_face_clusters(self) -> tuple[list[dict[str, Any]], int]:
        """Return face cluster summaries from the faces table."""
        cluster_counter: Counter[str] = Counter()
        try:
            conn = self._db._conn
            rows = conn.execute(
                "SELECT cluster_label, COUNT(*) as cnt FROM faces "
                "WHERE cluster_label IS NOT NULL "
                "GROUP BY cluster_label ORDER BY cnt DESC"
            ).fetchall()
            for row in rows:
                cluster_counter[row["cluster_label"]] = row["cnt"]
        except Exception:
            pass

        clusters = [
            {"label": label, "count": count}
            for label, count in cluster_counter.most_common()
        ]
        return clusters, len(clusters)

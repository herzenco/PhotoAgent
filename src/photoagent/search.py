"""Semantic search engine for PhotoAgent.

Supports text-based matching against catalog metadata and optional
CLIP-based semantic similarity when embeddings are available.
Works fully offline with zero network access.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from photoagent.database import CatalogDB

logger = logging.getLogger(__name__)


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


def _normalize(text: str) -> str:
    """Lowercase and strip whitespace for comparison."""
    return text.strip().lower()


class ImageSearcher:
    """Search the image catalog using text matching and optional CLIP similarity."""

    def __init__(self, db: CatalogDB, base_path: Path) -> None:
        self._db = db
        self._base_path = Path(base_path)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        top_k: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Search images by query string with optional filters.

        Parameters
        ----------
        query:
            Natural-language search query.
        top_k:
            Maximum number of results to return.
        filters:
            Optional filter dict. Supported keys: year, location,
            min_quality, type, camera, person.

        Returns
        -------
        List of result dicts sorted by score descending, each containing:
        id, file_path, filename, score, caption, tags, match_reason.
        """
        filters = filters or {}

        # Fetch candidate images (apply SQL-level filters first)
        candidates = self._fetch_candidates(filters)

        if not candidates:
            return []

        query_terms = [t for t in _normalize(query).split() if len(t) > 1]

        # Score each candidate
        scored: list[dict[str, Any]] = []
        for img in candidates:
            text_score, reasons = self._text_match_score(img, query_terms)
            if text_score > 0:
                scored.append(
                    self._build_result(img, text_score, reasons)
                )

        # Attempt CLIP semantic search for additional / re-ranked results
        clip_scores = self._clip_search(candidates, query)
        if clip_scores:
            # Merge CLIP scores with text scores
            scored = self._merge_scores(scored, candidates, clip_scores)

        # If no text matches and no CLIP, try broader substring match
        if not scored and not clip_scores:
            for img in candidates:
                score, reasons = self._broad_match(img, query)
                if score > 0:
                    scored.append(self._build_result(img, score, reasons))

        # Sort by score descending and limit
        scored.sort(key=lambda r: r["score"], reverse=True)
        return scored[:top_k]

    # ------------------------------------------------------------------
    # SQL-level filtering
    # ------------------------------------------------------------------

    def _fetch_candidates(
        self, filters: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Fetch images from DB applying SQL-level filters."""
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
        rows = self._db._conn.execute(sql, params).fetchall()
        candidates = [dict(r) for r in rows]

        # Person filter requires a join with faces table
        if "person" in filters:
            person_val = filters["person"]
            person_image_ids = self._get_person_image_ids(person_val)
            candidates = [c for c in candidates if c["id"] in person_image_ids]

        return candidates

    def _get_person_image_ids(self, person: str) -> set[int]:
        """Return image IDs that contain a face with the given cluster label or ID."""
        ids: set[int] = set()
        try:
            cluster_id = int(person)
            rows = self._db._conn.execute(
                "SELECT DISTINCT image_id FROM faces WHERE cluster_id = ?",
                (cluster_id,),
            ).fetchall()
            ids.update(r["image_id"] for r in rows)
        except (ValueError, TypeError):
            pass

        rows = self._db._conn.execute(
            "SELECT DISTINCT image_id FROM faces WHERE cluster_label LIKE ?",
            (f"%{person}%",),
        ).fetchall()
        ids.update(r["image_id"] for r in rows)
        return ids

    # ------------------------------------------------------------------
    # Text matching
    # ------------------------------------------------------------------

    def _text_match_score(
        self,
        img: dict[str, Any],
        query_terms: list[str],
    ) -> tuple[float, list[str]]:
        """Score an image based on text matching against metadata fields.

        Returns (score 0-1, list of match reason strings).
        """
        if not query_terms:
            return 0.0, []

        field_matches: list[str] = []
        total_fields = 6  # tags, caption, scene_type, filename, city, country

        # Tags
        tags = _safe_json_loads(img.get("ai_tags"))
        tag_labels = [_normalize(t.get("label", "")) for t in tags]
        matched_tags = [
            term for term in query_terms
            if any(term in label for label in tag_labels)
        ]
        if matched_tags:
            field_matches.append(f"tags: {', '.join(matched_tags)}")

        # Caption
        caption = _normalize(img.get("ai_caption") or "")
        matched_caption = [t for t in query_terms if t in caption]
        if matched_caption:
            field_matches.append(f"caption: {', '.join(matched_caption)}")

        # Scene type
        scene = _normalize(img.get("ai_scene_type") or "")
        matched_scene = [t for t in query_terms if t in scene]
        if matched_scene:
            field_matches.append(f"scene: {', '.join(matched_scene)}")

        # Filename
        fname = _normalize(img.get("filename") or "")
        matched_fname = [t for t in query_terms if t in fname]
        if matched_fname:
            field_matches.append(f"filename: {', '.join(matched_fname)}")

        # City
        city = _normalize(img.get("city") or "")
        matched_city = [t for t in query_terms if t in city]
        if matched_city:
            field_matches.append(f"city: {', '.join(matched_city)}")

        # Country
        country = _normalize(img.get("country") or "")
        matched_country = [t for t in query_terms if t in country]
        if matched_country:
            field_matches.append(f"country: {', '.join(matched_country)}")

        if not field_matches:
            return 0.0, []

        score = len(field_matches) / total_fields
        return min(score, 1.0), field_matches

    def _broad_match(
        self,
        img: dict[str, Any],
        query: str,
    ) -> tuple[float, list[str]]:
        """Broader substring match when term-based matching yields nothing."""
        q = _normalize(query)
        reasons: list[str] = []

        searchable = " ".join(
            _normalize(str(img.get(f) or ""))
            for f in [
                "ai_tags", "ai_caption", "ai_scene_type",
                "filename", "city", "country",
            ]
        )

        if q in searchable:
            reasons.append(f"substring match: '{query}'")
            return 0.3, reasons

        return 0.0, []

    # ------------------------------------------------------------------
    # CLIP semantic search (optional)
    # ------------------------------------------------------------------

    def _clip_search(
        self,
        candidates: list[dict[str, Any]],
        query: str,
    ) -> dict[int, float]:
        """Attempt CLIP-based semantic similarity scoring.

        Returns a dict mapping image ID -> similarity score (0-1),
        or empty dict if CLIP is unavailable.
        """
        try:
            import numpy as np
            from photoagent.vision.clip_tagger import CLIPTagger
        except ImportError:
            logger.debug("CLIP not available for semantic search")
            return {}

        # Check if any candidate has a stored CLIP embedding
        # We look for embeddings in a clip_embeddings table or
        # recompute them. For now, attempt to encode the query and
        # compare against stored image embeddings if available.
        try:
            tagger = CLIPTagger()
            tagger.load_model()
        except Exception as exc:
            logger.debug("Could not load CLIP model: %s", exc)
            return {}

        try:
            import torch
            import open_clip

            # Encode the query text
            tokenizer = open_clip.get_tokenizer("ViT-B-32")
            tokens = tokenizer([f"a photo of {query}"]).to(tagger._device)
            with torch.no_grad():
                text_features = tagger._model.encode_text(tokens)
                text_features = text_features / text_features.norm(
                    dim=-1, keepdim=True
                )
            query_vec = text_features.squeeze(0).cpu().numpy().astype(np.float32)

            scores: dict[int, float] = {}
            for img in candidates:
                img_id = img["id"]
                # Try to load stored embedding from the faces table or
                # a dedicated embeddings column (not in current schema).
                # For now, we skip images without embeddings.
                embedding = self._get_stored_embedding(img_id)
                if embedding is not None:
                    sim = float(np.dot(query_vec, embedding) / (
                        np.linalg.norm(query_vec) * np.linalg.norm(embedding)
                        + 1e-8
                    ))
                    scores[img_id] = max(0.0, sim)

            return scores
        except Exception as exc:
            logger.debug("CLIP search failed: %s", exc)
            return {}
        finally:
            try:
                tagger.unload_model()
            except Exception:
                pass

    def _get_stored_embedding(self, image_id: int) -> Any:
        """Try to retrieve a stored CLIP embedding for an image.

        Returns numpy array or None if not available.
        """
        try:
            import numpy as np

            # Check for a clip_embedding column or a separate table.
            # Current schema does not store image-level CLIP embeddings,
            # so this is a placeholder for future extension.
            row = self._db._conn.execute(
                "SELECT embedding FROM faces WHERE image_id = ? LIMIT 1",
                (image_id,),
            ).fetchone()
            if row and row["embedding"]:
                # Face embeddings are not CLIP embeddings, but we try
                # to gracefully handle whatever is stored
                blob = row["embedding"]
                arr = np.frombuffer(blob, dtype=np.float32)
                # CLIP ViT-B/32 produces 512-dim vectors
                if arr.shape[0] == 512:
                    return arr
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Score merging
    # ------------------------------------------------------------------

    def _merge_scores(
        self,
        text_results: list[dict[str, Any]],
        candidates: list[dict[str, Any]],
        clip_scores: dict[int, float],
    ) -> list[dict[str, Any]]:
        """Merge text-based and CLIP-based scores using weighted average."""
        TEXT_WEIGHT = 0.6
        CLIP_WEIGHT = 0.4

        # Index existing text results by ID
        by_id: dict[int, dict[str, Any]] = {
            r["id"]: r for r in text_results
        }

        # Update existing results with combined score
        for result in text_results:
            img_id = result["id"]
            if img_id in clip_scores:
                text_score = result["score"]
                clip_score = clip_scores[img_id]
                result["score"] = (
                    TEXT_WEIGHT * text_score + CLIP_WEIGHT * clip_score
                )
                result["match_reason"] += f" | CLIP: {clip_score:.2f}"

        # Add CLIP-only results (not in text results)
        cand_by_id = {c["id"]: c for c in candidates}
        for img_id, clip_score in clip_scores.items():
            if img_id not in by_id and clip_score > 0.15:
                img = cand_by_id.get(img_id)
                if img:
                    text_results.append(
                        self._build_result(
                            img,
                            CLIP_WEIGHT * clip_score,
                            [f"CLIP similarity: {clip_score:.2f}"],
                        )
                    )

        return text_results

    # ------------------------------------------------------------------
    # Result building
    # ------------------------------------------------------------------

    def _build_result(
        self,
        img: dict[str, Any],
        score: float,
        reasons: list[str],
    ) -> dict[str, Any]:
        """Build a standardized search result dict."""
        tags = _safe_json_loads(img.get("ai_tags"))
        tag_labels = [t.get("label", "") for t in tags[:5]]

        return {
            "id": img["id"],
            "file_path": img["file_path"],
            "filename": img["filename"],
            "score": round(score, 4),
            "caption": img.get("ai_caption") or "",
            "tags": tag_labels,
            "match_reason": " | ".join(reasons),
        }

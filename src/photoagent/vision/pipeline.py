"""Orchestration pipeline for vision analysis.

Runs quality assessment, CLIP tagging, captioning, and face detection
sequentially — loading and unloading models one at a time to keep
memory usage manageable.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np

from photoagent.database import CatalogDB
from photoagent.models import AnalysisResult
from photoagent.vision.captioner import ImageCaptioner
from photoagent.vision.clip_tagger import CLIPTagger
from photoagent.vision.face_detector import FaceDetector
from photoagent.vision.quality import QualityAssessor

logger = logging.getLogger(__name__)


class AnalysisPipeline:
    """Run the full vision analysis pipeline over a catalog database.

    Parameters
    ----------
    device : str
        Device preference — "auto", "cuda", "mps", or "cpu".
    models : list[str]
        Which modules to run. Subset of ["clip", "caption", "quality", "faces"].
    skip_captions : bool
        If True, skip the captioning stage entirely.
    lite : bool
        Lightweight mode — skip captioning and face detection.
    """

    def __init__(
        self,
        device: str = "auto",
        models: list[str] | None = None,
        skip_captions: bool = False,
        lite: bool = False,
    ) -> None:
        self._device = device
        self._models = models if models is not None else ["clip", "caption", "quality", "faces"]
        self._skip_captions = skip_captions
        self._lite = lite

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _emit_progress(
        on_progress: Callable[..., Any] | None,
        stage: str,
        current: int,
        total: int,
    ) -> None:
        if on_progress is not None:
            on_progress(stage=stage, current=current, total=total)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(
        self,
        db: CatalogDB,
        on_progress: Callable[..., Any] | None = None,
    ) -> AnalysisResult:
        """Run analysis on all unanalyzed images in *db*.

        Models are loaded and unloaded sequentially to conserve memory.
        """
        start_time = time.time()
        result = AnalysisResult()

        # Gather images that need analysis (resume support)
        images = db.get_unanalyzed()
        total = len(images)
        result.total_processed = total

        if total == 0:
            logger.info("No unanalyzed images found — nothing to do.")
            result.duration = time.time() - start_time
            return result

        logger.info("Starting analysis pipeline for %d images", total)
        image_paths = [Path(img["file_path"]) for img in images]
        image_ids = [img["id"] for img in images]

        # Collect per-image analysis data (keyed by image id)
        analysis_data: dict[int, dict[str, Any]] = {
            img_id: {} for img_id in image_ids
        }

        # ----------------------------------------------------------
        # Stage 1: Quality assessment (lightweight, no ML model)
        # ----------------------------------------------------------
        if "quality" in self._models:
            logger.info("[1/4] Running quality assessment")
            assessor = QualityAssessor()

            for idx, (img_id, img_path) in enumerate(zip(image_ids, image_paths)):
                self._emit_progress(on_progress, "quality", idx + 1, total)
                try:
                    qa = assessor.assess(img_path)
                    analysis_data[img_id]["quality"] = qa
                    db.update_image(
                        img_id,
                        ai_quality_score=qa["quality_score"],
                        is_screenshot=qa["is_screenshot"],
                    )
                except Exception as exc:
                    logger.warning("Quality assessment failed for %s: %s", img_path, exc)
                    result.errors.append(f"quality:{img_path}: {exc}")

            logger.info("[1/4] Quality assessment complete")

        # ----------------------------------------------------------
        # Stage 2: CLIP tagging + embeddings
        # ----------------------------------------------------------
        if "clip" in self._models:
            logger.info("[2/4] Running CLIP tagging")
            tagger = CLIPTagger(device=self._device)
            try:
                tagger.load_model()
                tag_results = tagger.tag_batch(image_paths)

                for idx, (img_id, tag_result) in enumerate(
                    zip(image_ids, tag_results)
                ):
                    self._emit_progress(on_progress, "clip", idx + 1, total)
                    analysis_data[img_id]["tags"] = tag_result

                    tags_json = json.dumps(tag_result["tags"])
                    scene = tag_result.get("scene")
                    db.update_image(
                        img_id,
                        ai_tags=tags_json,
                        ai_scene_type=scene,
                    )

                # Compute embeddings (stored in analysis_data for potential
                # downstream use; DB storage could be added via a blobs table)
                for idx, (img_id, img_path) in enumerate(
                    zip(image_ids, image_paths)
                ):
                    try:
                        emb = tagger.get_embedding(img_path)
                        analysis_data[img_id]["clip_embedding"] = emb
                    except Exception as exc:
                        logger.warning("Embedding failed for %s: %s", img_path, exc)

            except Exception as exc:
                logger.error("CLIP tagging stage failed: %s", exc)
                result.errors.append(f"clip: {exc}")
            finally:
                tagger.unload_model()

            logger.info("[2/4] CLIP tagging complete")

        # ----------------------------------------------------------
        # Stage 3: Captioning
        # ----------------------------------------------------------
        run_model_captions = (
            "caption" in self._models
            and not self._skip_captions
            and not self._lite
        )

        if run_model_captions:
            logger.info("[3/4] Running captioning (model)")
            captioner = ImageCaptioner(device=self._device, use_model=True)
            try:
                captioner.load_model()
                for idx, (img_id, img_path) in enumerate(
                    zip(image_ids, image_paths)
                ):
                    self._emit_progress(on_progress, "caption", idx + 1, total)
                    try:
                        caption = captioner.caption_image(img_path)
                        db.update_image(img_id, ai_caption=caption)
                    except Exception as exc:
                        logger.warning("Caption failed for %s: %s", img_path, exc)
                        result.errors.append(f"caption:{img_path}: {exc}")
            except Exception as exc:
                logger.error("Captioner load failed, falling back to tags: %s", exc)
                result.errors.append(f"caption_load: {exc}")
                # Fallback: use tag-based captions
                self._caption_from_tags(db, images, analysis_data, on_progress, total)
            finally:
                captioner.unload_model()

            logger.info("[3/4] Captioning complete")

        elif "caption" in self._models and not self._skip_captions:
            # lite mode or CPU fallback — use tag-based captions
            logger.info("[3/4] Running captioning (tag-based fallback)")
            self._caption_from_tags(db, images, analysis_data, on_progress, total)
            logger.info("[3/4] Tag-based captioning complete")
        else:
            logger.info("[3/4] Captioning skipped")

        # ----------------------------------------------------------
        # Stage 4: Face detection + clustering
        # ----------------------------------------------------------
        if "faces" in self._models and not self._lite:
            logger.info("[4/4] Running face detection")
            detector = FaceDetector(device=self._device)
            try:
                detector.load_model()

                all_face_embeddings: list[tuple[int, np.ndarray]] = []

                for idx, (img_id, img_path) in enumerate(
                    zip(image_ids, image_paths)
                ):
                    self._emit_progress(on_progress, "faces", idx + 1, total)
                    try:
                        faces = detector.detect_faces(img_path)
                        db.update_image(img_id, face_count=len(faces))

                        for face in faces:
                            embedding = face["embedding"]
                            if embedding is not None:
                                # Store face record in DB
                                bbox = face["bbox"]
                                emb_bytes = embedding.tobytes()
                                db._conn.execute(
                                    "INSERT INTO faces "
                                    "(image_id, embedding, bbox_x, bbox_y, bbox_w, bbox_h) "
                                    "VALUES (?, ?, ?, ?, ?, ?)",
                                    (img_id, emb_bytes, *bbox),
                                )
                                all_face_embeddings.append((img_id, embedding))

                        db._conn.commit()

                    except Exception as exc:
                        logger.warning("Face detection failed for %s: %s", img_path, exc)
                        result.errors.append(f"faces:{img_path}: {exc}")

                # Cluster all detected faces
                if all_face_embeddings:
                    logger.info("Clustering %d face embeddings", len(all_face_embeddings))
                    clusters = detector.cluster_faces(all_face_embeddings)

                    for cluster_id, member_image_ids in clusters.items():
                        for member_img_id in member_image_ids:
                            db._conn.execute(
                                "UPDATE faces SET cluster_id = ? WHERE image_id = ?",
                                (cluster_id, member_img_id),
                            )
                    db._conn.commit()
                    logger.info("Found %d face clusters", len(clusters))

            except Exception as exc:
                logger.error("Face detection stage failed: %s", exc)
                result.errors.append(f"faces: {exc}")
            finally:
                detector.unload_model()

            logger.info("[4/4] Face detection complete")
        else:
            logger.info("[4/4] Face detection skipped")

        # ----------------------------------------------------------
        # Mark all images as analyzed
        # ----------------------------------------------------------
        now = datetime.now(timezone.utc).isoformat()
        for img_id in image_ids:
            db.update_image(img_id, analyzed_at=now)

        result.newly_analyzed = total
        result.duration = time.time() - start_time
        logger.info(
            "Pipeline finished: %d images in %.1fs (%d errors)",
            total, result.duration, len(result.errors),
        )
        return result

    # ------------------------------------------------------------------
    # Internal: tag-based captioning fallback
    # ------------------------------------------------------------------

    def _caption_from_tags(
        self,
        db: CatalogDB,
        images: list[dict[str, Any]],
        analysis_data: dict[int, dict[str, Any]],
        on_progress: Callable[..., Any] | None,
        total: int,
    ) -> None:
        """Generate captions from CLIP tags + metadata (no ML model)."""
        for idx, img in enumerate(images):
            self._emit_progress(on_progress, "caption", idx + 1, total)
            img_id = img["id"]

            tag_data = analysis_data.get(img_id, {}).get("tags", {})
            tags = tag_data.get("tags", [])
            scene = tag_data.get("scene")

            # Build location string from DB fields
            city = img.get("city")
            country = img.get("country")
            location = None
            if city and country:
                location = f"{city}, {country}"
            elif city:
                location = city
            elif country:
                location = country

            caption = ImageCaptioner.caption_from_tags(
                tags=tags, location=location, scene_type=scene,
            )
            db.update_image(img_id, ai_caption=caption)

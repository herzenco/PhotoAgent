"""Face detection and clustering using InsightFace buffalo_l.

Detects faces in images, extracts 512-dimensional embeddings, and
clusters them with DBSCAN for automatic person grouping.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


def _select_device(preference: str) -> str:
    """Return the best available device hint for ONNX / InsightFace."""
    if preference != "auto":
        return preference
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
    except ImportError:
        pass
    return "cpu"


class FaceDetector:
    """Detect faces and extract embeddings using InsightFace buffalo_l."""

    def __init__(self, device: str = "auto") -> None:
        self._device_pref = device
        self._device: str | None = None
        self._app: Any = None  # insightface.app.FaceAnalysis

    # ------------------------------------------------------------------
    # Model lifecycle
    # ------------------------------------------------------------------

    def load_model(self) -> None:
        """Load the InsightFace buffalo_l model."""
        from insightface.app import FaceAnalysis

        self._device = _select_device(self._device_pref)

        # InsightFace uses ONNX Runtime providers
        if self._device == "cuda":
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        else:
            providers = ["CPUExecutionProvider"]

        logger.info("Loading InsightFace buffalo_l (%s)", self._device)
        self._app = FaceAnalysis(
            name="buffalo_l",
            providers=providers,
        )
        # det_size controls the detection resolution; 640x640 is the default
        self._app.prepare(ctx_id=0 if self._device == "cuda" else -1, det_size=(640, 640))
        logger.info("FaceDetector ready")

    def unload_model(self) -> None:
        """Free model resources."""
        self._app = None
        self._device = None
        logger.info("FaceDetector unloaded")

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if self._app is None:
            raise RuntimeError(
                "FaceDetector model not loaded. Call load_model() first."
            )

    def detect_faces(self, image_path: Path) -> list[dict[str, Any]]:
        """Detect faces in an image.

        Returns
        -------
        list[dict] where each dict has:
            bbox       – tuple (x, y, w, h) in pixels
            embedding  – np.ndarray of shape (512,), float32
            confidence – float detection confidence
        """
        self._ensure_loaded()

        import cv2

        img = cv2.imread(str(image_path))
        if img is None:
            logger.warning("Could not read image: %s", image_path)
            return []

        faces = self._app.get(img)  # type: ignore[union-attr]
        results: list[dict[str, Any]] = []

        for face in faces:
            # InsightFace bbox is [x1, y1, x2, y2]
            bbox = face.bbox.astype(float)
            x1, y1, x2, y2 = bbox[0], bbox[1], bbox[2], bbox[3]
            w = x2 - x1
            h = y2 - y1

            embedding = face.embedding
            if embedding is not None:
                embedding = embedding.astype(np.float32)
                # L2-normalize for consistent cosine-distance clustering
                norm = np.linalg.norm(embedding)
                if norm > 0:
                    embedding = embedding / norm

            confidence = float(face.det_score) if hasattr(face, "det_score") else 0.0

            results.append({
                "bbox": (round(x1), round(y1), round(w), round(h)),
                "embedding": embedding,
                "confidence": confidence,
            })

        return results

    # ------------------------------------------------------------------
    # Clustering
    # ------------------------------------------------------------------

    @staticmethod
    def cluster_faces(
        face_embeddings: list[tuple[int, np.ndarray]],
        eps: float = 0.5,
        min_samples: int = 2,
    ) -> dict[int, list[int]]:
        """Cluster face embeddings using DBSCAN.

        Parameters
        ----------
        face_embeddings : list of (image_id, embedding) tuples
            Each embedding should be an L2-normalised 512-dim vector.
        eps : float
            DBSCAN epsilon (maximum distance between two samples).
        min_samples : int
            Minimum cluster size.

        Returns
        -------
        dict mapping cluster_id -> list of image_ids.
        Noise points (cluster_id == -1) are excluded.
        """
        if len(face_embeddings) < min_samples:
            return {}

        from sklearn.cluster import DBSCAN

        image_ids = [item[0] for item in face_embeddings]
        embeddings = np.stack([item[1] for item in face_embeddings])

        # Use cosine distance: dist = 1 - cosine_similarity
        # For L2-normalised vectors: cosine_dist = 1 - dot(a, b)
        clustering = DBSCAN(
            eps=eps,
            min_samples=min_samples,
            metric="cosine",
        ).fit(embeddings)

        clusters: dict[int, list[int]] = {}
        for idx, label in enumerate(clustering.labels_):
            label_int = int(label)
            if label_int == -1:
                continue  # noise
            clusters.setdefault(label_int, []).append(image_ids[idx])

        return clusters

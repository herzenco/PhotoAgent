"""CLIP-based image tagging using OpenCLIP ViT-B/32.

Produces semantic tags and embedding vectors for images by comparing
them against a comprehensive label taxonomy.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Comprehensive label taxonomy (~200 labels)
# ---------------------------------------------------------------------------

SCENE_LABELS: list[str] = [
    "beach", "mountain", "city", "street", "restaurant", "park", "office",
    "home", "concert", "wedding", "graduation", "birthday", "airport",
    "museum", "gym", "hospital", "school", "church", "stadium", "pool",
    "garden", "forest", "lake", "river", "desert", "snow", "farm",
    "harbor", "bridge", "tunnel", "rooftop", "balcony", "subway",
    "highway", "parking lot", "marketplace", "library", "cafe",
    "bar", "nightclub", "theater", "zoo", "amusement park",
    "train station", "bus stop", "pier", "waterfall", "cave",
    "countryside", "vineyard",
]

CONTENT_LABELS: list[str] = [
    "food", "animal", "pet", "dog", "cat", "bird", "car", "bicycle",
    "boat", "airplane", "document", "screenshot", "meme", "selfie",
    "group photo", "landscape", "sunset", "sunrise", "night",
    "fireworks", "flowers", "art", "building", "monument", "sign",
    "text", "tree", "water", "sky", "clouds", "rain", "snow scene",
    "mountain view", "ocean", "river view", "statue", "graffiti",
    "book", "phone", "computer", "furniture", "clothing", "jewelry",
    "toy", "musical instrument", "sports equipment", "vehicle",
    "architecture", "street art", "neon lights",
]

ACTIVITY_LABELS: list[str] = [
    "swimming", "hiking", "dining", "cooking", "playing", "working",
    "traveling", "celebrating", "dancing", "running", "reading",
    "shopping", "painting", "fishing", "camping", "skiing", "surfing",
    "climbing", "cycling", "yoga", "exercising", "singing", "studying",
    "gardening", "driving", "flying", "boating", "skateboarding",
    "snowboarding", "horseback riding", "kayaking", "scuba diving",
    "photography", "gaming", "volunteering",
]

PEOPLE_LABELS: list[str] = [
    "baby", "child", "teenager", "adult", "elderly", "crowd", "couple",
    "family", "portrait", "candid", "solo person", "small group",
    "large group", "wedding party", "athletes", "performers",
    "professional headshot", "casual photo",
]

AESTHETIC_LABELS: list[str] = [
    "black and white", "vintage", "HDR", "panorama", "macro",
    "long exposure", "bokeh", "aerial view", "drone shot",
    "wide angle", "close-up", "silhouette", "reflection",
    "symmetry", "minimalist", "abstract", "colorful",
    "moody", "bright", "dark",
]

ALL_LABELS: list[str] = (
    SCENE_LABELS + CONTENT_LABELS + ACTIVITY_LABELS
    + PEOPLE_LABELS + AESTHETIC_LABELS
)


def _select_device(preference: str) -> str:
    """Return the best available torch device string."""
    import torch

    if preference != "auto":
        return preference
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


class CLIPTagger:
    """Tag images using OpenCLIP ViT-B/32 against a fixed label taxonomy."""

    def __init__(self, device: str = "auto", batch_size: int = 32) -> None:
        self._device_pref = device
        self.batch_size = batch_size

        # Populated by load_model()
        self._device: str | None = None
        self._model: Any = None
        self._preprocess: Any = None
        self._tokenizer: Any = None
        self._text_features: Any = None  # pre-encoded label embeddings

    # ------------------------------------------------------------------
    # Model lifecycle
    # ------------------------------------------------------------------

    def load_model(self) -> None:
        """Load OpenCLIP ViT-B/32, pre-encode all text labels."""
        import torch
        import open_clip

        self._device = _select_device(self._device_pref)
        logger.info("Loading OpenCLIP ViT-B/32 on %s", self._device)

        model, _, preprocess = open_clip.create_model_and_transforms(
            "ViT-B-32", pretrained="laion2b_s34b_b79k",
        )
        model = model.to(self._device).eval()
        tokenizer = open_clip.get_tokenizer("ViT-B-32")

        self._model = model
        self._preprocess = preprocess
        self._tokenizer = tokenizer

        # Pre-encode the full label set
        prompts = [f"a photo of {label}" for label in ALL_LABELS]
        tokens = tokenizer(prompts).to(self._device)
        with torch.no_grad():
            text_features = model.encode_text(tokens)
            text_features = text_features / text_features.norm(dim=-1, keepdim=True)
        self._text_features = text_features

        logger.info(
            "CLIPTagger ready — %d labels pre-encoded", len(ALL_LABELS),
        )

    def unload_model(self) -> None:
        """Free model memory."""
        import torch

        self._model = None
        self._preprocess = None
        self._tokenizer = None
        self._text_features = None
        if self._device == "cuda":
            torch.cuda.empty_cache()
        self._device = None
        logger.info("CLIPTagger unloaded")

    # ------------------------------------------------------------------
    # Inference helpers
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if self._model is None:
            raise RuntimeError(
                "CLIPTagger model not loaded. Call load_model() first."
            )

    def _encode_image(self, image: Image.Image) -> Any:
        """Return the L2-normalised image embedding tensor (1, D)."""
        import torch

        tensor = self._preprocess(image).unsqueeze(0).to(self._device)  # type: ignore[union-attr]
        with torch.no_grad():
            features = self._model.encode_image(tensor)  # type: ignore[union-attr]
            features = features / features.norm(dim=-1, keepdim=True)
        return features

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def tag_image(self, image_path: Path) -> dict[str, Any]:
        """Return top-10 tags with confidence scores for a single image.

        Returns
        -------
        dict with keys:
            tags   – list of {"label": str, "score": float} (top 10)
            scene  – the top scene label (or None)
        """
        self._ensure_loaded()

        image = Image.open(image_path).convert("RGB")
        image_features = self._encode_image(image)

        # Cosine similarity against all labels
        similarity = (image_features @ self._text_features.T).squeeze(0)  # type: ignore[union-attr]
        scores = similarity.softmax(dim=-1).cpu().numpy()

        # Top-10 overall
        top_indices = scores.argsort()[::-1][:10]
        tags = [
            {"label": ALL_LABELS[i], "score": round(float(scores[i]), 4)}
            for i in top_indices
        ]

        # Best scene label
        scene_start = 0
        scene_end = len(SCENE_LABELS)
        scene_scores = scores[scene_start:scene_end]
        best_scene_idx = int(scene_scores.argmax())
        scene = SCENE_LABELS[best_scene_idx] if scene_scores[best_scene_idx] > 0.01 else None

        return {"tags": tags, "scene": scene}

    def tag_batch(self, image_paths: list[Path]) -> list[dict[str, Any]]:
        """Tag a list of images, processing in batches."""
        import torch

        self._ensure_loaded()
        results: list[dict[str, Any]] = []

        for batch_start in range(0, len(image_paths), self.batch_size):
            batch_paths = image_paths[batch_start : batch_start + self.batch_size]
            images: list[Any] = []
            valid_indices: list[int] = []

            for idx, p in enumerate(batch_paths):
                try:
                    img = Image.open(p).convert("RGB")
                    images.append(self._preprocess(img))  # type: ignore[misc]
                    valid_indices.append(idx)
                except Exception as exc:
                    logger.warning("Failed to load %s: %s", p, exc)

            if not images:
                results.extend(
                    [{"tags": [], "scene": None}] * len(batch_paths)
                )
                continue

            batch_tensor = torch.stack(images).to(self._device)
            with torch.no_grad():
                feats = self._model.encode_image(batch_tensor)  # type: ignore[union-attr]
                feats = feats / feats.norm(dim=-1, keepdim=True)
                sims = (feats @ self._text_features.T).softmax(dim=-1).cpu().numpy()  # type: ignore[union-attr]

            # Build placeholder results for this mini-batch
            batch_results: list[dict[str, Any]] = [
                {"tags": [], "scene": None}
            ] * len(batch_paths)

            for out_idx, valid_idx in enumerate(valid_indices):
                scores = sims[out_idx]
                top_indices = scores.argsort()[::-1][:10]
                tags = [
                    {"label": ALL_LABELS[i], "score": round(float(scores[i]), 4)}
                    for i in top_indices
                ]
                scene_scores = scores[: len(SCENE_LABELS)]
                best_scene_idx = int(scene_scores.argmax())
                scene = (
                    SCENE_LABELS[best_scene_idx]
                    if scene_scores[best_scene_idx] > 0.01
                    else None
                )
                batch_results[valid_idx] = {"tags": tags, "scene": scene}

            results.extend(batch_results)

        return results

    def get_embedding(self, image_path: Path) -> np.ndarray:
        """Return the CLIP embedding vector for an image (float32)."""
        self._ensure_loaded()
        image = Image.open(image_path).convert("RGB")
        features = self._encode_image(image)
        return features.squeeze(0).cpu().numpy().astype(np.float32)

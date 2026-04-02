"""Image captioning using Florence-2-base with CPU-friendly fallback.

Generates natural-language descriptions of images either through the
Florence-2 vision-language model or via a rule-based approach using
CLIP tags and metadata.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PIL import Image

logger = logging.getLogger(__name__)


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


class ImageCaptioner:
    """Generate captions for images using Florence-2 or a tag-based fallback."""

    def __init__(self, device: str = "auto", use_model: bool = True) -> None:
        self._device_pref = device
        self._use_model = use_model

        # Populated by load_model()
        self._device: str | None = None
        self._model: Any = None
        self._processor: Any = None

    # ------------------------------------------------------------------
    # Model lifecycle
    # ------------------------------------------------------------------

    def load_model(self) -> None:
        """Load the Florence-2-base model and processor."""
        if not self._use_model:
            logger.info("ImageCaptioner: model disabled, using tag-based fallback")
            return

        import torch
        from transformers import AutoProcessor, AutoModelForCausalLM

        self._device = _select_device(self._device_pref)
        logger.info("Loading Florence-2-base on %s", self._device)

        model_id = "microsoft/Florence-2-base"
        self._processor = AutoProcessor.from_pretrained(
            model_id, trust_remote_code=True,
        )
        self._model = AutoModelForCausalLM.from_pretrained(
            model_id,
            trust_remote_code=True,
            torch_dtype=torch.float32,
        ).to(self._device).eval()

        logger.info("ImageCaptioner ready (Florence-2-base)")

    def unload_model(self) -> None:
        """Free model memory."""
        import torch

        self._model = None
        self._processor = None
        if self._device == "cuda":
            torch.cuda.empty_cache()
        self._device = None
        logger.info("ImageCaptioner unloaded")

    # ------------------------------------------------------------------
    # Model-based captioning
    # ------------------------------------------------------------------

    def _caption_with_model(self, image: Image.Image) -> str:
        """Generate a caption using Florence-2."""
        import torch

        task_prompt = "<CAPTION>"
        inputs = self._processor(
            text=task_prompt, images=image, return_tensors="pt",
        )
        inputs = {k: v.to(self._device) for k, v in inputs.items()}

        with torch.no_grad():
            generated_ids = self._model.generate(
                **inputs,
                max_new_tokens=128,
                num_beams=3,
                early_stopping=True,
            )

        generated_text: str = self._processor.batch_decode(
            generated_ids, skip_special_tokens=False,
        )[0]

        # Post-process Florence-2 output
        parsed = self._processor.post_process_generation(
            generated_text, task=task_prompt, image_size=image.size,
        )
        caption: str = parsed.get(task_prompt, generated_text).strip()
        return caption

    # ------------------------------------------------------------------
    # Tag-based fallback captioning (no ML model needed)
    # ------------------------------------------------------------------

    @staticmethod
    def caption_from_tags(
        tags: list[dict[str, Any]],
        location: str | None = None,
        scene_type: str | None = None,
    ) -> str:
        """Construct a caption from CLIP tags and optional metadata.

        Parameters
        ----------
        tags : list[dict]
            Each dict must have "label" and "score" keys.
        location : str | None
            Human-readable location string, e.g. "Paris, France".
        scene_type : str | None
            Top scene label from CLIP tagger.

        Returns
        -------
        str
            A natural-language caption.
        """
        if not tags:
            parts = ["A photo"]
            if location:
                parts.append(f"taken in {location}")
            return " ".join(parts) + "."

        # Pick top descriptive labels (skip duplicates of scene_type)
        descriptors: list[str] = []
        for tag in tags[:5]:
            label = tag["label"]
            if scene_type and label.lower() == scene_type.lower():
                continue
            descriptors.append(label)
            if len(descriptors) >= 3:
                break

        # Build caption
        scene_part = f"{scene_type} " if scene_type else ""
        caption = f"A {scene_part}photo"

        if descriptors:
            if len(descriptors) == 1:
                caption += f" showing {descriptors[0]}"
            else:
                caption += f" showing {', '.join(descriptors[:-1])} and {descriptors[-1]}"

        if location:
            caption += f" in {location}"

        caption += "."
        return caption

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def caption_image(self, image_path: Path) -> str:
        """Generate a caption for a single image.

        Uses the Florence-2 model if loaded, otherwise raises.
        For CPU/tag-based fallback use ``caption_from_tags`` directly.
        """
        if self._model is None:
            raise RuntimeError(
                "Captioner model not loaded. Call load_model() first "
                "or use caption_from_tags() for CPU fallback."
            )

        image = Image.open(image_path).convert("RGB")
        return self._caption_with_model(image)

    def caption_batch(self, image_paths: list[Path]) -> list[str]:
        """Generate captions for a batch of images.

        Processes images one at a time through Florence-2 (the model
        handles variable-size inputs best individually).
        """
        if self._model is None:
            raise RuntimeError(
                "Captioner model not loaded. Call load_model() first."
            )

        captions: list[str] = []
        for path in image_paths:
            try:
                captions.append(self.caption_image(path))
            except Exception as exc:
                logger.warning("Failed to caption %s: %s", path, exc)
                captions.append("")
        return captions

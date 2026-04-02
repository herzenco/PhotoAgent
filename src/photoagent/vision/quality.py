"""Image quality assessment using traditional computer-vision heuristics.

No ML models required — uses Laplacian variance for blur detection,
histogram analysis for exposure, and aspect-ratio / color-uniformity
heuristics for screenshot detection.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

BLUR_LAPLACIAN_THRESHOLD = 100.0  # variance below this => blurry
BLUR_NORMALIZER = 500.0           # score = min(variance / NORMALIZER, 1.0)

EXPOSURE_EXTREME_RATIO = 0.40     # >40 % of pixels in extreme bucket
EXPOSURE_TOP_BUCKET = 0.90        # top 10 % of intensity range
EXPOSURE_BOTTOM_BUCKET = 0.10     # bottom 10 %

MIN_WIDTH = 640
MIN_HEIGHT = 480

# Common phone-screen aspect ratios (height/width when portrait)
SCREENSHOT_RATIOS: list[tuple[float, float]] = [
    (19.5 / 9.0, 0.02),   # modern iPhones
    (16.0 / 9.0, 0.02),   # older phones / Android
    (20.0 / 9.0, 0.02),   # Samsung S-series
    (2.0 / 1.0, 0.02),    # 18:9
    (2.1 / 1.0, 0.02),    # 19:9 ~2.11
]

STATUS_BAR_MIN_PX = 44
STATUS_BAR_MAX_PX = 88
UNIFORM_COLOR_STD_THRESHOLD = 15.0  # per-channel std in the bar region
SHARPNESS_HIGH_THRESHOLD = 800.0    # Laplacian var above this = very sharp (no optical blur)


class QualityAssessor:
    """Assess image quality via blur, exposure, resolution, and screenshot heuristics."""

    def __init__(self) -> None:
        pass  # no model to load — pure CV

    # ------------------------------------------------------------------
    # Blur detection
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_blur_score(gray: np.ndarray) -> tuple[float, float]:
        """Return (laplacian_variance, blur_score_0_to_1)."""
        # Laplacian kernel (3x3)
        # We compute manually to avoid an OpenCV dependency.
        # Laplacian via convolution: kernel = [[0,1,0],[1,-4,1],[0,1,0]]
        from PIL import ImageFilter

        # Convert numpy gray back to PIL for the Laplacian filter
        pil_gray = Image.fromarray(gray)
        laplacian = pil_gray.filter(ImageFilter.Kernel(
            size=(3, 3),
            kernel=[0, 1, 0, 1, -4, 1, 0, 1, 0],
            scale=1,
            offset=128,
        ))
        lap_array = np.asarray(laplacian, dtype=np.float64) - 128.0
        variance = float(lap_array.var())
        score = min(variance / BLUR_NORMALIZER, 1.0)
        return variance, score

    # ------------------------------------------------------------------
    # Exposure analysis
    # ------------------------------------------------------------------

    @staticmethod
    def _analyze_exposure(gray: np.ndarray) -> tuple[bool, bool, float]:
        """Return (is_overexposed, is_underexposed, exposure_score)."""
        total_pixels = gray.size
        if total_pixels == 0:
            return False, False, 0.5

        high_threshold = int(255 * EXPOSURE_TOP_BUCKET)
        low_threshold = int(255 * EXPOSURE_BOTTOM_BUCKET)

        bright_ratio = float(np.sum(gray >= high_threshold)) / total_pixels
        dark_ratio = float(np.sum(gray <= low_threshold)) / total_pixels

        is_over = bright_ratio > EXPOSURE_EXTREME_RATIO
        is_under = dark_ratio > EXPOSURE_EXTREME_RATIO

        # Score: 1.0 = perfectly balanced, 0.0 = heavily skewed
        if is_over or is_under:
            worst = max(bright_ratio, dark_ratio)
            score = max(0.0, 1.0 - (worst - EXPOSURE_EXTREME_RATIO))
        else:
            score = 1.0

        return is_over, is_under, score

    # ------------------------------------------------------------------
    # Resolution check
    # ------------------------------------------------------------------

    @staticmethod
    def _check_resolution(width: int, height: int) -> tuple[bool, float]:
        """Return (is_low_resolution, resolution_score)."""
        is_low = width < MIN_WIDTH or height < MIN_HEIGHT
        # Score based on total megapixels — 2MP = 1.0, below that scales down
        megapixels = (width * height) / 1_000_000
        score = min(megapixels / 2.0, 1.0)
        return is_low, score

    # ------------------------------------------------------------------
    # Screenshot detection
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_screenshot(
        img_array: np.ndarray,
        width: int,
        height: int,
        blur_variance: float,
    ) -> bool:
        """Heuristic screenshot detection.

        Checks:
        1. Aspect ratio matches known phone screens
        2. Uniform color region at the top (status bar)
        3. Very high sharpness (no optical blur)
        """
        # 1. Aspect ratio — use portrait orientation (taller dimension / shorter)
        long_side = max(width, height)
        short_side = min(width, height)
        if short_side == 0:
            return False
        ratio = long_side / short_side

        ratio_match = any(
            abs(ratio - target) <= tolerance
            for target, tolerance in SCREENSHOT_RATIOS
        )

        if not ratio_match:
            return False

        # 2. Check for uniform color bar at top of image
        # Try multiple bar heights since status bars vary (44px, 48px, 64px, 88px)
        uniform_bar = False
        for bar_height in (STATUS_BAR_MIN_PX, 48, 64, STATUS_BAR_MAX_PX):
            if bar_height <= 0 or bar_height >= height:
                continue
            top_bar = img_array[:bar_height, :, :]
            channel_stds = [float(top_bar[:, :, c].std()) for c in range(min(3, top_bar.shape[2]))]
            avg_std = sum(channel_stds) / len(channel_stds) if channel_stds else 999.0
            if avg_std < UNIFORM_COLOR_STD_THRESHOLD:
                uniform_bar = True
                break

        # 3. Very sharp — no optical blur
        very_sharp = blur_variance > SHARPNESS_HIGH_THRESHOLD

        # Need at least 2 of 3 signals (ratio already confirmed)
        signals = sum([uniform_bar, very_sharp])
        return signals >= 1

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def assess(self, image_path: Path) -> dict[str, Any]:
        """Assess quality of a single image.

        Returns
        -------
        dict with keys:
            quality_score      – float 0.0-1.0
            is_blurry          – bool
            is_overexposed     – bool
            is_underexposed    – bool
            is_low_resolution  – bool
            is_screenshot      – bool
            issues             – list[str] human-readable issues
        """
        image = Image.open(image_path).convert("RGB")
        width, height = image.size
        img_array = np.asarray(image)

        # Grayscale for blur / exposure
        gray = np.asarray(image.convert("L"))

        # --- Blur ---
        blur_variance, blur_score = self._compute_blur_score(gray)
        is_blurry = blur_variance < BLUR_LAPLACIAN_THRESHOLD

        # --- Exposure ---
        is_overexposed, is_underexposed, exposure_score = self._analyze_exposure(gray)

        # --- Resolution ---
        is_low_res, resolution_score = self._check_resolution(width, height)

        # --- Screenshot ---
        is_screenshot = self._detect_screenshot(
            img_array, width, height, blur_variance,
        )

        # --- Issues list ---
        issues: list[str] = []
        if is_blurry:
            issues.append("Image is blurry")
        if is_overexposed:
            issues.append("Image is overexposed")
        if is_underexposed:
            issues.append("Image is underexposed")
        if is_low_res:
            issues.append(f"Low resolution ({width}x{height})")
        if is_screenshot:
            issues.append("Image appears to be a screenshot")

        # --- Overall score ---
        # Weights: blur 0.4, exposure 0.3, resolution 0.2, not-screenshot 0.1
        screenshot_score = 0.0 if is_screenshot else 1.0
        quality_score = round(
            blur_score * 0.4
            + exposure_score * 0.3
            + resolution_score * 0.2
            + screenshot_score * 0.1,
            4,
        )

        return {
            "quality_score": quality_score,
            "is_blurry": is_blurry,
            "is_overexposed": is_overexposed,
            "is_underexposed": is_underexposed,
            "is_low_resolution": is_low_res,
            "is_screenshot": is_screenshot,
            "issues": issues,
        }

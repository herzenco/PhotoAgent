"""Tests for photoagent.vision.quality — QualityAssessor.

Verifies that the quality assessment module correctly scores images,
detects blur, underexposure, screenshots, and low resolution.

Expected interface (being built concurrently):

    from photoagent.vision.quality import QualityAssessor

    assessor = QualityAssessor()
    result = assessor.assess(image_path: str | Path) -> dict[str, Any]
    # Keys: "score" (float 0-1), "is_blurry" (bool), "is_dark" (bool),
    #        "is_screenshot" (bool), "is_low_resolution" (bool),
    #        "issues" (list[str])
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageDraw, ImageFilter

from photoagent.vision.quality import QualityAssessor


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def assessor() -> QualityAssessor:
    """Create a QualityAssessor instance."""
    return QualityAssessor()


@pytest.fixture
def good_image(tmp_path: Path) -> Path:
    """Create a well-exposed, sharp, reasonably-sized image."""
    img = Image.new("RGB", (800, 600), color=(120, 150, 180))
    draw = ImageDraw.Draw(img)
    # Add sharp edges and varied content for high quality score
    for x in range(0, 800, 40):
        draw.line([(x, 0), (x, 600)], fill="black", width=1)
    for y in range(0, 600, 40):
        draw.line([(0, y), (800, y)], fill="black", width=1)
    draw.rectangle([200, 150, 600, 450], outline="red", width=3)
    draw.ellipse([300, 200, 500, 400], fill="yellow")
    p = tmp_path / "good.jpg"
    img.save(str(p), "JPEG", quality=95)
    return p


@pytest.fixture
def tiny_image(tmp_path: Path) -> Path:
    """Create a very small (32x32) image that should be flagged as low-resolution."""
    img = Image.new("RGB", (32, 32), color="green")
    p = tmp_path / "tiny.jpg"
    img.save(str(p), "JPEG")
    return p


# ------------------------------------------------------------------
# Quality score tests
# ------------------------------------------------------------------


class TestQualityScoring:
    """Tests for overall quality scoring."""

    def test_quality_normal_image(
        self, assessor: QualityAssessor, good_image: Path
    ) -> None:
        """A well-exposed, sharp image should get a high quality score (> 0.7)."""
        result = assessor.assess(good_image)
        assert isinstance(result, dict)
        score = result.get("score", result.get("quality_score", result.get("ai_quality_score")))
        assert score is not None, "Result should contain a score"
        assert score > 0.7, f"Good image scored only {score}"

    def test_quality_score_range(
        self, assessor: QualityAssessor, good_image: Path
    ) -> None:
        """Quality score should always be between 0 and 1 inclusive."""
        result = assessor.assess(good_image)
        score = result.get("score", result.get("quality_score", result.get("ai_quality_score")))
        assert score is not None
        assert 0.0 <= score <= 1.0, f"Score {score} outside [0, 1] range"

    @pytest.mark.parametrize("image_fixture", ["good_image", "tiny_image"])
    def test_quality_returns_required_keys(
        self, assessor: QualityAssessor, image_fixture: str, request: pytest.FixtureRequest
    ) -> None:
        """The result dict should contain the expected keys."""
        image_path = request.getfixturevalue(image_fixture)
        result = assessor.assess(image_path)
        assert isinstance(result, dict)
        # Should have at least a score
        has_score = any(
            k in result for k in ("score", "quality_score", "ai_quality_score")
        )
        assert has_score, f"No score key found in result keys: {list(result.keys())}"


# ------------------------------------------------------------------
# Defect detection
# ------------------------------------------------------------------


class TestDefectDetection:
    """Tests for blur, darkness, screenshot, and resolution detection."""

    def test_quality_blurry_image(
        self, assessor: QualityAssessor, tmp_image_dir: Path
    ) -> None:
        """A blurry image should be flagged and score lower than a sharp image."""
        result = assessor.assess(tmp_image_dir / "blurry.jpg")
        # Check for blur flag
        is_blurry = result.get("is_blurry", False)
        issues = result.get("issues", [])
        score = result.get("score", result.get("quality_score", result.get("ai_quality_score")))

        # Either is_blurry flag is set, or "blur" appears in issues, or score is low
        blur_detected = (
            is_blurry
            or any("blur" in str(i).lower() for i in issues)
            or (score is not None and score < 0.7)
        )
        assert blur_detected, "Blurry image should be flagged or score lower"

    def test_quality_dark_image(
        self, assessor: QualityAssessor, tmp_image_dir: Path
    ) -> None:
        """A very dark image should be flagged as underexposed."""
        result = assessor.assess(tmp_image_dir / "dark.jpg")
        is_dark = result.get("is_dark", False)
        issues = result.get("issues", [])
        score = result.get("score", result.get("quality_score", result.get("ai_quality_score")))

        dark_detected = (
            is_dark
            or any("dark" in str(i).lower() or "exposure" in str(i).lower() for i in issues)
            or (score is not None and score < 0.7)
        )
        assert dark_detected, "Dark image should be flagged or score lower"

    def test_quality_screenshot(
        self, assessor: QualityAssessor, tmp_image_dir: Path
    ) -> None:
        """A screenshot-sized image should be detected as a screenshot."""
        result = assessor.assess(tmp_image_dir / "screenshot.jpg")
        is_screenshot = result.get("is_screenshot", False)
        issues = result.get("issues", [])

        screenshot_detected = (
            is_screenshot
            or any("screenshot" in str(i).lower() for i in issues)
        )
        assert screenshot_detected, "Screenshot image should be detected"

    def test_quality_low_resolution(
        self, assessor: QualityAssessor, tiny_image: Path
    ) -> None:
        """A tiny (32x32) image should be flagged as low resolution."""
        result = assessor.assess(tiny_image)
        is_low_res = result.get("is_low_resolution", False)
        issues = result.get("issues", [])
        score = result.get("score", result.get("quality_score", result.get("ai_quality_score")))

        low_res_detected = (
            is_low_res
            or any("resolution" in str(i).lower() or "small" in str(i).lower() for i in issues)
            or (score is not None and score < 0.5)
        )
        assert low_res_detected, "Tiny image should be flagged as low resolution"

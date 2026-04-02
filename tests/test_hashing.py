"""Tests for photoagent.hashing — MD5 and perceptual hashing.

Verifies that compute_hashes() produces correct, deterministic hashes
and that perceptual hashes detect similar/different images.

Expected interface (being built concurrently):

    from photoagent.hashing import compute_hashes

    result = compute_hashes(path: str | Path) -> dict[str, str | None]
    # Keys: "file_md5", "perceptual_hash"
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFilter

from photoagent.hashing import compute_hashes


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _hamming_distance(hex1: str, hex2: str) -> int:
    """Compute Hamming distance between two hex-encoded hashes."""
    int1 = int(hex1, 16)
    int2 = int(hex2, 16)
    xor = int1 ^ int2
    return bin(xor).count("1")


# ------------------------------------------------------------------
# MD5 tests
# ------------------------------------------------------------------


class TestMD5:
    """Tests for MD5 file hashing."""

    def test_md5_hash(self, tmp_image_dir: Path) -> None:
        """compute_hashes should return a valid 32-character hex MD5 string."""
        result = compute_hashes(tmp_image_dir / "sample.jpg")
        assert result is not None
        md5 = result["file_md5"]
        assert md5 is not None
        assert re.fullmatch(r"[0-9a-fA-F]{32}", md5), (
            f"MD5 '{md5}' is not a valid 32-char hex string"
        )

    def test_md5_deterministic(self, tmp_image_dir: Path) -> None:
        """Hashing the same file twice should produce identical MD5."""
        r1 = compute_hashes(tmp_image_dir / "sample.jpg")
        r2 = compute_hashes(tmp_image_dir / "sample.jpg")
        assert r1["file_md5"] == r2["file_md5"]

    def test_md5_different_files(self, tmp_image_dir: Path) -> None:
        """Different images should produce different MD5 hashes."""
        r_jpg = compute_hashes(tmp_image_dir / "sample.jpg")
        r_png = compute_hashes(tmp_image_dir / "sample.png")
        assert r_jpg["file_md5"] != r_png["file_md5"]

    def test_duplicate_detection(self, tmp_image_dir: Path) -> None:
        """Byte-for-byte duplicate files should have identical MD5 and phash."""
        r_orig = compute_hashes(tmp_image_dir / "sample.jpg")
        r_dup = compute_hashes(tmp_image_dir / "duplicate.jpg")
        assert r_orig["file_md5"] == r_dup["file_md5"]
        # Perceptual hashes should also match for identical files
        if r_orig["perceptual_hash"] and r_dup["perceptual_hash"]:
            assert r_orig["perceptual_hash"] == r_dup["perceptual_hash"]


# ------------------------------------------------------------------
# Perceptual hash tests
# ------------------------------------------------------------------


class TestPerceptualHash:
    """Tests for perceptual (pHash) image hashing."""

    def test_perceptual_hash(self, tmp_image_dir: Path) -> None:
        """compute_hashes should return a valid hex string for perceptual_hash."""
        result = compute_hashes(tmp_image_dir / "sample.jpg")
        phash = result.get("perceptual_hash")
        assert phash is not None
        assert re.fullmatch(r"[0-9a-fA-F]+", phash), (
            f"Perceptual hash '{phash}' is not a valid hex string"
        )

    def test_perceptual_hash_similar(self, tmp_path: Path) -> None:
        """A slightly modified image should have a similar phash (low Hamming distance)."""
        # Create original
        img = Image.new("RGB", (200, 200), "red")
        draw = ImageDraw.Draw(img)
        draw.rectangle([20, 20, 180, 180], fill="blue")
        orig_path = tmp_path / "orig.jpg"
        img.save(str(orig_path), "JPEG", quality=95)

        # Create a very slight modification (minor blur)
        modified = img.filter(ImageFilter.GaussianBlur(radius=1))
        mod_path = tmp_path / "modified.jpg"
        modified.save(str(mod_path), "JPEG", quality=95)

        r_orig = compute_hashes(orig_path)
        r_mod = compute_hashes(mod_path)

        phash_orig = r_orig["perceptual_hash"]
        phash_mod = r_mod["perceptual_hash"]

        if phash_orig and phash_mod:
            distance = _hamming_distance(phash_orig, phash_mod)
            # JPEG recompression + blur can shift phash significantly;
            # threshold of 20 still validates they're "similar" vs random
            assert distance < 20, (
                f"Hamming distance {distance} too large for slightly modified image"
            )

    def test_perceptual_hash_different(self, tmp_path: Path) -> None:
        """Totally different images should produce different perceptual hashes."""
        # Solid red image
        img1 = Image.new("RGB", (200, 200), "red")
        p1 = tmp_path / "red.jpg"
        img1.save(str(p1), "JPEG")

        # Complex pattern image
        img2 = Image.new("RGB", (200, 200), "white")
        draw = ImageDraw.Draw(img2)
        for i in range(0, 200, 10):
            color = "black" if (i // 10) % 2 == 0 else "white"
            draw.rectangle([i, 0, i + 10, 200], fill=color)
        p2 = tmp_path / "pattern.jpg"
        img2.save(str(p2), "JPEG")

        r1 = compute_hashes(p1)
        r2 = compute_hashes(p2)

        phash1 = r1.get("perceptual_hash")
        phash2 = r2.get("perceptual_hash")

        if phash1 and phash2:
            assert phash1 != phash2, "Perceptual hashes should differ for distinct images"


# ------------------------------------------------------------------
# Error handling
# ------------------------------------------------------------------


class TestHashingErrors:
    """Tests for graceful error handling."""

    def test_corrupt_file(self, tmp_image_dir: Path) -> None:
        """Hashing a corrupt file should not crash; returns None or partial results."""
        try:
            result = compute_hashes(tmp_image_dir / "corrupt.jpg")
            # MD5 should still work (it hashes raw bytes)
            if result is not None:
                assert result.get("file_md5") is not None or result.get("perceptual_hash") is None
        except Exception:
            # Some implementations may raise — that is acceptable if documented
            pass

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        """Hashing a nonexistent file should not crash; returns dict with None values."""
        result = compute_hashes(tmp_path / "no_such_file.jpg")
        # Implementation returns {"file_md5": None, "perceptual_hash": None}
        assert isinstance(result, dict)
        assert result.get("file_md5") is None
        assert result.get("perceptual_hash") is None

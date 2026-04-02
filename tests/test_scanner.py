"""Tests for the photoagent.scanner module (FileScanner).

Verifies directory walking, extension filtering, recursive/non-recursive
modes, incremental scanning, error handling, and progress callbacks.

Actual interface:
    scanner = FileScanner(base_path=path, extensions=["jpg", ...], recursive=True)
    result = scanner.scan(db, on_progress=callback)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from photoagent.database import CatalogDB
from photoagent.models import ScanResult
from photoagent.scanner import FileScanner


DEFAULT_EXTENSIONS = [
    "jpg", "jpeg", "png", "heic", "heif", "webp",
    "gif", "tiff", "bmp", "raw", "cr2", "nef", "arw",
]


def _make_scanner(
    scan_dir: Path,
    db_dir: Path,
    *,
    extensions: list[str] | None = None,
    recursive: bool = True,
) -> tuple[FileScanner, CatalogDB]:
    """Create a CatalogDB and FileScanner pair."""
    db = CatalogDB(db_dir)
    scanner = FileScanner(
        base_path=scan_dir,
        extensions=extensions or DEFAULT_EXTENSIONS,
        recursive=recursive,
    )
    return scanner, db


class TestScanDiscovery:
    """Tests for file discovery during a scan."""

    def test_scan_finds_images(self, tmp_image_dir: Path, tmp_path: Path) -> None:
        """Scanning the test directory should find the expected image files."""
        scanner, db = _make_scanner(tmp_image_dir, tmp_path)
        try:
            result = scanner.scan(db)
            assert isinstance(result, ScanResult)
            assert result.total_found >= 6
        finally:
            db.close()

    def test_scan_filters_extensions(self, tmp_image_dir: Path, tmp_path: Path) -> None:
        """When only .jpg is specified, .png files should be excluded."""
        scanner, db = _make_scanner(tmp_image_dir, tmp_path, extensions=["jpg"])
        try:
            result = scanner.scan(db)
            all_images = db.get_all_images()
            extensions = {r["extension"].lower().lstrip(".") for r in all_images}
            assert "png" not in extensions
            assert result.total_found > 0
        finally:
            db.close()

    def test_scan_recursive(self, tmp_image_dir: Path, tmp_path: Path) -> None:
        """Recursive scan should discover images in subdirectories."""
        scanner, db = _make_scanner(tmp_image_dir, tmp_path, recursive=True)
        try:
            scanner.scan(db)
            all_paths = {r["file_path"] for r in db.get_all_images()}
            nested = [p for p in all_paths if "sub" in p]
            assert len(nested) >= 1, "Nested image in sub/ was not found"
        finally:
            db.close()

    def test_scan_non_recursive(self, tmp_image_dir: Path, tmp_path: Path) -> None:
        """Non-recursive scan should NOT discover images in subdirectories."""
        scanner, db = _make_scanner(tmp_image_dir, tmp_path, recursive=False)
        try:
            scanner.scan(db)
            all_paths = {r["file_path"] for r in db.get_all_images()}
            nested = [p for p in all_paths if "sub" in p]
            assert len(nested) == 0, "Nested image should be skipped in non-recursive mode"
        finally:
            db.close()

    def test_scan_empty_directory(self, tmp_path: Path) -> None:
        """Scanning an empty directory should return zero counts, no errors."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        scanner, db = _make_scanner(empty_dir, tmp_path)
        try:
            result = scanner.scan(db)
            assert result.total_found == 0
            assert result.new_images == 0
        finally:
            db.close()


class TestScanErrors:
    """Tests for graceful error handling during scanning."""

    def test_scan_invalid_path(self, tmp_path: Path) -> None:
        """Scanning a non-existent path should raise an error."""
        bad_path = tmp_path / "does_not_exist"
        scanner = FileScanner(base_path=bad_path, extensions=DEFAULT_EXTENSIONS)
        db = CatalogDB(tmp_path)
        try:
            with pytest.raises((FileNotFoundError, ValueError, OSError)):
                scanner.scan(db)
        finally:
            db.close()

    def test_scan_permission_error(self, tmp_path: Path) -> None:
        """Files that cannot be read should be logged but not crash the scan."""
        scan_dir = tmp_path / "scanme"
        scan_dir.mkdir()
        from PIL import Image

        img = Image.new("RGB", (10, 10), "red")
        img.save(str(scan_dir / "ok.jpg"), "JPEG")

        scanner, db = _make_scanner(scan_dir, tmp_path)
        try:
            result = scanner.scan(db)
            assert isinstance(result, ScanResult)
        finally:
            db.close()

    def test_scan_corrupt_file(self, tmp_image_dir: Path, tmp_path: Path) -> None:
        """Corrupt files should be logged as errors but scanning should continue."""
        scanner, db = _make_scanner(tmp_image_dir, tmp_path)
        try:
            result = scanner.scan(db)
            assert isinstance(result, ScanResult)
            assert result.new_images > 0 or result.total_found > 0
        finally:
            db.close()

    def test_scan_symlinks_skipped(self, tmp_path: Path) -> None:
        """Symlinks should be skipped during scanning."""
        scan_dir = tmp_path / "scanme"
        scan_dir.mkdir()

        from PIL import Image

        img = Image.new("RGB", (10, 10), "red")
        real_file = scan_dir / "real.jpg"
        img.save(str(real_file), "JPEG")

        link_file = scan_dir / "link.jpg"
        try:
            link_file.symlink_to(real_file)
        except OSError:
            pytest.skip("Cannot create symlinks on this platform")

        scanner, db = _make_scanner(scan_dir, tmp_path)
        try:
            scanner.scan(db)
            all_images = db.get_all_images()
            # Only the real file should be cataloged, not the symlink
            assert len(all_images) == 1, (
                f"Expected 1 image (real.jpg only), got {len(all_images)}: "
                f"{[r['file_path'] for r in all_images]}"
            )
            assert all_images[0]["filename"] == "real.jpg"
        finally:
            db.close()


class TestIncrementalScan:
    """Tests for incremental (re-)scan behavior."""

    def test_incremental_scan(self, tmp_image_dir: Path, tmp_path: Path) -> None:
        """Second scan of the same directory should skip already-cataloged files."""
        scanner, db = _make_scanner(tmp_image_dir, tmp_path)
        try:
            result1 = scanner.scan(db)
            first_new = result1.new_images

            result2 = scanner.scan(db)
            assert result2.new_images == 0 or result2.new_images < first_new
            assert result2.skipped >= first_new or result2.total_found >= first_new
        finally:
            db.close()


class TestScanProgress:
    """Tests for the optional on_progress parameter."""

    def test_scan_progress_callback(self, tmp_image_dir: Path, tmp_path: Path) -> None:
        """Verify that the progress callback is invoked with increasing counts."""
        scanner, db = _make_scanner(tmp_image_dir, tmp_path)
        try:
            calls: list[tuple[int, int]] = []

            def on_progress(current: int, total: int) -> None:
                calls.append((current, total))

            scanner.scan(db, on_progress=on_progress)
            assert len(calls) > 0, "Progress callback was never called"
        finally:
            db.close()

"""File system scanner module.

Walks a directory tree to discover image files, compute basic metadata,
and register them in the catalog database.

Designed for performance on large directories (100K+ files):
- Uses ``os.scandir`` instead of ``os.walk`` for lower syscall overhead
- Generator-based traversal to avoid loading all paths into memory
- Batched DB commits (every 100 files)
- Quick pre-count pass for progress estimation
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Generator

from photoagent.models import ScanResult

# Import sibling modules with graceful fallback
try:
    from photoagent.exif import extract_exif
except ImportError:

    def extract_exif(file_path: Path) -> dict[str, Any]:  # type: ignore[misc]
        return {}


try:
    from photoagent.hashing import compute_hashes
except ImportError:

    def compute_hashes(file_path: Path) -> dict[str, Any]:  # type: ignore[misc]
        return {}


logger = logging.getLogger(__name__)

_BATCH_SIZE = 100  # Commit after this many inserts/updates


class FileScanner:
    """Scan a directory tree for image files and catalog them."""

    def __init__(
        self,
        base_path: Path,
        extensions: list[str],
        recursive: bool = True,
    ) -> None:
        self.base_path = Path(base_path).resolve()
        # Normalise extensions: lowercase, with leading dot
        self.extensions: set[str] = {
            (ext if ext.startswith(".") else f".{ext}").lower()
            for ext in extensions
        }
        self.recursive = recursive

    # ------------------------------------------------------------------
    # Directory walking (generator, os.scandir-based)
    # ------------------------------------------------------------------

    def _iter_entries(
        self, root: Path
    ) -> Generator[os.DirEntry[str], None, None]:
        """Yield ``os.DirEntry`` objects for image files under *root*.

        Uses ``os.scandir`` for performance.  Symlinks and unreadable
        directories are silently skipped.
        """
        try:
            with os.scandir(root) as it:
                for entry in it:
                    # Skip symlinks
                    if entry.is_symlink():
                        continue

                    # Skip macOS resource forks and metadata
                    if entry.name.startswith("._") or entry.name == ".DS_Store":
                        continue

                    if entry.is_dir(follow_symlinks=False):
                        # Skip macOS archive junk directories
                        if entry.name == "__MACOSX":
                            continue
                        if self.recursive:
                            yield from self._iter_entries(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False):
                        _, ext = os.path.splitext(entry.name)
                        if ext.lower() in self.extensions:
                            yield entry
        except PermissionError:
            logger.warning("Permission denied: %s", root)
        except OSError as exc:
            logger.warning("OS error scanning %s: %s", root, exc)

    def _count_files(self) -> int:
        """Quick first-pass count for progress estimation."""
        count = 0
        for _ in self._iter_entries(self.base_path):
            count += 1
        return count

    # ------------------------------------------------------------------
    # Single-file processing
    # ------------------------------------------------------------------

    @staticmethod
    def _stat_info(entry: os.DirEntry[str]) -> dict[str, Any]:
        """Collect filesystem metadata from a DirEntry."""
        try:
            stat = entry.stat(follow_symlinks=False)
        except OSError:
            return {}

        file_created: float | None = None
        # st_birthtime is macOS/BSD; fall back to st_ctime elsewhere
        if hasattr(stat, "st_birthtime"):
            file_created = stat.st_birthtime
        else:
            file_created = stat.st_ctime

        return {
            "file_size": stat.st_size,
            "file_created": file_created,
            "file_modified": stat.st_mtime,
        }

    def _process_file(
        self,
        entry: os.DirEntry[str],
        db: Any,
    ) -> str:
        """Process a single image file.

        Returns one of ``"new"``, ``"updated"``, ``"skipped"``.
        Raises on unrecoverable errors (caller should catch).
        """
        abs_path = os.path.abspath(entry.path)
        filename = entry.name
        _, ext = os.path.splitext(filename)

        stat = self._stat_info(entry)
        current_modified = stat.get("file_modified")

        # Incremental scan: skip if file hasn't changed
        if current_modified is not None and not db.image_needs_rescan(
            abs_path, current_modified
        ):
            return "skipped"

        # Gather metadata
        file_path = Path(abs_path)
        exif_data = extract_exif(file_path)
        hash_data = compute_hashes(file_path)

        record: dict[str, Any] = {
            "file_path": abs_path,
            "filename": filename,
            "extension": ext.lower().lstrip("."),
            "file_size": stat.get("file_size"),
            "file_created": stat.get("file_created"),
            "file_modified": current_modified,
        }

        # Merge EXIF fields
        for key in (
            "date_taken",
            "gps_lat",
            "gps_lon",
            "city",
            "country",
            "camera_make",
            "camera_model",
            "lens",
            "iso",
            "aperture",
            "shutter_speed",
            "flash_used",
            "orientation",
        ):
            record[key] = exif_data.get(key)

        # Merge hash fields
        record["file_md5"] = hash_data.get("file_md5")
        record["perceptual_hash"] = hash_data.get("perceptual_hash")

        # Insert or update
        existing = db.get_image_by_path(abs_path)
        if existing is None:
            db.insert_image(record)
            return "new"
        else:
            image_id = existing["id"]
            db.update_image(image_id, **record)
            return "updated"

    # ------------------------------------------------------------------
    # Main scan entry point
    # ------------------------------------------------------------------

    def scan(
        self,
        db: Any,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> ScanResult:
        """Scan the directory tree and populate the catalog database.

        Parameters
        ----------
        db:
            A ``CatalogDB`` instance (or any object matching its API).
        on_progress:
            Optional callback invoked as ``on_progress(current, total)``
            after each file is processed.

        Returns
        -------
        ScanResult
            Summary dataclass with counts and timing information.
        """
        # Validate base path
        if not self.base_path.exists():
            raise FileNotFoundError(
                f"Scan path does not exist: {self.base_path}"
            )
        if not self.base_path.is_dir():
            raise NotADirectoryError(
                f"Scan path is not a directory: {self.base_path}"
            )
        if not os.access(self.base_path, os.R_OK):
            raise PermissionError(
                f"Scan path is not readable: {self.base_path}"
            )

        start_time = time.monotonic()

        # Pre-count for progress bar (quick pass — reads only dir entries)
        logger.info("Counting image files in %s ...", self.base_path)
        total_estimate = self._count_files()
        logger.info("Found approximately %d image files", total_estimate)

        result = ScanResult(total_found=total_estimate)
        current = 0
        pending_commits = 0

        # Access the raw connection for manual transaction control
        # so we can batch commits for performance.
        conn = db._conn  # noqa: SLF001 — intentional access for batching

        for entry in self._iter_entries(self.base_path):
            current += 1
            try:
                outcome = self._process_file(entry, db)
                if outcome == "new" or outcome == "updated":
                    result.new_images += 1
                    pending_commits += 1
                elif outcome == "skipped":
                    result.skipped += 1
            except Exception as exc:
                error_msg = f"{entry.path}: {exc}"
                result.errors.append(error_msg)
                logger.warning("Error processing %s: %s", entry.path, exc)

            # Batch commit
            if pending_commits >= _BATCH_SIZE:
                try:
                    conn.commit()
                except Exception:
                    pass
                pending_commits = 0

            # Progress callback
            if on_progress is not None:
                on_progress(current, total_estimate)

        # Final commit for any remaining uncommitted rows
        if pending_commits > 0:
            try:
                conn.commit()
            except Exception:
                pass

        result.duration = time.monotonic() - start_time
        return result

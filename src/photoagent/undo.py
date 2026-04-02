"""Undo system for PhotoAgent file operations.

Reads a manifest produced by PlanExecutor and reverses every move,
using the same copy-verify-delete safety semantics.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from photoagent.database import CatalogDB
from photoagent.executor import _md5
from photoagent.models import ExecutionResult

logger = logging.getLogger(__name__)


class UndoManager:
    """Reverse a previously executed organization plan."""

    def __init__(self, base_path: Path, db: CatalogDB) -> None:
        self._base_path = Path(base_path).resolve()
        self._db = db
        self._manifests_dir = self._base_path / ".photoagent" / "manifests"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def undo(
        self,
        manifest_path: Path | None = None,
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> ExecutionResult:
        """Undo the operations described in a manifest.

        Args:
            manifest_path: Path to the manifest JSON.  If *None*, the most
                recent manifest is used.
            on_progress: Optional callback(current, total, description).

        Returns:
            ExecutionResult summarising the undo.
        """
        t0 = time.monotonic()

        if manifest_path is None:
            manifest_path = self.get_manifest_path()
        if manifest_path is None or not manifest_path.exists():
            return ExecutionResult(
                errors=["No manifest found to undo."],
                duration=time.monotonic() - t0,
            )

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        operations: list[dict[str, str]] = manifest.get("operations", [])

        result = ExecutionResult(total_planned=len(operations))

        # Find the matching operations-table row so we can mark it undone.
        operation_id = self._find_operation_id(manifest_path)

        # Reverse in reverse order so nested dirs are emptied bottom-up.
        for idx, op in enumerate(reversed(operations)):
            src_abs = op.get("source_abs", "")
            dst_abs = op.get("dest_abs", "")
            src = Path(src_abs)
            dst = Path(dst_abs)

            desc = f"{dst_abs} -> {src_abs}"

            try:
                if not dst.exists():
                    msg = f"Destination missing, skipped undo: {dst_abs}"
                    logger.warning(msg)
                    result.skipped += 1
                    result.errors.append(msg)
                    if on_progress:
                        on_progress(idx + 1, len(operations), f"SKIP {dst_abs}")
                    continue

                # Ensure original directory exists
                src.parent.mkdir(parents=True, exist_ok=True)

                # Handle conflict at the original location
                actual_src = src
                if src.exists():
                    actual_src = self._resolve_conflict(src)
                    result.conflicts_resolved += 1

                # Copy dest back to original source location
                import shutil

                shutil.copy2(str(dst), str(actual_src))

                # Verify
                if _md5(dst) != _md5(actual_src):
                    try:
                        actual_src.unlink()
                    except OSError:
                        pass
                    msg = f"MD5 verification failed during undo: {desc}"
                    logger.error(msg)
                    result.errors.append(msg)
                    result.skipped += 1
                    if on_progress:
                        on_progress(idx + 1, len(operations), f"VERIFY FAIL")
                    continue

                # Delete the destination copy
                try:
                    dst.unlink()
                except OSError as exc:
                    msg = f"Could not remove dest {dst_abs}: {exc}"
                    logger.warning(msg)
                    result.errors.append(msg)

                # Update catalog DB back to original path
                self._update_catalog_path(str(dst), str(actual_src))

                result.successful += 1
                if on_progress:
                    on_progress(idx + 1, len(operations), f"UNDO {Path(dst_abs).name}")

            except PermissionError as exc:
                msg = f"Permission denied during undo: {desc} -- {exc}"
                logger.error(msg)
                result.errors.append(msg)
                result.skipped += 1
                if on_progress:
                    on_progress(idx + 1, len(operations), f"ERROR")

            except OSError as exc:
                msg = f"OS error during undo: {desc} -- {exc}"
                logger.error(msg)
                result.errors.append(msg)
                result.skipped += 1
                if on_progress:
                    on_progress(idx + 1, len(operations), f"ERROR")

            except Exception as exc:  # noqa: BLE001
                msg = f"Unexpected error during undo: {desc} -- {exc}"
                logger.error(msg)
                result.errors.append(msg)
                result.skipped += 1
                if on_progress:
                    on_progress(idx + 1, len(operations), f"ERROR")

        # Mark operation as undone
        if operation_id is not None:
            self._db._conn.execute(
                "UPDATE operations SET status = 'undone', "
                "completed_at = CURRENT_TIMESTAMP WHERE id = ?",
                (operation_id,),
            )
            self._db._conn.commit()

        result.duration = time.monotonic() - t0
        return result

    def get_history(self) -> list[dict[str, Any]]:
        """Return a list of past operations from the operations table.

        Each dict has: id, timestamp, instruction, status, file_count.
        """
        rows = self._db._conn.execute(
            "SELECT id, timestamp, instruction, manifest_json, status "
            "FROM operations ORDER BY id DESC"
        ).fetchall()

        history: list[dict[str, Any]] = []
        for row in rows:
            manifest_json = row["manifest_json"] or "{}"
            try:
                manifest = json.loads(manifest_json)
                file_count = len(manifest.get("operations", []))
            except (json.JSONDecodeError, TypeError):
                file_count = 0

            history.append(
                {
                    "id": row["id"],
                    "timestamp": row["timestamp"],
                    "instruction": row["instruction"] or "",
                    "status": row["status"] or "unknown",
                    "file_count": file_count,
                }
            )
        return history

    def get_manifest_path(self, operation_id: int | None = None) -> Path | None:
        """Return the manifest file path for an operation.

        If *operation_id* is None, return the most recent manifest file.
        """
        if operation_id is not None:
            row = self._db._conn.execute(
                "SELECT manifest_json FROM operations WHERE id = ?",
                (operation_id,),
            ).fetchone()
            if row and row["manifest_json"]:
                try:
                    manifest = json.loads(row["manifest_json"])
                    created = manifest.get("created_at", "")
                    # Search for matching manifest file
                    if self._manifests_dir.exists():
                        for p in sorted(self._manifests_dir.glob("*.json"), reverse=True):
                            try:
                                m = json.loads(p.read_text(encoding="utf-8"))
                                if m.get("created_at") == created:
                                    return p
                            except (json.JSONDecodeError, OSError):
                                continue
                except (json.JSONDecodeError, TypeError):
                    pass
            return None

        # Most recent manifest by filename (timestamps sort lexicographically)
        if not self._manifests_dir.exists():
            return None
        manifests = sorted(self._manifests_dir.glob("*.json"), reverse=True)
        return manifests[0] if manifests else None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_conflict(self, dest: Path) -> Path:
        """Append _001 .. _999 before the extension until a free name is found."""
        stem = dest.stem
        suffix = dest.suffix
        parent = dest.parent
        for i in range(1, 1000):
            candidate = parent / f"{stem}_{i:03d}{suffix}"
            if not candidate.exists():
                return candidate
        raise OSError(
            f"Could not resolve conflict for {dest}: "
            "all 999 alternative names are taken"
        )

    def _find_operation_id(self, manifest_path: Path) -> int | None:
        """Find the operations-table row that matches *manifest_path*."""
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            created_at = manifest.get("created_at", "")
        except (json.JSONDecodeError, OSError):
            return None

        rows = self._db._conn.execute(
            "SELECT id, manifest_json FROM operations "
            "ORDER BY id DESC"
        ).fetchall()

        for row in rows:
            try:
                m = json.loads(row["manifest_json"] or "{}")
                if m.get("created_at") == created_at:
                    return row["id"]
            except (json.JSONDecodeError, TypeError):
                continue
        return None

    def _update_catalog_path(self, old_path: str, new_path: str) -> None:
        """Update the image record's file_path from *old_path* to *new_path*."""
        row = self._db.get_image_by_path(old_path)
        if row is not None:
            new_filename = Path(new_path).name
            new_ext = Path(new_path).suffix.lower()
            self._db.update_image(
                row["id"],
                file_path=new_path,
                filename=new_filename,
                extension=new_ext,
            )
        else:
            logger.debug(
                "No catalog entry found for %s; DB not updated", old_path
            )

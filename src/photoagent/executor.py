"""Safe file execution engine for PhotoAgent.

Implements copy-verify-delete semantics with full manifest logging,
conflict resolution, and per-file error isolation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from photoagent.database import CatalogDB
from photoagent.models import ExecutionResult

logger = logging.getLogger(__name__)


class PlanExecutor:
    """Execute an organization plan with safety-first file operations."""

    def __init__(self, base_path: Path, db: CatalogDB) -> None:
        self._base_path = Path(base_path).resolve()
        self._db = db
        self._manifests_dir = self._base_path / ".photoagent" / "manifests"
        self._manifests_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(
        self,
        plan: dict[str, Any],
        on_progress: Callable[[int, int, str], None] | None = None,
    ) -> ExecutionResult:
        """Execute an organization plan.

        Args:
            plan: Plan dict with ``folder_structure``, ``moves``, ``summary``.
            on_progress: Optional callback(current, total, description).

        Returns:
            ExecutionResult with counts and timing.
        """
        t0 = time.monotonic()
        moves = plan.get("moves", [])
        result = ExecutionResult(total_planned=len(moves))

        # 1. Write manifest BEFORE any file operations
        manifest = self._build_manifest(plan)
        manifest_path = self._write_manifest(manifest)

        # 2. Record operation in DB
        operation_id = self._record_operation(
            instruction=plan.get("summary", ""),
            manifest_json=json.dumps(manifest),
        )

        # 3. Create destination directories
        for folder in plan.get("folder_structure", []):
            dest_dir = self._base_path / folder
            try:
                dest_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                msg = f"Failed to create directory {folder}: {exc}"
                logger.error(msg)
                result.errors.append(msg)

        # 4. Process each move
        for idx, move in enumerate(moves):
            src_rel = move.get("from", "")
            dst_rel = move.get("to", "")
            src = (self._base_path / src_rel).resolve()
            dst = (self._base_path / dst_rel).resolve()

            desc = f"{src_rel} -> {dst_rel}"

            try:
                # 4c. Source must exist
                if not src.exists():
                    msg = f"Source missing, skipped: {src_rel}"
                    logger.warning(msg)
                    result.skipped += 1
                    result.errors.append(msg)
                    if on_progress:
                        on_progress(idx + 1, len(moves), f"SKIP {src_rel}")
                    continue

                # 4d. Conflict resolution
                conflict_resolved = False
                if dst.exists():
                    dst = self._resolve_conflict(dst)
                    conflict_resolved = True
                    result.conflicts_resolved += 1

                # Ensure parent directory exists
                dst.parent.mkdir(parents=True, exist_ok=True)

                # 4e. COPY first (never move directly)
                shutil.copy2(str(src), str(dst))

                # 4f. Verify copy via MD5
                if not self._verify_copy(src, dst):
                    # Verification failed -- remove the bad copy, skip
                    try:
                        dst.unlink()
                    except OSError:
                        pass
                    msg = f"MD5 verification failed: {desc}"
                    logger.error(msg)
                    result.errors.append(msg)
                    result.skipped += 1
                    if on_progress:
                        on_progress(idx + 1, len(moves), f"VERIFY FAIL {src_rel}")
                    continue

                # 4g. Delete source only after verified copy
                try:
                    src.unlink()
                except OSError as exc:
                    # Copy succeeded but source delete failed -- non-fatal
                    msg = f"Could not remove source {src_rel}: {exc}"
                    logger.warning(msg)
                    result.errors.append(msg)

                # 4h. Update catalog DB
                self._update_catalog_path(str(src), str(dst))

                result.successful += 1
                if on_progress:
                    status = "MOVE" if not conflict_resolved else "MOVE (conflict resolved)"
                    on_progress(idx + 1, len(moves), f"{status} {src_rel}")

            except PermissionError as exc:
                msg = f"Permission denied: {desc} -- {exc}"
                logger.error(msg)
                result.errors.append(msg)
                result.skipped += 1
                if on_progress:
                    on_progress(idx + 1, len(moves), f"ERROR {src_rel}")

            except OSError as exc:
                msg = f"OS error: {desc} -- {exc}"
                logger.error(msg)
                result.errors.append(msg)
                result.skipped += 1
                if on_progress:
                    on_progress(idx + 1, len(moves), f"ERROR {src_rel}")

            except Exception as exc:  # noqa: BLE001
                msg = f"Unexpected error: {desc} -- {exc}"
                logger.error(msg)
                result.errors.append(msg)
                result.skipped += 1
                if on_progress:
                    on_progress(idx + 1, len(moves), f"ERROR {src_rel}")

        # 5. Mark operation as completed
        self._complete_operation(operation_id)

        result.duration = time.monotonic() - t0
        return result

    def simulate(self, plan: dict[str, Any]) -> list[dict[str, Any]]:
        """Dry-run: return list of dicts describing what would happen.

        Each dict has keys: from, to, action, conflict_resolved_to.
        """
        results: list[dict[str, Any]] = []
        moves = plan.get("moves", [])

        # Track destinations we've "claimed" during simulation to detect
        # intra-plan conflicts as well.
        claimed: set[str] = set()

        for move in moves:
            src_rel = move.get("from", "")
            dst_rel = move.get("to", "")
            src = (self._base_path / src_rel).resolve()
            dst = (self._base_path / dst_rel).resolve()

            entry: dict[str, Any] = {
                "from": str(src),
                "to": str(dst),
                "action": "move",
                "conflict_resolved_to": None,
            }

            if not src.exists():
                entry["action"] = "skip_missing"
                results.append(entry)
                continue

            if dst.exists() or str(dst) in claimed:
                resolved = self._resolve_conflict_simulated(dst, claimed)
                entry["action"] = "conflict_rename"
                entry["conflict_resolved_to"] = str(resolved)
                claimed.add(str(resolved))
            else:
                claimed.add(str(dst))

            results.append(entry)

        return results

    # ------------------------------------------------------------------
    # Conflict resolution
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

    def _resolve_conflict_simulated(
        self, dest: Path, claimed: set[str]
    ) -> Path:
        """Like _resolve_conflict but also considers simulation-claimed names."""
        stem = dest.stem
        suffix = dest.suffix
        parent = dest.parent

        for i in range(1, 1000):
            candidate = parent / f"{stem}_{i:03d}{suffix}"
            if not candidate.exists() and str(candidate) not in claimed:
                return candidate

        raise OSError(
            f"Could not resolve conflict for {dest}: "
            "all 999 alternative names are taken"
        )

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def _verify_copy(self, source: Path, dest: Path) -> bool:
        """Compare MD5 hashes of *source* and *dest* (8 KB chunks)."""
        return _md5(source) == _md5(dest)

    # ------------------------------------------------------------------
    # Manifest I/O
    # ------------------------------------------------------------------

    def _build_manifest(self, plan: dict[str, Any]) -> dict[str, Any]:
        """Build a manifest dict with absolute paths for every operation."""
        operations: list[dict[str, str]] = []
        for move in plan.get("moves", []):
            operations.append(
                {
                    "id": str(move.get("id", "")),
                    "source_rel": move.get("from", ""),
                    "dest_rel": move.get("to", ""),
                    "source_abs": str((self._base_path / move["from"]).resolve()),
                    "dest_abs": str((self._base_path / move["to"]).resolve()),
                }
            )

        return {
            "base_path": str(self._base_path),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "summary": plan.get("summary", ""),
            "folder_structure": plan.get("folder_structure", []),
            "operations": operations,
        }

    def _write_manifest(self, manifest: dict[str, Any]) -> Path:
        """Write manifest JSON and return its path."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%f")
        path = self._manifests_dir / f"{ts}.json"
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        logger.info("Manifest written to %s", path)
        return path

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------

    def _record_operation(self, instruction: str, manifest_json: str) -> int:
        """Insert a row into the operations table and return its id."""
        cur = self._db._conn.execute(
            "INSERT INTO operations (instruction, manifest_json, status) "
            "VALUES (?, ?, 'executing')",
            (instruction, manifest_json),
        )
        self._db._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def _complete_operation(self, operation_id: int) -> None:
        """Mark an operation as completed."""
        self._db._conn.execute(
            "UPDATE operations SET status = 'completed', "
            "completed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (operation_id,),
        )
        self._db._conn.commit()

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


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _md5(path: Path) -> str:
    """Return the hex MD5 digest of a file, reading in 8 KB chunks."""
    h = hashlib.md5()  # noqa: S324
    with open(path, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()

"""Claude API client and plan generator for PhotoAgent.

Sends catalog summaries and manifests (text metadata only) to Claude to
generate file-organization plans.  Includes robust privacy guards that
prevent any pixel data, base64 blobs, or binary content from leaving
the local machine.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anthropic

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------
# Exceptions
# -----------------------------------------------------------------------


class PrivacyViolationError(Exception):
    """Raised when a payload fails privacy validation.

    This is a critical safety guard -- if this fires, the request is
    blocked before any data leaves the machine.
    """


# -----------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are a file organization planner. Given a summary of an image "
    "library, a list of images with metadata, and a user instruction, "
    "generate a JSON plan. Each image should be mapped to a new relative "
    "path. Consider dates, locations, tags, captions, face clusters, and "
    "quality when organizing. Respond ONLY with valid JSON."
)

_MODEL = "claude-sonnet-4-20250514"

# Privacy-guard thresholds
_MAX_PAYLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
_BASE64_PATTERN = re.compile(r"[A-Za-z0-9+/=]{100,}")
_BINARY_PATTERNS = [
    re.compile(rb"\\x[0-9a-fA-F]{2}"),       # escaped hex bytes
    re.compile(rb"\x89PNG"),                   # PNG magic
    re.compile(rb"\xff\xd8\xff"),              # JPEG magic
    re.compile(rb"GIF8[79]a"),                 # GIF magic
    re.compile(rb"RIFF.{4}WEBP", re.DOTALL),  # WebP magic
]


# -----------------------------------------------------------------------
# Planner
# -----------------------------------------------------------------------


class OrganizationPlanner:
    """Generates file-organization plans via the Anthropic Claude API."""

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or self._resolve_api_key()
        self._client = anthropic.Anthropic(api_key=self._api_key)

    # ------------------------------------------------------------------
    # API key resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_api_key() -> str:
        """Try keyring, then environment variable.  Raises ValueError."""
        # 1. keyring
        try:
            import keyring

            stored = keyring.get_password("photoagent", "anthropic_api_key")
            if stored:
                return stored
        except Exception:
            # keyring may not be configured or available
            pass

        # 2. environment variable
        env_key = os.environ.get("ANTHROPIC_API_KEY")
        if env_key:
            return env_key

        raise ValueError(
            "No Anthropic API key found. Set ANTHROPIC_API_KEY or store "
            "it via: python -c \"import keyring; keyring.set_password("
            "'photoagent', 'anthropic_api_key', 'sk-...')\""
        )

    # ------------------------------------------------------------------
    # Privacy guard
    # ------------------------------------------------------------------

    def _validate_payload(self, payload: str) -> None:
        """Validate that the payload contains no pixel/binary data.

        Raises PrivacyViolationError if any check fails.  This runs
        *before* any network request is made.
        """
        # Size check
        payload_bytes = payload.encode("utf-8", errors="replace")
        if len(payload_bytes) > _MAX_PAYLOAD_BYTES:
            raise PrivacyViolationError(
                f"Payload too large: {len(payload_bytes):,} bytes "
                f"(limit {_MAX_PAYLOAD_BYTES:,} bytes). This likely means "
                "binary or pixel data was accidentally included."
            )

        # Base64 blob check
        match = _BASE64_PATTERN.search(payload)
        if match:
            snippet = match.group()[:40]
            raise PrivacyViolationError(
                f"Payload contains a long base64-like string "
                f"(starts with '{snippet}...'). Image pixel data must "
                "never be sent to the API."
            )

        # Binary magic-byte check
        for pattern in _BINARY_PATTERNS:
            if pattern.search(payload_bytes):
                raise PrivacyViolationError(
                    "Payload contains binary data signatures (e.g. PNG/JPEG "
                    "magic bytes). Image pixel data must never be sent to "
                    "the API."
                )

    # ------------------------------------------------------------------
    # Plan generation (single chunk)
    # ------------------------------------------------------------------

    def generate_plan(
        self,
        summary: dict[str, Any],
        manifest_chunk: list[dict[str, Any]],
        instruction: str,
        existing_folders: list[str] | None = None,
        verbose: bool = False,
    ) -> dict[str, Any]:
        """Generate an organization plan for one manifest chunk.

        Parameters
        ----------
        summary:
            High-level catalog summary from CatalogSummarizer.build_summary.
        manifest_chunk:
            A list of per-image metadata dicts (one chunk).
        instruction:
            The user's natural-language organization instruction.
        existing_folders:
            Folder names from prior chunks (for multi-chunk consistency).
        verbose:
            If True, log the full request/response to disk.

        Returns
        -------
        dict with keys ``folder_structure``, ``moves``, ``summary``.
        """
        # Build user message -------------------------------------------
        user_parts: list[str] = []

        user_parts.append("## Catalog Summary\n")
        user_parts.append(json.dumps(summary, indent=2, default=str))

        user_parts.append("\n\n## Image Manifest (this chunk)\n")
        user_parts.append(json.dumps(manifest_chunk, indent=2, default=str))

        user_parts.append(f"\n\n## User Instruction\n{instruction}")

        if existing_folders:
            user_parts.append(
                "\n\n## Existing Folders (from prior chunks)\n"
                + json.dumps(existing_folders)
            )

        user_parts.append(
            "\n\n## Required Output Format\n"
            "Respond with ONLY a JSON object with exactly these keys:\n"
            '- "folder_structure": list of folder path strings\n'
            '- "moves": list of objects with "id", "from", "to" keys\n'
            '- "summary": a short text summary of what the plan does'
        )

        user_message = "\n".join(user_parts)

        # Privacy check ------------------------------------------------
        full_payload = _SYSTEM_PROMPT + "\n" + user_message
        self._validate_payload(full_payload)

        # API call -----------------------------------------------------
        request_body = {
            "model": _MODEL,
            "max_tokens": 16384,
            "system": _SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user_message}],
        }

        if verbose:
            self._log_request(request_body)

        response = self._client.messages.create(**request_body)

        # Parse response -----------------------------------------------
        raw_text = response.content[0].text if response.content else ""

        if verbose:
            self._log_response(raw_text)

        plan = self._parse_plan_json(raw_text)
        return plan

    # ------------------------------------------------------------------
    # Plan generation (multi-chunk)
    # ------------------------------------------------------------------

    def generate_plan_chunked(
        self,
        summary: dict[str, Any],
        manifest_chunks: list[list[dict[str, Any]]],
        instruction: str,
        verbose: bool = False,
    ) -> dict[str, Any]:
        """Generate a unified plan across all manifest chunks.

        For a single chunk this is a simple pass-through.  For multiple
        chunks, each subsequent call receives the folder structure from
        prior chunks to maintain consistency.
        """
        if not manifest_chunks or (
            len(manifest_chunks) == 1 and not manifest_chunks[0]
        ):
            return {
                "folder_structure": [],
                "moves": [],
                "summary": "No images to organize.",
            }

        if len(manifest_chunks) == 1:
            return self.generate_plan(
                summary=summary,
                manifest_chunk=manifest_chunks[0],
                instruction=instruction,
                verbose=verbose,
            )

        # Multi-chunk: accumulate folders for consistency
        all_folders: list[str] = []
        all_moves: list[dict[str, Any]] = []
        summaries: list[str] = []

        for i, chunk in enumerate(manifest_chunks):
            logger.info(
                "Processing chunk %d/%d (%d images)",
                i + 1,
                len(manifest_chunks),
                len(chunk),
            )
            plan = self.generate_plan(
                summary=summary,
                manifest_chunk=chunk,
                instruction=instruction,
                existing_folders=all_folders if all_folders else None,
                verbose=verbose,
            )

            # Accumulate
            chunk_folders = plan.get("folder_structure", [])
            for folder in chunk_folders:
                if folder not in all_folders:
                    all_folders.append(folder)

            all_moves.extend(plan.get("moves", []))
            chunk_summary = plan.get("summary", "")
            if chunk_summary:
                summaries.append(chunk_summary)

        merged_summary = " | ".join(summaries) if summaries else ""

        return {
            "folder_structure": all_folders,
            "moves": all_moves,
            "summary": merged_summary,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_plan_json(raw_text: str) -> dict[str, Any]:
        """Extract and parse JSON from the model response.

        The model should return raw JSON, but we handle markdown code
        fences and leading/trailing text gracefully.
        """
        text = raw_text.strip()

        # Strip markdown code fences if present
        if text.startswith("```"):
            # Remove opening fence (```json or ```)
            first_newline = text.index("\n") if "\n" in text else len(text)
            text = text[first_newline + 1 :]
            # Remove closing fence
            if text.endswith("```"):
                text = text[: -3].rstrip()

        # Try direct parse first
        try:
            return json.loads(text)  # type: ignore[no-any-return]
        except json.JSONDecodeError:
            pass

        # Try to find a JSON object in the text
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
            try:
                return json.loads(text[brace_start : brace_end + 1])  # type: ignore[no-any-return]
            except json.JSONDecodeError:
                pass

        raise ValueError(
            f"Failed to parse plan JSON from model response. "
            f"Raw text (first 500 chars): {raw_text[:500]}"
        )

    def _log_request(self, request_body: dict[str, Any]) -> None:
        """Write request payload to disk for debugging."""
        log_dir = Path.cwd() / ".photoagent" / "api_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        log_path = log_dir / f"{ts}_request.json"
        log_path.write_text(
            json.dumps(request_body, indent=2, default=str),
            encoding="utf-8",
        )
        logger.info("Logged API request to %s", log_path)

    def _log_response(self, response_text: str) -> None:
        """Write response payload to disk for debugging."""
        log_dir = Path.cwd() / ".photoagent" / "api_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        log_path = log_dir / f"{ts}_response.json"
        log_path.write_text(response_text, encoding="utf-8")
        logger.info("Logged API response to %s", log_path)

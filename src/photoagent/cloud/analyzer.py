"""Cloud-based image analyzer using Claude Haiku vision."""

from __future__ import annotations

import base64
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import anthropic

from photoagent.cloud.models import CloudAnalysisResult

_SYSTEM_PROMPT = """\
You are a photo analysis engine. For each image return ONLY a JSON object:
{
  "category": "<primary>",
  "subcategory": "<specific type>",
  "subject": "<main subject>",
  "mood": "<mood or feel>",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
  "quality_note": "<brief note or null>"
}

Categories: landscape, portrait, street, food, architecture, nature, wildlife,
event, product, abstract, screenshot, document, selfie, group_photo,
pet, sport, travel, night, macro, aerial, underwater, other.

Return ONLY valid JSON. No markdown fences. No explanation."""

_MAX_RETRIES = 3
_RETRY_DELAYS = [1.0, 2.0, 4.0]


class CloudAnalyzer:
    """Sends thumbnail images to Claude Haiku for vision-based analysis."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-haiku-4-5-20251001",
    ) -> None:
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def analyze_one(
        self,
        jpeg_bytes: bytes,
        filename: str,
    ) -> CloudAnalysisResult:
        """Analyze a single image thumbnail.

        Parameters
        ----------
        jpeg_bytes:
            JPEG-encoded thumbnail bytes.
        filename:
            Original filename (used in the prompt and result).

        Returns
        -------
        A CloudAnalysisResult populated from the API response.
        """
        image_b64 = base64.standard_b64encode(jpeg_bytes).decode("ascii")

        user_message = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": image_b64,
                },
            },
            {
                "type": "text",
                "text": f"Analyze this photo. Filename: {filename}",
            },
        ]

        # Retry loop for rate-limit and server errors
        last_exception: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                response = self._client.messages.create(
                    model=self._model,
                    max_tokens=300,
                    system=_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_message}],
                )
                return self._parse_response(response, filename, len(jpeg_bytes))

            except anthropic.RateLimitError as exc:
                last_exception = exc
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_DELAYS[attempt])
                    continue
                break

            except anthropic.InternalServerError as exc:
                last_exception = exc
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(_RETRY_DELAYS[attempt])
                    continue
                break

            except Exception as exc:
                # Non-retryable error
                return self._error_result(
                    filename=filename,
                    error_msg=str(exc),
                    thumb_byte_size=len(jpeg_bytes),
                )

        # All retries exhausted
        return self._error_result(
            filename=filename,
            error_msg=str(last_exception),
            thumb_byte_size=len(jpeg_bytes),
        )

    def _parse_response(
        self,
        response: anthropic.types.Message,
        filename: str,
        thumb_byte_size: int,
    ) -> CloudAnalysisResult:
        """Parse the API response into a CloudAnalysisResult."""
        raw_text = response.content[0].text
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        now_iso = datetime.now(timezone.utc).isoformat()

        data = self._try_parse_json(raw_text)

        if data is None:
            return CloudAnalysisResult(
                image_path=filename,
                category="parse_error",
                subcategory="",
                subject=raw_text[:500],
                mood="",
                tags=[],
                quality_note=None,
                model=self._model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                thumb_byte_size=thumb_byte_size,
                analyzed_at=now_iso,
            )

        return CloudAnalysisResult(
            image_path=filename,
            category=data.get("category", "other"),
            subcategory=data.get("subcategory", ""),
            subject=data.get("subject", ""),
            mood=data.get("mood", ""),
            tags=data.get("tags", []),
            quality_note=data.get("quality_note"),
            model=self._model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            thumb_byte_size=thumb_byte_size,
            analyzed_at=now_iso,
        )

    @staticmethod
    def _try_parse_json(text: str) -> dict | None:
        """Attempt to parse JSON, stripping markdown fences if needed."""
        # First try direct parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Strip markdown fences and try again
        stripped = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
        stripped = re.sub(r"\n?```\s*$", "", stripped)
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return None

    def _error_result(
        self,
        filename: str,
        error_msg: str,
        thumb_byte_size: int,
    ) -> CloudAnalysisResult:
        """Build an error result when the API call fails entirely."""
        return CloudAnalysisResult(
            image_path=filename,
            category="error",
            subcategory="",
            subject=error_msg[:500],
            mood="",
            tags=[],
            quality_note=None,
            model=self._model,
            input_tokens=0,
            output_tokens=0,
            thumb_byte_size=thumb_byte_size,
            analyzed_at=datetime.now(timezone.utc).isoformat(),
        )

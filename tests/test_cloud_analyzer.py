"""Tests for photoagent.cloud.analyzer.CloudAnalyzer.

All tests mock ``anthropic.Anthropic`` — no real API calls are made.
"""

from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock, patch

import pytest

from photoagent.cloud.analyzer import CloudAnalyzer
from photoagent.cloud.models import CloudAnalysisResult


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

_VALID_JSON_RESPONSE = json.dumps(
    {
        "category": "landscape",
        "subcategory": "mountain",
        "subject": "snow peak",
        "mood": "serene",
        "tags": ["mountain", "snow", "peak", "nature", "winter"],
        "quality_note": None,
    }
)


def _make_mock_response(
    text: str = _VALID_JSON_RESPONSE,
    input_tokens: int = 100,
    output_tokens: int = 50,
) -> MagicMock:
    """Build a mock Anthropic API response object."""
    content_block = MagicMock()
    content_block.text = text

    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens

    response = MagicMock()
    response.content = [content_block]
    response.usage = usage
    return response


def _make_mock_client(response: MagicMock | None = None) -> MagicMock:
    """Build a mock ``anthropic.Anthropic`` instance.

    Returns a tuple of (mock_client_instance, mock_create) so callers
    can inspect how ``messages.create`` was called.
    """
    if response is None:
        response = _make_mock_response()

    mock_client = MagicMock()
    mock_create = mock_client.messages.create
    mock_create.return_value = response
    return mock_client


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def sample_jpeg_bytes() -> bytes:
    """Minimal JPEG-like bytes for testing (not a real image, just data)."""
    return b"\xff\xd8\xff\xe0" + b"\x00" * 100


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


class TestCloudAnalyzer:
    """Unit tests for CloudAnalyzer.analyze_one."""

    @patch("photoagent.cloud.analyzer.anthropic.Anthropic")
    def test_analyze_valid_response(
        self, mock_anthropic_cls: MagicMock, sample_jpeg_bytes: bytes
    ) -> None:
        """A well-formed JSON response is parsed into correct fields."""
        mock_client = _make_mock_client()
        mock_anthropic_cls.return_value = mock_client

        analyzer = CloudAnalyzer(api_key="test-key")
        result = analyzer.analyze_one(sample_jpeg_bytes, "photo.jpg")

        assert isinstance(result, CloudAnalysisResult)
        assert result.category == "landscape"
        assert result.subcategory == "mountain"
        assert result.subject == "snow peak"
        assert result.mood == "serene"
        assert result.tags == ["mountain", "snow", "peak", "nature", "winter"]
        assert result.quality_note is None
        assert result.image_path == "photo.jpg"

    @patch("photoagent.cloud.analyzer.anthropic.Anthropic")
    def test_analyze_extracts_tokens(
        self, mock_anthropic_cls: MagicMock, sample_jpeg_bytes: bytes
    ) -> None:
        """Token counts from API usage are captured in the result."""
        response = _make_mock_response(input_tokens=100, output_tokens=50)
        mock_client = _make_mock_client(response)
        mock_anthropic_cls.return_value = mock_client

        analyzer = CloudAnalyzer(api_key="test-key")
        result = analyzer.analyze_one(sample_jpeg_bytes, "photo.jpg")

        assert result.input_tokens == 100
        assert result.output_tokens == 50

    @patch("photoagent.cloud.analyzer.anthropic.Anthropic")
    def test_analyze_sends_base64_image(
        self, mock_anthropic_cls: MagicMock, sample_jpeg_bytes: bytes
    ) -> None:
        """The API receives a base64-encoded image with correct media type."""
        mock_client = _make_mock_client()
        mock_anthropic_cls.return_value = mock_client

        analyzer = CloudAnalyzer(api_key="test-key")
        analyzer.analyze_one(sample_jpeg_bytes, "photo.jpg")

        create_call = mock_client.messages.create
        assert create_call.called, "messages.create was not called"

        # Extract the call arguments
        call_kwargs = create_call.call_args
        messages = call_kwargs.kwargs.get("messages") or call_kwargs[1].get("messages")
        if messages is None:
            # Try positional args
            messages = call_kwargs.args[0] if call_kwargs.args else None

        # Find the image content block in the messages
        found_image = False
        expected_b64 = base64.standard_b64encode(sample_jpeg_bytes).decode("utf-8")
        for msg in messages:
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "image":
                        source = block.get("source", {})
                        assert source.get("media_type") == "image/jpeg"
                        assert source.get("data") == expected_b64
                        found_image = True

        assert found_image, "No image block found in API call"

    @patch("photoagent.cloud.analyzer.anthropic.Anthropic")
    def test_analyze_sends_correct_prompt(
        self, mock_anthropic_cls: MagicMock, sample_jpeg_bytes: bytes
    ) -> None:
        """System prompt mentions 'photo analysis engine'; user message has filename."""
        mock_client = _make_mock_client()
        mock_anthropic_cls.return_value = mock_client

        analyzer = CloudAnalyzer(api_key="test-key")
        analyzer.analyze_one(sample_jpeg_bytes, "sunset_beach.jpg")

        call_kwargs = mock_client.messages.create.call_args
        kwargs = call_kwargs.kwargs if call_kwargs.kwargs else call_kwargs[1]

        # Check system prompt
        system = kwargs.get("system", "")
        assert "photo analysis engine" in system.lower(), (
            f"System prompt should contain 'photo analysis engine', got: {system!r}"
        )

        # Check that filename appears in user message
        messages = kwargs.get("messages", [])
        user_text = ""
        for msg in messages:
            if msg.get("role") == "user":
                content = msg.get("content", [])
                if isinstance(content, str):
                    user_text += content
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            user_text += block.get("text", "")

        assert "sunset_beach.jpg" in user_text, (
            f"User message should contain filename 'sunset_beach.jpg'"
        )

    @patch("photoagent.cloud.analyzer.anthropic.Anthropic")
    def test_analyze_markdown_fences(
        self, mock_anthropic_cls: MagicMock, sample_jpeg_bytes: bytes
    ) -> None:
        """JSON wrapped in ```json ... ``` markdown fences is still parsed."""
        fenced = f"```json\n{_VALID_JSON_RESPONSE}\n```"
        response = _make_mock_response(text=fenced)
        mock_client = _make_mock_client(response)
        mock_anthropic_cls.return_value = mock_client

        analyzer = CloudAnalyzer(api_key="test-key")
        result = analyzer.analyze_one(sample_jpeg_bytes, "photo.jpg")

        assert result.category == "landscape"
        assert result.subject == "snow peak"

    @patch("photoagent.cloud.analyzer.anthropic.Anthropic")
    def test_analyze_invalid_json(
        self, mock_anthropic_cls: MagicMock, sample_jpeg_bytes: bytes
    ) -> None:
        """Non-JSON response produces category='parse_error'."""
        response = _make_mock_response(text="this is not json at all")
        mock_client = _make_mock_client(response)
        mock_anthropic_cls.return_value = mock_client

        analyzer = CloudAnalyzer(api_key="test-key")
        result = analyzer.analyze_one(sample_jpeg_bytes, "photo.jpg")

        assert result.category == "parse_error"

    @patch("photoagent.cloud.analyzer.anthropic.Anthropic")
    def test_analyze_api_error(
        self, mock_anthropic_cls: MagicMock, sample_jpeg_bytes: bytes
    ) -> None:
        """An API exception results in category='error' with message in subject."""
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = RuntimeError("connection timeout")
        mock_anthropic_cls.return_value = mock_client

        analyzer = CloudAnalyzer(api_key="test-key")
        result = analyzer.analyze_one(sample_jpeg_bytes, "photo.jpg")

        assert result.category == "error"
        assert "connection timeout" in result.subject

    @patch("photoagent.cloud.analyzer.anthropic.Anthropic")
    def test_analyze_model_parameter(
        self, mock_anthropic_cls: MagicMock, sample_jpeg_bytes: bytes
    ) -> None:
        """Custom model string is forwarded to the API call."""
        mock_client = _make_mock_client()
        mock_anthropic_cls.return_value = mock_client

        custom_model = "claude-sonnet-4-20250514"
        analyzer = CloudAnalyzer(api_key="test-key", model=custom_model)
        analyzer.analyze_one(sample_jpeg_bytes, "photo.jpg")

        call_kwargs = mock_client.messages.create.call_args
        kwargs = call_kwargs.kwargs if call_kwargs.kwargs else call_kwargs[1]
        assert kwargs.get("model") == custom_model

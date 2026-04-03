"""Tests for cloud CLI commands (cloud-analyze, cloud-search).

Mocks all external APIs. No network access required.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from photoagent.cloud.models import CloudAnalysisResult
from photoagent.cloud.store import ensure_table, get_analyzed_paths, save_result


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_analysis_result(
    image_path: str,
    category: str = "landscape",
    input_tokens: int = 150,
    output_tokens: int = 60,
) -> CloudAnalysisResult:
    """Build a CloudAnalysisResult with sensible defaults."""
    return CloudAnalysisResult(
        image_path=image_path,
        category=category,
        subcategory="generic",
        subject="test subject",
        mood="neutral",
        tags=["test"],
        quality_note=None,
        model="claude-haiku-4-5-20251001",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        thumb_byte_size=4096,
        analyzed_at="2026-01-01T00:00:00+00:00",
    )


def _create_test_jpeg(path: Path) -> None:
    """Create a minimal JPEG at *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    img = Image.new("RGB", (100, 100), color="blue")
    img.save(str(path), "JPEG", quality=60)


def _setup_catalog_with_images(
    base_dir: Path, n: int = 5
) -> tuple[Path, list[str]]:
    """Create a catalog directory with *n* scanned image records.

    Returns (base_dir, list_of_image_paths).
    """
    from photoagent.database import CatalogDB

    image_paths: list[str] = []
    for i in range(n):
        img_path = base_dir / f"img_{i:03d}.jpg"
        _create_test_jpeg(img_path)
        image_paths.append(str(img_path))

    db = CatalogDB(base_dir)
    for ip in image_paths:
        p = Path(ip)
        db.insert_image(
            {
                "file_path": ip,
                "filename": p.name,
                "extension": p.suffix,
                "file_size": p.stat().st_size,
            }
        )
    db.close()
    return base_dir, image_paths


def _mock_anthropic_response(
    category: str = "landscape",
    subject: str = "test",
) -> MagicMock:
    """Build a mock Anthropic messages.create response."""
    response_json = json.dumps(
        {
            "category": category,
            "subcategory": "generic",
            "subject": subject,
            "mood": "neutral",
            "tags": ["test"],
            "quality_note": None,
        }
    )
    content_block = MagicMock()
    content_block.text = response_json

    usage = MagicMock()
    usage.input_tokens = 150
    usage.output_tokens = 60

    response = MagicMock()
    response.content = [content_block]
    response.usage = usage
    return response


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def cli_runner():
    """Return a typer CliRunner."""
    from typer.testing import CliRunner

    return CliRunner()


@pytest.fixture
def app():
    """Return the photoagent CLI app."""
    from photoagent.cli import app as _app

    return _app


@pytest.fixture(autouse=True)
def fake_api_key(monkeypatch):
    """Set a fake ANTHROPIC_API_KEY so the CLI does not bail early."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-fake-key-for-testing")


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


class TestCloudCLIHelp:
    """Verify that help text is shown for cloud commands."""

    def test_cloud_analyze_help(self, cli_runner, app) -> None:
        """cloud-analyze --help shows available options."""
        result = cli_runner.invoke(app, ["cloud-analyze", "--help"])
        assert result.exit_code == 0
        assert "cloud" in result.output.lower() or "analyze" in result.output.lower()

    def test_cloud_search_help(self, cli_runner, app) -> None:
        """cloud-search --help shows available options."""
        result = cli_runner.invoke(app, ["cloud-search", "--help"])
        assert result.exit_code == 0
        assert "search" in result.output.lower() or "query" in result.output.lower()


class TestCloudAnalyzeCLI:
    """Integration tests for the cloud-analyze command."""

    @patch("photoagent.cloud.analyzer.anthropic.Anthropic")
    def test_dry_run_no_api_call(
        self, mock_anthropic_cls: MagicMock, tmp_path: Path, cli_runner, app
    ) -> None:
        """--dry-run should NOT call the API and should show a cost estimate."""
        mock_client = MagicMock()
        mock_anthropic_cls.return_value = mock_client

        base_dir, image_paths = _setup_catalog_with_images(tmp_path, n=5)

        result = cli_runner.invoke(
            app,
            ["cloud-analyze", str(base_dir), "--dry-run"],
        )

        # API should not have been called
        assert not mock_client.messages.create.called, (
            "API should not be called during --dry-run"
        )

        # Output should mention the count or cost
        output_lower = result.output.lower()
        assert (
            "dry" in output_lower
            or "cost" in output_lower
            or "estimate" in output_lower
            or "would" in output_lower
            or "5" in result.output
        ), f"Expected dry-run/cost info in output, got: {result.output}"

    @patch("photoagent.cloud.analyzer.anthropic.Anthropic")
    def test_limit_restricts_count(
        self, mock_anthropic_cls: MagicMock, tmp_path: Path, cli_runner, app
    ) -> None:
        """--limit=3 should analyze at most 3 images out of 10."""
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_anthropic_response()
        mock_anthropic_cls.return_value = mock_client

        base_dir, image_paths = _setup_catalog_with_images(tmp_path, n=10)

        result = cli_runner.invoke(
            app,
            ["cloud-analyze", str(base_dir), "--limit", "3"],
        )

        call_count = mock_client.messages.create.call_count
        assert call_count <= 3, (
            f"Expected at most 3 API calls with --limit=3, got {call_count}"
        )

    @patch("photoagent.cloud.analyzer.anthropic.Anthropic")
    def test_reanalyze_reprocesses(
        self, mock_anthropic_cls: MagicMock, tmp_path: Path, cli_runner, app
    ) -> None:
        """--reanalyze should reprocess already-analyzed images."""
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _mock_anthropic_response()
        mock_anthropic_cls.return_value = mock_client

        base_dir, image_paths = _setup_catalog_with_images(tmp_path, n=3)

        # First run: analyze all 3
        result1 = cli_runner.invoke(app, ["cloud-analyze", str(base_dir)])
        first_count = mock_client.messages.create.call_count
        assert first_count == 3, (
            f"Expected 3 calls on first run, got {first_count}. "
            f"Output: {result1.output}"
        )

        # Second run without --reanalyze: should skip already-analyzed
        mock_client.messages.create.reset_mock()
        result2 = cli_runner.invoke(app, ["cloud-analyze", str(base_dir)])
        skip_count = mock_client.messages.create.call_count
        assert skip_count == 0, (
            f"Expected 0 calls without --reanalyze, got {skip_count}. "
            f"Output: {result2.output}"
        )

        # Third run with --reanalyze: should reprocess all 3
        mock_client.messages.create.reset_mock()
        result3 = cli_runner.invoke(
            app, ["cloud-analyze", str(base_dir), "--reanalyze"]
        )
        reanalyze_count = mock_client.messages.create.call_count
        assert reanalyze_count == 3, (
            f"Expected 3 calls with --reanalyze, got {reanalyze_count}. "
            f"Output: {result3.output}"
        )

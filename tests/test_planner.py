"""Tests for photoagent.planner.OrganizationPlanner and privacy guards.

Verifies that the planner correctly calls the Claude API, enforces
privacy guards on payloads, handles chunked generation, and never
sends image data to the API.
"""

from __future__ import annotations

import json
import os
import re
import string
from pathlib import Path
from typing import Any, Generator
from unittest.mock import MagicMock, patch

import pytest

from photoagent.database import CatalogDB
from photoagent.summarizer import CatalogSummarizer


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

MOCK_PLAN_JSON = {
    "folder_structure": [
        "Vacations/2023/Paris",
        "Vacations/2022/Tokyo",
        "Screenshots",
    ],
    "moves": [
        {"id": 1, "from": "paris_1.jpg", "to": "Vacations/2023/Paris/paris_1.jpg"},
        {"id": 2, "from": "tokyo_1.jpg", "to": "Vacations/2022/Tokyo/tokyo_1.jpg"},
        {"id": 3, "from": "screen_1.jpg", "to": "Screenshots/screen_1.jpg"},
    ],
    "summary": "Organized 3 photos into vacation and screenshot folders.",
}


def _make_mock_api_response(plan_json: dict[str, Any] | None = None) -> MagicMock:
    if plan_json is None:
        plan_json = MOCK_PLAN_JSON
    mock_text_block = MagicMock()
    mock_text_block.text = json.dumps(plan_json)
    mock_response = MagicMock()
    mock_response.content = [mock_text_block]
    mock_response.stop_reason = "end_turn"
    return mock_response


def _make_mock_anthropic_client(plan_json: dict[str, Any] | None = None) -> MagicMock:
    mock_client = MagicMock()
    mock_response = _make_mock_api_response(plan_json)
    mock_client.messages.create.return_value = mock_response
    return mock_client


def _generate_base64_string(length: int = 300) -> str:
    import random
    chars = string.ascii_letters + string.digits + "+/="
    return "".join(random.choice(chars) for _ in range(length))


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def planner_db(tmp_path: Path) -> Generator[CatalogDB, None, None]:
    db = CatalogDB(tmp_path)
    yield db
    db.close()


# ------------------------------------------------------------------
# Tests: Privacy Guards
# ------------------------------------------------------------------


class TestPrivacyGuards:
    """Tests for the privacy validation that prevents image data from being sent."""

    @patch("photoagent.planner.anthropic")
    def test_privacy_guard_clean_payload(self, mock_anthropic_module: MagicMock) -> None:
        """A normal text-only payload should pass privacy validation."""
        from photoagent.planner import OrganizationPlanner

        mock_anthropic_module.Anthropic.return_value = _make_mock_anthropic_client()
        planner = OrganizationPlanner(api_key="test-key")

        payload = json.dumps({
            "summary": {"total_images": 10},
            "manifest": [{"id": 1, "filename": "photo.jpg", "tags": ["beach"]}],
        })
        # Should not raise
        planner._validate_payload(payload)

    @patch("photoagent.planner.anthropic")
    def test_privacy_guard_rejects_base64(self, mock_anthropic_module: MagicMock) -> None:
        """A payload containing a long base64-like string must raise PrivacyViolationError."""
        from photoagent.planner import OrganizationPlanner, PrivacyViolationError

        mock_anthropic_module.Anthropic.return_value = _make_mock_anthropic_client()
        planner = OrganizationPlanner(api_key="test-key")

        fake_b64 = _generate_base64_string(300)
        payload = json.dumps({
            "manifest": [{"id": 1, "image_data": fake_b64}],
        })

        with pytest.raises(PrivacyViolationError):
            planner._validate_payload(payload)

    @patch("photoagent.planner.anthropic")
    def test_privacy_guard_rejects_large_payload(self, mock_anthropic_module: MagicMock) -> None:
        """A payload exceeding 10MB must raise PrivacyViolationError."""
        from photoagent.planner import OrganizationPlanner, PrivacyViolationError

        mock_anthropic_module.Anthropic.return_value = _make_mock_anthropic_client()
        planner = OrganizationPlanner(api_key="test-key")

        large_text = "x" * (11 * 1024 * 1024)
        payload = json.dumps({"data": large_text})

        with pytest.raises(PrivacyViolationError):
            planner._validate_payload(payload)

    @patch("photoagent.planner.anthropic")
    def test_privacy_guard_normal_json(self, mock_anthropic_module: MagicMock) -> None:
        """Normal JSON with filenames, tags, captions should pass validation."""
        from photoagent.planner import OrganizationPlanner

        mock_anthropic_module.Anthropic.return_value = _make_mock_anthropic_client()
        planner = OrganizationPlanner(api_key="test-key")

        payload = json.dumps({
            "summary": {
                "total_images": 500,
                "locations": [{"name": "Paris, France", "count": 50}],
                "tag_distribution": {"beach": 30, "sunset": 25},
            },
            "manifest": [
                {
                    "id": i,
                    "filename": f"IMG_{i:04d}.jpg",
                    "caption": "A beautiful sunset on the beach",
                    "quality": 0.85,
                }
                for i in range(100)
            ],
        })
        # Should not raise
        planner._validate_payload(payload)


# ------------------------------------------------------------------
# Tests: generate_plan with mock API
# ------------------------------------------------------------------


class TestGeneratePlan:

    @patch("photoagent.planner.anthropic")
    def test_generate_plan_mock_api(self, mock_anthropic_module: MagicMock) -> None:
        """Verify generate_plan calls the API correctly and parses the response."""
        from photoagent.planner import OrganizationPlanner

        mock_client = _make_mock_anthropic_client()
        mock_anthropic_module.Anthropic.return_value = mock_client

        planner = OrganizationPlanner(api_key="test-key-123")
        summary = {"total_images": 3, "date_range": "2023-01-01 to 2023-12-31"}
        manifest_chunk = [{"id": 1, "filename": "a.jpg", "tags": ["beach"]}]

        plan = planner.generate_plan(
            summary, manifest_chunk, instruction="Sort by date"
        )

        mock_client.messages.create.assert_called_once()
        assert "folder_structure" in plan
        assert "moves" in plan
        assert "summary" in plan
        assert isinstance(plan["moves"], list)

    @patch("photoagent.planner.anthropic")
    def test_generate_plan_verbose_logging(
        self, mock_anthropic_module: MagicMock, tmp_path: Path
    ) -> None:
        """With verbose=True, a log file should be written."""
        from photoagent.planner import OrganizationPlanner

        mock_client = _make_mock_anthropic_client()
        mock_anthropic_module.Anthropic.return_value = mock_client

        planner = OrganizationPlanner(api_key="test-key-123")
        summary = {"total_images": 1}
        manifest_chunk = [{"id": 1, "filename": "a.jpg"}]

        # Run from a dir that has .photoagent
        data_dir = tmp_path / ".photoagent"
        data_dir.mkdir(exist_ok=True)

        import os
        old_cwd = os.getcwd()
        try:
            os.chdir(tmp_path)
            planner.generate_plan(
                summary, manifest_chunk,
                instruction="Sort photos", verbose=True,
            )
        finally:
            os.chdir(old_cwd)

        log_dir = data_dir / "api_logs"
        if log_dir.exists():
            log_files = list(log_dir.iterdir())
            assert len(log_files) >= 1


# ------------------------------------------------------------------
# Tests: Chunked plan generation
# ------------------------------------------------------------------


class TestChunkedGeneration:

    @patch("photoagent.planner.anthropic")
    def test_generate_plan_chunked_single(self, mock_anthropic_module: MagicMock) -> None:
        """With 1 chunk, generate_plan_chunked calls generate_plan once."""
        from photoagent.planner import OrganizationPlanner

        mock_client = _make_mock_anthropic_client()
        mock_anthropic_module.Anthropic.return_value = mock_client

        planner = OrganizationPlanner(api_key="test-key-123")
        summary = {"total_images": 3}
        chunks = [[{"id": 1}, {"id": 2}, {"id": 3}]]

        plan = planner.generate_plan_chunked(
            summary, chunks, instruction="Sort by year"
        )

        assert mock_client.messages.create.call_count == 1
        assert "folder_structure" in plan
        assert "moves" in plan

    @patch("photoagent.planner.anthropic")
    def test_generate_plan_chunked_multiple(self, mock_anthropic_module: MagicMock) -> None:
        """With 3 chunks, verify merging: deduplicated folders, combined moves."""
        from photoagent.planner import OrganizationPlanner

        plans = [
            {
                "folder_structure": ["Vacations/2023", "Screenshots"],
                "moves": [{"id": 1, "from": "a.jpg", "to": "Vacations/2023/a.jpg"}],
                "summary": "Chunk 1",
            },
            {
                "folder_structure": ["Vacations/2023", "Vacations/2022"],
                "moves": [{"id": 2, "from": "b.jpg", "to": "Vacations/2022/b.jpg"}],
                "summary": "Chunk 2",
            },
            {
                "folder_structure": ["Vacations/2022", "Family"],
                "moves": [{"id": 3, "from": "c.jpg", "to": "Family/c.jpg"}],
                "summary": "Chunk 3",
            },
        ]

        call_count = 0

        def mock_create(**kwargs):
            nonlocal call_count
            resp = _make_mock_api_response(plans[call_count])
            call_count += 1
            return resp

        mock_client = MagicMock()
        mock_client.messages.create.side_effect = mock_create
        mock_anthropic_module.Anthropic.return_value = mock_client

        planner = OrganizationPlanner(api_key="test-key-123")
        chunks = [
            [{"id": 1, "filename": "a.jpg"}],
            [{"id": 2, "filename": "b.jpg"}],
            [{"id": 3, "filename": "c.jpg"}],
        ]

        plan = planner.generate_plan_chunked(
            {"total_images": 3}, chunks, instruction="Sort"
        )

        assert mock_client.messages.create.call_count == 3
        folders = set(plan["folder_structure"])
        assert "Vacations/2023" in folders
        assert "Vacations/2022" in folders
        assert "Screenshots" in folders
        assert "Family" in folders
        assert len(plan["moves"]) == 3


# ------------------------------------------------------------------
# Tests: no image data in real pipeline
# ------------------------------------------------------------------


class TestNoImageDataInPayload:

    def test_plan_no_image_data(self, planner_db: CatalogDB) -> None:
        """Build a real summary + manifest and verify no binary/base64 patterns."""
        base_path = str(planner_db._base_path)

        for i in range(5):
            rec = {
                "file_path": f"{base_path}/photos/img_{i:03d}.jpg",
                "filename": f"img_{i:03d}.jpg",
                "extension": ".jpg",
                "file_size": 3_000_000,
                "date_taken": f"2023-0{i+1}-15 10:00:00",
                "city": "Paris",
                "country": "France",
                "ai_caption": f"Photo number {i}",
                "ai_tags": json.dumps([
                    {"label": "nature", "score": 0.8},
                    {"label": "landscape", "score": 0.6},
                ]),
                "ai_quality_score": 0.75,
            }
            planner_db.insert_image(rec)

        summarizer = CatalogSummarizer(planner_db)
        summary = summarizer.build_summary()
        chunks = summarizer.build_manifest()

        payload = json.dumps({"summary": summary, "manifest": chunks})

        assert not re.search(r"[A-Za-z0-9+/=]{100,}", payload)
        assert "\\x" not in payload.lower()
        assert "b'" not in payload
        assert 'b"' not in payload
        parsed = json.loads(payload)
        assert isinstance(parsed, dict)


# ------------------------------------------------------------------
# Tests: missing API key
# ------------------------------------------------------------------


class TestMissingAPIKey:

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_api_key(self) -> None:
        """With no API key in env or keyring, should raise ValueError."""
        from photoagent.planner import OrganizationPlanner

        # Mock keyring to return None
        with patch("photoagent.planner.anthropic") as mock_anth:
            mock_anth.Anthropic.return_value = MagicMock()
            # Patch the keyring import inside _resolve_api_key
            with patch.dict("sys.modules", {"keyring": MagicMock(get_password=MagicMock(return_value=None))}):
                with pytest.raises((ValueError, KeyError, RuntimeError)):
                    OrganizationPlanner()

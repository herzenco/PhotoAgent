"""Tests for photoagent.plan_display module.

Verifies the rich terminal UI for displaying organization plans,
folder trees, export functionality, and user approval prompts.
"""

from __future__ import annotations

import json
import tempfile
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import patch, MagicMock

import pytest
from rich.console import Console

from photoagent.plan_display import (
    display_plan,
    display_folder_tree,
    export_plan,
    get_user_approval,
)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_plan(
    num_moves: int = 5,
    summary: str = "Organized photos into folders by date and location.",
    folder_structure: list[str] | None = None,
) -> dict[str, Any]:
    """Build a valid plan dict with the given number of moves."""
    if folder_structure is None:
        folder_structure = [
            "Vacations/2023/Paris",
            "Vacations/2022/Tokyo",
            "Screenshots",
            "Family/Birthdays",
        ]

    moves = []
    for i in range(num_moves):
        folder = folder_structure[i % len(folder_structure)]
        moves.append({
            "id": i + 1,
            "from": f"unsorted/IMG_{i:04d}.jpg",
            "to": f"{folder}/IMG_{i:04d}.jpg",
        })

    return {
        "folder_structure": folder_structure,
        "moves": moves,
        "summary": summary,
    }


def _capture_display_output(plan: dict[str, Any], **kwargs: Any) -> str:
    """Capture display_plan output by temporarily replacing the module console."""
    import photoagent.plan_display as pd

    buf = StringIO()
    original_console = pd.console
    pd.console = Console(file=buf, force_terminal=True, width=120)
    try:
        display_plan(plan, **kwargs)
    finally:
        pd.console = original_console

    return buf.getvalue()


def _capture_tree_output(
    folder_structure: list[str], move_counts: dict[str, int]
) -> str:
    """Capture display_folder_tree output."""
    import photoagent.plan_display as pd

    buf = StringIO()
    original_console = pd.console
    pd.console = Console(file=buf, force_terminal=True, width=120)
    try:
        display_folder_tree(folder_structure, move_counts)
    finally:
        pd.console = original_console

    return buf.getvalue()


# ------------------------------------------------------------------
# Tests: display_plan
# ------------------------------------------------------------------


class TestDisplayPlan:
    """Tests for the display_plan function."""

    def test_display_plan_runs_without_error(self) -> None:
        """Passing a valid plan should not raise any exceptions."""
        plan = _make_plan(num_moves=5)
        # Should not raise
        output = _capture_display_output(plan)
        assert len(output) > 0

    def test_display_plan_shows_summary(self) -> None:
        """The plan's summary text must appear in the rendered output."""
        summary_text = "Organized 42 vacation photos into date-based folders."
        plan = _make_plan(num_moves=3, summary=summary_text)

        output = _capture_display_output(plan)
        assert "42 vacation photos" in output or "Organized" in output

    def test_display_plan_shows_move_count(self) -> None:
        """The total move count should appear in the output."""
        plan = _make_plan(num_moves=25)
        output = _capture_display_output(plan)

        # The stats panel should show "25" as the total files to move
        assert "25" in output

    def test_display_plan_max_preview(self) -> None:
        """With 100 moves and max_preview=10, output should show truncation."""
        plan = _make_plan(num_moves=100)
        output = _capture_display_output(plan, max_preview=10)

        # Should indicate there are 90 more moves
        assert "90" in output
        assert "more" in output.lower()

    def test_display_plan_empty_moves(self) -> None:
        """A plan with zero moves should render without error."""
        plan = _make_plan(num_moves=0)
        output = _capture_display_output(plan)
        assert len(output) > 0


# ------------------------------------------------------------------
# Tests: display_folder_tree
# ------------------------------------------------------------------


class TestDisplayFolderTree:
    """Tests for the display_folder_tree function."""

    def test_display_folder_tree(self) -> None:
        """Folder tree renders without error and includes folder names."""
        folders = [
            "Vacations/2023/Paris",
            "Vacations/2023/London",
            "Vacations/2022/Tokyo",
            "Family/Birthdays",
            "Screenshots",
        ]
        move_counts = {
            "Vacations/2023/Paris": 15,
            "Vacations/2023/London": 8,
            "Vacations/2022/Tokyo": 12,
            "Family/Birthdays": 5,
            "Screenshots": 20,
        }

        output = _capture_tree_output(folders, move_counts)

        # Should contain folder names
        assert "Paris" in output
        assert "London" in output
        assert "Tokyo" in output
        assert "Birthdays" in output
        assert "Screenshots" in output

        # Should contain at least some file counts
        assert "15" in output or "file" in output.lower()

    def test_display_folder_tree_empty(self) -> None:
        """An empty folder structure should render without error."""
        output = _capture_tree_output([], {})
        assert len(output) > 0


# ------------------------------------------------------------------
# Tests: export_plan
# ------------------------------------------------------------------


class TestExportPlan:
    """Tests for exporting a plan to a JSON file."""

    def test_export_plan(self, tmp_path: Path) -> None:
        """Export plan to a file, read it back, verify JSON matches."""
        plan = _make_plan(num_moves=10)
        output_path = tmp_path / "exported_plan.json"

        export_plan(plan, output_path)

        assert output_path.exists()

        with open(output_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)

        assert loaded["folder_structure"] == plan["folder_structure"]
        assert loaded["moves"] == plan["moves"]
        assert loaded["summary"] == plan["summary"]

    def test_export_plan_creates_parent_dirs(self, tmp_path: Path) -> None:
        """Export should create parent directories if they do not exist."""
        plan = _make_plan(num_moves=2)
        output_path = tmp_path / "nested" / "deep" / "plan.json"

        export_plan(plan, output_path)

        assert output_path.exists()
        loaded = json.loads(output_path.read_text())
        assert loaded["summary"] == plan["summary"]


# ------------------------------------------------------------------
# Tests: get_user_approval
# ------------------------------------------------------------------


class TestGetUserApproval:
    """Tests for the interactive approval prompt."""

    @pytest.mark.parametrize(
        "input_choice, expected_result",
        [
            ("a", "approve"),
            ("r", "reject"),
            ("m", "modify"),
            ("e", "export"),
        ],
    )
    def test_get_user_approval_choices(
        self, input_choice: str, expected_result: str
    ) -> None:
        """Each input choice maps to the correct return value."""
        with patch("photoagent.plan_display.Prompt.ask", return_value=input_choice):
            result = get_user_approval()
            assert result == expected_result

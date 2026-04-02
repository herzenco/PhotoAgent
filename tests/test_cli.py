"""Tests for the photoagent CLI (typer app).

Uses typer.testing.CliRunner to invoke commands and verify output
without spawning a subprocess.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from photoagent.cli import app
from photoagent.database import CatalogDB

runner = CliRunner()


# ------------------------------------------------------------------
# Command registration
# ------------------------------------------------------------------


class TestCommandRegistration:
    """Verify that expected commands are registered on the Typer app."""

    EXPECTED_COMMANDS = [
        "scan",
        "status",
        "analyze",
        "organize",
        "search",
        "export-catalog",
        "config",
        "undo",
        "history",
        "rename-person",
        "list-people",
    ]

    def test_all_commands_registered(self) -> None:
        """Every expected command name should appear in the app's registered commands."""
        # Typer stores commands in app.registered_commands or via click info
        # Use --help output as a reliable source of truth.
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        for cmd in self.EXPECTED_COMMANDS:
            assert cmd in result.output, (
                f"Command '{cmd}' not found in --help output"
            )

    @pytest.mark.parametrize(
        "command",
        ["scan", "status", "analyze", "organize", "search"],
    )
    def test_command_help(self, command: str) -> None:
        """Each command should respond to --help without error."""
        result = runner.invoke(app, [command, "--help"])
        assert result.exit_code == 0
        assert "Usage" in result.output or "usage" in result.output.lower()


# ------------------------------------------------------------------
# scan command
# ------------------------------------------------------------------


class TestScanCommand:
    """Tests for the 'scan' CLI command."""

    def test_scan_command_exists(self) -> None:
        """'scan --help' should work without error."""
        result = runner.invoke(app, ["scan", "--help"])
        assert result.exit_code == 0
        assert "scan" in result.output.lower()

    def test_scan_help_shows_options(self) -> None:
        """Scan help should mention --recursive and --extensions options."""
        result = runner.invoke(app, ["scan", "--help"])
        assert "--recursive" in result.output or "--no-recursive" in result.output
        assert "--extensions" in result.output or "-e" in result.output


# ------------------------------------------------------------------
# status command
# ------------------------------------------------------------------


class TestStatusCommand:
    """Tests for the 'status' CLI command."""

    def test_status_command_exists(self) -> None:
        """'status --help' should work without error."""
        result = runner.invoke(app, ["status", "--help"])
        assert result.exit_code == 0

    def test_status_empty_catalog(self, tmp_path: Path) -> None:
        """Running status on an empty catalog should display zero counts."""
        # Create the .photoagent directory so status doesn't error out
        db = CatalogDB(tmp_path)
        db.close()

        result = runner.invoke(app, ["status", str(tmp_path)])
        assert result.exit_code == 0
        # Output should contain "0" for total images
        assert "0" in result.output

    def test_status_with_data(self, tmp_path: Path) -> None:
        """Insert test data into the catalog, then run status and verify output."""
        db = CatalogDB(tmp_path)
        db.insert_image({
            "file_path": "/photos/a.jpg",
            "filename": "a.jpg",
            "extension": ".jpg",
            "file_size": 5_000_000,
            "camera_model": "EOS R5",
            "date_taken": "2023-06-15 14:30:00",
            "city": "Paris",
            "country": "France",
        })
        db.insert_image({
            "file_path": "/photos/b.jpg",
            "filename": "b.jpg",
            "extension": ".jpg",
            "file_size": 3_000_000,
            "camera_model": "EOS R5",
            "date_taken": "2023-08-01 10:00:00",
            "is_screenshot": True,
        })
        db.close()

        result = runner.invoke(app, ["status", str(tmp_path)])
        assert result.exit_code == 0
        # Should mention total count
        assert "2" in result.output
        # Should mention camera model
        assert "EOS R5" in result.output
        # Should mention screenshot count
        assert "1" in result.output

    def test_status_no_catalog(self, tmp_path: Path) -> None:
        """Running status when no catalog exists should show an error."""
        result = runner.invoke(app, ["status", str(tmp_path)])
        # Should exit with error code
        assert result.exit_code != 0

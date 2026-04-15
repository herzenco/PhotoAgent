"""CLI wiring for the template-based organize command.

Connects TemplateEngine to plan display and execution flow.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from rich.console import Console

from photoagent.database import CatalogDB
from photoagent.templates import TemplateEngine

_console_stdout = Console()


def run_template_organize(
    path: Path,
    template_name: str | None = None,
    yaml_path: Path | None = None,
    json_output: bool = False,
) -> None:
    """Run template-based organization.

    Parameters
    ----------
    path:
        Root directory of the photo catalog.
    template_name:
        Name of a built-in template (e.g. "by-date").
    yaml_path:
        Path to a custom YAML template file. Takes precedence
        over template_name if both are provided.
    """
    console = Console(stderr=True) if json_output else _console_stdout

    db_dir = path / ".photoagent"
    if not db_dir.exists():
        console.print(
            f"[red]No catalog found at {path}. "
            "Run 'photoagent scan' first.[/red]"
        )
        sys.exit(1)

    if not template_name and not yaml_path:
        console.print("[red]Provide a template name or YAML file path.[/red]")
        console.print(
            "[dim]Built-in templates: "
            + ", ".join(TemplateEngine.get_builtin_templates())
            + "[/dim]"
        )
        sys.exit(1)

    # Generate the plan
    with CatalogDB(path) as db:
        engine = TemplateEngine(db, path)

        try:
            if yaml_path:
                console.print(
                    f"[bold]Applying custom template: {yaml_path}[/bold]"
                )
                plan = engine.apply_custom_template(Path(yaml_path))
            else:
                console.print(
                    f"[bold]Applying template: {template_name}[/bold]"
                )
                plan = engine.apply_template(template_name)  # type: ignore[arg-type]
        except (ValueError, FileNotFoundError, ImportError) as exc:
            console.print(f"[red]Template error: {exc}[/red]")
            sys.exit(1)

    moves = plan.get("moves", [])
    if not moves:
        if json_output:
            from photoagent.cli import _json_output
            _json_output({"folder_structure": [], "moves": [], "summary": "No files to organize."})
        console.print("[dim]No files to organize with this template.[/dim]")
        return

    # JSON output (skip interactive approval) ---------------------------
    if json_output:
        from photoagent.cli import _json_output
        _json_output({
            "folder_structure": plan.get("folder_structure", []),
            "moves": plan.get("moves", []),
            "summary": plan.get("summary", ""),
        })

    # Display the plan
    from photoagent.plan_display import (
        display_plan,
        export_plan,
        get_user_approval,
    )

    display_plan(plan)

    # Approval flow
    choice = get_user_approval()

    if choice == "reject":
        console.print("[yellow]Organization cancelled.[/yellow]")
        return

    if choice == "export":
        export_path = path / ".photoagent" / "template_plan.json"
        export_plan(plan, export_path)
        return

    if choice == "modify":
        console.print(
            "[yellow]Modification not supported for templates. "
            "Edit the YAML file and re-run.[/yellow]"
        )
        return

    if choice == "approve":
        # Execute the plan
        try:
            from photoagent.execute_cli import run_execute

            run_execute(path, plan)
        except ImportError:
            console.print(
                "[yellow]Execution engine not available. "
                "Export the plan and execute manually.[/yellow]"
            )

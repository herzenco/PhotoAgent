"""CLI wiring for execute, undo, and history commands.

Connects PlanExecutor and UndoManager to Rich progress bars and tables.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from rich.table import Table

from photoagent.database import CatalogDB
from photoagent.executor import PlanExecutor
from photoagent.models import ExecutionResult
from photoagent.undo import UndoManager

console = Console()


# ------------------------------------------------------------------
# Execute
# ------------------------------------------------------------------


def run_execute(path: str | Path, plan: dict[str, Any]) -> ExecutionResult:
    """Execute an organization plan with a Rich progress bar.

    Args:
        path: The base directory (root of the photo library).
        plan: Plan dict produced by the planner/organizer.

    Returns:
        ExecutionResult from the executor.
    """
    base_path = Path(path).resolve()
    moves = plan.get("moves", [])
    total = len(moves)

    with CatalogDB(base_path) as db:
        executor = PlanExecutor(base_path, db)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("{task.completed}/{task.total}"),
            console=console,
        ) as progress:
            task = progress.add_task("Executing plan...", total=total)

            def _on_progress(current: int, total: int, desc: str) -> None:
                progress.update(task, completed=current, description=desc)

            result = executor.execute(plan, on_progress=_on_progress)

    _print_result_summary(result, action="Execution")
    return result


# ------------------------------------------------------------------
# Undo
# ------------------------------------------------------------------


def run_undo(
    path: str | Path, manifest: str | Path | None = None
) -> ExecutionResult:
    """Undo a previous execution with a Rich progress bar.

    Args:
        path: The base directory (root of the photo library).
        manifest: Path to a specific manifest JSON, or *None* for the
            most recent one.

    Returns:
        ExecutionResult from the undo manager.
    """
    base_path = Path(path).resolve()
    manifest_path = Path(manifest).resolve() if manifest else None

    with CatalogDB(base_path) as db:
        mgr = UndoManager(base_path, db)

        # Determine total from manifest for the progress bar
        actual_manifest = manifest_path or mgr.get_manifest_path()
        total = 0
        if actual_manifest and actual_manifest.exists():
            import json

            try:
                m = json.loads(actual_manifest.read_text(encoding="utf-8"))
                total = len(m.get("operations", []))
            except (json.JSONDecodeError, OSError):
                pass

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("{task.completed}/{task.total}"),
            console=console,
        ) as progress:
            task = progress.add_task("Undoing...", total=max(total, 1))

            def _on_progress(current: int, total: int, desc: str) -> None:
                progress.update(task, completed=current, description=desc)

            result = mgr.undo(
                manifest_path=manifest_path, on_progress=_on_progress
            )

    _print_result_summary(result, action="Undo")
    return result


# ------------------------------------------------------------------
# History
# ------------------------------------------------------------------


def run_history(path: str | Path) -> list[dict[str, Any]]:
    """Display operation history as a Rich table.

    Args:
        path: The base directory (root of the photo library).

    Returns:
        The list of history dicts.
    """
    base_path = Path(path).resolve()

    with CatalogDB(base_path) as db:
        mgr = UndoManager(base_path, db)
        history = mgr.get_history()

    if not history:
        console.print("[dim]No operations recorded yet.[/dim]")
        return history

    table = Table(title="Operation History", show_lines=True)
    table.add_column("ID", justify="right", style="cyan", no_wrap=True)
    table.add_column("Timestamp", style="dim")
    table.add_column("Instruction", max_width=60)
    table.add_column("Status", justify="center")
    table.add_column("Files", justify="right")

    status_styles = {
        "completed": "[green]completed[/green]",
        "executing": "[yellow]executing[/yellow]",
        "undone": "[blue]undone[/blue]",
        "pending": "[dim]pending[/dim]",
    }

    for entry in history:
        status_text = status_styles.get(
            entry["status"], f"[red]{entry['status']}[/red]"
        )
        instruction = entry["instruction"]
        if len(instruction) > 80:
            instruction = instruction[:77] + "..."
        table.add_row(
            str(entry["id"]),
            str(entry["timestamp"] or ""),
            instruction,
            status_text,
            str(entry["file_count"]),
        )

    console.print(table)
    return history


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _print_result_summary(result: ExecutionResult, action: str) -> None:
    """Print a coloured summary of an ExecutionResult."""
    console.print()
    if result.successful == result.total_planned and not result.errors:
        console.print(
            f"[bold green]{action} complete:[/bold green] "
            f"{result.successful}/{result.total_planned} files processed "
            f"in {result.duration:.1f}s"
        )
    else:
        console.print(
            f"[bold yellow]{action} finished with issues:[/bold yellow] "
            f"{result.successful} succeeded, {result.skipped} skipped, "
            f"{len(result.errors)} errors in {result.duration:.1f}s"
        )

    if result.conflicts_resolved:
        console.print(
            f"  [dim]{result.conflicts_resolved} filename conflicts "
            f"auto-resolved[/dim]"
        )

    if result.errors:
        console.print(f"\n[bold red]Errors ({len(result.errors)}):[/bold red]")
        for err in result.errors[:20]:
            console.print(f"  [red]- {err}[/red]")
        if len(result.errors) > 20:
            console.print(
                f"  [dim]... and {len(result.errors) - 20} more[/dim]"
            )

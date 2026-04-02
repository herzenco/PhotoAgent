"""CLI wiring for the 'organize' command.

Connects the catalog summarizer, Claude planner, and plan display
components into a single workflow.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from photoagent.database import CatalogDB
from photoagent.planner import OrganizationPlanner, PrivacyViolationError
from photoagent.summarizer import CatalogSummarizer

console = Console()


def run_organize(
    path: Path,
    instruction: str | None = None,
    dry_run: bool = True,
    max_preview: int = 20,
    verbose: bool = False,
) -> None:
    """Run the full organize workflow.

    Parameters
    ----------
    path:
        Root directory of the photo catalog.
    instruction:
        Natural-language organization instruction from the user.
    dry_run:
        If True (default), display the plan but do not execute moves.
    max_preview:
        Maximum number of moves to show in the preview.
    verbose:
        If True, log full API request/response payloads.
    """
    # Validate catalog exists ------------------------------------------
    db_dir = path / ".photoagent"
    if not db_dir.exists():
        console.print(
            f"[red]No catalog found at {path}. "
            "Run 'photoagent scan' first.[/red]"
        )
        sys.exit(1)

    if not instruction:
        console.print(
            "[red]Please provide an organization instruction with "
            "--instruction / -i[/red]"
        )
        sys.exit(1)

    # Build summary & manifest ----------------------------------------
    console.print("[bold]Building catalog summary...[/bold]")
    with CatalogDB(path) as db:
        summarizer = CatalogSummarizer(db)
        summary = summarizer.build_summary()
        manifest_chunks = summarizer.build_manifest()

    _print_summary(summary)

    # Generate plan ----------------------------------------------------
    console.print("\n[bold]Generating organization plan via Claude...[/bold]")
    try:
        planner = OrganizationPlanner()
    except ValueError as exc:
        console.print(f"[red]API key error: {exc}[/red]")
        sys.exit(1)

    try:
        plan = planner.generate_plan_chunked(
            summary=summary,
            manifest_chunks=manifest_chunks,
            instruction=instruction,
            verbose=verbose,
        )
    except PrivacyViolationError as exc:
        console.print(
            f"[red bold]PRIVACY GUARD BLOCKED REQUEST:[/red bold] {exc}"
        )
        sys.exit(1)
    except Exception as exc:
        console.print(f"[red]API error: {exc}[/red]")
        sys.exit(1)

    # Display plan -----------------------------------------------------
    try:
        from photoagent.plan_display import display_plan, get_user_approval
    except ImportError:
        # Fallback if plan_display hasn't been built yet
        _fallback_display_plan(plan, max_preview)
        if dry_run:
            console.print("\n[yellow]Dry run -- no files moved.[/yellow]")
            return
        console.print(
            "\n[yellow]plan_display module not available. "
            "Cannot prompt for approval.[/yellow]"
        )
        return

    display_plan(plan, max_preview=max_preview)

    if dry_run:
        console.print("\n[yellow]Dry run -- no files moved.[/yellow]")
        return

    # Approval flow ----------------------------------------------------
    approved = get_user_approval()
    if not approved:
        console.print("[yellow]Organization cancelled.[/yellow]")
        return

    console.print(
        "[yellow]Execution engine not yet implemented (Phase 4).[/yellow]"
    )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _print_summary(summary: dict[str, Any]) -> None:
    """Print a compact summary table to the console."""
    table = Table(title="Catalog Summary", show_header=False)
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    table.add_row("Total images", f"{summary['total_images']:,}")
    table.add_row("Date range", summary["date_range"])
    table.add_row("Screenshots", f"{summary['screenshot_count']:,}")
    table.add_row("Duplicate groups", f"{summary['duplicate_groups']:,}")
    table.add_row("Face clusters", f"{summary['face_cluster_count']:,}")

    locations = summary.get("locations", [])
    if locations:
        top_locs = ", ".join(
            f"{loc['name']} ({loc['count']})" for loc in locations[:5]
        )
        table.add_row("Top locations", top_locs)

    cameras = summary.get("cameras", [])
    if cameras:
        top_cams = ", ".join(
            f"{cam['name']} ({cam['count']})" for cam in cameras[:3]
        )
        table.add_row("Top cameras", top_cams)

    quality = summary.get("quality_issues", {})
    if quality:
        issues_str = ", ".join(f"{k}: {v}" for k, v in quality.items())
        table.add_row("Quality issues", issues_str)

    console.print(table)


def _fallback_display_plan(
    plan: dict[str, Any], max_preview: int = 20
) -> None:
    """Minimal plan display when plan_display module is unavailable."""
    folders = plan.get("folder_structure", [])
    moves = plan.get("moves", [])
    plan_summary = plan.get("summary", "")

    if plan_summary:
        console.print(f"\n[bold]Plan summary:[/bold] {plan_summary}")

    console.print(f"\n[bold]Folders to create:[/bold] {len(folders)}")
    for folder in folders[:10]:
        console.print(f"  {folder}")
    if len(folders) > 10:
        console.print(f"  ... and {len(folders) - 10} more")

    console.print(f"\n[bold]File moves:[/bold] {len(moves)}")
    for move in moves[:max_preview]:
        console.print(
            f"  {move.get('from', '?')} -> {move.get('to', '?')}"
        )
    if len(moves) > max_preview:
        console.print(f"  ... and {len(moves) - max_preview} more")

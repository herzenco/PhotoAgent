"""CLI handlers for cloud vision analysis commands."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

from photoagent.cloud import store
from photoagent.cloud.thumbnail import make_thumbnail

console = Console()


def cloud_analyze(
    path: str,
    limit: Optional[int],
    max_size: int,
    quality: int,
    reanalyze: bool,
    verbose: bool,
    dry_run: bool,
) -> None:
    """Analyze photos using Claude Haiku vision (cloud API).

    Parameters
    ----------
    path:
        Root directory of the photo catalog.
    limit:
        Maximum number of images to process, or None for all.
    max_size:
        Maximum thumbnail dimension in pixels.
    quality:
        JPEG quality for thumbnails (1-100).
    reanalyze:
        If True, re-analyze already processed images.
    verbose:
        If True, print per-image details.
    dry_run:
        If True, estimate cost without calling the API.
    """
    db_path = store.get_db_path(path)
    if not db_path.exists():
        console.print(
            f"[red]No catalog found at {path}. Run 'photoagent scan' first.[/red]"
        )
        return

    conn = sqlite3.connect(str(db_path))
    try:
        _run_analyze(conn, path, limit, max_size, quality, reanalyze, verbose, dry_run)
    finally:
        conn.close()


def _run_analyze(
    conn: sqlite3.Connection,
    path: str,
    limit: Optional[int],
    max_size: int,
    quality: int,
    reanalyze: bool,
    verbose: bool,
    dry_run: bool,
) -> None:
    """Core analysis logic."""
    # Read all cataloged image paths
    rows = conn.execute("SELECT file_path FROM images").fetchall()
    all_paths = [row[0] for row in rows]

    if not all_paths:
        console.print("[yellow]No images found in catalog. Run 'photoagent scan' first.[/yellow]")
        return

    # Ensure the cloud_analysis table exists
    store.ensure_table(conn)

    # Filter to unanalyzed images unless --reanalyze
    if reanalyze:
        to_process = all_paths
    else:
        already_done = store.get_analyzed_paths(conn)
        to_process = [p for p in all_paths if p not in already_done]

    if not to_process:
        console.print("[green]All images already analyzed. Use --reanalyze to re-process.[/green]")
        return

    # Apply limit
    if limit is not None:
        to_process = to_process[:limit]

    console.print(f"Found [bold]{len(to_process)}[/bold] image(s) to process.")

    # Dry run: generate thumbnails for first 5, estimate cost
    if dry_run:
        _dry_run(to_process, max_size, quality)
        return

    # Get API key
    api_key = _get_api_key()
    if api_key is None:
        console.print(
            "[red]No API key found. Set via 'photoagent config --set-api-key' "
            "or ANTHROPIC_API_KEY env var.[/red]"
        )
        return

    # Import analyzer here to avoid requiring anthropic when not needed
    from photoagent.cloud.analyzer import CloudAnalyzer

    analyzer = CloudAnalyzer(api_key=api_key)

    # Process images with progress bar
    total_input_tokens = 0
    total_output_tokens = 0
    successes = 0
    skips = 0
    errors = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Analyzing...", total=len(to_process))

        for image_path in to_process:
            filename = Path(image_path).name

            # Generate thumbnail
            jpeg_bytes, info = make_thumbnail(
                Path(image_path), max_size=max_size, quality=quality
            )

            if jpeg_bytes is None:
                skips += 1
                if verbose:
                    console.print(f"  [dim]SKIP[/dim] {filename} (unsupported format)")
                progress.advance(task)
                continue

            # Analyze via API
            result = analyzer.analyze_one(jpeg_bytes, image_path)
            result.thumb_byte_size = info["thumb_byte_size"]  # type: ignore[index]

            if result.category == "error":
                errors += 1
                if verbose:
                    console.print(f"  [red]ERROR[/red] {filename}: {result.subject}")
            else:
                successes += 1
                total_input_tokens += result.input_tokens
                total_output_tokens += result.output_tokens

                if verbose:
                    cost = _compute_cost(result.input_tokens, result.output_tokens)
                    console.print(
                        f"  [green]OK[/green] {filename}: "
                        f"{result.category}/{result.subcategory} "
                        f"({result.input_tokens}+{result.output_tokens} tokens, "
                        f"${cost:.4f})"
                    )

            # Save result
            store.save_result(conn, result)
            progress.advance(task)

    # Summary
    total_cost = _compute_cost(total_input_tokens, total_output_tokens)
    console.print()
    console.print("[bold]Summary[/bold]")
    console.print(f"  Analyzed:  {successes}")
    console.print(f"  Skipped:   {skips} (RAW/unsupported)")
    console.print(f"  Errors:    {errors}")
    console.print(f"  Tokens:    {total_input_tokens:,} input + {total_output_tokens:,} output")
    console.print(f"  Est. cost: ${total_cost:.4f}")


def _dry_run(to_process: list[str], max_size: int, quality: int) -> None:
    """Generate thumbnails for the first 5 images and estimate total cost."""
    console.print("[bold]Dry run mode[/bold] -- estimating cost without calling API.\n")

    sample = to_process[:5]
    thumb_sizes: list[int] = []
    supported_count = 0

    for image_path in sample:
        filename = Path(image_path).name
        jpeg_bytes, info = make_thumbnail(
            Path(image_path), max_size=max_size, quality=quality
        )
        if jpeg_bytes is not None:
            size = info["thumb_byte_size"]  # type: ignore[index]
            thumb_sizes.append(size)
            supported_count += 1
            console.print(f"  {filename}: {size:,} bytes thumbnail")
        else:
            console.print(f"  {filename}: [dim]skipped (unsupported)[/dim]")

    if not thumb_sizes:
        console.print("[yellow]No supported images found in sample.[/yellow]")
        return

    avg_size = sum(thumb_sizes) / len(thumb_sizes)
    # Rough estimate: ~1600 input tokens per image (base + thumbnail), ~80 output tokens
    est_input_per_image = 1600
    est_output_per_image = 80
    total_images = len(to_process)

    est_total_cost = total_images * _compute_cost(est_input_per_image, est_output_per_image)

    console.print()
    console.print(f"  Avg thumbnail size: {avg_size:,.0f} bytes")
    console.print(f"  Total images to process: {total_images}")
    console.print(f"  Estimated cost: [bold]${est_total_cost:.4f}[/bold]")
    console.print(
        f"  (based on ~{est_input_per_image} input + ~{est_output_per_image} output tokens/image)"
    )


def _compute_cost(input_tokens: int, output_tokens: int) -> float:
    """Compute estimated cost from token counts."""
    return (input_tokens * 1.00 / 1_000_000) + (output_tokens * 5.00 / 1_000_000)


def _get_api_key() -> str | None:
    """Retrieve the API key from ConfigManager or environment."""
    # Try ConfigManager first
    try:
        from photoagent.config_manager import ConfigManager

        mgr = ConfigManager()
        key = mgr.get_api_key()
        if key:
            return key
    except Exception:
        pass

    # Fallback to env var
    return os.environ.get("ANTHROPIC_API_KEY")


def cloud_search(path: str, query: str) -> None:
    """Search photos using cloud analysis tags.

    Parameters
    ----------
    path:
        Root directory of the photo catalog.
    query:
        Search term to match against analysis fields.
    """
    db_path = store.get_db_path(path)
    if not db_path.exists():
        console.print(
            f"[red]No catalog found at {path}. Run 'photoagent scan' first.[/red]"
        )
        return

    conn = sqlite3.connect(str(db_path))
    try:
        store.ensure_table(conn)
        results = store.search_cloud(conn, query)
    finally:
        conn.close()

    if not results:
        console.print(f"[yellow]No results found for '{query}'.[/yellow]")
        return

    table = Table(title=f"Cloud Search: '{query}'")
    table.add_column("Filename")
    table.add_column("Category")
    table.add_column("Subcategory")
    table.add_column("Subject")
    table.add_column("Mood")
    table.add_column("Tags")

    for row in results:
        filename = Path(row["image_path"]).name
        table.add_row(
            filename,
            row["category"],
            row["subcategory"],
            row["subject"],
            row["mood"],
            row["tags"],
        )

    console.print(table)
    console.print(f"[dim]{len(results)} result(s) found.[/dim]")


# ------------------------------------------------------------------
# cloud-organize
# ------------------------------------------------------------------


def cloud_organize(
    path: str,
    mapping_path: str | None,
    copy: bool,
    dry_run: bool,
) -> None:
    """Organize photos into folders based on cloud analysis categories."""
    db_path = store.get_db_path(path)
    if not db_path.exists():
        console.print(
            f"[red]No catalog found at {path}. Run 'photoagent scan' first.[/red]"
        )
        return

    conn = sqlite3.connect(str(db_path))
    try:
        store.ensure_table(conn)

        # Load custom mapping if provided
        mapping = None
        if mapping_path:
            from photoagent.cloud.organize import load_custom_mapping

            mapping = load_custom_mapping(Path(mapping_path))

        # Build the plan
        from photoagent.cloud.organize import build_organize_plan

        plan = build_organize_plan(conn, Path(path), mapping)
    finally:
        conn.close()

    moves = plan.get("moves", [])
    if not moves:
        console.print(
            "[dim]No files to organize. Run 'photoagent cloud-analyze' first.[/dim]"
        )
        return

    # Display the plan
    from photoagent.plan_display import display_plan, get_user_approval, export_plan

    action = "copy" if copy else "move"
    console.print(f"\n[bold]Mode:[/bold] {action} | [bold]Files:[/bold] {len(moves)}\n")
    display_plan(plan)

    if dry_run:
        console.print(
            "\n[yellow]Dry run — no files touched. Use --execute to apply.[/yellow]"
        )
        return

    # Approval flow
    choice = get_user_approval()

    if choice == "reject":
        console.print("[yellow]Cancelled.[/yellow]")
        return

    if choice == "export":
        export_path = Path(path) / ".photoagent" / "cloud_organize_plan.json"
        export_plan(plan, export_path)
        return

    if choice == "modify":
        console.print(
            "[yellow]Edit your mapping JSON and re-run.[/yellow]"
        )
        return

    if choice == "approve":
        _execute_cloud_plan(Path(path), plan, copy_only=copy)


def _execute_cloud_plan(
    base_path: Path,
    plan: dict,
    copy_only: bool = False,
) -> None:
    """Execute a cloud organize plan with Rich progress."""
    from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

    from photoagent.database import CatalogDB
    from photoagent.execute_cli import _print_result_summary
    from photoagent.executor import PlanExecutor

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
            task = progress.add_task("Organizing...", total=total)

            def _on_progress(current: int, total: int, desc: str) -> None:
                progress.update(task, completed=current, description=desc)

            result = executor.execute(
                plan, on_progress=_on_progress, copy_only=copy_only
            )

    action = "Copy" if copy_only else "Move"
    _print_result_summary(result, action=action)

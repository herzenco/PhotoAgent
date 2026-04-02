"""CLI wiring for the analyze command.

Sets up the vision analysis pipeline with a rich progress display,
runs it against the catalog, and prints a summary.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
)

from photoagent.database import CatalogDB

console = Console()

_STAGE_LABELS = {
    "quality": "[1/4] Quality assessment",
    "clip": "[2/4] CLIP tagging",
    "caption": "[3/4] Captioning",
    "faces": "[4/4] Face detection",
}


def run_analyze(
    path: Path,
    *,
    device: str = "auto",
    models: str = "clip,caption,quality,faces",
    skip_captions: bool = False,
    lite: bool = False,
    batch_size: int = 32,
) -> None:
    """Run the full analysis pipeline with a rich progress display."""
    resolved = Path(path).resolve()
    db_dir = resolved / ".photoagent"

    if not db_dir.exists():
        console.print(
            f"[red]No catalog found at {resolved}. Run 'photoagent scan' first.[/red]"
        )
        return

    model_list = [m.strip() for m in models.split(",") if m.strip()]

    mode_label = "lite" if lite else ("no-captions" if skip_captions else "full")
    console.print(
        f"[bold]Analyzing[/bold] images in [cyan]{resolved}[/cyan]  "
        f"(mode: {mode_label}, device: {device})"
    )

    # Import lazily so we don't pull in torch/numpy when just running scan
    try:
        from photoagent.vision.pipeline import AnalysisPipeline
    except ImportError as exc:
        console.print(
            f"[red]Missing vision dependencies: {exc}[/red]\n"
            "Install them with: pip install -e '.[vision]'"
        )
        return

    db = CatalogDB(resolved)

    try:
        # Check how many images need analysis
        unanalyzed = db.get_unanalyzed()
        total = len(unanalyzed)

        if total == 0:
            console.print("[green]All images are already analyzed.[/green]")
            return

        console.print(f"  Images to analyze: [bold]{total}[/bold]")

        if lite:
            console.print("  [dim]Lite mode: CLIP tagging + quality only[/dim]")
        elif skip_captions:
            console.print("  [dim]Skipping model-based captioning[/dim]")

        pipeline = AnalysisPipeline(
            device=device,
            models=model_list,
            skip_captions=skip_captions,
            lite=lite,
        )

        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
        )

        task_ids: dict[str, int] = {}

        def on_progress(stage: str, current: int, total: int) -> None:
            label = _STAGE_LABELS.get(stage, stage)
            if stage not in task_ids:
                task_ids[stage] = progress.add_task(label, total=total)
            progress.update(task_ids[stage], completed=current)

        with progress:
            result = pipeline.run(db, on_progress=on_progress)

        # Summary
        console.print()
        console.print("[bold green]Analysis complete![/bold green]")
        console.print(f"  Images processed : {result.total_processed}")
        console.print(f"  Newly analyzed   : {result.newly_analyzed}")
        console.print(f"  Errors           : {len(result.errors)}")
        console.print(f"  Duration         : {result.duration:.1f}s")

        if result.errors:
            console.print()
            console.print(f"[yellow]{len(result.errors)} error(s):[/yellow]")
            for err in result.errors[:20]:
                console.print(f"  [dim]{err}[/dim]")
            if len(result.errors) > 20:
                console.print(f"  ... and {len(result.errors) - 20} more")

    finally:
        db.close()

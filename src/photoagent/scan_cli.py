"""CLI wiring for the scan command.

Provides ``run_scan()`` which sets up a rich progress bar, invokes the
``FileScanner``, and prints a summary.  Called from ``cli.py``'s scan
command.
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
from photoagent.scanner import FileScanner

console = Console()


def run_scan(
    path: Path,
    recursive: bool = True,
    extensions: str = "jpg,jpeg,png,heic,heif,webp,gif,tiff,bmp,raw,cr2,nef,arw",
) -> None:
    """Run a full directory scan with a rich progress bar and summary.

    Parameters
    ----------
    path:
        Root directory to scan for images.
    recursive:
        Whether to descend into subdirectories.
    extensions:
        Comma-separated list of file extensions to include (no dots).
    """
    ext_list = [e.strip().lower() for e in extensions.split(",") if e.strip()]

    resolved_path = Path(path).resolve()

    console.print(
        f"[bold]Scanning[/bold] [cyan]{resolved_path}[/cyan] "
        f"for [green]{', '.join(ext_list)}[/green] files ..."
    )

    db = CatalogDB(resolved_path)

    try:
        scanner = FileScanner(
            base_path=resolved_path,
            extensions=ext_list,
            recursive=recursive,
        )

        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console,
        )

        task_id = None

        def _on_progress(current: int, total: int) -> None:
            nonlocal task_id
            if task_id is None:
                task_id = progress.add_task("Scanning images", total=total)
            progress.update(task_id, completed=current)

        with progress:
            result = scanner.scan(db, on_progress=_on_progress)

        # ---- Summary ----
        console.print()
        console.print("[bold green]Scan complete![/bold green]")
        console.print(f"  Total files found : {result.total_found}")
        console.print(f"  New / updated     : {result.new_images}")
        console.print(f"  Skipped (unchanged): {result.skipped}")
        console.print(f"  Errors            : {len(result.errors)}")
        console.print(f"  Duration          : {result.duration:.1f}s")

        if result.errors:
            console.print()
            console.print(
                f"[yellow]{len(result.errors)} file(s) had errors:[/yellow]"
            )
            for err in result.errors[:20]:
                console.print(f"  [dim]{err}[/dim]")
            if len(result.errors) > 20:
                console.print(
                    f"  ... and {len(result.errors) - 20} more"
                )
    finally:
        db.close()

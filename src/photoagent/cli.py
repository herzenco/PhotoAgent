"""CLI entry point for PhotoAgent."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from photoagent.database import CatalogDB

app = typer.Typer(
    name="photoagent",
    help="AI-powered local image organizer",
    no_args_is_help=True,
)

console = Console()


def _human_readable_size(size_bytes: int) -> str:
    """Convert bytes to a human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size_bytes) < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024  # type: ignore[assignment]
    return f"{size_bytes:.1f} PB"


# ------------------------------------------------------------------
# scan
# ------------------------------------------------------------------


@app.command()
def scan(
    path: Path = typer.Argument(..., help="Root directory to scan for images"),
    recursive: bool = typer.Option(True, "--recursive/--no-recursive", help="Scan subdirectories"),
    extensions: str = typer.Option(
        "jpg,jpeg,png,heic,heif,webp,gif,tiff,bmp,raw,cr2,nef,arw",
        "--extensions",
        "-e",
        help="Comma-separated list of file extensions to include",
    ),
) -> None:
    """Scan a directory for image files and register them in the catalog."""
    from photoagent.scan_cli import run_scan

    run_scan(path=path, recursive=recursive, extensions=extensions)


# ------------------------------------------------------------------
# status  (fully implemented)
# ------------------------------------------------------------------


@app.command()
def status(
    path: Path = typer.Argument(..., help="Root directory of the photo catalog"),
) -> None:
    """Show catalog statistics for a scanned directory."""
    db_dir = Path(path) / ".photoagent"
    if not db_dir.exists():
        console.print(
            f"[red]No catalog found at {path}. Run 'photoagent scan' first.[/red]"
        )
        raise typer.Exit(code=1)

    with CatalogDB(Path(path)) as db:
        stats = db.get_stats()

    total = stats["total_images"]
    analyzed = stats["analyzed_count"]
    pct = (analyzed / total * 100) if total else 0.0

    # ---- Overview table ----
    overview = Table(title="Catalog Overview", show_header=False)
    overview.add_column("Metric", style="bold")
    overview.add_column("Value", justify="right")
    overview.add_row("Total images", str(total))
    overview.add_row("Analyzed", f"{analyzed} ({pct:.1f}%)")
    overview.add_row("Duplicates", str(stats["duplicate_count"]))
    overview.add_row("Screenshots", str(stats["screenshot_count"]))
    overview.add_row("Disk usage", _human_readable_size(stats["total_disk_usage"]))
    console.print(overview)

    # ---- Yearly breakdown ----
    by_year: dict[str, int] = stats["by_year"]
    if by_year:
        yr_table = Table(title="Images by Year")
        yr_table.add_column("Year")
        yr_table.add_column("Count", justify="right")
        for year, count in sorted(by_year.items()):
            yr_table.add_row(year, str(count))
        console.print(yr_table)

    # ---- Camera breakdown ----
    by_camera: dict[str, int] = stats["by_camera"]
    if by_camera:
        cam_table = Table(title="Images by Camera")
        cam_table.add_column("Camera Model")
        cam_table.add_column("Count", justify="right")
        for model, count in by_camera.items():
            cam_table.add_row(model, str(count))
        console.print(cam_table)

    # ---- Top 10 locations ----
    by_location: dict[str, int] = stats["by_location"]
    if by_location:
        loc_table = Table(title="Top 10 Locations")
        loc_table.add_column("Location")
        loc_table.add_column("Count", justify="right")
        for loc, count in list(by_location.items())[:10]:
            loc_table.add_row(loc, str(count))
        console.print(loc_table)


# ------------------------------------------------------------------
# Stub commands
# ------------------------------------------------------------------


@app.command()
def analyze(
    path: Path = typer.Argument(..., help="Root directory of the photo catalog"),
    device: str = typer.Option("auto", "--device", "-d", help="Device: auto, cpu, cuda, mps"),
    models: str = typer.Option(
        "clip,caption,quality,faces",
        "--models",
        "-m",
        help="Comma-separated list of models to run",
    ),
    skip_captions: bool = typer.Option(False, "--skip-captions", help="Skip model-based captioning"),
    lite: bool = typer.Option(False, "--lite", help="Lite mode: CLIP + quality only"),
    batch_size: int = typer.Option(32, "--batch-size", "-b", help="Batch size for inference"),
) -> None:
    """Run AI analysis on scanned images."""
    from photoagent.analyze_cli import run_analyze

    run_analyze(
        path=path,
        device=device,
        models=models,
        skip_captions=skip_captions,
        lite=lite,
        batch_size=batch_size,
    )


@app.command()
def organize(
    path: Path = typer.Argument(..., help="Root directory of the photo catalog"),
    instruction: str = typer.Argument(..., help="Natural-language organization instruction"),
    dry_run: bool = typer.Option(True, "--dry-run/--execute", help="Show plan without executing (default: dry-run)"),
    max_preview: int = typer.Option(50, "--max-preview", help="Max moves to show in preview"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Log all outbound API requests for privacy audit"),
) -> None:
    """Organize images according to a natural-language instruction."""
    from photoagent.organize_cli import run_organize

    run_organize(
        path=path,
        instruction=instruction,
        dry_run=dry_run,
        max_preview=max_preview,
        verbose=verbose,
    )


@app.command()
def search(
    path: Path = typer.Argument(..., help="Root directory of the photo catalog"),
    query: str = typer.Argument(..., help="Natural-language search query"),
    top_k: int = typer.Option(20, "--top", "-k", help="Max results to return"),
    year: Optional[int] = typer.Option(None, "--year", help="Filter by year"),
    location: Optional[str] = typer.Option(None, "--location", help="Filter by location"),
    min_quality: Optional[float] = typer.Option(None, "--min-quality", help="Min quality score (0-1)"),
    type_filter: Optional[str] = typer.Option(None, "--type", help="Filter: photo or screenshot"),
    camera: Optional[str] = typer.Option(None, "--camera", help="Filter by camera model"),
    person: Optional[str] = typer.Option(None, "--person", help="Filter by person/face cluster"),
) -> None:
    """Search images by natural-language query."""
    from photoagent.search_cli import run_search

    run_search(
        path=path, query=query, top_k=top_k,
        year=year, location=location, min_quality=min_quality,
        type_filter=type_filter, camera=camera, person=person,
    )


@app.command()
def export_catalog(
    path: Path = typer.Argument(..., help="Root directory of the photo catalog"),
    output: Path = typer.Option("catalog.json", "--output", "-o", help="Output file path"),
    fmt: str = typer.Option("json", "--format", "-f", help="Export format: json or csv"),
    year: Optional[int] = typer.Option(None, "--year", help="Filter by year"),
    location: Optional[str] = typer.Option(None, "--location", help="Filter by location"),
    min_quality: Optional[float] = typer.Option(None, "--min-quality", help="Min quality score"),
) -> None:
    """Export catalog data to JSON or CSV."""
    from photoagent.export import export_catalog as do_export
    from photoagent.database import CatalogDB as DB

    db_dir = Path(path) / ".photoagent"
    if not db_dir.exists():
        console.print(f"[red]No catalog found at {path}. Run 'photoagent scan' first.[/red]")
        raise typer.Exit(code=1)

    filters = {}
    if year: filters["year"] = year
    if location: filters["location"] = location
    if min_quality: filters["min_quality"] = min_quality

    with DB(Path(path)) as db:
        count = do_export(db, Path(path), output, format=fmt, filters=filters or None)
    console.print(f"[green]Exported {count} images to {output}[/green]")


@app.command()
def config(
    set_api_key: Optional[str] = typer.Option(None, "--set-api-key", help="Store Anthropic API key in keyring"),
    show: bool = typer.Option(False, "--show", help="Show current configuration"),
    device: Optional[str] = typer.Option(None, "--device", help="Set preferred device (cpu/cuda/mps)"),
    template: Optional[str] = typer.Option(None, "--template", help="Set default template"),
) -> None:
    """Manage PhotoAgent configuration."""
    from photoagent.config_manager import ConfigManager

    mgr = ConfigManager()
    if set_api_key:
        mgr.set_api_key(set_api_key)
        console.print("[green]API key stored in system keyring.[/green]")
    if device:
        mgr.set_config(preferred_device=device)
        console.print(f"[green]Default device set to {device}[/green]")
    if template:
        mgr.set_config(default_template=template)
        console.print(f"[green]Default template set to {template}[/green]")
    if show or (not set_api_key and not device and not template):
        cfg = mgr.get_config()
        has_key = mgr.get_api_key() is not None
        console.print(f"  API key: {'[green]configured[/green]' if has_key else '[yellow]not set[/yellow]'}")
        for k, v in cfg.items():
            console.print(f"  {k}: {v}")


@app.command()
def undo(
    path: Path = typer.Argument(..., help="Root directory of the photo catalog"),
    manifest: Optional[str] = typer.Option(None, "--manifest", "-m", help="Specific manifest timestamp to undo"),
) -> None:
    """Undo the last file-organization operation."""
    from photoagent.execute_cli import run_undo

    manifest_path = Path(manifest) if manifest else None
    run_undo(path=path, manifest=manifest_path)


@app.command()
def history(
    path: Path = typer.Argument(..., help="Root directory of the photo catalog"),
) -> None:
    """Show operation history."""
    from photoagent.execute_cli import run_history

    run_history(path=path)


@app.command()
def rename_person(
    path: Path = typer.Argument(..., help="Root directory of the photo catalog"),
    cluster_id: str = typer.Argument(..., help="Face cluster ID or current label"),
    name: str = typer.Argument(..., help="New name for the person"),
) -> None:
    """Assign a name to a detected face cluster."""
    from photoagent.face_manager import FaceManager

    db_dir = Path(path) / ".photoagent"
    if not db_dir.exists():
        console.print(f"[red]No catalog found at {path}.[/red]")
        raise typer.Exit(code=1)

    with CatalogDB(Path(path)) as db:
        mgr = FaceManager(db)
        count = mgr.rename_person(cluster_id, name)
    console.print(f"[green]Updated {count} face record(s) to '{name}'[/green]")


@app.command()
def list_people(
    path: Path = typer.Argument(..., help="Root directory of the photo catalog"),
) -> None:
    """List all detected face clusters / people."""
    from photoagent.face_manager import FaceManager

    db_dir = Path(path) / ".photoagent"
    if not db_dir.exists():
        console.print(f"[red]No catalog found at {path}.[/red]")
        raise typer.Exit(code=1)

    with CatalogDB(Path(path)) as db:
        mgr = FaceManager(db)
        people = mgr.list_people()

    if not people:
        console.print("[dim]No face clusters found. Run 'photoagent analyze' first.[/dim]")
        return

    table = Table(title="Face Clusters")
    table.add_column("Cluster ID", justify="right")
    table.add_column("Label")
    table.add_column("Photos", justify="right")
    table.add_column("Sample File")
    for p in people:
        table.add_row(
            str(p.get("cluster_id", "")),
            p.get("label", "Unknown"),
            str(p.get("photo_count", 0)),
            p.get("sample_filename", ""),
        )
    console.print(table)


@app.command()
def organize_template(
    path: Path = typer.Argument(..., help="Root directory of the photo catalog"),
    template: str = typer.Option("by-date", "--template", "-t", help="Built-in template name"),
    yaml_file: Optional[str] = typer.Option(None, "--yaml", help="Path to custom YAML template"),
    dry_run: bool = typer.Option(True, "--dry-run/--execute", help="Show plan without executing"),
) -> None:
    """Organize images using a template (offline, no API needed)."""
    from photoagent.template_cli import run_template_organize

    yaml_path = Path(yaml_file) if yaml_file else None
    run_template_organize(path=path, template_name=template, yaml_path=yaml_path)


# ------------------------------------------------------------------
# Cloud vision commands
# ------------------------------------------------------------------


@app.command(name="cloud-analyze")
def cloud_analyze_cmd(
    path: Path = typer.Argument(..., help="Path to photo directory"),
    limit: Optional[int] = typer.Option(None, "--limit", "-n", help="Max images to process"),
    max_size: int = typer.Option(256, "--size", help="Thumbnail max dimension (px)"),
    quality: int = typer.Option(65, "--quality", help="JPEG quality (1-100)"),
    reanalyze: bool = typer.Option(False, "--reanalyze", help="Re-analyze already processed images"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show per-image details"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Estimate cost without calling API"),
) -> None:
    """Analyze photos using Claude Haiku vision (cloud API)."""
    from photoagent.cloud.cli import cloud_analyze

    cloud_analyze(str(path), limit, max_size, quality, reanalyze, verbose, dry_run)


@app.command(name="cloud-search")
def cloud_search_cmd(
    path: Path = typer.Argument(..., help="Path to photo directory"),
    query: str = typer.Argument(..., help="Search query"),
) -> None:
    """Search photos using cloud analysis tags."""
    from photoagent.cloud.cli import cloud_search

    cloud_search(str(path), query)

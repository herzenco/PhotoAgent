"""CLI wiring for the 'search' command.

Connects ImageSearcher to Rich table output.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from photoagent.database import CatalogDB
from photoagent.search import ImageSearcher

_console_stdout = Console()


def run_search(
    path: Path,
    query: str,
    top_k: int = 20,
    year: int | None = None,
    location: str | None = None,
    min_quality: float | None = None,
    type_filter: str | None = None,
    camera: str | None = None,
    person: str | None = None,
    json_output: bool = False,
) -> list[dict[str, Any]]:
    """Run a search query and display results.

    Parameters
    ----------
    path:
        Root directory of the photo catalog.
    query:
        Natural-language search query.
    top_k:
        Maximum number of results.
    year:
        Filter by year of date_taken.
    location:
        Filter by city or country.
    min_quality:
        Filter by minimum quality score.
    type_filter:
        Filter by type: "photo" or "screenshot".
    camera:
        Filter by camera model.
    person:
        Filter by face cluster label.

    Returns
    -------
    List of search result dicts.
    """
    console = Console(stderr=True) if json_output else _console_stdout

    db_dir = path / ".photoagent"
    if not db_dir.exists():
        console.print(
            f"[red]No catalog found at {path}. "
            "Run 'photoagent scan' first.[/red]"
        )
        sys.exit(1)

    # Build filters
    filters: dict[str, Any] = {}
    if year is not None:
        filters["year"] = year
    if location is not None:
        filters["location"] = location
    if min_quality is not None:
        filters["min_quality"] = min_quality
    if type_filter is not None:
        filters["type"] = type_filter
    if camera is not None:
        filters["camera"] = camera
    if person is not None:
        filters["person"] = person

    with CatalogDB(path) as db:
        searcher = ImageSearcher(db, path)
        results = searcher.search(query, top_k=top_k, filters=filters)

    if json_output:
        from photoagent.cli import _json_output
        _json_output([
            {
                "filename": r.get("filename"),
                "score": r.get("score"),
                "caption": r.get("caption"),
                "tags": r.get("tags"),
                "match_reason": r.get("match_reason"),
                "date_taken": r.get("date_taken"),
                "city": r.get("city"),
                "country": r.get("country"),
                "camera_model": r.get("camera_model"),
                "ai_quality_score": r.get("ai_quality_score"),
                "is_screenshot": r.get("is_screenshot"),
                "face_count": r.get("face_count"),
                "file_size": r.get("file_size"),
            }
            for r in results
        ])

    if not results:
        console.print("[dim]No results found.[/dim]")
        return []

    # Display results as rich table
    table = Table(
        title=f"Search Results for '{query}'",
        show_lines=False,
        padding=(0, 1),
    )
    table.add_column("#", style="dim", justify="right", width=4)
    table.add_column("Score", justify="right", width=6)
    table.add_column("Filename", style="cyan", max_width=30)
    table.add_column("Caption", max_width=40)
    table.add_column("Tags", style="dim", max_width=30)
    table.add_column("Match Reason", style="green", max_width=40)

    for i, result in enumerate(results, 1):
        # Top 3 tags
        tags_str = ", ".join(result.get("tags", [])[:3])
        caption = result.get("caption", "")
        if len(caption) > 40:
            caption = caption[:37] + "..."

        table.add_row(
            str(i),
            f"{result['score']:.2f}",
            result["filename"],
            caption,
            tags_str,
            result.get("match_reason", ""),
        )

    console.print(table)
    console.print(f"\n[dim]{len(results)} result(s) found.[/dim]")

    return results

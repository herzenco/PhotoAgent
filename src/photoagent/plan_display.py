"""Plan display and user approval UI for PhotoAgent.

Renders organization plans in the terminal using rich and handles
interactive user approval.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.tree import Tree

console = Console()

# Colors by tree depth for visual clarity
_DEPTH_COLORS = ["bright_cyan", "cyan", "dark_cyan", "blue", "bright_blue", "magenta"]


def _classify_move(move: dict[str, str]) -> str:
    """Classify a move as 'move', 'rename', or 'move+rename'."""
    from_path = Path(move["from"])
    to_path = Path(move["to"])

    same_dir = from_path.parent == to_path.parent
    same_name = from_path.name == to_path.name

    if same_dir and not same_name:
        return "rename"
    elif not same_dir and same_name:
        return "move"
    elif not same_dir and not same_name:
        return "move+rename"
    else:
        # Same dir and same name — file stays in place
        return "no-op"


def _count_moves_per_folder(moves: list[dict[str, Any]]) -> dict[str, int]:
    """Count how many files are moved into each destination folder."""
    counts: dict[str, int] = defaultdict(int)
    for move in moves:
        folder = str(Path(move["to"]).parent)
        counts[folder] += 1
    return dict(counts)


def _truncate_path(path: str, max_len: int = 60) -> str:
    """Truncate a path with ellipsis if it exceeds max_len."""
    if len(path) <= max_len:
        return path
    # Keep the beginning and end, insert ellipsis in the middle
    keep = max_len - 3
    head = keep // 2
    tail = keep - head
    return path[:head] + "..." + path[-tail:]


def display_folder_tree(
    folder_structure: list[str], move_counts: dict[str, int]
) -> None:
    """Build and print a rich Tree showing the proposed folder hierarchy.

    Parameters
    ----------
    folder_structure:
        List of folder paths like ``["Vacations/2023/Cancun", ...]``.
    move_counts:
        Mapping of folder path -> number of files destined for that folder.
    """
    tree = Tree("[bold bright_cyan]Proposed Folder Structure[/]", guide_style="dim")

    # Build a nested dict representing the tree structure
    nodes: dict[str, Any] = {}

    for folder_path in sorted(folder_structure):
        parts = folder_path.split("/")
        current = nodes
        for part in parts:
            if part not in current:
                current[part] = {}
            current = current[part]

    # Recursively add nodes to the rich Tree
    def _add_nodes(
        parent_tree: Tree,
        children: dict[str, Any],
        current_path: str,
        depth: int,
    ) -> None:
        color = _DEPTH_COLORS[depth % len(_DEPTH_COLORS)]
        for name in sorted(children.keys()):
            full_path = f"{current_path}/{name}" if current_path else name
            count = move_counts.get(full_path, 0)
            label = f"[{color}]{name}[/{color}]"
            if count > 0:
                label += f"  [dim]({count} file{'s' if count != 1 else ''})[/dim]"
            branch = parent_tree.add(label)
            _add_nodes(branch, children[name], full_path, depth + 1)

    _add_nodes(tree, nodes, "", 0)

    console.print()
    console.print(tree)


def display_plan(plan: dict[str, Any], max_preview: int = 50) -> None:
    """Display an organization plan in the terminal using rich.

    Parameters
    ----------
    plan:
        Plan dictionary with keys ``folder_structure``, ``moves``, and ``summary``.
    max_preview:
        Maximum number of sample moves to display in the preview table.
    """
    moves = plan.get("moves", [])
    folder_structure = plan.get("folder_structure", [])
    summary_text = plan.get("summary", "No summary provided.")

    # --- 1. Summary banner ---
    console.print()
    console.print(
        Panel(
            f"[bold]{summary_text}[/bold]",
            title="[bold bright_white]Organization Plan[/]",
            border_style="bright_cyan",
            padding=(1, 2),
        )
    )

    # --- 2. Statistics ---
    total_moves = len(moves)
    move_counts = _count_moves_per_folder(moves)

    # Classify each move
    classifications: dict[str, int] = defaultdict(int)
    for move in moves:
        classifications[_classify_move(move)] += 1

    files_moving = classifications.get("move", 0) + classifications.get("move+rename", 0)
    files_renaming = classifications.get("rename", 0) + classifications.get("move+rename", 0)
    files_staying = classifications.get("no-op", 0)
    new_folders = len(folder_structure)
    est_seconds = total_moves * 0.1
    if est_seconds < 60:
        est_time = f"{est_seconds:.0f} seconds"
    elif est_seconds < 3600:
        est_time = f"{est_seconds / 60:.1f} minutes"
    else:
        est_time = f"{est_seconds / 3600:.1f} hours"

    stats_table = Table(show_header=False, box=None, padding=(0, 2))
    stats_table.add_column("label", style="dim", no_wrap=True)
    stats_table.add_column("value", no_wrap=True)

    stats_table.add_row("Total files to move", f"[bold]{total_moves}[/bold]")
    if files_staying > 0:
        stats_table.add_row("Files staying in place", f"[bold]{files_staying}[/bold]")
    stats_table.add_row("Files to relocate", f"[bold]{files_moving}[/bold]")
    stats_table.add_row("Files to rename", f"[bold]{files_renaming}[/bold]")
    stats_table.add_row("New folders to create", f"[bold]{new_folders}[/bold]")
    stats_table.add_row("Estimated time", f"[bold]{est_time}[/bold]")

    console.print()
    console.print(
        Panel(stats_table, title="[bold]Statistics[/]", border_style="dim", padding=(1, 2))
    )

    # --- 3. Folder structure tree ---
    display_folder_tree(folder_structure, move_counts)

    # --- 4. Sample moves table ---
    if moves:
        console.print()
        moves_table = Table(
            title="[bold]Sample Moves[/]",
            title_style="bold",
            border_style="dim",
            show_lines=False,
            padding=(0, 1),
        )
        moves_table.add_column("#", style="dim", justify="right", width=5)
        moves_table.add_column("From", style="dim")
        moves_table.add_column("To", style="green")
        moves_table.add_column("Change Type", justify="center")

        change_type_styles = {
            "move": "[cyan]move[/cyan]",
            "rename": "[yellow]rename[/yellow]",
            "move+rename": "[magenta]move+rename[/magenta]",
            "no-op": "[dim]no-op[/dim]",
        }

        for move in moves[:max_preview]:
            change_type = _classify_move(move)
            moves_table.add_row(
                str(move.get("id", "")),
                _truncate_path(move["from"]),
                _truncate_path(move["to"]),
                change_type_styles.get(change_type, change_type),
            )

        console.print(moves_table)

        remaining = total_moves - max_preview
        if remaining > 0:
            console.print(
                f"  [dim]... and [bold]{remaining}[/bold] more moves[/dim]"
            )

    console.print()


def get_user_approval() -> str:
    """Prompt the user for what to do with the plan.

    Returns
    -------
    str
        One of ``"approve"``, ``"reject"``, ``"modify"``, or ``"export"``.
    """
    console.print()
    console.print("[bold]What would you like to do?[/bold]")
    console.print("  [green]\\[a][/green] Approve and execute")
    console.print("  [red]\\[r][/red] Reject (cancel)")
    console.print("  [yellow]\\[m][/yellow] Modify instruction")
    console.print("  [cyan]\\[e][/cyan] Export plan as JSON")
    console.print()

    choice = Prompt.ask(
        "Choice",
        choices=["a", "r", "m", "e"],
        default="a",
    )

    mapping = {
        "a": "approve",
        "r": "reject",
        "m": "modify",
        "e": "export",
    }
    return mapping[choice]


def export_plan(plan: dict[str, Any], output_path: Path) -> None:
    """Write the plan to a JSON file with pretty formatting.

    Parameters
    ----------
    plan:
        The plan dictionary to export.
    output_path:
        Destination file path for the JSON output.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)

    console.print(
        f"\n[green]Plan exported to:[/green] [bold]{output_path.resolve()}[/bold]"
    )

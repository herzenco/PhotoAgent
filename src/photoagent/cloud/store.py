"""Database storage for cloud vision analysis results."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from photoagent.cloud.models import CloudAnalysisResult


def get_db_path(photo_path: str) -> Path:
    """Return the path to the catalog database for a photo directory.

    Parameters
    ----------
    photo_path:
        Root directory of the photo catalog.

    Returns
    -------
    Path to ``<photo_path>/.photoagent/catalog.db``.
    """
    return Path(photo_path) / ".photoagent" / "catalog.db"


def ensure_table(conn: sqlite3.Connection) -> None:
    """Create the ``cloud_analysis`` table if it does not already exist.

    Parameters
    ----------
    conn:
        An open SQLite connection to the catalog database.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cloud_analysis (
            image_path      TEXT PRIMARY KEY,
            category        TEXT,
            subcategory     TEXT,
            subject         TEXT,
            mood            TEXT,
            tags            TEXT,
            quality_note    TEXT,
            model           TEXT,
            input_tokens    INTEGER,
            output_tokens   INTEGER,
            thumb_byte_size INTEGER,
            analyzed_at     TEXT
        )
    """)
    conn.commit()


def save_result(conn: sqlite3.Connection, result: CloudAnalysisResult) -> None:
    """Insert or replace a cloud analysis result.

    Parameters
    ----------
    conn:
        An open SQLite connection.
    result:
        The analysis result to persist.
    """
    conn.execute(
        """
        INSERT OR REPLACE INTO cloud_analysis
            (image_path, category, subcategory, subject, mood, tags,
             quality_note, model, input_tokens, output_tokens,
             thumb_byte_size, analyzed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            result.image_path,
            result.category,
            result.subcategory,
            result.subject,
            result.mood,
            json.dumps(result.tags),
            result.quality_note,
            result.model,
            result.input_tokens,
            result.output_tokens,
            result.thumb_byte_size,
            result.analyzed_at,
        ),
    )
    conn.commit()


def get_analyzed_paths(conn: sqlite3.Connection) -> set[str]:
    """Return the set of all image paths that have been analyzed.

    Parameters
    ----------
    conn:
        An open SQLite connection.

    Returns
    -------
    A set of image_path strings.
    """
    rows = conn.execute("SELECT image_path FROM cloud_analysis").fetchall()
    return {row[0] for row in rows}


def search_cloud(conn: sqlite3.Connection, query: str) -> list[dict[str, str]]:
    """Search cloud analysis results across text columns.

    Performs a case-insensitive LIKE search across category, subcategory,
    subject, mood, and tags columns.

    Parameters
    ----------
    conn:
        An open SQLite connection.
    query:
        The search term.

    Returns
    -------
    A list of matching rows as dicts.
    """
    pattern = f"%{query}%"
    rows = conn.execute(
        """
        SELECT image_path, category, subcategory, subject, mood, tags
        FROM cloud_analysis
        WHERE category    LIKE ?
           OR subcategory LIKE ?
           OR subject     LIKE ?
           OR mood        LIKE ?
           OR tags        LIKE ?
        """,
        (pattern, pattern, pattern, pattern, pattern),
    ).fetchall()

    results: list[dict[str, str]] = []
    for row in rows:
        results.append({
            "image_path": row[0],
            "category": row[1],
            "subcategory": row[2],
            "subject": row[3],
            "mood": row[4],
            "tags": row[5],
        })
    return results


def get_stats(conn: sqlite3.Connection) -> dict:
    """Return aggregate statistics for cloud analysis.

    Parameters
    ----------
    conn:
        An open SQLite connection.

    Returns
    -------
    A dict with keys: total_analyzed, total_input_tokens,
    total_output_tokens, category_breakdown.
    """
    total_analyzed: int = conn.execute(
        "SELECT COUNT(*) FROM cloud_analysis"
    ).fetchone()[0]

    token_row = conn.execute(
        "SELECT COALESCE(SUM(input_tokens), 0), COALESCE(SUM(output_tokens), 0) "
        "FROM cloud_analysis"
    ).fetchone()
    total_input_tokens: int = token_row[0]
    total_output_tokens: int = token_row[1]

    category_breakdown: dict[str, int] = {}
    for row in conn.execute(
        "SELECT category, COUNT(*) AS cnt FROM cloud_analysis "
        "GROUP BY category ORDER BY cnt DESC"
    ).fetchall():
        category_breakdown[row[0]] = row[1]

    return {
        "total_analyzed": total_analyzed,
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "category_breakdown": category_breakdown,
    }

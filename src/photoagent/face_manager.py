"""Face cluster management for PhotoAgent.

Provides listing, renaming, and querying of detected face clusters.
"""

from __future__ import annotations

from typing import Any

from photoagent.database import CatalogDB


class FaceManager:
    """Manage face clusters: list people, rename, and query photos by person."""

    def __init__(self, db: CatalogDB) -> None:
        self._db = db

    def list_people(self) -> list[dict[str, Any]]:
        """Return a list of face clusters with metadata.

        Returns
        -------
        List of dicts, each containing:
        cluster_id, label, photo_count, sample_filename.
        """
        rows = self._db._conn.execute(
            """
            SELECT
                f.cluster_id,
                f.cluster_label,
                COUNT(DISTINCT f.image_id) AS photo_count,
                MIN(i.filename) AS sample_filename
            FROM faces f
            JOIN images i ON f.image_id = i.id
            WHERE f.cluster_id IS NOT NULL
            GROUP BY f.cluster_id
            ORDER BY photo_count DESC
            """
        ).fetchall()

        return [
            {
                "cluster_id": row["cluster_id"],
                "label": row["cluster_label"] or f"Person {row['cluster_id']}",
                "photo_count": row["photo_count"],
                "sample_filename": row["sample_filename"],
            }
            for row in rows
        ]

    def rename_person(self, cluster_id_or_label: str, new_name: str) -> int:
        """Rename a face cluster.

        Parameters
        ----------
        cluster_id_or_label:
            Either a numeric cluster ID or the current label string.
        new_name:
            The new name to assign to the cluster.

        Returns
        -------
        Number of face records updated.
        """
        # Try as numeric cluster_id first
        updated = 0
        try:
            cluster_id = int(cluster_id_or_label)
            cursor = self._db._conn.execute(
                "UPDATE faces SET cluster_label = ? WHERE cluster_id = ?",
                (new_name, cluster_id),
            )
            updated = cursor.rowcount
            self._db._conn.commit()
            if updated > 0:
                return updated
        except (ValueError, TypeError):
            pass

        # Try as current label string
        cursor = self._db._conn.execute(
            "UPDATE faces SET cluster_label = ? WHERE cluster_label = ?",
            (new_name, cluster_id_or_label),
        )
        updated = cursor.rowcount
        self._db._conn.commit()
        return updated

    def get_person_photos(
        self, cluster_id_or_label: str
    ) -> list[dict[str, Any]]:
        """Return images containing a given person.

        Parameters
        ----------
        cluster_id_or_label:
            Either a numeric cluster ID or a cluster label string.

        Returns
        -------
        List of image dicts for photos containing the specified person.
        """
        image_ids: set[int] = set()

        # Try as numeric cluster_id
        try:
            cluster_id = int(cluster_id_or_label)
            rows = self._db._conn.execute(
                "SELECT DISTINCT image_id FROM faces WHERE cluster_id = ?",
                (cluster_id,),
            ).fetchall()
            image_ids.update(r["image_id"] for r in rows)
        except (ValueError, TypeError):
            pass

        # Also try as label (case-insensitive)
        rows = self._db._conn.execute(
            "SELECT DISTINCT image_id FROM faces WHERE cluster_label LIKE ?",
            (f"%{cluster_id_or_label}%",),
        ).fetchall()
        image_ids.update(r["image_id"] for r in rows)

        if not image_ids:
            return []

        placeholders = ", ".join("?" for _ in image_ids)
        rows = self._db._conn.execute(
            f"SELECT * FROM images WHERE id IN ({placeholders})",
            list(image_ids),
        ).fetchall()

        return [dict(r) for r in rows]

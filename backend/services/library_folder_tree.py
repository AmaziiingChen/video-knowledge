"""Shared recursive queries for the durable library-folder tree."""

from __future__ import annotations


def folder_tree_ids(connection, folder_id: str) -> list[str]:
    """Return one folder and every descendant in tree order."""
    rows = connection.execute(
        """
        WITH RECURSIVE folder_tree(id) AS (
            SELECT id FROM library_folders WHERE id = ?
            UNION ALL
            SELECT library_folders.id
            FROM library_folders
            JOIN folder_tree ON library_folders.parent_folder_id = folder_tree.id
        )
        SELECT id FROM folder_tree
        """,
        (folder_id,),
    ).fetchall()
    return [row["id"] for row in rows]

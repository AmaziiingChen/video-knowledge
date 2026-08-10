from __future__ import annotations

from pathlib import Path

from config import settings
from services.database import connect, initialize_database
from services.knowledge_library import attachments_root


def _is_within(path: Path, root: Path) -> bool:
    """Compare resolved paths so ``..`` and escaping symlinks cannot pass."""
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def is_under_data_dir(path: Path) -> bool:
    return _is_within(path, settings.data_dir)


def is_managed_local_media(path: Path, *, content_item_id: str | None = None) -> bool:
    """Allow managed roots or the exact original attachment owned by an item."""
    if is_under_data_dir(path) or _is_within(path, attachments_root()):
        return True
    if not content_item_id:
        return False
    try:
        initialize_database()
        with connect() as connection:
            row = connection.execute(
                """SELECT 1 FROM media_assets
                   WHERE content_item_id=? AND asset_type='original_file' AND path=? LIMIT 1""",
                (content_item_id, str(path)),
            ).fetchone()
        return row is not None
    except Exception:
        return False

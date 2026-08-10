from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from services.cache import ensure_preview_thumbnails
from services.database import connect, initialize_database


def set_content_status(content_item_id: str, status: str) -> None:
    try:
        initialize_database()
        with connect() as connection:
            connection.execute(
                "UPDATE content_items SET status = ?, updated_at = ? WHERE id = ?",
                (status, datetime.now().isoformat(), content_item_id),
            )
            connection.commit()
    except Exception:
        return


def set_content_title(content_item_id: str, title: str) -> None:
    safe_title = (title or "").strip()
    if not safe_title:
        return
    try:
        initialize_database()
        with connect() as connection:
            connection.execute(
                "UPDATE content_items SET title = ?, updated_at = ? WHERE id = ?",
                (safe_title, datetime.now().isoformat(), content_item_id),
            )
            connection.commit()
    except Exception:
        return


def prepare_preview_thumbnails(
    cache_dir: Path | None,
    video_path: Path | None,
    add_log: Callable[[str, str, str, float | None], None],
) -> None:
    if not cache_dir or not video_path:
        return
    add_log("download", "正在准备播放器预览缩略图…", "info", None)
    preview_path = ensure_preview_thumbnails(cache_dir, video_path)
    if preview_path:
        add_log("download", "播放器预览缩略图已生成", "success", None)

from __future__ import annotations

from pathlib import Path
import shutil

from services.cache import cache_dir_for_url, cache_meta_path
from services.xiaohongshu_client import note_id_from_url


def xiaohongshu_cache_dir(source_url: str) -> Path:
    """Return stable note-id cache storage, falling back to a legacy URL cache."""
    stable_dir = _stable_cache_dir(source_url)
    legacy_dir = cache_dir_for_url(source_url)
    if cache_meta_path(stable_dir).is_file() or not cache_meta_path(legacy_dir).is_file():
        return stable_dir
    return legacy_dir


def promote_xiaohongshu_cache(source_url: str) -> Path:
    """Preserve lightweight metadata before an expiring source URL is refreshed."""
    stable_dir = _stable_cache_dir(source_url)
    current_dir = xiaohongshu_cache_dir(source_url)
    if current_dir == stable_dir or not current_dir.exists():
        return stable_dir
    current_meta = cache_meta_path(current_dir)
    if current_meta.is_file():
        stable_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(current_meta, cache_meta_path(stable_dir))
    return stable_dir


def _stable_cache_dir(source_url: str) -> Path:
    note_id = note_id_from_url(source_url)
    if not note_id:
        return cache_dir_for_url(source_url)
    return cache_dir_for_url(f"xiaohongshu:note:{note_id}")

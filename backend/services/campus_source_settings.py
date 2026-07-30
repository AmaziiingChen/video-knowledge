from __future__ import annotations

from datetime import datetime, timezone
import json
import tempfile
from pathlib import Path
from threading import Lock

from config import settings
from services.campus_sources import CAMPUS_SOURCES, get_campus_source


SETTINGS_FILE = "campus_source_settings.json"
DEFAULT_INTERVAL_MINUTES = 360
ALLOWED_INTERVAL_MINUTES = {30, 60, 180, 360, 720, 1440}
MAX_SOURCE_GROUPS = 3
_SETTINGS_LOCK = Lock()


def campus_source_settings_path() -> Path:
    return settings.data_dir / SETTINGS_FILE


def load_campus_source_settings() -> list[dict[str, object]]:
    with _SETTINGS_LOCK:
        saved = _read_saved()
    return [_normalized(source.slug, saved.get(source.slug, {})) for source in CAMPUS_SOURCES]


def update_campus_source_setting(
    source_slug: str,
    *,
    enabled: bool | None = None,
    interval_minutes: int | None = None,
    auto_analyze: bool | None = None,
    notify_on_new: bool | None = None,
    group_ids: list[str] | None = None,
) -> dict[str, object]:
    get_campus_source(source_slug)
    if interval_minutes is not None and interval_minutes not in ALLOWED_INTERVAL_MINUTES:
        raise ValueError("检查频率必须是 30 分钟、1/3/6/12/24 小时之一")
    normalized_group_ids = None
    if group_ids is not None:
        normalized_group_ids = list(dict.fromkeys(
            str(value).strip() for value in group_ids if str(value).strip()
        ))
        if len(normalized_group_ids) > MAX_SOURCE_GROUPS:
            raise ValueError("一个校园来源最多加入 3 个分组")
    with _SETTINGS_LOCK:
        saved = _read_saved()
        current = dict(saved.get(source_slug, {}))
        if enabled is not None:
            current["enabled"] = bool(enabled)
        if interval_minutes is not None:
            current["interval_minutes"] = int(interval_minutes)
        if auto_analyze is not None:
            current["auto_analyze"] = bool(auto_analyze)
        if notify_on_new is not None:
            current["notify_on_new"] = bool(notify_on_new)
        if normalized_group_ids is not None:
            current["group_ids"] = normalized_group_ids
        saved[source_slug] = current
        _write_saved(saved)
    return _normalized(source_slug, current)


def record_campus_source_sync(
    source_slug: str,
    *,
    status: str,
    message: str = "",
    discovered: int = 0,
    created: int = 0,
) -> dict[str, object]:
    get_campus_source(source_slug)
    with _SETTINGS_LOCK:
        saved = _read_saved()
        current = dict(saved.get(source_slug, {}))
        current.update(
            {
                "last_sync_at": datetime.now(timezone.utc).isoformat(),
                "last_status": str(status or "unknown"),
                "last_message": str(message or "")[:500],
                "last_discovered": max(0, int(discovered or 0)),
                "last_created": max(0, int(created or 0)),
            }
        )
        saved[source_slug] = current
        _write_saved(saved)
    return _normalized(source_slug, current)


def enable_unconfigured_sources_for_digest() -> int:
    """Enable new registered sources once without overriding an explicit pause."""
    changed = 0
    with _SETTINGS_LOCK:
        saved = _read_saved()
        for source in CAMPUS_SOURCES:
            current = dict(saved.get(source.slug, {}))
            if "enabled" in current:
                continue
            current["enabled"] = True
            saved[source.slug] = current
            changed += 1
        if changed:
            _write_saved(saved)
    return changed


def _normalized(source_slug: str, value: object) -> dict[str, object]:
    source = get_campus_source(source_slug)
    raw = value if isinstance(value, dict) else {}
    interval = int(raw.get("interval_minutes") or DEFAULT_INTERVAL_MINUTES)
    if interval not in ALLOWED_INTERVAL_MINUTES:
        interval = DEFAULT_INTERVAL_MINUTES
    return {
        "slug": source.slug,
        "name": source.name,
        "base_url": source.base_url,
        "sections": list(source.sections),
        "enabled": bool(raw.get("enabled", False)),
        "interval_minutes": interval,
        "auto_analyze": bool(raw.get("auto_analyze", False)),
        "notify_on_new": bool(raw.get("notify_on_new", False)),
        "group_ids": list(dict.fromkeys(
            str(value).strip()
            for value in (raw.get("group_ids") if isinstance(raw.get("group_ids"), list) else [])
            if str(value).strip()
        ))[:MAX_SOURCE_GROUPS],
        "last_sync_at": str(raw.get("last_sync_at") or ""),
        "last_status": str(raw.get("last_status") or "idle"),
        "last_message": str(raw.get("last_message") or ""),
        "last_discovered": max(0, int(raw.get("last_discovered") or 0)),
        "last_created": max(0, int(raw.get("last_created") or 0)),
    }


def _read_saved() -> dict[str, dict[str, object]]:
    path = campus_source_settings_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): value for key, value in data.items() if isinstance(value, dict)}


def _write_saved(data: dict[str, dict[str, object]]) -> None:
    path = campus_source_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.stem}-",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.flush()
        temporary = Path(handle.name)
    temporary.replace(path)


__all__ = [
    "ALLOWED_INTERVAL_MINUTES",
    "MAX_SOURCE_GROUPS",
    "enable_unconfigured_sources_for_digest",
    "load_campus_source_settings",
    "record_campus_source_sync",
    "update_campus_source_setting",
]

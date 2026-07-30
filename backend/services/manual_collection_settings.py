"""Local policy for links the user explicitly saves for later reading."""
from __future__ import annotations

import json

from config import settings


_FILE_NAME = "manual_collection_settings.json"
_DEFAULTS = {"auto_summarize": True}


def _path():
    return settings.data_dir / _FILE_NAME


def manual_collection_settings() -> dict[str, bool]:
    try:
        raw = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    return {"auto_summarize": bool(raw.get("auto_summarize", _DEFAULTS["auto_summarize"]))}


def save_manual_collection_settings(*, auto_summarize: bool) -> dict[str, bool]:
    values = {"auto_summarize": bool(auto_summarize)}
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
    return values


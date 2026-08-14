from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

from config import settings

SETTINGS_FILE = "obsidian_settings.json"
DEFAULT_AUTO_WRITE = False
_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def obsidian_settings_path() -> Path:
    return settings.data_dir / SETTINGS_FILE


def load_obsidian_settings() -> dict:
    path = obsidian_settings_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def markdown_output_settings() -> dict[str, object]:
    saved = load_obsidian_settings()
    default_path = (settings.data_dir / "markdown").expanduser().resolve()
    vault_value = str(saved.get("vault_path") or default_path).strip()
    export_value = str(saved.get("export_path") or vault_value or default_path).strip()
    # Existing installations had no switch and always wrote automatically.
    # Preserve that behavior only when an old explicit path is present; new
    # installations start with automatic writes disabled.
    auto_write = bool(saved.get("auto_write")) if "auto_write" in saved else bool(saved.get("vault_path"))
    return {
        "vault_path": str(Path(vault_value).expanduser().resolve()),
        "export_path": str(Path(export_value).expanduser().resolve()),
        "auto_write": auto_write,
    }


def default_content_library_root() -> Path:
    """The private fallback when no external library directory is enabled."""
    return (settings.data_dir / "library").expanduser().resolve()


def content_storage_root_for(*, vault_path: str | Path, auto_write: bool) -> Path:
    """Resolve the parent containing the managed ``library`` and ``attachments``."""
    if not auto_write:
        return settings.data_dir.expanduser().resolve()
    return Path(vault_path).expanduser().resolve()


def content_library_root_for(*, vault_path: str | Path, auto_write: bool) -> Path:
    """Resolve the canonical Markdown root for one settings snapshot."""
    return content_storage_root_for(vault_path=vault_path, auto_write=auto_write) / "library"


def content_library_root() -> Path:
    output_settings = markdown_output_settings()
    return content_library_root_for(
        vault_path=str(output_settings["vault_path"]),
        auto_write=bool(output_settings["auto_write"]),
    )


def automatic_markdown_write_enabled() -> bool:
    return bool(markdown_output_settings()["auto_write"])


def export_markdown_document(*, title: str, markdown: str) -> tuple[Path, bool]:
    output_settings = markdown_output_settings()
    export_dir = resolve_obsidian_vault_path(str(output_settings["export_path"]))
    filename = _safe_markdown_filename(title)
    destination = export_dir / filename
    overwritten = destination.exists()
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=export_dir,
        prefix=f".{destination.stem}-",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(markdown)
        handle.flush()
        temporary_path = Path(handle.name)
    temporary_path.replace(destination)
    return destination, overwritten


def _safe_markdown_filename(title: str) -> str:
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(title or "").strip())
    stem = stem.rstrip(" .")[:120] or "AI 对话"
    if stem.upper() in _WINDOWS_RESERVED_NAMES:
        stem = f"_{stem}"
    return f"{stem}.md"


def resolve_obsidian_vault_path(value: str | Path) -> Path:
    raw_path = Path(str(value).strip()).expanduser()
    if not raw_path.is_absolute():
        raise ValueError("自动保存目录必须是本机绝对路径")
    resolved = raw_path.resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    if not resolved.is_dir():
        raise ValueError("自动保存目录不是文件夹")
    probe = resolved / ".knowledgehub-write-test"
    try:
        probe.touch(exist_ok=True)
        probe.unlink(missing_ok=True)
    except OSError as exc:
        raise ValueError("自动保存目录不可写") from exc
    return resolved


def apply_saved_obsidian_settings() -> Path:
    output_settings = markdown_output_settings()
    settings.obsidian_vault = resolve_obsidian_vault_path(str(output_settings["vault_path"]))
    return settings.obsidian_vault


def is_managed_obsidian_note_path(path_value: str | Path) -> bool:
    """Whether an absolute note path belongs to a current or previous app vault."""
    path = Path(path_value).expanduser().resolve()
    for vault in managed_obsidian_vault_paths():
        try:
            path.relative_to(vault)
            return True
        except ValueError:
            continue
    return False


def managed_obsidian_vault_paths() -> tuple[Path, ...]:
    """Return validated current and historical vault roots used by this app."""
    saved = load_obsidian_settings()
    raw_paths = saved.get("managed_vault_paths")
    values = list(raw_paths) if isinstance(raw_paths, list) else []
    values.extend([saved.get("vault_path"), str(settings.obsidian_vault)])
    resolved_paths: list[Path] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            continue
        resolved = candidate.resolve()
        if resolved not in resolved_paths:
            resolved_paths.append(resolved)
    return tuple(resolved_paths)


def save_obsidian_settings(
    vault_path: str | Path,
    *,
    export_path: str | Path,
    auto_write: bool,
    recover_existing: bool = False,
) -> dict[str, object]:
    previous = markdown_output_settings()
    resolved = resolve_obsidian_vault_path(vault_path)
    resolved_export = resolve_obsidian_vault_path(export_path)
    previous_root = content_library_root_for(
        vault_path=str(previous["vault_path"]),
        auto_write=bool(previous["auto_write"]),
    )
    destination_root = content_library_root_for(
        vault_path=resolved,
        auto_write=bool(auto_write),
    )
    # Only files indexed by the application are moved.  A selected directory
    # can contain a user's own Obsidian notes, which must never be treated as
    # KnowledgeHub content merely because they share a parent folder.
    from services.knowledge_library import (
        align_sync_records_to_canonical_documents,
        migrate_managed_library_storage,
    )

    migration = migrate_managed_library_storage(
        source_roots=(previous_root, default_content_library_root()),
        destination_root=destination_root,
    )
    from services.existing_library_recovery import (
        empty_recovery_stats,
        recover_existing_library,
    )

    recovery = (
        recover_existing_library(resolved)
        if auto_write and recover_existing
        else empty_recovery_stats()
    )
    if auto_write:
        align_sync_records_to_canonical_documents()
    path = obsidian_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    managed_paths = [str(item) for item in managed_obsidian_vault_paths()]
    if str(resolved) not in managed_paths:
        managed_paths.append(str(resolved))
    payload = {
        "vault_path": str(resolved),
        "export_path": str(resolved_export),
        "auto_write": bool(auto_write),
        "managed_vault_paths": managed_paths,
        "migrated_documents": migration["documents"],
        "migrated_attachments": migration["attachments"],
        **recovery,
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    settings.obsidian_vault = resolved
    return payload

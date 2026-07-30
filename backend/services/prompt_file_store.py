"""Local Markdown mirror for editable prompt templates.

Prompt text lives in ``data/prompts`` so it can be inspected and edited with a
normal editor. SQLite remains a disposable runtime index for the existing UI
and prompt lookup APIs. The body of a Markdown file is the prompt itself;
frontmatter is intentionally managed by the application.
"""

from __future__ import annotations

import json
import re
import sqlite3
import tempfile
import uuid
from hashlib import sha256
from pathlib import Path

from config import settings
from services.database import utc_now_iso
from services.prompt_templates import PromptTemplateRecord, PromptTemplateRepository


_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", re.DOTALL)


def prompt_root() -> Path:
    root = settings.data_dir / "prompts"
    root.mkdir(parents=True, exist_ok=True)
    return root


def sync_prompt_files(connection: sqlite3.Connection) -> None:
    """Import external body edits, then create Markdown files for missing rows."""
    repository = PromptTemplateRepository(connection)
    records = repository.list_templates()
    paths_by_id = _existing_prompt_paths()
    for record in records:
        path = paths_by_id.get(record.id)
        if path and path.exists():
            external = _read_prompt_body(path)
            if external is not None and external != record.template:
                record = repository.update_template(record.id, template=external)
        else:
            write_prompt_file(record)


def write_prompt_file(record: PromptTemplateRecord) -> Path:
    path = _existing_prompt_paths().get(record.id) or _path_for(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    frontmatter = {
        "id": record.id,
        "name": record.name,
        "task_type": record.task_type,
        "version": record.version,
        "active": bool(record.is_active),
        "variables_schema": _schema_value(record.variables_schema),
    }
    metadata = "\n".join(f"{key}: {_yaml(value)}" for key, value in frontmatter.items())
    _atomic_write(path, f"---\n{metadata}\n---\n\n{record.template.rstrip()}\n")
    return path


def prompt_file_path(template_id: str) -> Path | None:
    return _existing_prompt_paths().get(template_id)


def remove_prompt_files(template_ids: list[str]) -> None:
    """Remove local Markdown mirrors after their templates are permanently deleted."""
    if not template_ids:
        return
    paths = _existing_prompt_paths()
    for template_id in template_ids:
        path = paths.get(str(template_id))
        if not path:
            continue
        path.unlink(missing_ok=True)
        _prune_empty_prompt_directories(path.parent)


def managed_prompt_text(task_type: str, fallback: str) -> str:
    """Read an active local prompt while retaining an exact code fallback."""
    try:
        from services.database import connect, ensure_database_initialized

        ensure_database_initialized()
        with connect() as connection:
            sync_prompt_files(connection)
            connection.commit()
            record = PromptTemplateRepository(connection).get_active_template(task_type)
            return record.template if record else fallback
    except Exception:
        return fallback


def sync_report_prompt_files(connection: sqlite3.Connection) -> None:
    """Import external edits for the context and editorial adapters of every group."""
    rows = connection.execute(
        """SELECT p.id, p.group_id, p.report_type, p.template, p.template_version,
                  COALESCE(NULLIF(p.display_name, ''), '区间报告') AS display_name,
                  g.name AS group_name
           FROM wechat_report_prompts p JOIN wechat_subscription_groups g ON g.id = p.group_id
           WHERE p.report_type IN (
               'group_context', 'group_report_section_plan', 'group_report_event_ledger', 'group_report_section_writer',
               'group_report_overview'
           )"""
    ).fetchall()
    paths = _existing_prompt_paths()
    for row in rows:
        identifier = str(row["id"])
        path = paths.get(identifier)
        if path and path.exists():
            external = _read_prompt_body(path)
            if external is not None and external != str(row["template"]):
                now = utc_now_iso()
                connection.execute(
                    "UPDATE wechat_report_prompts SET template=?, template_version='custom', updated_at=? WHERE id=?",
                    (external, now, identifier),
                )
                if connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='wechat_report_prompt_versions'"
                ).fetchone():
                    connection.execute(
                        """INSERT OR IGNORE INTO wechat_report_prompt_versions
                           (id,prompt_id,group_id,report_type,template,template_hash,
                            template_version,display_name,change_kind,created_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (
                            uuid.uuid4().hex,
                            identifier,
                            row["group_id"],
                            row["report_type"],
                            external,
                            sha256(external.encode("utf-8")).hexdigest(),
                            "custom",
                            row["display_name"],
                            "file_sync",
                            now,
                        ),
                    )
        else:
            write_report_prompt_file(row)


def write_report_prompt_file(row: sqlite3.Row | dict) -> Path:
    identifier = str(row["id"])
    directory = prompt_root() / "group-reports" / _safe_component(str(row["group_name"]))
    path = directory / f"{_report_prompt_filename(str(row['report_type']))}.md"
    old_path = _existing_prompt_paths().get(identifier)
    # Group names are normally unique and intentionally map to the concise
    # user-facing filename. Keep the identifier only if a legacy database
    # contains two groups with the same name.
    if path.exists() and path != old_path:
        path = directory / f"{_report_prompt_filename(str(row['report_type']))}--{identifier[:12]}.md"
    if old_path and old_path != path:
        old_path.unlink(missing_ok=True)
        _prune_empty_prompt_directories(old_path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "id": identifier,
        "name": str(row["display_name"]),
        "task_type": "wechat_reports",
        "report_type": str(row["report_type"]),
        "group_id": str(row["group_id"]),
        "group_name": str(row["group_name"]),
        "version": str(row["template_version"]),
        "variables": ["articles"],
    }
    head = "\n".join(f"{key}: {_yaml(value)}" for key, value in metadata.items())
    _atomic_write(path, f"---\n{head}\n---\n\n{str(row['template']).rstrip()}\n")
    return path


def _report_prompt_filename(report_type: str) -> str:
    return {
        "group_context": "组别说明",
        "group_report_section_plan": "栏目规划",
        "group_report_event_ledger": "事件事实账本",
        "group_report_section_writer": "栏目写作",
        "group_report_overview": "概览写作",
    }.get(report_type, _safe_component(report_type))


def remove_report_prompt_files(prompt_ids: list[str]) -> None:
    """Remove Markdown mirrors for report prompts deleted from the runtime index."""
    if not prompt_ids:
        return
    paths = _existing_prompt_paths()
    for identifier in prompt_ids:
        path = paths.get(str(identifier))
        if not path:
            continue
        path.unlink(missing_ok=True)
        _prune_empty_prompt_directories(path.parent)


def _prune_empty_prompt_directories(path: Path) -> None:
    root = prompt_root()
    while path != root and path.is_relative_to(root):
        try:
            path.rmdir()
        except OSError:
            return
        path = path.parent


def _existing_prompt_paths() -> dict[str, Path]:
    matches: dict[str, Path] = {}
    for path in prompt_root().rglob("*.md"):
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        parsed = _FRONTMATTER.match(content)
        if not parsed:
            continue
        identifier = re.search(r"^id:\s*[\"']?([^\s\"']+)", parsed.group(1), re.MULTILINE)
        if identifier:
            matches[identifier.group(1)] = path
    return matches


def _read_prompt_body(path: Path) -> str | None:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None
    parsed = _FRONTMATTER.match(content)
    if not parsed:
        return None
    body = parsed.group(2).strip()
    return body or None


def _path_for(record: PromptTemplateRecord) -> Path:
    directory = prompt_root() / _safe_component(record.task_type)
    return directory / f"{_safe_component(record.name)[:80]}--{record.id[:12]}.md"


def _safe_component(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value or "").strip())
    return cleaned.rstrip(" .") or "untitled"


def _schema_value(value: str | None) -> object:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return value
    return parsed


def _yaml(value: object) -> str:
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def _atomic_write(path: Path, text: str) -> None:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.stem}-", suffix=".tmp", delete=False) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    temporary.replace(path)

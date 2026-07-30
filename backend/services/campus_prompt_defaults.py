"""Registration metadata for internal campus-report prompt nodes."""

from __future__ import annotations

import sqlite3

from services.prompt_file_store import write_prompt_file
from services.prompt_templates import PromptTemplateRepository


def campus_prompt_defaults() -> list[dict[str, object]]:
    # Lazy imports avoid a startup import cycle with report services.
    from services.campus_digest_generation import FACT_SYSTEM_PROMPT, RELATION_SYSTEM_PROMPT, BRIEF_SYSTEM_PROMPT
    from services.campus_digest_editorial import (
        SECTION_EDITOR_SYSTEM_PROMPT, SECTION_REPAIR_SYSTEM_PROMPT,
        OVERVIEW_SYSTEM_PROMPT, OVERVIEW_REPAIR_SYSTEM_PROMPT, AUDIT_SYSTEM_PROMPT,
    )
    return [
        {"name": "发布卡提取", "task_type": "campus_fact_card", "template": FACT_SYSTEM_PROMPT},
        {"name": "同源内容判断", "task_type": "campus_duplicate_relation", "template": RELATION_SYSTEM_PROMPT},
        {"name": "事件摘要（兼容）", "task_type": "campus_event_brief", "template": BRIEF_SYSTEM_PROMPT},
        {"name": "栏目生成", "task_type": "campus_category_section", "template": SECTION_EDITOR_SYSTEM_PROMPT},
        {"name": "栏目修复", "task_type": "campus_section_repair", "template": SECTION_REPAIR_SYSTEM_PROMPT},
        {"name": "概览生成", "task_type": "campus_overview", "template": OVERVIEW_SYSTEM_PROMPT},
        {"name": "概览修复", "task_type": "campus_overview_repair", "template": OVERVIEW_REPAIR_SYSTEM_PROMPT},
        {"name": "事实与引用审校", "task_type": "campus_audit", "template": AUDIT_SYSTEM_PROMPT},
    ]


def ensure_campus_prompt_templates(connection: sqlite3.Connection) -> None:
    repository = PromptTemplateRepository(connection)
    for item in campus_prompt_defaults():
        task_type = str(item["task_type"])
        default_key = campus_default_key(task_type)
        row = connection.execute(
            "SELECT id, default_key FROM prompt_templates WHERE task_type=? AND version='campus-v1' AND deleted_at IS NULL LIMIT 1",
            (task_type,),
        ).fetchone()
        if row:
            if not row["default_key"]:
                connection.execute(
                    "UPDATE prompt_templates SET default_key=? WHERE id=?",
                    (default_key, row["id"]),
                )
            continue
        record = repository.create_template(
            name=str(item["name"]), task_type=task_type, version="campus-v1",
            template=str(item["template"]),
            variables_schema={"managed": True, "internal_campus_report_node": True}, is_active=True,
            default_key=default_key,
        )
        write_prompt_file(record)


def campus_default_key(task_type: str) -> str:
    return f"campus:{task_type}"


def campus_default_for_key(default_key: str | None) -> dict[str, object] | None:
    if not default_key or not default_key.startswith("campus:"):
        return None
    task_type = default_key.removeprefix("campus:")
    return next((item for item in campus_prompt_defaults() if item["task_type"] == task_type), None)

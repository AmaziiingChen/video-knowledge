from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from config import settings
from services import database as database_service
from services.database import SCHEMA_VERSION, connect, initialize_database
from services.prompt_file_store import prompt_file_path
from services.prompt_templates import (
    DEFAULT_PROMPT_TEMPLATES,
    DEFAULT_SUMMARY_PROMPT,
    PromptTemplateRepository,
    default_prompt_key,
    seed_default_prompt_templates,
    sync_builtin_prompt_definitions,
)
from services.prompt_workspace import PromptWorkspaceRepository
from services.wechat_reports import create_group, list_report_prompts, update_report_prompt
from services.system_prompt_catalog import list_fixed_system_prompts


def test_prompt_workspace_migration_adds_tree_and_trash_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()

    with connect() as connection:
        tables = {
            str(row["name"])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        prompt_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(prompt_templates)").fetchall()
        }
        report_columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(wechat_report_prompts)").fetchall()
        }

    assert "prompt_folders" in tables
    assert {"folder_id", "sort_order", "deleted_at", "trash_batch_id"} <= prompt_columns
    assert "display_name" in report_columns


def test_fixed_system_prompt_catalog_is_readable_and_has_no_mutation_surface():
    prompts = list_fixed_system_prompts()

    prompt_ids = {prompt["id"] for prompt in prompts}
    assert {
        "source-context:core-guardrail",
        "wechat-report:writer",
        "wechat-report:fact-extraction",
        "wechat-report:coverage-audit",
        "fallback:group-report:source-summary",
        "fallback:group-report:section-plan",
        "fallback:group-report:section-writer",
        "fallback:group-report:overview",
    } <= prompt_ids
    assert any(prompt["category"].startswith("系统兜底") for prompt in prompts)
    assert all(prompt["template"].strip() and prompt["description"].strip() for prompt in prompts)


def test_last_prompt_is_protected_and_folder_trash_is_restorable(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()

    with connect() as connection:
        templates = PromptTemplateRepository(connection)
        workspace = PromptWorkspaceRepository(connection)
        original = templates.get_active_template("summary")
        assert original is not None

        with pytest.raises(ValueError, match="至少保留一个"):
            templates.delete_template(original.id)

        parent = workspace.create_folder(name="方法", task_type="summary")
        child = workspace.create_folder(
            name="复盘",
            task_type="summary",
            parent_folder_id=parent.id,
        )
        custom = templates.create_template(
            name="复盘模板",
            task_type="summary",
            version="v-test",
            template="测试提示词",
            folder_id=child.id,
        )
        templates.activate_template(custom.id)
        connection.commit()

        workspace.trash_folder(parent.id)
        connection.commit()

        assert templates.get_active_template("summary").id == original.id
        trash = workspace.list_trash()
        entry = next(item for item in trash if item["id"] == parent.id)
        assert entry["entry_type"] == "folder"
        assert entry["item_count"] == 3
        assert all(folder.id != parent.id for folder in workspace.list_folders())
        assert all(template.id != custom.id for template in templates.list_templates())

        workspace.restore_trash("folder", parent.id)
        connection.commit()
        assert workspace.get_folder(parent.id).name == "方法"
        assert workspace.get_folder(child.id).parent_folder_id == parent.id
        assert templates.get_template(custom.id).folder_id == child.id

        workspace.trash_folder(parent.id)
        workspace.permanently_delete_trash("folder", parent.id)
        connection.commit()
        with pytest.raises(LookupError):
            workspace.get_folder(parent.id, include_deleted=True)
        with pytest.raises(LookupError):
            templates.get_template(custom.id, include_deleted=True)


def test_prompt_tree_rejects_cross_task_moves_and_cycles(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()

    with connect() as connection:
        templates = PromptTemplateRepository(connection)
        workspace = PromptWorkspaceRepository(connection)
        summary_parent = workspace.create_folder(name="总结目录", task_type="summary")
        summary_child = workspace.create_folder(
            name="总结子目录",
            task_type="summary",
            parent_folder_id=summary_parent.id,
        )
        article_folder = workspace.create_folder(name="文章目录", task_type="article_summary")
        template = templates.create_template(
            name="总结草稿",
            task_type="summary",
            version="v-test",
            template="测试提示词",
        )

        with pytest.raises(ValueError, match="同一功能"):
            templates.update_template(template.id, folder_id=article_folder.id, update_folder=True)
        with pytest.raises(ValueError, match="子文件夹"):
            workspace.update_folder(
                summary_parent.id,
                parent_folder_id=summary_child.id,
                update_parent=True,
            )


def test_group_report_prompt_display_name_can_change_without_rewriting_content(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    group = create_group("校园生活")
    original = next(
        prompt
        for prompt in list_report_prompts()
        if prompt["group_id"] == group["id"] and prompt["report_type"] == "group_context"
    )
    assert (tmp_path / "prompts" / "group-reports" / "校园生活" / "组别说明.md").exists()

    updated = update_report_prompt(
        group["id"],
        "group_context",
        None,
        display_name="校园生活说明",
    )

    assert updated["display_name"] == "校园生活说明"
    assert updated["template"] == original["template"]


def test_renaming_builtin_prompt_keeps_default_identity_and_reset(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    with connect() as connection:
        templates = PromptTemplateRepository(connection)
        original = templates.get_active_template("summary")
        assert original is not None
        templates.update_template(
            original.id,
            name="课程视频总结",
            template="这是改名后继续编辑过的提示词。",
        )
        # Simulate a database created before stable built-in identities existed.
        connection.execute("UPDATE prompt_templates SET default_key = NULL WHERE id = ?", (original.id,))
        connection.commit()

    with connect() as connection:
        # Database maintenance performs this repair during the corresponding
        # schema migration, not on every ordinary request.
        seed_default_prompt_templates(connection)
        connection.commit()
        templates = PromptTemplateRepository(connection).list_templates("summary")
        assert [(item.id, item.name) for item in templates] == [
            (original.id, "课程视频总结")
        ]

    from routers.prompts import reset_prompt_template

    reset = asyncio.run(reset_prompt_template(original.id))
    assert reset.name == "课程视频总结"
    assert reset.template == DEFAULT_SUMMARY_PROMPT


def test_newer_builtin_prompt_revision_cannot_be_rolled_back_by_stale_process(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    definition = next(
        item
        for item in DEFAULT_PROMPT_TEMPLATES
        if item["task_type"] == "wechat_cover_image"
    )
    old_template = "旧进程中的写实摄影封面提示词"
    new_template = "新进程中的现代平面编辑插画提示词"
    monkeypatch.setitem(definition, "template", old_template)
    monkeypatch.setitem(definition, "code_revision", 5)
    initialize_database()

    monkeypatch.setitem(definition, "template", new_template)
    monkeypatch.setitem(definition, "code_revision", 6)
    with connect() as connection:
        sync_builtin_prompt_definitions(connection)
        connection.commit()
        published = PromptTemplateRepository(connection).get_active_template(
            "wechat_cover_image"
        )
        state = connection.execute(
            """SELECT template_hash, code_revision
               FROM prompt_code_sync_state WHERE default_key=?""",
            (default_prompt_key(definition),),
        ).fetchone()

    assert published is not None
    assert published.template == new_template
    assert state["code_revision"] == 6
    mirror = prompt_file_path(published.id)
    assert mirror is not None
    assert new_template in mirror.read_text(encoding="utf-8")

    # Simulate a request still being served by the pre-update process.
    monkeypatch.setitem(definition, "template", old_template)
    monkeypatch.setitem(definition, "code_revision", 5)
    with connect() as connection:
        sync_builtin_prompt_definitions(connection)
        connection.commit()
        retained = PromptTemplateRepository(connection).get_active_template(
            "wechat_cover_image"
        )
        retained_state = connection.execute(
            """SELECT template_hash, code_revision
               FROM prompt_code_sync_state WHERE default_key=?""",
            (default_prompt_key(definition),),
        ).fetchone()

    assert retained is not None
    assert retained.template == new_template
    assert retained_state["code_revision"] == 6
    assert new_template in mirror.read_text(encoding="utf-8")


def test_cover_style_prompt_migration_recovers_poisoned_and_missing_sync_state(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    db_path = initialize_database()
    definitions = {
        str(item["task_type"]): item
        for item in DEFAULT_PROMPT_TEMPLATES
        if item["task_type"] in {"wechat_cover_planner", "wechat_cover_image"}
    }
    planner_key = default_prompt_key(definitions["wechat_cover_planner"])
    image_key = default_prompt_key(definitions["wechat_cover_image"])

    with connect() as connection:
        connection.execute(
            """UPDATE prompt_templates SET template='旧版双风格策划提示词'
               WHERE default_key=?""",
            (planner_key,),
        )
        connection.execute(
            """UPDATE prompt_templates SET template='旧版双风格生图提示词'
               WHERE default_key=?""",
            (image_key,),
        )
        # Reproduce both observed failure modes: revision 5 was recorded while
        # old text remained live, or the sync-state row never existed.
        connection.execute(
            """UPDATE prompt_code_sync_state
               SET template_hash='', code_revision=5
               WHERE default_key=?""",
            (planner_key,),
        )
        connection.execute(
            "DELETE FROM prompt_code_sync_state WHERE default_key=?",
            (image_key,),
        )
        connection.execute("DELETE FROM schema_migrations WHERE version >= 73")
        connection.commit()

    database_service._INITIALIZED_DATABASES.discard(db_path.resolve())
    initialize_database()

    with connect() as connection:
        rows = connection.execute(
            """SELECT task_type, template
               FROM prompt_templates
               WHERE task_type IN ('wechat_cover_planner', 'wechat_cover_image')
                 AND default_key IS NOT NULL AND deleted_at IS NULL"""
        ).fetchall()
        states = connection.execute(
            """SELECT default_key, code_revision
               FROM prompt_code_sync_state
               WHERE default_key IN (?, ?)""",
            (planner_key, image_key),
        ).fetchall()
        schema_version = connection.execute(
            "SELECT MAX(version) AS version FROM schema_migrations"
        ).fetchone()["version"]

    assert schema_version == SCHEMA_VERSION
    assert {row["task_type"] for row in rows} == {
        "wechat_cover_planner",
        "wechat_cover_image",
    }
    assert all("[[STYLE:transparent_watercolor]]" in row["template"] for row in rows)
    assert {row["default_key"]: row["code_revision"] for row in states} == {
        planner_key: 7,
        image_key: 7,
    }
    assert all(int(definition["code_revision"]) == 7 for definition in definitions.values())

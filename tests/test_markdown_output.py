import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient

from config import settings
from main import app
from services.database import connect, initialize_database
from services.markdown_sync import replace_content_summary_and_sync, save_markdown_draft_and_sync
from services.knowledge_library import write_content_markdown_document
from services.obsidian_settings import save_obsidian_settings
from services.repository import ContentRepository
from services.search_index import _markdown_search_fields


def test_new_install_keeps_markdown_as_draft_until_auto_write_is_enabled(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "obsidian_vault", tmp_path / "auto")
    initialize_database()
    with connect() as connection:
        item = ContentRepository(connection).create_content_item(
            source_provider="campus",
            content_type="article",
            source_url="https://example.edu/notice/1",
            canonical_source_id="notice-1",
            title="通知",
        )
        connection.commit()

    note_path = settings.obsidian_vault / "通知.md"
    state = save_markdown_draft_and_sync(
        markdown="# 通知\n\n正文",
        title="通知",
        obsidian_path=note_path,
        content_item_id=item.id,
    )

    assert state.sync_status == "dirty"
    assert Path(state.markdown_draft_path).exists()
    assert not note_path.exists()


def test_markdown_content_metadata_reports_the_actual_document_size(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "obsidian_vault", tmp_path / "auto")
    initialize_database()
    with connect() as connection:
        item = ContentRepository(connection).create_content_item(
            source_provider="wechat",
            content_type="article",
            source_url="https://mp.weixin.qq.com/s/example",
            canonical_source_id="article-size",
            title="正文大小",
        )
        connection.commit()

    markdown = "# 正文大小\n\n这里是一段用于验证 Markdown 文件大小的正文。\n"
    state = save_markdown_draft_and_sync(
        markdown=markdown,
        title=item.title,
        obsidian_path=settings.obsidian_vault / "正文大小.md",
        content_item_id=item.id,
    )
    response = TestClient(app).get(f"/api/markdown/content/{item.id}")

    assert response.status_code == 200
    assert response.json()["markdown_size_bytes"] == Path(state.markdown_draft_path).stat().st_size


def test_markdown_content_export_supports_chinese_managed_paths(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "中文数据")
    monkeypatch.setattr(settings, "obsidian_vault", tmp_path / "中文资料库")
    initialize_database()
    with connect() as connection:
        item = ContentRepository(connection).create_content_item(
            source_provider="wechat",
            content_type="article",
            source_url="https://mp.weixin.qq.com/s/chinese-export",
            canonical_source_id="chinese-export",
            title="中文导出",
        )
        connection.commit()

    markdown = "# 中文导出\n\n正文内容。\n"
    save_markdown_draft_and_sync(
        markdown=markdown,
        title=item.title,
        obsidian_path=settings.obsidian_vault / "中文导出.md",
        content_item_id=item.id,
    )

    response = TestClient(app).get(f"/api/markdown/content/{item.id}/export")

    assert response.status_code == 200
    assert response.text == markdown
    assert "x-markdown-draft-path" not in response.headers
    assert "x-obsidian-path" not in response.headers


def test_saved_source_markdown_is_promoted_and_reports_its_actual_size(monkeypatch, tmp_path):
    """Saved WeChat body/OCR documents must not need an AI summary first."""
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "obsidian_vault", tmp_path / "auto")
    initialize_database()
    with connect() as connection:
        item = ContentRepository(connection).create_content_item(
            source_provider="wechat",
            content_type="article",
            source_url="https://mp.weixin.qq.com/s/source-document",
            canonical_source_id="source-document-size",
            title="图文与 OCR 正文",
        )
        connection.commit()

    markdown = "# 图文与 OCR 正文\n\n正文内容。\n\n图片 OCR：识别出的文字。\n"
    path = write_content_markdown_document(item.id, markdown)
    client = TestClient(app)

    markdown_response = client.get(f"/api/markdown/content/{item.id}")
    item_response = client.get(f"/api/content/item/{item.id}")

    assert markdown_response.status_code == 200
    assert markdown_response.json()["markdown_draft_path"] == str(path)
    assert markdown_response.json()["markdown_size_bytes"] == path.stat().st_size
    assert item_response.status_code == 200
    assert item_response.json()["markdown_draft_path"] == str(path)
    assert item_response.json()["markdown_size_bytes"] == path.stat().st_size


def test_conversation_export_uses_configured_folder_and_reports_overwrite(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    export_dir = tmp_path / "exports"
    auto_dir = tmp_path / "auto"
    save_obsidian_settings(auto_dir, export_path=export_dir, auto_write=False)
    client = TestClient(app)

    first = client.post(
        "/api/markdown/export",
        json={"title": "课程:问答", "markdown": "# 第一版\n"},
    )
    second = client.post(
        "/api/markdown/export",
        json={"title": "课程:问答", "markdown": "# 第二版\n"},
    )

    assert first.status_code == 200
    assert first.json()["overwritten"] is False
    assert second.json()["overwritten"] is True
    destination = Path(second.json()["path"])
    assert destination.parent == export_dir.resolve()
    assert ":" not in destination.name
    assert destination.read_text(encoding="utf-8") == "# 第二版\n"


def test_assistant_sections_keep_inner_headings_and_never_leak_qa_to_reader_data(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "obsidian_vault", tmp_path / "auto")
    initialize_database()
    with connect() as connection:
        item = ContentRepository(connection).create_content_item(
            source_provider="wechat_report",
            content_type="report",
            canonical_source_id="report:section-contract",
            title="区段契约周报",
        )
        connection.commit()
    save_markdown_draft_and_sync(
        markdown=(
            "# 区段契约周报\n\n## AI 摘要\n\n## 旧栏目\n\n旧内容。\n\n"
            "## 追问记录\n\n### 对话 1（当前）\n\n**问：** 旧问题\n\n**答：** 旧回答\n"
        ),
        title=item.title,
        obsidian_path=settings.obsidian_vault / "区段契约周报.md",
        content_item_id=item.id,
    )

    state = replace_content_summary_and_sync(item.id, "## 新栏目\n\n新内容。")
    summary, source_text = _markdown_search_fields(state.markdown)

    assert "## 新栏目\n\n新内容。" in state.markdown
    assert "旧内容。" not in state.markdown
    assert "**问：** 旧问题" in state.markdown
    assert summary == "## 新栏目\n\n新内容。"
    assert "新内容。" not in source_text
    assert "旧回答" not in source_text

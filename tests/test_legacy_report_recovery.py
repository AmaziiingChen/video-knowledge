from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from config import settings
from services.database import connect, initialize_database
from services.knowledge_library import recover_legacy_report_documents
from services.markdown_sync import get_markdown_state
from services.repository import ContentRepository
from services.wechat_reports import create_group


def test_recover_legacy_reports_reindexes_markdown_and_rebuilds_report_link(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    initialize_database()
    group = create_group("校园生活")
    with connect() as connection:
        item = ContentRepository(connection).create_content_item(
            source_provider="wechat_report",
            content_type="report",
            title="旧标题",
            status="to_read",
        )
        connection.commit()

    legacy = tmp_path / "library" / "legacy-drafts" / f"{item.id}-2026-07-16日报_校园生活.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        "# 2026-07-16日报｜校园生活\n\n> 分组：校园生活 · 分析文章：20 篇 · 正文引用：19 篇\n\n正文仍在。\n",
        encoding="utf-8",
    )

    result = recover_legacy_report_documents()

    assert result["documents_recovered"] == 1
    assert result["report_links_recovered"] == 1
    with connect() as connection:
        report = connection.execute(
            "SELECT group_id, report_type, period_start, period_end, source_count FROM wechat_reports WHERE content_item_id=?",
            (item.id,),
        ).fetchone()
        document = connection.execute(
            "SELECT markdown_path FROM content_documents WHERE content_item_id=?",
            (item.id,),
        ).fetchone()
        title = connection.execute("SELECT title FROM content_items WHERE id=?", (item.id,)).fetchone()[0]
    assert tuple(report) == (group["id"], "daily", "2026-07-16", "2026-07-16", 20)
    assert Path(str(document["markdown_path"])).read_text(encoding="utf-8").endswith("正文仍在。\n")
    assert title == "2026-07-16日报｜校园生活"
    assert "正文仍在。" in get_markdown_state(item.id).markdown

    repeated = recover_legacy_report_documents()
    assert repeated["documents_recovered"] == 0
    assert repeated["report_links_recovered"] == 0

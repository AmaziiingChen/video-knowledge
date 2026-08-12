from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from services.database import connect, initialize_database
from services.repository import ContentRepository
from services.knowledge_library import (
    _document_is_manually_modified,
    update_source_context_section,
    write_content_markdown_document,
)
from services.search_index import (
    search_documents,
    upsert_search_document,
    upsert_source_text_document,
)
from services.source_context import (
    DEFAULT_SOURCE_CONTEXT_ANALYSIS_PROMPT,
    SOURCE_CONTEXT_CORE_GUARDRAIL,
    SOURCE_CONTEXT_GUARDRAIL,
    build_source_context,
)
from services.source_context_refresh import backfill_source_contexts, refresh_source_context
from services.source_context_store import (
    get_source_context_record,
    load_source_context,
)
from services.summarizer import build_qa_messages


def _create_video(*, provider: str = "bilibili", suffix: str = "one"):
    initialize_database()
    if provider == "bilibili":
        source_url = f"https://www.bilibili.com/video/BV1xx411c7m{suffix}"
    elif provider == "xiaohongshu":
        source_url = f"https://www.xiaohongshu.com/explore/{suffix}?xsec_token=private-token"
    else:
        source_url = f"https://www.douyin.com/video/7660847053097979{suffix}"
    with connect() as connection:
        item = ContentRepository(connection).create_content_item(
            source_provider=provider,
            source_url=source_url,
            canonical_source_id=f"{provider}-{suffix}",
            title=f"{provider} 测试视频",
            status="to_read",
        )
        connection.commit()
    return item


def test_refresh_persists_first_class_status_cache_and_search_material():
    item = _create_video()
    context = build_source_context(
        provider="bilibili",
        engagement={"play": 200, "comment": 12},
        comments=[{"author": "观众", "text": "希望补充边界条件", "like_count": 9}],
        comment_total=12,
    )
    with (
        patch(
            "services.source_context_refresh.fetch_bilibili_source_context",
            return_value=context,
        ) as fetch,
        patch(
            "services.source_context_refresh._refresh_local_outputs",
            return_value=True,
        ),
    ):
        result = refresh_source_context(item.id)

    fetch.assert_called_once_with(item.source_url, comment_limit=60, comment_pages=3)
    record = get_source_context_record(item.id)
    assert result["status"] == "ready"
    assert record is not None
    assert record.status == "ready"
    assert record.comment_sample_count == 1
    assert load_source_context(item.id)["comments"][0]["text"] == "希望补充边界条件"

    upsert_search_document(
        content_key=item.id,
        title=item.title,
        summary="正文摘要",
        transcript="正文转写",
        source_context=context,
    )
    assert search_documents("边界条件")[0].content_key == item.id


def test_refresh_failure_is_recorded_without_storing_sensitive_token():
    item = _create_video(provider="douyin", suffix="123")
    with patch(
        "services.source_context_refresh.fetch_douyin_source_context",
        side_effect=ValueError("请求失败 xsec_token=secret-value&cursor=1"),
    ):
        try:
            refresh_source_context(item.id)
        except ValueError:
            pass

    record = get_source_context_record(item.id)
    assert record is not None
    assert record.status == "failed"
    assert "secret-value" not in record.last_error
    assert "[已隐藏]" in record.last_error


def test_backfill_is_bounded_and_continues_after_one_item_fails():
    first = _create_video(suffix="one")
    second = _create_video(provider="douyin", suffix="222")
    calls = []

    def fake_refresh(item_id, **_kwargs):
        calls.append(item_id)
        if item_id == first.id:
            raise ValueError("平台暂不可用")
        return {"comment_sample_count": 3}

    with patch("services.source_context_refresh.refresh_source_context", side_effect=fake_refresh):
        result = backfill_source_contexts(limit=2)

    assert set(calls) == {first.id, second.id}
    assert result["completed"] == 2
    assert result["succeeded"] == 1
    assert result["failed"] == 1
    assert result["comments_saved"] == 3


def test_source_context_status_and_refresh_endpoints_use_the_durable_queue():
    item = _create_video(provider="xiaohongshu", suffix="privacy-check")
    client = TestClient(app)

    pending = client.get(f"/api/content/{item.id}/source-context")
    assert pending.status_code == 200
    assert pending.json()["status"] == "pending"

    with patch("routers.tasks.task_manager.create_source_sync") as create:
        from services.task_manager import TaskRecord

        create.return_value = TaskRecord(
            task_id="context-task",
            task_type="source_sync",
            content_item_id=item.id,
            source_title="补采互动数据",
        )
        queued = client.post(f"/api/content/{item.id}/refresh-source-context")

    assert queued.status_code == 200
    assert queued.json()["task_id"] == "context-task"
    assert queued.json()["source_url"] is None
    request = create.call_args.args[0]
    assert request["kind"] == "source_context_refresh"
    assert request["source_id"] == item.id
    assert "source_url" not in request
    assert create.call_args.kwargs.get("source_url") is None


def test_qa_prompt_treats_saved_comments_as_untrusted_auxiliary_material():
    context = build_source_context(
        provider="bilibili",
        comments=[{"author": "观众", "text": "评论区的代表问题"}],
        comment_total=10,
    )
    messages, _ = build_qa_messages(
        question="观众在问什么？",
        summary="已有总结",
        transcript="视频正文",
        source_context=context,
    )

    assert any(message.role == "system" and message.content == SOURCE_CONTEXT_GUARDRAIL for message in messages)
    assert any("评论区的代表问题" in message.content for message in messages if message.role == "user")


def test_source_text_refresh_preserves_indexed_comment_evidence():
    item = _create_video(suffix="search-preserve")
    context = build_source_context(
        provider="bilibili",
        comments=[{"author": "观众", "text": "需要保留的评论证据"}],
        comment_total=1,
    )
    upsert_search_document(
        content_key=item.id,
        title=item.title,
        summary="旧总结",
        transcript="旧正文",
        source_context=context,
    )

    upsert_source_text_document(
        content_key=item.id,
        title=item.title,
        transcript="新正文",
    )

    assert search_documents("需要保留的评论证据")[0].content_key == item.id
    assert search_documents("新正文")[0].content_key == item.id


def test_source_context_analysis_prompt_is_editable_and_used_by_qa():
    initialize_database()
    client = TestClient(app)
    listed = client.get(
        "/api/prompts",
        params={"task_type": "source_context_analysis"},
    )

    assert listed.status_code == 200
    templates = listed.json()
    assert len(templates) == 1
    template = templates[0]
    assert template["name"] == "互动评论分析规则"
    assert template["template"] == DEFAULT_SOURCE_CONTEXT_ANALYSIS_PROMPT
    custom_rule = "先归纳高频疑问，再列出相互冲突的观点；没有足够样本时明确停止推断。"
    updated = client.patch(
        f"/api/prompts/{template['id']}",
        json={"template": custom_rule},
    )
    assert updated.status_code == 200

    context = build_source_context(
        provider="douyin",
        comments=[{"author": "观众", "text": "这个方法有什么限制？"}],
        comment_total=20,
    )
    messages, _ = build_qa_messages(
        question="评论区关注什么？",
        summary="已有总结",
        transcript="视频正文",
        source_context=context,
    )

    source_guardrail = next(message.content for message in messages if SOURCE_CONTEXT_CORE_GUARDRAIL in message.content)
    assert custom_rule in source_guardrail
    assert DEFAULT_SOURCE_CONTEXT_ANALYSIS_PROMPT not in source_guardrail


def test_context_section_updates_a_manual_document_without_claiming_its_edits():
    item = _create_video(suffix="manual-markdown")
    path = write_content_markdown_document(
        item.id,
        "# 用户笔记\n\n人工保留内容\n\n## AI 摘要\n\n人工摘要\n",
    )
    path.write_text(
        path.read_text(encoding="utf-8") + "\n人工追加内容\n",
        encoding="utf-8",
    )
    assert _document_is_manually_modified(item.id, path) is True
    context = build_source_context(
        provider="bilibili",
        comments=[{"author": "观众", "text": "需要写入文档的评论"}],
        comment_total=8,
    )

    assert update_source_context_section(item.id, context) is True

    updated = path.read_text(encoding="utf-8")
    assert "人工保留内容" in updated
    assert "人工摘要" in updated
    assert "人工追加内容" in updated
    assert "<!-- source-context:start -->" in updated
    assert "需要写入文档的评论" in updated
    assert _document_is_manually_modified(item.id, path) is True

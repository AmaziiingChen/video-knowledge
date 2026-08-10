from dataclasses import replace
from unittest.mock import Mock, call

import pytest
from services.content_source_text import ContentSourceText
from services.pipeline_contracts import PipelineResponse
from services.pipeline_run_reporter import PipelineRunReporter
from services.pipeline_stored_article import (
    PreparedStoredArticle,
    StoredArticlePreparationError,
    prepare_stored_article,
    run_prepared_stored_article,
)
from services.repository import ContentItemRecord


def _item(*, provider: str = "campus", content_type: str = "article") -> ContentItemRecord:
    return ContentItemRecord(
        id="item-1",
        content_type=content_type,
        source_provider=provider,
        source_url="https://example.test/article",
        canonical_source_id="article-1",
        title="文章标题",
        cover_url=None,
        duration_seconds=None,
        status="processing",
        series_id=None,
        library_folder_id="folder-1",
        sort_order=0,
        created_at="2026-08-10T00:00:00+00:00",
        updated_at="2026-08-10T00:00:00+00:00",
    )


def _prepared_article() -> PreparedStoredArticle:
    return PreparedStoredArticle(
        item=_item(),
        transcript="正文内容",
        source_context={"comment_sample_count": 2},
    )


def test_runs_transcript_only_stored_article_without_ai_or_summary_write() -> None:
    prepared = _prepared_article()
    response = PipelineResponse(success=False, task_id="task-1")
    updates = []
    reporter = PipelineRunReporter(response, updates.append)
    status = Mock()
    summarize_article = Mock(side_effect=AssertionError("transcript mode must not call AI"))

    result = run_prepared_stored_article(
        prepared,
        response=response,
        reporter=reporter,
        fail=Mock(side_effect=AssertionError("transcript mode must not fail")),
        processing_mode="transcript",
        api_key_configured=False,
        ai_model=None,
        total_started_at=0.0,
        summarize_article=summarize_article,
        set_content_status=status,
        set_content_title=Mock(),
        replace_summary=Mock(),
        update_search=Mock(),
    )

    assert result is response
    assert response.success is True
    assert response.display_title == prepared.item.title
    assert response.transcript == prepared.transcript
    assert response.text_source and response.text_source.kind == "article"
    assert response.step is None
    assert all(response.progress[step] == 100 for step in response.progress)
    status.assert_called_once_with(prepared.item.id, "to_read")
    summarize_article.assert_not_called()
    assert updates[-1].success is True


def test_runs_full_stored_article_and_keeps_search_failure_non_fatal() -> None:
    prepared = _prepared_article()
    response = PipelineResponse(success=False, task_id="task-2")
    reporter = PipelineRunReporter(response, None)
    summarize_article = Mock(return_value=("AI 标题", "总结正文"))
    set_status = Mock()
    set_title = Mock()
    replace_summary = Mock()
    update_search = Mock(side_effect=RuntimeError("index unavailable"))

    result = run_prepared_stored_article(
        prepared,
        response=response,
        reporter=reporter,
        fail=Mock(side_effect=AssertionError("successful summary must not fail")),
        processing_mode="full",
        api_key_configured=True,
        ai_model="deepseek-chat",
        total_started_at=0.0,
        summarize_article=summarize_article,
        set_content_status=set_status,
        set_content_title=set_title,
        replace_summary=replace_summary,
        update_search=update_search,
    )

    assert result is response
    assert response.success is True
    assert response.summary == "总结正文"
    assert response.display_title == "AI 标题"
    assert response.step is None
    summarize_article.assert_called_once()
    assert summarize_article.call_args.args == (prepared.transcript, prepared.item.title)
    assert summarize_article.call_args.kwargs["task_type"] == "article_summary"
    assert summarize_article.call_args.kwargs["source_context"] == prepared.source_context
    set_title.assert_called_once_with(prepared.item.id, "AI 标题")
    replace_summary.assert_called_once_with(prepared.item.id, "总结正文")
    set_status.assert_called_once_with(prepared.item.id, "to_read")
    update_search.assert_called_once_with(
        content_key=prepared.item.id,
        title="AI 标题",
        summary="总结正文",
        transcript=prepared.transcript,
        source_context=prepared.source_context,
    )
    assert any(log.level == "warn" and "index unavailable" in log.message for log in response.logs)


@pytest.mark.parametrize(
    ("api_key_configured", "summary_result", "expected_error"),
    [
        (False, ("", ""), "未配置 DeepSeek API Key（请在设置 → 处理与 AI 中填写）"),
        (True, ("标题", ""), "总结生成失败"),
    ],
)
def test_stored_article_summary_preconditions_use_the_pipeline_failure_contract(
    api_key_configured: bool,
    summary_result: tuple[str, str],
    expected_error: str,
) -> None:
    prepared = _prepared_article()
    response = PipelineResponse(success=False, task_id="task-3")
    failure = PipelineResponse(success=False, task_id="failed")
    fail = Mock(return_value=failure)

    result = run_prepared_stored_article(
        prepared,
        response=response,
        reporter=PipelineRunReporter(response, None),
        fail=fail,
        processing_mode="full",
        api_key_configured=api_key_configured,
        ai_model=None,
        total_started_at=0.0,
        summarize_article=Mock(return_value=summary_result),
        set_content_status=Mock(),
        set_content_title=Mock(),
        replace_summary=Mock(),
        update_search=Mock(),
    )

    assert result is failure
    fail.assert_called_once_with("summarize", expected_error)


def test_prepares_a_persisted_article_without_touching_media_paths() -> None:
    item = _item()
    add_log = Mock()
    load_source = Mock(
        return_value=ContentSourceText(item.id, item.title, item.source_url or "", "  正文内容  ", "article")
    )

    prepared = prepare_stored_article(
        item.id,
        add_log=add_log,
        load_and_repair_item=Mock(return_value=(item, False)),
        load_source=load_source,
        capture_xiaohongshu=Mock(side_effect=AssertionError("campus must not capture XHS")),
    )

    assert prepared is not None
    assert prepared.item is item
    assert prepared.transcript == "正文内容"
    assert prepared.source_context == {}
    load_source.assert_called_once_with(item.id)
    add_log.assert_called_once_with("parse", "读取已入库的校园官网文章", "success")


def test_repairs_and_captures_a_legacy_xiaohongshu_item() -> None:
    legacy = _item(provider="xiaohongshu", content_type="video")
    repaired = replace(legacy, content_type="article")
    load_and_repair = Mock(return_value=(repaired, True))
    reload_item = Mock(return_value=repaired)
    context = {"comment_sample_count": 2}
    persist = Mock()
    add_log = Mock()

    prepared = prepare_stored_article(
        legacy.id,
        add_log=add_log,
        load_and_repair_item=load_and_repair,
        reload_item=reload_item,
        capture_xiaohongshu=Mock(return_value={"source_context": context}),
        load_source=Mock(
            return_value=ContentSourceText(repaired.id, repaired.title, repaired.source_url or "", "图文正文", "article")
        ),
        persist_source_context=persist,
    )

    assert prepared is not None
    assert prepared.item is repaired
    assert prepared.source_context == context
    load_and_repair.assert_called_once_with(legacy.id)
    reload_item.assert_called_once_with(legacy.id)
    persist.assert_called_once_with(repaired, context)
    assert add_log.call_args_list == [
        call("parse", "已修复旧小红书图文类型，正在按图文采集…"),
        call("parse", "正在读取小红书图文与图片…"),
        call("info", "图文素材已缓存，正在整理图片文字", "success"),
        call("parse", "读取已入库的小红书文章", "success"),
    ]


def test_xiaohongshu_capture_failure_is_a_structured_info_stage_error() -> None:
    item = _item(provider="xiaohongshu")

    with pytest.raises(StoredArticlePreparationError, match="小红书图文采集失败：browser unavailable") as error:
        prepare_stored_article(
            item.id,
            add_log=Mock(),
            load_and_repair_item=Mock(return_value=(item, False)),
            capture_xiaohongshu=Mock(side_effect=RuntimeError("browser unavailable")),
        )

    assert error.value.step == "info"


def test_xiaohongshu_context_persistence_failure_does_not_discard_body() -> None:
    item = _item(provider="xiaohongshu")
    add_log = Mock()
    context = {"comment_sample_count": 1}

    prepared = prepare_stored_article(
        item.id,
        add_log=add_log,
        load_and_repair_item=Mock(return_value=(item, False)),
        reload_item=Mock(return_value=item),
        capture_xiaohongshu=Mock(return_value={"source_context": context}),
        load_source=Mock(
            return_value=ContentSourceText(item.id, item.title, item.source_url or "", "图文正文", "article")
        ),
        persist_source_context=Mock(side_effect=RuntimeError("database busy")),
    )

    assert prepared is not None
    assert prepared.transcript == "图文正文"
    assert call("info", "互动数据持久化失败，继续使用图文正文：database busy", "warn") in add_log.call_args_list


def test_returns_none_for_missing_or_non_article_items() -> None:
    assert prepare_stored_article(None, add_log=Mock()) is None
    assert (
        prepare_stored_article(
            "missing",
            add_log=Mock(),
            load_and_repair_item=Mock(return_value=(None, False)),
        )
        is None
    )
    assert (
        prepare_stored_article(
            "video",
            add_log=Mock(),
            load_and_repair_item=Mock(
                return_value=(_item(provider="bilibili", content_type="video"), False)
            ),
        )
        is None
    )


@pytest.mark.parametrize(
    ("source_text", "expected_message"),
    [
        (None, "读取文章正文失败：source unavailable"),
        ("   ", "文章正文为空"),
    ],
)
def test_reports_source_loading_failures_with_the_info_stage(source_text: str | None, expected_message: str) -> None:
    item = _item(provider="rss")
    if source_text is None:
        load_source = Mock(side_effect=RuntimeError("source unavailable"))
    else:
        load_source = Mock(
            return_value=ContentSourceText(item.id, item.title, item.source_url or "", source_text, "article")
        )

    with pytest.raises(StoredArticlePreparationError, match=expected_message) as error:
        prepare_stored_article(
            item.id,
            add_log=Mock(),
            load_and_repair_item=Mock(return_value=(item, False)),
            load_source=load_source,
        )

    assert error.value.step == "info"

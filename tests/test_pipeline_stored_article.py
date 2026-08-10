from dataclasses import replace
from unittest.mock import Mock, call

import pytest
from services.content_source_text import ContentSourceText
from services.pipeline_stored_article import (
    StoredArticlePreparationError,
    prepare_stored_article,
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

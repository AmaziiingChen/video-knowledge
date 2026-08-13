from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, call, patch

from services.pipeline_source_context import refresh_pipeline_source_context


def test_refreshes_stale_context_and_preserves_runner_fetcher_injection() -> None:
    fresh = {"comment_sample_count": 3, "comments": [{"text": "new"}]}
    fetch = Mock(return_value=fresh)
    add_log = Mock()
    check_cancel = Mock()
    item = object()
    repository = Mock()
    repository.get_content_item.return_value = item

    with (
        patch("services.pipeline_source_context.source_context_is_fresh", return_value=False),
        patch("services.pipeline_source_context.write_cache_meta") as write_cache,
        patch("services.pipeline_source_context.connect", return_value=nullcontext(object())),
        patch("services.pipeline_source_context.ContentRepository", return_value=repository),
        patch("services.pipeline_source_context.save_source_context") as save_context,
    ):
        result = refresh_pipeline_source_context(
            platform="bilibili",
            url="https://www.bilibili.com/video/BV1test",
            source_context={"comment_sample_count": 1},
            use_cache=True,
            cache_dir=Path("/tmp/cache"),
            content_item_id="item-1",
            add_log=add_log,
            check_cancel=check_cancel,
            fetch_bilibili=fetch,
        )

    assert result is fresh
    fetch.assert_called_once_with("https://www.bilibili.com/video/BV1test")
    assert check_cancel.call_count == 2
    write_cache.assert_called_once_with(Path("/tmp/cache"), {"source_context": fresh})
    repository.get_content_item.assert_called_once_with("item-1")
    save_context.assert_called_once_with(item, fresh)
    add_log.assert_called_once_with("info", "已采集互动指标与 3 条评论样本", "success")


def test_fetch_failure_keeps_stale_context_and_does_not_replace_its_cache() -> None:
    stale = {"comment_sample_count": 1}
    add_log = Mock()
    check_cancel = Mock()

    with (
        patch("services.pipeline_source_context.source_context_is_fresh", return_value=False),
        patch("services.pipeline_source_context.write_cache_meta") as write_cache,
        patch("services.pipeline_source_context.connect", side_effect=RuntimeError("database unavailable")),
    ):
        result = refresh_pipeline_source_context(
            platform="douyin",
            url="https://www.douyin.com/video/123",
            source_context=stale,
            use_cache=True,
            cache_dir=Path("/tmp/cache"),
            content_item_id="item-1",
            add_log=add_log,
            check_cancel=check_cancel,
            fetch_douyin=Mock(side_effect=RuntimeError("provider unavailable")),
        )

    assert result is stale
    assert check_cancel.call_count == 2
    write_cache.assert_not_called()
    assert add_log.call_args_list == [
        call("info", "互动与评论采集失败，继续使用正文总结：provider unavailable", "warn"),
        call("info", "互动数据持久化失败，继续生成总结：database unavailable", "warn"),
    ]


def test_fresh_context_skips_network_but_refreshes_cache_and_durable_store() -> None:
    current = {"comment_sample_count": 2}
    fetch = Mock()
    check_cancel = Mock()
    item = object()
    repository = Mock()
    repository.get_content_item.return_value = item

    with (
        patch("services.pipeline_source_context.source_context_is_fresh", return_value=True),
        patch("services.pipeline_source_context.write_cache_meta") as write_cache,
        patch("services.pipeline_source_context.connect", return_value=nullcontext(object())),
        patch("services.pipeline_source_context.ContentRepository", return_value=repository),
        patch("services.pipeline_source_context.save_source_context") as save_context,
    ):
        result = refresh_pipeline_source_context(
            platform="bilibili",
            url="https://www.bilibili.com/video/BV1test",
            source_context=current,
            use_cache=True,
            cache_dir=Path("/tmp/cache"),
            content_item_id="item-1",
            add_log=Mock(),
            check_cancel=check_cancel,
            fetch_bilibili=fetch,
        )

    assert result is current
    fetch.assert_not_called()
    check_cancel.assert_not_called()
    write_cache.assert_called_once_with(Path("/tmp/cache"), {"source_context": current})
    save_context.assert_called_once_with(item, current)

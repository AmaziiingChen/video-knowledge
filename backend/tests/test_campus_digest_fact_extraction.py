from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from services import campus_digest_fact_extraction as extraction

SETTINGS = extraction.FactCardSettings(
    prompt_version="test-v1",
    source_chunk_chars=8,
    workers=5,
    schema="{\"summary\":\"摘要\"}",
    system_prompt=lambda: "测试系统提示",
    categories=("其他动态",),
    content_decisions={"include", "mixed", "exclude_ad"},
    document_types={"activity", "other"},
    event_stages={"announcement", "unknown"},
    include_decisions={"include", "mixed"},
)


def _source(*, content_id: str = "item-1", material: str = "正文") -> SimpleNamespace:
    return SimpleNamespace(
        content_item_id=content_id,
        title="校园活动通知",
        source_url="https://example.test/article",
        published_at="2026-08-10T10:00:00+08:00",
        publisher="校园公众号",
        source_channel="wechat",
        source_section="校园活动",
        material=material,
    )


def _card(summary: str = "活动安排") -> dict[str, object]:
    return {
        "summary": summary,
        "content_decision": "include",
        "decision_reason": "可核验",
        "category": "其他动态",
        "document_type": "activity",
        "event_stage": "announcement",
        "event_or_subject": "校园活动",
        "atomic_facts": [{"text": summary, "evidence": "原文", "origin": "html"}],
    }


def test_cached_cards_preserve_source_order_without_requesting_the_model(monkeypatch):
    source = _source()
    cached = extraction.parse_fact_card(_card("缓存事实"), settings=SETTINGS)
    load_calls = []
    monkeypatch.setattr(
        extraction,
        "load_cached_facts",
        lambda *args, **kwargs: load_calls.append((args, kwargs)) or {source.content_item_id: cached},
    )

    result = extraction.prepare_fact_cards(
        [source],
        provider=SimpleNamespace(model="test-model"),
        use_cache=True,
        progress_callback=None,
        tracking_task_id=None,
        settings=SETTINGS,
        chat_json=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("模型不应被调用")),
    )

    assert result == [cached]
    assert load_calls[0][1]["prompt_version"] == "test-v1"


def test_chunked_cards_keep_metadata_calls_then_merge_at_the_stricter_temperature():
    source = _source(material="第一段\n第二段\n")
    calls = []
    resolved_system_prompts = []
    responses = [_card("第一段事实"), _card("第二段事实"), _card("合并事实")]

    def chat_json(_provider, system_prompt, user_prompt, *, temperature):
        calls.append((system_prompt, user_prompt, temperature))
        return responses.pop(0)

    result = extraction.prepare_fact_cards(
        [source],
        provider=SimpleNamespace(model="test-model"),
        use_cache=False,
        progress_callback=None,
        tracking_task_id=None,
        settings=replace(
            SETTINGS,
            source_chunk_chars=6,
            system_prompt=lambda: resolved_system_prompts.append("测试系统提示") or "测试系统提示",
        ),
        chat_json=chat_json,
    )

    assert result[0]["summary"] == "合并事实"
    assert [call[2] for call in calls] == [0.05, 0.05, 0.0]
    assert resolved_system_prompts == ["测试系统提示"] * 3
    assert "<source_metadata>" in calls[0][1]
    assert "分段事实卡" in calls[-1][1]


def test_transient_fact_extraction_failure_retries_once_and_surfaces_a_warning():
    source = _source()
    events = []
    attempts = 0

    def chat_json(_provider, _system_prompt, _user_prompt, *, temperature):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("暂时不可用")
        assert temperature == 0.05
        return _card("重试成功")

    result = extraction.prepare_fact_cards(
        [source],
        provider=SimpleNamespace(model="test-model"),
        use_cache=False,
        progress_callback=events.append,
        tracking_task_id=None,
        settings=SETTINGS,
        chat_json=chat_json,
    )

    assert result[0]["summary"] == "重试成功"
    assert attempts == 2
    assert any(event["level"] == "warn" and "正在重试" in str(event["message"]) for event in events)

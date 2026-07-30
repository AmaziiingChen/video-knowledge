from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest
import requests


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services.ai_call_logger import image_catalog_price
from services.database import connect, initialize_database, utc_now_iso
from services.llm_provider import LLMResponse
from services.prompt_templates import (
    DEFAULT_WECHAT_COVER_IMAGE_PROMPT,
    DEFAULT_WECHAT_COVER_PLANNER_PROMPT,
)
from services.wechat_publishing import (
    COVER_STYLE_LABELS,
    CoverVisualBrief,
    PublishingCredentials,
    QWEN_COVER_NEGATIVE_PROMPTS,
    QwenCoverCredentials,
    WeChatPublishingError,
    WeChatPublishingService,
    _select_cover_style_block,
)


class FakeSecretStore:
    def __init__(self) -> None:
        self.qwen_keys: dict[str, str] = {}

    def save_qwen_cover(self, keychain_ref: str, credentials: QwenCoverCredentials) -> None:
        self.qwen_keys[keychain_ref] = credentials.api_key

    def load_qwen_cover(self, keychain_ref: str) -> QwenCoverCredentials:
        api_key = self.qwen_keys.get(keychain_ref, "")
        if not api_key:
            raise WeChatPublishingError("未找到千问封面 API Key，请在设置中重新配置")
        return QwenCoverCredentials(api_key)

    def load(self, _keychain_ref: str) -> PublishingCredentials:
        return PublishingCredentials(app_id="wx-test", app_secret="test-secret")


def test_qwen_cover_settings_keep_api_key_out_of_database_response():
    secrets = FakeSecretStore()
    service = WeChatPublishingService(secret_store=secrets)

    value = service.save_cover_settings(
        api_key="sk-test-secret",
        endpoint="https://workspace.cn-beijing.maas.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
        model="qwen-image-2.0",
    )

    assert value == {
        "configured": True,
        "generation_enabled": True,
        "provider": "qwen",
        "endpoint": "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
        "model": "qwen-image-2.0",
    }
    assert secrets.qwen_keys == {"wechat-publishing:qwen-cover": "sk-test-secret"}
    assert "api_key" not in value

    retained = service.save_cover_settings(
        api_key=None,
        endpoint="https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
        model="qwen-image-2.0",
    )
    assert retained["configured"] is True
    assert secrets.qwen_keys == {"wechat-publishing:qwen-cover": "sk-test-secret"}


def test_qwen_cover_settings_reject_non_https_endpoint():
    service = WeChatPublishingService(secret_store=FakeSecretStore())

    try:
        service.save_cover_settings(api_key="sk-test", endpoint="http://example.test/generate", model="qwen-image-2.0")
    except WeChatPublishingError as exc:
        assert "HTTPS" in str(exc)
    else:
        raise AssertionError("应拒绝非 HTTPS 封面接口")


def test_qwen_cover_settings_converts_workspace_compatible_base_url():
    secrets = FakeSecretStore()
    service = WeChatPublishingService(secret_store=secrets)

    value = service.save_cover_settings(
        api_key="sk-test",
        endpoint="https://workspace-id.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        model="qwen-image-2.0",
    )

    assert value["endpoint"] == (
        "https://workspace-id.cn-beijing.maas.aliyuncs.com/"
        "api/v1/services/aigc/multimodal-generation/generation"
    )


def test_qwen_cover_settings_preserves_fixed_free_quota_snapshot_model():
    service = WeChatPublishingService(secret_store=FakeSecretStore())

    value = service.save_cover_settings(
        api_key="sk-test",
        endpoint="https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
        model="qwen-image-2.0-pro-2026-06-22",
    )

    assert value["model"] == "qwen-image-2.0-pro-2026-06-22"
    assert service.cover_settings()["model"] == "qwen-image-2.0-pro-2026-06-22"


class FakeResponse:
    def __init__(self, *, payload=None, content=b"") -> None:
        self._payload = payload
        self.content = content

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        return None


def test_qwen_cover_connection_test_uses_current_model_without_persisting_settings():
    posted: dict[str, object] = {}

    def request_post(url, **kwargs):
        posted["url"] = url
        posted.update(kwargs)
        return FakeResponse(
            payload={
                "request_id": "req-cover-connection-test",
                "usage": {"image_count": 1, "width": 2688, "height": 1536},
                "output": {
                    "choices": [
                        {"message": {"content": [{"image": "https://example.test/test-cover.png"}]}}
                    ]
                },
            }
        )

    service = WeChatPublishingService(secret_store=FakeSecretStore(), request_post=request_post)

    result = service.test_cover_connection(
        api_key="sk-unsaved-test-key",
        endpoint="https://workspace-id.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        model="qwen-image-2.0-pro-2026-06-22",
    )

    assert result["available"] is True
    assert result["model"] == "qwen-image-2.0-pro-2026-06-22"
    assert result["image_count"] == 1
    assert result["request_id"] == "req-cover-connection-test"
    assert posted["url"] == (
        "https://workspace-id.cn-beijing.maas.aliyuncs.com/"
        "api/v1/services/aigc/multimodal-generation/generation"
    )
    assert posted["headers"] == {
        "Authorization": "Bearer sk-unsaved-test-key",
        "Content-Type": "application/json",
    }
    payload = json.loads(posted["data"].decode("utf-8"))
    assert payload["model"] == "qwen-image-2.0-pro-2026-06-22"
    assert payload["parameters"]["size"] == "2688*1536"
    assert service.cover_settings()["configured"] is False


def _insert_publishing_account(*, last_verified_public_ip: str = "") -> None:
    initialize_database()
    now = utc_now_iso()
    with connect() as connection:
        connection.execute(
            """INSERT INTO wechat_publishing_accounts
               (id, display_name, app_id, keychain_ref, status, last_error,
                last_verified_public_ip, created_at, updated_at)
               VALUES (1, '测试订阅号', 'wx-test', 'wechat-publishing:default',
                       'configured', '', ?, ?, ?)""",
            (last_verified_public_ip, now, now),
        )
        connection.commit()


def test_wechat_ip_preflight_detects_changed_public_ipv4_before_draft_work():
    _insert_publishing_account(last_verified_public_ip="203.0.113.10")
    service = WeChatPublishingService(
        secret_store=FakeSecretStore(),
        public_ip_get=lambda *_args, **_kwargs: FakeResponse(payload={"ip": "203.0.113.11"}),
    )

    result = service.public_ip_preflight()

    assert result["status"] == "changed"
    assert result["current_ip"] == "203.0.113.11"
    assert result["last_verified_ip"] == "203.0.113.10"
    assert result["can_submit"] is False


def test_wechat_ip_verification_records_newly_whitelisted_ipv4():
    _insert_publishing_account(last_verified_public_ip="203.0.113.10")
    service = WeChatPublishingService(
        secret_store=FakeSecretStore(),
        public_ip_get=lambda *_args, **_kwargs: FakeResponse(payload={"ip": "203.0.113.11"}),
        request_get=lambda *_args, **_kwargs: FakeResponse(payload={"access_token": "token", "expires_in": 7200}),
    )

    result = service.verify_public_ip_whitelist()

    assert result["status"] == "verified"
    assert result["can_submit"] is True
    with connect() as connection:
        row = connection.execute(
            "SELECT last_verified_public_ip FROM wechat_publishing_accounts WHERE id=1"
        ).fetchone()
    assert row["last_verified_public_ip"] == "203.0.113.11"


def test_wechat_ip_verification_uses_wechat_error_when_public_lookup_is_unavailable():
    _insert_publishing_account()

    def unavailable_ip_lookup(*_args, **_kwargs):
        raise requests.RequestException("network blocked")

    service = WeChatPublishingService(
        secret_store=FakeSecretStore(),
        public_ip_get=unavailable_ip_lookup,
        request_get=lambda *_args, **_kwargs: FakeResponse(
            payload={"errcode": 40164, "errmsg": "invalid ip 14.219.53.223 ipv6 ::ffff:14.219.53.223"}
        ),
    )

    result = service.verify_public_ip_whitelist()

    assert result["status"] == "verification_failed"
    assert result["current_ip"] == "14.219.53.223"
    assert result["can_submit"] is False


def _visual_brief(*, cover_style: str = "minimal_zine") -> dict:
    return {
        "cover_style": cover_style,
        "core_theme": "图书馆夜间延时开放",
        "selection_reason": "这是本期对读者行动影响最大的安排",
        "evidence_sections": ["本期概览：图书馆延长开放时间"],
        "confidence": 0.92,
        "content_category": "通知政策",
        "primary_subject": "夜色中的开放阅览室",
        "scene": "温暖灯光下的阅览室保持开放",
        "visual_metaphor": "",
        "decorative_microcopy": "OPEN LATE｜ARCHIVE 07",
        "rendering_style": "横版极简 Zine 编辑海报；单一标本、档案微排字、钴蓝色锚点、Risograph 颗粒、安静夜间情绪",
        "mood": "安静而可靠",
        "palette": "深蓝夜色与暖黄灯光",
        "composition": "阅览室落在中央方形安全区，左右延伸夜色",
        "supporting_elements": ["一枚钴蓝色印刷方块"],
        "factual_constraints": ["不得出现具体闭馆时间"],
        "must_avoid": ["教学楼庆典场景"],
    }


def test_legacy_cover_brief_defaults_to_minimal_zine():
    legacy_brief = _visual_brief()
    legacy_brief.pop("cover_style")

    assert CoverVisualBrief.model_validate(legacy_brief).cover_style == "minimal_zine"


def test_image_prompt_keeps_editorial_reasoning_out_of_the_image_model():
    service = WeChatPublishingService(secret_store=FakeSecretStore())
    brief_data = _visual_brief()
    brief_data.update(
        {
            "selection_reason": "INTERNAL_SELECTION_REASON",
            "evidence_sections": ["INTERNAL_EVIDENCE_SECTION"],
            "factual_constraints": ["INTERNAL_FACTUAL_CONSTRAINT"],
            "supporting_elements": ["微型排字：LEGACY_TEXT_MUST_NOT_RENDER", "钴蓝印刷方块"],
            "decorative_microcopy": "",
        }
    )

    initialize_database()
    resolved, _template = service._resolved_image_prompt(
        {"report_type": "daily"},
        CoverVisualBrief.model_validate(brief_data),
        title="INTERNAL_ARTICLE_TITLE",
    )

    assert "唯一主题：图书馆夜间延时开放" in resolved
    assert "钴蓝印刷方块" in resolved
    assert "允许的唯一装饰微文案：无" in resolved
    assert "INTERNAL_SELECTION_REASON" not in resolved
    assert "INTERNAL_EVIDENCE_SECTION" not in resolved
    assert "INTERNAL_FACTUAL_CONSTRAINT" not in resolved
    assert "LEGACY_TEXT_MUST_NOT_RENDER" not in resolved
    assert "INTERNAL_ARTICLE_TITLE" not in resolved


def test_image_prompt_only_permits_microcopy_for_editorial_styles():
    service = WeChatPublishingService(secret_store=FakeSecretStore())
    brief_data = _visual_brief()
    brief_data.update(
        {
            "cover_style": "transparent_watercolor",
            "decorative_microcopy": "SHOULD_NOT_RENDER",
        }
    )

    initialize_database()
    resolved, _template = service._resolved_image_prompt(
        {"report_type": "daily"},
        CoverVisualBrief.model_validate(brief_data),
        title="校园日报",
    )

    assert "允许的唯一装饰微文案：无" in resolved
    assert "SHOULD_NOT_RENDER" not in resolved


NEW_COVER_STYLE_CONTRACTS = [
    (
        "transparent_watercolor",
        "雨幕透明水彩风格规则",
        "雨幕透明水彩契约",
        "儿童课本插画",
    ),
    (
        "twilight_painterly",
        "暮色氛围绘画风格规则",
        "暮色氛围绘画契约",
        "清晰相机锐化",
    ),
    (
        "duotone_risograph",
        "两色孔版印刷风格规则",
        "两色孔版印刷契约",
        "超过三种主色",
    ),
    (
        "modern_geometric",
        "现代几何平涂风格规则",
        "现代几何平涂契约",
        "通用企业团队插画",
    ),
    (
        "editorial_collector",
        "编辑型收藏海报风格规则",
        "编辑型收藏海报契约",
        "逐栏目拼贴",
    ),
    (
        "oriental_ink",
        "东方水墨留白风格规则",
        "东方水墨留白契约",
        "伪造书法",
    ),
]


@pytest.mark.parametrize(
    ("cover_style", "planner_marker", "image_marker", "negative_marker"),
    NEW_COVER_STYLE_CONTRACTS,
)
def test_new_cover_style_contracts_stay_synchronized(
    cover_style: str,
    planner_marker: str,
    image_marker: str,
    negative_marker: str,
):
    brief = CoverVisualBrief.model_validate(_visual_brief(cover_style=cover_style))
    planner_prompt = _select_cover_style_block(
        DEFAULT_WECHAT_COVER_PLANNER_PROMPT,
        cover_style,
    )
    image_prompt = _select_cover_style_block(
        DEFAULT_WECHAT_COVER_IMAGE_PROMPT,
        cover_style,
    )

    assert brief.cover_style == cover_style
    assert COVER_STYLE_LABELS[cover_style]
    assert planner_marker in planner_prompt
    assert image_marker in image_prompt
    assert "2.35:1" in planner_prompt
    assert "2688×1536" in image_prompt
    assert negative_marker in QWEN_COVER_NEGATIVE_PROMPTS[cover_style]

    other_planner_markers = {
        contract[1] for contract in NEW_COVER_STYLE_CONTRACTS if contract[0] != cover_style
    }
    other_image_markers = {
        contract[2] for contract in NEW_COVER_STYLE_CONTRACTS if contract[0] != cover_style
    }
    assert all(marker not in planner_prompt for marker in other_planner_markers)
    assert all(marker not in image_prompt for marker in other_image_markers)
    assert "Minimal Zine 风格规则" not in planner_prompt
    assert "Minimal Zine 契约" not in image_prompt
    assert "诗意动画背景插画风格规则" not in planner_prompt
    assert "诗意动画背景插画契约" not in image_prompt


def test_qwen_cover_generation_is_explicit_and_persists_local_compact_jpeg():
    secrets = FakeSecretStore()
    posted: dict[str, object] = {}
    image_buffer = io.BytesIO()
    Image.new("RGB", (2688, 1536), "#556B2F").save(image_buffer, format="PNG")

    def request_post(url, **kwargs):
        posted["url"] = url
        posted.update(kwargs)
        return FakeResponse(
            payload={
                "request_id": "req-cover-test",
                "usage": {"image_count": 1, "width": 2688, "height": 1536},
                "output": {
                    "choices": [
                        {"message": {"content": [{"image": "https://example.test/generated-cover.png"}]}}
                    ]
                }
            }
        )

    service = WeChatPublishingService(
        secret_store=secrets,
        request_post=request_post,
        request_get=lambda *_args, **_kwargs: FakeResponse(content=image_buffer.getvalue()),
    )
    service.save_cover_settings(
        api_key="sk-test-secret",
        endpoint="https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
        model="qwen-image-2.0",
    )
    initialize_database()
    now = utc_now_iso()
    with connect() as connection:
        connection.execute(
            """INSERT INTO wechat_subscription_groups (id, name, description, sort_order, created_at, updated_at)
               VALUES ('group-1', '测试分组', '', 0, ?, ?)""",
            (now, now),
        )
        connection.execute(
            """INSERT INTO content_items
               (id, content_type, source_provider, title, cover_url, status, created_at, updated_at)
               VALUES ('report-1', 'report', 'wechat_report', '校园日报', '', 'ready', ?, ?)""",
            (now, now),
        )
        connection.execute(
            """INSERT INTO wechat_reports
               (id, group_id, content_item_id, report_type, period_start, period_end,
                source_count, source_coverage_json, cover_status, created_at)
               VALUES ('wechat-report-1', 'group-1', 'report-1', 'daily', '2026-07-24',
                       '2026-07-24', 0, '[]', 'placeholder', ?)""",
            (now,),
        )
        connection.commit()

    updates = []
    result = service.run_cover_task(
        content_item_id="report-1",
        title="校园日报",
        digest="摘要",
        visual_brief=_visual_brief(),
        task_id="cover-task",
        on_update=updates.append,
        cancel_check=lambda: False,
    )

    assert result.success is True
    assert updates[-1].overall_progress == 100
    with connect() as connection:
        content_row = connection.execute(
            "SELECT cover_url FROM content_items WHERE id='report-1'"
        ).fetchone()
        report_row = connection.execute(
            "SELECT cover_status, cover_path FROM wechat_reports WHERE content_item_id='report-1'"
        ).fetchone()
        usage_row = connection.execute(
            """SELECT usage_unit, image_count, unit_price_cny, estimated_cost,
                      billing_region, request_id, image_width, image_height
               FROM ai_calls
               WHERE content_item_id='report-1' AND call_type='wechat_cover_image'"""
        ).fetchone()
    assert str(content_row["cover_url"]).startswith("http://127.0.0.1:8000/api/media?")
    assert "base64" not in str(content_row["cover_url"])
    with Image.open(Path(str(report_row["cover_path"]))) as generated:
        assert generated.size == (900, 383)
    request_payload = json.loads(bytes(posted["data"]).decode("utf-8"))
    assert request_payload["model"] == "qwen-image-2.0"
    assert request_payload["parameters"]["size"] == "2688*1536"
    assert request_payload["parameters"]["prompt_extend"] is False
    resolved_prompt = request_payload["input"]["messages"][0]["content"][0]["text"]
    assert "Minimal Zine 契约" in resolved_prompt
    assert "65%–85% 是安静的纸面留白" in resolved_prompt
    assert "视觉执行简报中的所有自然语言都是后台操作指令" in resolved_prompt
    assert "允许的唯一装饰微文案：OPEN LATE｜ARCHIVE 07" in resolved_prompt
    assert "OPEN LATE｜ARCHIVE 07" in resolved_prompt
    assert "全幅写实场景、高分辨率图库摄影" in resolved_prompt
    assert "诗意动画背景插画契约" not in resolved_prompt
    assert "干净企业矢量插画" in request_payload["parameters"]["negative_prompt"]
    assert posted["headers"]["Authorization"] == "Bearer sk-test-secret"
    assert report_row["cover_status"] == "qwen_generated"
    assert dict(usage_row) == {
        "usage_unit": "images",
        "image_count": 1,
        "unit_price_cny": 0.2,
        "estimated_cost": 0.2,
        "billing_region": "cn-mainland",
        "request_id": "req-cover-test",
        "image_width": 2688,
        "image_height": 1536,
    }

    first_history = service.list_report_covers("report-1")
    assert len(first_history["covers"]) == 1
    first_cover = first_history["covers"][0]
    assert first_cover["selected"] is True
    first_cover_path = Path(str(report_row["cover_path"]))
    assert first_cover_path.is_file()

    second_image_buffer = io.BytesIO()
    Image.new("RGB", (2688, 1536), "#355C7D").save(
        second_image_buffer,
        format="PNG",
    )
    service._request_get = lambda *_args, **_kwargs: FakeResponse(
        content=second_image_buffer.getvalue()
    )
    second = service.run_cover_task(
        content_item_id="report-1",
        title="校园日报",
        digest="摘要",
        visual_brief=_visual_brief(cover_style="poetic_animation"),
        task_id="cover-task-second",
        on_update=lambda _value: None,
        cancel_check=lambda: False,
    )

    assert second.success is True
    second_history = service.list_report_covers("report-1")
    assert len(second_history["covers"]) == 2
    assert second_history["covers"][-1]["selected"] is True
    second_cover_path = Path(
        service._load_report("report-1")["cover_path"]
    )
    assert second_cover_path != first_cover_path
    assert first_cover_path.is_file()
    assert second_cover_path.is_file()

    selected = service.select_report_cover("report-1", first_cover["id"])

    assert selected["active_cover_id"] == first_cover["id"]
    assert selected["cover_url"] == first_cover["url"]
    restored_report = service._load_report("report-1")
    assert Path(restored_report["cover_path"]) == first_cover_path
    assert json.loads(restored_report["cover_plan_json"])["cover_style"] == "minimal_zine"


def test_qwen_image_catalog_price_distinguishes_model_and_region():
    assert image_catalog_price(
        model="qwen-image-2.0-pro",
        endpoint="https://workspace.cn-beijing.maas.aliyuncs.com/api/v1/generation",
    ) == ("cn-mainland", 0.5)
    assert image_catalog_price(
        model="qwen-image-2.0",
        endpoint="https://dashscope-intl.aliyuncs.com/api/v1/generation",
    ) == ("international", 0.256873)


def test_cover_planner_uses_managed_prompt_and_returns_editable_brief(monkeypatch):
    class FakePlanner:
        name = "fake"
        model = "text-planner"

        def chat(self, messages, **_kwargs):
            assert "<report_markdown>" in messages[0].content
            assert "图书馆延时开放" in messages[0].content
            assert "{report_markdown}" not in messages[0].content
            assert "Minimal Zine 风格规则" in messages[0].content
            assert "65%–85% 是纸面留白" in messages[0].content
            assert '"decorative_microcopy": ""' in messages[0].content
            assert "微型排字：准确短句" not in messages[0].content
            assert "诗意动画背景插画风格规则" not in messages[0].content
            return LLMResponse(
                content=json.dumps(_visual_brief(), ensure_ascii=False),
                provider=self.name,
                model=self.model,
            )

    initialize_database()
    now = utc_now_iso()
    with connect() as connection:
        connection.execute(
            """INSERT INTO wechat_subscription_groups
               (id, name, description, sort_order, created_at, updated_at)
               VALUES ('group-plan', '测试分组', '', 0, ?, ?)""",
            (now, now),
        )
        connection.execute(
            """INSERT INTO content_items
               (id, content_type, source_provider, title, cover_url, status, created_at, updated_at)
               VALUES ('report-plan', 'report', 'wechat_report', '校园日报', '', 'ready', ?, ?)""",
            (now, now),
        )
        connection.execute(
            """INSERT INTO wechat_reports
               (id, group_id, content_item_id, report_type, period_start, period_end,
                source_count, source_coverage_json, cover_status, created_at)
               VALUES ('wechat-report-plan', 'group-plan', 'report-plan', 'daily',
                       '2026-07-24', '2026-07-24', 0, '[]', 'placeholder', ?)""",
            (now,),
        )
        connection.commit()
    monkeypatch.setattr(
        "services.wechat_publishing.get_markdown_state",
        lambda _content_item_id: SimpleNamespace(
            markdown="## 本期概览\n\n图书馆延时开放，方便晚间学习。"
        ),
    )

    result = WeChatPublishingService(secret_store=FakeSecretStore()).plan_report_cover(
        "report-plan",
        provider=FakePlanner(),
    )

    assert result["visual_brief"]["core_theme"] == "图书馆夜间延时开放"
    assert result["visual_brief"]["cover_style"] == "minimal_zine"
    assert "图书馆夜间延时开放" in result["resolved_image_prompt"]
    assert "诗意动画背景插画契约" not in result["resolved_image_prompt"]
    with connect() as connection:
        row = connection.execute(
            """SELECT cover_plan_json
               FROM wechat_reports WHERE content_item_id='report-plan'"""
        ).fetchone()
    # Planning is review-only. The brief becomes durable only after the user
    # confirms it and queues image generation.
    assert json.loads(row["cover_plan_json"]) == {}


def test_cover_planner_selects_only_poetic_animation_style(monkeypatch):
    class FakePlanner:
        name = "fake"
        model = "text-planner"

        def chat(self, messages, **_kwargs):
            prompt = messages[0].content
            assert "诗意动画背景插画风格规则" in prompt
            assert "Minimal Zine 风格规则" not in prompt
            assert "不得出现任何可读文字" in prompt
            # The explicitly selected request style remains authoritative even
            # if a model echoes the wrong enum value.
            return LLMResponse(
                content=json.dumps(_visual_brief(), ensure_ascii=False),
                provider=self.name,
                model=self.model,
            )

    initialize_database()
    now = utc_now_iso()
    with connect() as connection:
        connection.execute(
            """INSERT INTO wechat_subscription_groups
               (id, name, description, sort_order, created_at, updated_at)
               VALUES ('group-poetic', '测试分组', '', 0, ?, ?)""",
            (now, now),
        )
        connection.execute(
            """INSERT INTO content_items
               (id, content_type, source_provider, title, cover_url, status, created_at, updated_at)
               VALUES ('report-poetic', 'report', 'wechat_report', '校园日报', '', 'ready', ?, ?)""",
            (now, now),
        )
        connection.execute(
            """INSERT INTO wechat_reports
               (id, group_id, content_item_id, report_type, period_start, period_end,
                source_count, source_coverage_json, cover_status, created_at)
               VALUES ('wechat-report-poetic', 'group-poetic', 'report-poetic', 'daily',
                       '2026-07-24', '2026-07-24', 0, '[]', 'placeholder', ?)""",
            (now,),
        )
        connection.commit()
    monkeypatch.setattr(
        "services.wechat_publishing.get_markdown_state",
        lambda _content_item_id: SimpleNamespace(
            markdown="## 本期概览\n\n图书馆延时开放，方便晚间学习。"
        ),
    )

    result = WeChatPublishingService(secret_store=FakeSecretStore()).plan_report_cover(
        "report-poetic",
        cover_style="poetic_animation",
        provider=FakePlanner(),
    )

    assert result["cover_style"] == "poetic_animation"
    assert result["cover_style_label"] == "诗意动画背景插画"
    assert result["visual_brief"]["cover_style"] == "poetic_animation"
    assert "诗意动画背景插画契约" in result["resolved_image_prompt"]
    assert "Minimal Zine 契约" not in result["resolved_image_prompt"]
    assert "不得出现任何文字、数字、标题" in result["resolved_image_prompt"]


def test_confirmed_cover_brief_is_persisted_before_queueing(monkeypatch):
    secrets = FakeSecretStore()
    service = WeChatPublishingService(secret_store=secrets)
    service.save_cover_settings(
        api_key="sk-test-secret",
        endpoint="https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
        model="qwen-image-2.0",
    )
    initialize_database()
    now = utc_now_iso()
    with connect() as connection:
        connection.execute(
            """INSERT INTO wechat_subscription_groups
               (id, name, description, sort_order, created_at, updated_at)
               VALUES ('group-queue', '测试分组', '', 0, ?, ?)""",
            (now, now),
        )
        connection.execute(
            """INSERT INTO content_items
               (id, content_type, source_provider, title, cover_url, status, created_at, updated_at)
               VALUES ('report-queue', 'report', 'wechat_report', '校园日报', '', 'ready', ?, ?)""",
            (now, now),
        )
        connection.execute(
            """INSERT INTO wechat_reports
               (id, group_id, content_item_id, report_type, period_start, period_end,
                source_count, source_coverage_json, cover_status, created_at)
               VALUES ('wechat-report-queue', 'group-queue', 'report-queue', 'daily',
                       '2026-07-24', '2026-07-24', 0, '[]', 'placeholder', ?)""",
            (now,),
        )
        connection.commit()

    captured = {}

    def fake_create(request, *, task_type):
        captured["request"] = request
        captured["task_type"] = task_type
        return SimpleNamespace(
            task_id="cover-queued",
            task_type=task_type,
            content_item_id=request.content_item_id,
            status="queued",
            result=SimpleNamespace(step="queued", error=""),
        )

    monkeypatch.setattr("services.task_manager.task_manager.create", fake_create)
    queued = service.queue_report_cover(
        "report-queue",
        visual_brief=_visual_brief(),
    )

    assert queued["status"] == "queued"
    assert captured["task_type"] == "generate_wechat_cover"
    assert captured["request"].cover_visual_brief["core_theme"] == "图书馆夜间延时开放"
    with connect() as connection:
        row = connection.execute(
            """SELECT cover_plan_json, cover_prompt_metadata_json
               FROM wechat_reports WHERE content_item_id='report-queue'"""
        ).fetchone()
    assert json.loads(row["cover_plan_json"])["core_theme"] == "图书馆夜间延时开放"
    metadata = json.loads(row["cover_prompt_metadata_json"])
    assert metadata["approved_at"]
    assert metadata["cover_style"] == "minimal_zine"
    assert metadata["cover_style_label"] == "Minimal Zine"


def test_failed_regeneration_keeps_previous_local_cover():
    secrets = FakeSecretStore()
    image_buffer = io.BytesIO()
    Image.new("RGB", (2688, 1536), "#556B2F").save(image_buffer, format="PNG")

    def successful_post(_url, **_kwargs):
        return FakeResponse(
            payload={
                "output": {
                    "choices": [
                        {"message": {"content": [{"image": "https://example.test/generated-cover.png"}]}}
                    ]
                }
            }
        )

    service = WeChatPublishingService(
        secret_store=secrets,
        request_post=successful_post,
        request_get=lambda *_args, **_kwargs: FakeResponse(content=image_buffer.getvalue()),
    )
    service.save_cover_settings(
        api_key="sk-test-secret",
        endpoint="https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
        model="qwen-image-2.0",
    )
    initialize_database()
    now = utc_now_iso()
    with connect() as connection:
        connection.execute(
            """INSERT INTO wechat_subscription_groups
               (id, name, description, sort_order, created_at, updated_at)
               VALUES ('group-keep', '测试分组', '', 0, ?, ?)""",
            (now, now),
        )
        connection.execute(
            """INSERT INTO content_items
               (id, content_type, source_provider, title, cover_url, status, created_at, updated_at)
               VALUES ('report-keep', 'report', 'wechat_report', '校园日报', '', 'ready', ?, ?)""",
            (now, now),
        )
        connection.execute(
            """INSERT INTO wechat_reports
               (id, group_id, content_item_id, report_type, period_start, period_end,
                source_count, source_coverage_json, cover_status, created_at)
               VALUES ('wechat-report-keep', 'group-keep', 'report-keep', 'daily',
                       '2026-07-24', '2026-07-24', 0, '[]', 'placeholder', ?)""",
            (now,),
        )
        connection.commit()
    first = service.run_cover_task(
        content_item_id="report-keep",
        title="校园日报",
        digest="",
        visual_brief=_visual_brief(),
        task_id="cover-first",
        on_update=lambda _value: None,
        cancel_check=lambda: False,
    )
    assert first.success is True
    with connect() as connection:
        before = dict(
            connection.execute(
                """SELECT content.cover_url, report.cover_path
                   FROM content_items AS content
                   JOIN wechat_reports AS report ON report.content_item_id=content.id
                   WHERE content.id='report-keep'"""
            ).fetchone()
        )

    failing_service = WeChatPublishingService(
        secret_store=secrets,
        request_post=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            requests.RequestException("offline")
        ),
    )
    failed = failing_service.run_cover_task(
        content_item_id="report-keep",
        title="校园日报",
        digest="",
        visual_brief=_visual_brief(),
        task_id="cover-failed",
        on_update=lambda _value: None,
        cancel_check=lambda: False,
    )

    assert failed.success is False
    with connect() as connection:
        after = dict(
            connection.execute(
                """SELECT content.cover_url, report.cover_path, report.cover_last_error
                   FROM content_items AS content
                   JOIN wechat_reports AS report ON report.content_item_id=content.id
                   WHERE content.id='report-keep'"""
            ).fetchone()
        )
    assert after["cover_url"] == before["cover_url"]
    assert after["cover_path"] == before["cover_path"]
    assert Path(after["cover_path"]).is_file()
    assert "调用千问生成封面失败" in after["cover_last_error"]


def test_publishing_requests_ignore_proxy_environment(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7897")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7897")
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:7897")
    monkeypatch.setenv("WECHAT_OFFICIAL_PROXY_URL", "http://proxy.example.test:8080")
    service = WeChatPublishingService(secret_store=FakeSecretStore())

    assert service._wechat_session.trust_env is False
    assert service._wechat_session.proxies == {}
    assert service._wechat_request_get.__self__ is service._wechat_session
    assert service._wechat_request_post.__self__ is service._wechat_session
    assert service._request_get.__self__ is service._wechat_session
    assert service._request_post.__self__ is service._wechat_session

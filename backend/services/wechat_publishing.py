from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

import requests

from services.ai_call_logger import record_image_generation_call, tracked_llm_provider
from services.wechat_cover_brief import (
    CoverVisualBrief,
    json_object as _json_object,
    parse_visual_brief as _parse_visual_brief,
    stored_visual_brief as _stored_visual_brief,
)
from services.database import connect, initialize_database, utc_now_iso
from services.llm_provider import LLMMessage, LLMProvider, default_llm_provider
from services.markdown_sync import get_markdown_state
from services.network_policy import direct_requests_session
from services.pipeline_runner import PipelineErrorInfo, PipelineLog, PipelineResponse
from services.prompt_templates import PromptTemplateRecord, PromptTemplateRepository
from services.public_report_export import (
    PublicReportExportError,
    export_report as export_public_report,
    refresh_published_manifest,
)
from services.github_pages_deployment import (
    GitHubPagesDeploymentError,
    deploy_github_pages,
    verify_github_pages_url,
)
from services.repository import new_id
from services.wechat_publishing_markdown import (
    default_digest as _default_digest,
    markdown_to_wechat_html,
    plain_text as _plain_text,
    wechat_digest as _wechat_digest,
)
from services.wechat_publishing_covers import (
    cover_bytes as _cover_bytes,
    has_persisted_cover as _has_persisted_cover,
    local_cover_url as _local_cover_url,
    normalized_cover_jpeg_bytes as _normalized_cover_jpeg_bytes,
    remove_uncommitted_cover as _remove_uncommitted_cover,
    validated_local_cover_path as _validated_local_cover_path,
    write_local_cover as _write_local_cover,
)
from services.wechat_publishing_secrets import (
    KeychainPublishingSecretStore,
    PublishingCredentials,
    QwenCoverCredentials,
    WeChatPublishingError,
)
from services.wechat_report_layout import ReportSource, render_wechat_report

__all__ = ["markdown_to_wechat_html"]


WECHAT_API_BASE = "https://api.weixin.qq.com/cgi-bin"
KEYCHAIN_ACCOUNT = "wechat-publishing:default"
QWEN_COVER_KEYCHAIN_ACCOUNT = "wechat-publishing:qwen-cover"
REQUEST_TIMEOUT_SECONDS = 20
PUBLIC_IP_REQUEST_TIMEOUT_SECONDS = 6
PUBLIC_IPV4_ENDPOINT = "https://api4.ipify.org?format=json"
QWEN_REQUEST_TIMEOUT_SECONDS = 75
QWEN_COVER_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
QWEN_COVER_MODEL = "qwen-image-2.0"
WECHAT_COVER_PLANNER_TASK_TYPE = "wechat_cover_planner"
WECHAT_COVER_IMAGE_TASK_TYPE = "wechat_cover_image"
WECHAT_COVER_QUEUE_TASK_TYPE = "generate_wechat_cover"
COVER_STYLE_MINIMAL_ZINE = "minimal_zine"
COVER_STYLE_POETIC_ANIMATION = "poetic_animation"
COVER_STYLE_TRANSPARENT_WATERCOLOR = "transparent_watercolor"
COVER_STYLE_TWILIGHT_PAINTERLY = "twilight_painterly"
COVER_STYLE_DUOTONE_RISOGRAPH = "duotone_risograph"
COVER_STYLE_MODERN_GEOMETRIC = "modern_geometric"
COVER_STYLE_EDITORIAL_COLLECTOR = "editorial_collector"
COVER_STYLE_ORIENTAL_INK = "oriental_ink"
COVER_STYLE_LABELS = {
    COVER_STYLE_MINIMAL_ZINE: "Minimal Zine",
    COVER_STYLE_POETIC_ANIMATION: "诗意动画背景插画",
    COVER_STYLE_TRANSPARENT_WATERCOLOR: "雨幕透明水彩",
    COVER_STYLE_TWILIGHT_PAINTERLY: "暮色氛围绘画",
    COVER_STYLE_DUOTONE_RISOGRAPH: "两色孔版印刷",
    COVER_STYLE_MODERN_GEOMETRIC: "现代几何平涂",
    COVER_STYLE_EDITORIAL_COLLECTOR: "编辑型收藏海报",
    COVER_STYLE_ORIENTAL_INK: "东方水墨留白",
}
TEXT_PERMITTED_COVER_STYLES = {
    COVER_STYLE_MINIMAL_ZINE,
    COVER_STYLE_DUOTONE_RISOGRAPH,
    COVER_STYLE_EDITORIAL_COLLECTOR,
}
QWEN_ZINE_NEGATIVE_PROMPT = (
    "全幅写实场景，高分辨率图库摄影，商业广告，产品宣传，巨大商业标题，"
    "长段整齐文字，未指定文字，错误文字，乱码汉字，logo，品牌标志，CTA，"
    "水印，二维码，光泽海报样机，桌面摆拍，电影光效，硬阴影，景深虚化，"
    "3D，霓虹，干净企业矢量插画，可爱卡通，动漫，时尚大片，密集手账拼贴，"
    "多主题拼贴，过多物件，过多颜色，可辨识人物肖像，主体畸变"
)
QWEN_POETIC_ANIMATION_NEGATIVE_PROMPT = (
    "写实摄影，纪实摄影，图库摄影，3D，光泽CG，电影级写实渲染，景深虚化，"
    "真实皮肤，过度精细人脸，Q版人物，儿童绘本，可爱贴纸，粗重描边，"
    "企业矢量插画，信息图，PPT，UI，霓虹色，赛博朋克，拥挤场景，"
    "巨大标题，汉字，字母，数字，标牌，logo，品牌标志，水印，二维码，"
    "可辨识人物肖像，主体畸变"
)
QWEN_TRANSPARENT_WATERCOLOR_NEGATIVE_PROMPT = (
    "写实摄影，图库摄影，3D，光泽CG，镜头光斑，景深虚化，厚重油画，"
    "不透明厚涂，硬边矢量，粗黑描边，儿童课本插画，儿童绘本，Q版人物，"
    "可爱贴纸，企业宣传插画，信息图，PPT，霓虹色，拥挤场景，"
    "巨大标题，汉字，字母，数字，标牌，logo，品牌标志，水印，二维码，"
    "可辨识人物肖像，主体畸变"
)
QWEN_TWILIGHT_PAINTERLY_NEGATIVE_PROMPT = (
    "写实摄影，图库摄影，3D，光泽CG，镜头景深，清晰相机锐化，线稿插画，"
    "粗重描边，儿童课本插画，儿童绘本，Q版，可爱卡通，企业矢量插画，"
    "宣传合影，信息图，PPT，霓虹，赛博朋克，拥挤场景，"
    "标题，文字，数字，标牌，logo，水印，二维码，可辨识人物肖像，主体畸变"
)
QWEN_DUOTONE_RISOGRAPH_NEGATIVE_PROMPT = (
    "写实摄影，3D，光泽CG，平滑数字渐变，完美无颗粒表面，超过三种主色，"
    "彩虹配色，企业矢量插画，可爱卡通，儿童绘本，信息图，PPT，产品广告，"
    "巨大商业标题，长段文字，乱码汉字，logo，品牌标志，CTA，水印，二维码，"
    "密集拼贴，可辨识人物肖像，主体畸变"
)
QWEN_MODERN_GEOMETRIC_NEGATIVE_PROMPT = (
    "写实摄影，3D，光泽CG，复杂渐变，景深，厚重纹理，粗黑动漫描边，"
    "儿童课本插画，儿童绘本，Q版，可爱贴纸，通用企业团队插画，"
    "瑜伽健康素材插画，信息图，PPT，霓虹，密集小物件，巨大标题，"
    "文字，数字，logo，品牌标志，水印，二维码，可辨识人物肖像，主体畸变"
)
QWEN_EDITORIAL_COLLECTOR_NEGATIVE_PROMPT = (
    "写实图库摄影，商业广告，产品宣传，九宫格，信息墙，逐栏目拼贴，"
    "密集手账，PPT，信息图，3D，光泽样机，霓虹，赛博朋克，巨大商业标题，"
    "长段文字，乱码汉字，logo，品牌标志，CTA，二维码，水印，"
    "可辨识人物肖像，主体畸变"
)
QWEN_ORIENTAL_INK_NEGATIVE_PROMPT = (
    "写实摄影，3D，光泽CG，西式油画，厚重颜料，硬边矢量，粗黑动漫描边，"
    "儿童课本插画，儿童绘本，古风游戏海报，仙侠宣传图，金色奢华边框，"
    "饱和多彩背景，信息图，PPT，伪造书法，伪造印章，题字，文字，数字，"
    "logo，品牌标志，水印，二维码，可辨识人物肖像，主体畸变"
)
QWEN_COVER_NEGATIVE_PROMPTS = {
    COVER_STYLE_MINIMAL_ZINE: QWEN_ZINE_NEGATIVE_PROMPT,
    COVER_STYLE_POETIC_ANIMATION: QWEN_POETIC_ANIMATION_NEGATIVE_PROMPT,
    COVER_STYLE_TRANSPARENT_WATERCOLOR: QWEN_TRANSPARENT_WATERCOLOR_NEGATIVE_PROMPT,
    COVER_STYLE_TWILIGHT_PAINTERLY: QWEN_TWILIGHT_PAINTERLY_NEGATIVE_PROMPT,
    COVER_STYLE_DUOTONE_RISOGRAPH: QWEN_DUOTONE_RISOGRAPH_NEGATIVE_PROMPT,
    COVER_STYLE_MODERN_GEOMETRIC: QWEN_MODERN_GEOMETRIC_NEGATIVE_PROMPT,
    COVER_STYLE_EDITORIAL_COLLECTOR: QWEN_EDITORIAL_COLLECTOR_NEGATIVE_PROMPT,
    COVER_STYLE_ORIENTAL_INK: QWEN_ORIENTAL_INK_NEGATIVE_PROMPT,
}
_COVER_STYLE_BLOCK = re.compile(
    r"\[\[STYLE:([a-z_]+)\]\](.*?)\[\[/STYLE\]\]",
    re.DOTALL,
)


class WeChatIpWhitelistError(WeChatPublishingError):
    """The direct home-network IPv4 changed before a costly draft job."""

    def __init__(self, message: str, *, current_ip: str = "") -> None:
        super().__init__(message)
        self.current_ip = current_ip


class WeChatPublishingService:
    def __init__(
        self,
        *,
        secret_store: KeychainPublishingSecretStore | None = None,
        request_get: Callable[..., Any] | None = None,
        request_post: Callable[..., Any] | None = None,
        public_ip_get: Callable[..., Any] | None = None,
    ) -> None:
        self._secret_store = secret_store or KeychainPublishingSecretStore()
        # Publishing must remain independent from proxy variables inherited by
        # the desktop process.  In particular, a locally running Clash listener
        # must never become an implicit runtime dependency.
        self._wechat_session = direct_requests_session()
        self._wechat_request_get = request_get or self._wechat_session.get
        self._wechat_request_post = request_post or self._wechat_session.post
        self._request_get = request_get or self._wechat_session.get
        self._request_post = request_post or self._wechat_session.post
        self._public_ip_get = public_ip_get or self._wechat_session.get
        self._access_token = ""
        self._access_token_expires_at: datetime | None = None

    def settings(self) -> dict[str, Any]:
        initialize_database()
        with connect() as connection:
            row = connection.execute("SELECT * FROM wechat_publishing_accounts WHERE id=1").fetchone()
        if row is None:
            return {
                "configured": False,
                "display_name": "",
                "app_id_masked": "",
                "status": "unconfigured",
                "last_verified_at": None,
                "last_error": "",
                "public_site_base_url": "",
                "public_site_provider": "",
                "public_site_repository": "",
                "last_verified_public_ip": "",
                "last_verified_public_ip_at": None,
                "cover": self.cover_settings(),
            }
        value = dict(row)
        app_id = str(value.get("app_id") or "")
        return {
            "configured": bool(app_id),
            "display_name": str(value.get("display_name") or ""),
            "app_id_masked": _mask_app_id(app_id),
            "status": str(value.get("status") or "unconfigured"),
            "last_verified_at": value.get("last_verified_at"),
            "last_error": str(value.get("last_error") or ""),
            "public_site_base_url": str(value.get("public_site_base_url") or ""),
            "public_site_provider": str(value.get("public_site_provider") or ""),
            "public_site_repository": str(value.get("public_site_repository") or ""),
            "last_verified_public_ip": str(value.get("last_verified_public_ip") or ""),
            "last_verified_public_ip_at": value.get("last_verified_public_ip_at"),
            "cover": self.cover_settings(value),
        }

    def public_ip_preflight(self) -> dict[str, Any]:
        """Compare the current direct IPv4 with the last WeChat-verified one.

        This does not call WeChat or alter account state.  It is intentionally
        safe to run when the draft dialog opens, so an IP change is visible
        before report export and GitHub Pages deployment begin.
        """
        initialize_database()
        with connect() as connection:
            row = connection.execute(
                """SELECT last_verified_public_ip, last_verified_public_ip_at
                   FROM wechat_publishing_accounts WHERE id=1"""
            ).fetchone()
        last_verified_ip = str(row["last_verified_public_ip"] or "") if row else ""
        last_verified_at = row["last_verified_public_ip_at"] if row else None
        try:
            current_ip = self._current_public_ipv4()
        except WeChatPublishingError as exc:
            return {
                "status": "unavailable",
                "current_ip": "",
                "last_verified_ip": last_verified_ip,
                "last_verified_at": last_verified_at,
                "can_submit": True,
                "message": str(exc),
            }
        if last_verified_ip and current_ip != last_verified_ip:
            return {
                "status": "changed",
                "current_ip": current_ip,
                "last_verified_ip": last_verified_ip,
                "last_verified_at": last_verified_at,
                "can_submit": False,
                "message": (
                    f"当前公网 IP 已从 {last_verified_ip} 变为 {current_ip}。"
                    "请先在微信公众平台 IP 白名单中加入当前 IP，再点击“已加入白名单，重新验证”。"
                ),
            }
        if last_verified_ip:
            return {
                "status": "unchanged",
                "current_ip": current_ip,
                "last_verified_ip": last_verified_ip,
                "last_verified_at": last_verified_at,
                "can_submit": True,
                "message": "当前公网 IP 与上次公众号验证一致；提交时仍会先进行快速连接验证。",
            }
        return {
            "status": "unverified",
            "current_ip": current_ip,
            "last_verified_ip": "",
            "last_verified_at": None,
            "can_submit": True,
            "message": "尚未保存公众号验证过的公网 IP；提交时会先快速验证，再开始导出和部署。",
        }

    def verify_public_ip_whitelist(self) -> dict[str, Any]:
        """Verify a newly whitelisted IP with WeChat before a draft workflow."""
        preflight = self.public_ip_preflight()
        current_ip = str(preflight.get("current_ip") or "")
        try:
            self._ensure_wechat_ip_ready(
                current_ip=current_ip,
                previous_ip=str(preflight.get("last_verified_ip") or ""),
                allow_changed_ip=True,
            )
        except WeChatPublishingError as exc:
            verified_ip = exc.current_ip if isinstance(exc, WeChatIpWhitelistError) else current_ip
            return {
                **preflight,
                "current_ip": verified_ip,
                "status": "verification_failed",
                "can_submit": False,
                "message": str(exc),
            }
        verified_at = utc_now_iso()
        return {
            **preflight,
            "status": "verified",
            "current_ip": current_ip,
            "last_verified_ip": current_ip or str(preflight.get("last_verified_ip") or ""),
            "last_verified_at": verified_at,
            "can_submit": True,
            "message": "公众号连接验证通过，可以存入草稿箱。",
        }

    def cover_settings(self, row: dict[str, Any] | None = None) -> dict[str, Any]:
        initialize_database()
        if row is None:
            with connect() as connection:
                raw = connection.execute("SELECT * FROM wechat_publishing_accounts WHERE id=1").fetchone()
            row = dict(raw) if raw else {}
        keychain_ref = str(row.get("cover_keychain_ref") or QWEN_COVER_KEYCHAIN_ACCOUNT)
        configured = False
        if row:
            try:
                configured = bool(self._secret_store.load_qwen_cover(keychain_ref).api_key)
            except WeChatPublishingError:
                configured = False
        return {
            "configured": configured,
            "generation_enabled": True,
            "provider": "qwen",
            "endpoint": str(row.get("cover_endpoint") or QWEN_COVER_ENDPOINT),
            "model": str(row.get("cover_model") or QWEN_COVER_MODEL),
        }

    def reveal_cover_api_key(self) -> str:
        """Return only the locally stored visual-model key on explicit request."""
        initialize_database()
        with connect() as connection:
            row = connection.execute(
                "SELECT cover_keychain_ref FROM wechat_publishing_accounts WHERE id=1"
            ).fetchone()
        keychain_ref = str((row["cover_keychain_ref"] if row else "") or QWEN_COVER_KEYCHAIN_ACCOUNT)
        try:
            return self._secret_store.load_qwen_cover(keychain_ref).api_key
        except WeChatPublishingError:
            return ""

    def save_cover_settings(self, *, api_key: str | None, endpoint: str, model: str) -> dict[str, Any]:
        cleaned_endpoint = _normalize_qwen_endpoint(str(endpoint or "").strip() or QWEN_COVER_ENDPOINT)
        cleaned_model = str(model or "").strip() or QWEN_COVER_MODEL
        if not cleaned_endpoint.startswith("https://"):
            raise WeChatPublishingError("千问封面接口地址必须使用 HTTPS")
        initialize_database()
        with connect() as connection:
            row = connection.execute("SELECT cover_keychain_ref FROM wechat_publishing_accounts WHERE id=1").fetchone()
            if row is None:
                now = utc_now_iso()
                connection.execute(
                    """INSERT INTO wechat_publishing_accounts
                       (id, display_name, app_id, keychain_ref, cover_provider, cover_endpoint, cover_model, cover_keychain_ref, status, last_error, created_at, updated_at)
                       VALUES (1, '', '', ?, 'qwen', ?, ?, ?, 'unconfigured', '', ?, ?)""",
                    (KEYCHAIN_ACCOUNT, cleaned_endpoint, cleaned_model, QWEN_COVER_KEYCHAIN_ACCOUNT, now, now),
                )
                keychain_ref = QWEN_COVER_KEYCHAIN_ACCOUNT
            else:
                keychain_ref = str(row["cover_keychain_ref"] or QWEN_COVER_KEYCHAIN_ACCOUNT)
                connection.execute(
                    """UPDATE wechat_publishing_accounts
                       SET cover_provider='qwen', cover_endpoint=?, cover_model=?, cover_keychain_ref=?, updated_at=? WHERE id=1""",
                    (cleaned_endpoint, cleaned_model, keychain_ref, utc_now_iso()),
                )
            connection.commit()
        if api_key is not None:
            cleaned_key = str(api_key).strip()
            if not cleaned_key:
                raise WeChatPublishingError("千问封面 API Key 不能为空")
            self._secret_store.save_qwen_cover(keychain_ref, QwenCoverCredentials(cleaned_key))
        return self.cover_settings()

    def test_cover_connection(self, *, api_key: str | None, endpoint: str, model: str) -> dict[str, Any]:
        """Generate one disposable image to verify the selected Qwen model end to end."""
        cleaned_endpoint = _normalize_qwen_endpoint(str(endpoint or "").strip() or QWEN_COVER_ENDPOINT)
        cleaned_model = str(model or "").strip() or QWEN_COVER_MODEL
        if not cleaned_endpoint.startswith("https://"):
            raise WeChatPublishingError("千问封面接口地址必须使用 HTTPS")
        cleaned_key = str(api_key or "").strip()
        if cleaned_key:
            credentials = QwenCoverCredentials(cleaned_key)
        else:
            credentials = self._secret_store.load_qwen_cover(QWEN_COVER_KEYCHAIN_ACCOUNT)

        prompt = "A quiet abstract paper collage in soft blue and warm ivory, no text, no logo, horizontal composition."
        requested_width, requested_height = 2688, 1536
        request_started_at = perf_counter()
        try:
            response = self._request_post(
                cleaned_endpoint,
                headers={
                    "Authorization": f"Bearer {credentials.api_key}",
                    "Content-Type": "application/json",
                },
                data=json.dumps(
                    {
                        "model": cleaned_model,
                        "input": {
                            "messages": [
                                {"role": "user", "content": [{"text": prompt}]}
                            ]
                        },
                        "parameters": {
                            "size": "2688*1536",
                            "n": 1,
                            "prompt_extend": False,
                            "watermark": False,
                        },
                    },
                    ensure_ascii=False,
                ).encode("utf-8"),
                timeout=QWEN_REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise WeChatPublishingError("封面模型测试失败，请检查网络、API Key、接口地址和模型名称") from exc

        data = _response_json(response, "千问未返回有效测试图片")
        _qwen_image_url(data)
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        image_count = _positive_int(usage.get("image_count"), default=1)
        image_width = _positive_int(usage.get("width"), default=requested_width)
        image_height = _positive_int(usage.get("height"), default=requested_height)
        elapsed_seconds = perf_counter() - request_started_at
        usage_record = record_image_generation_call(
            call_type=WECHAT_COVER_IMAGE_TASK_TYPE,
            provider="qwen",
            model=cleaned_model,
            endpoint=cleaned_endpoint,
            image_count=image_count,
            input_chars=len(prompt),
            elapsed_seconds=elapsed_seconds,
            request_id=str(data.get("request_id") or "").strip() or None,
            image_width=image_width,
            image_height=image_height,
        )
        return {
            "available": True,
            "model": cleaned_model,
            "image_count": usage_record.image_count,
            "elapsed_ms": round(elapsed_seconds * 1000),
            "request_id": usage_record.request_id,
        }

    def save_settings(
        self,
        *,
        display_name: str,
        app_id: str,
        app_secret: str,
        public_site_base_url: str = "",
    ) -> dict[str, Any]:
        cleaned_name = str(display_name or "").strip() or "订阅号"
        cleaned_app_id = str(app_id or "").strip()
        cleaned_secret = str(app_secret or "").strip()
        if not cleaned_app_id:
            raise WeChatPublishingError("请填写订阅号 AppID")
        if not cleaned_secret:
            raise WeChatPublishingError("请填写订阅号 AppSecret")
        public_site_base_url = str(public_site_base_url or "").strip().rstrip("/")
        if public_site_base_url and not public_site_base_url.startswith("https://"):
            raise WeChatPublishingError("公开网站地址必须使用 HTTPS")
        self._secret_store.save(KEYCHAIN_ACCOUNT, PublishingCredentials(cleaned_app_id, cleaned_secret))
        now = utc_now_iso()
        initialize_database()
        with connect() as connection:
            connection.execute(
                """INSERT INTO wechat_publishing_accounts
                   (id, display_name, app_id, keychain_ref, public_site_base_url, status, last_error, created_at, updated_at)
                   VALUES (1, ?, ?, ?, ?, 'configured', '', ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     display_name=excluded.display_name,
                     app_id=excluded.app_id,
                     keychain_ref=excluded.keychain_ref,
                     public_site_base_url=excluded.public_site_base_url,
                     status='configured',
                     last_error='',
                     updated_at=excluded.updated_at""",
                (cleaned_name, cleaned_app_id, KEYCHAIN_ACCOUNT, public_site_base_url, now, now),
            )
            connection.commit()
        self._access_token = ""
        self._access_token_expires_at = None
        return self.settings()

    def configure_github_pages(self, repository: str) -> dict[str, Any]:
        """Deploy the public build once and make GitHub Pages the draft-link origin."""
        try:
            deployment = deploy_github_pages(repository)
        except GitHubPagesDeploymentError as exc:
            raise WeChatPublishingError(str(exc)) from exc
        now = utc_now_iso()
        initialize_database()
        with connect() as connection:
            row = connection.execute("SELECT id FROM wechat_publishing_accounts WHERE id=1").fetchone()
            if row is None:
                connection.execute(
                    """INSERT INTO wechat_publishing_accounts
                       (id, display_name, app_id, keychain_ref, public_site_base_url, public_site_provider,
                        public_site_repository, status, last_error, created_at, updated_at)
                       VALUES (1, '', '', ?, ?, 'github_pages', ?, 'unconfigured', '', ?, ?)""",
                    (KEYCHAIN_ACCOUNT, deployment["public_site_base_url"], deployment["repository"], now, now),
                )
            else:
                connection.execute(
                    """UPDATE wechat_publishing_accounts
                       SET public_site_base_url=?, public_site_provider='github_pages',
                           public_site_repository=?, updated_at=? WHERE id=1""",
                    (deployment["public_site_base_url"], deployment["repository"], now),
                )
            connection.commit()
        return self.settings()

    def draft_defaults(self, content_item_id: str) -> dict[str, Any]:
        report = self._load_report(content_item_id)
        markdown = get_markdown_state(content_item_id).markdown
        digest = _wechat_digest(_default_digest(markdown))
        visual_brief = _stored_visual_brief(report)
        latest_publication = self.latest_publication(content_item_id)
        if latest_publication is not None:
            latest_publication["is_current_source"] = (
                str(latest_publication.get("source_markdown_hash") or "")
                == hashlib.sha256(markdown.encode("utf-8")).hexdigest()
            )
        return {
            "content_item_id": content_item_id,
            "title": str(report["title"] or "报告").strip(),
            "digest": digest,
            "author": "",
            "can_publish": bool(self.settings()["configured"]),
            "public_site_configured": bool(self.settings().get("public_site_base_url")),
            "latest_publication": latest_publication,
            "preview_html": self._render_report_html(report, markdown, digest),
            "cover_url": str(report.get("cover_url") or ""),
            "cover_status": str(report.get("cover_status") or ""),
            "cover_visual_brief": visual_brief,
            "cover_style": str(
                visual_brief.get("cover_style") or COVER_STYLE_MINIMAL_ZINE
            ),
            "cover_last_error": str(report.get("cover_last_error") or ""),
            "cover_generation_available": bool(self.cover_settings()["configured"]),
        }

    def list_report_covers(self, content_item_id: str) -> dict[str, Any]:
        """List retained local cover versions in chronological order."""
        report = self._load_report(content_item_id)
        current_path = str(report.get("cover_path") or "")
        with connect() as connection:
            rows = connection.execute(
                """
                SELECT id, cover_path, content_hash, visual_brief_json,
                       prompt_metadata_json, created_at
                FROM wechat_report_covers
                WHERE content_item_id=?
                ORDER BY created_at, id
                """,
                (content_item_id,),
            ).fetchall()
        covers = [
            value
            for row in rows
            if (
                value := _cover_version_payload(
                    dict(row),
                    current_path=current_path,
                )
            )
        ]
        active = next((item for item in covers if item["selected"]), None)
        return {
            "content_item_id": content_item_id,
            "active_cover_id": str(active["id"] if active else ""),
            "covers": covers,
        }

    def select_report_cover(
        self,
        content_item_id: str,
        cover_id: str,
    ) -> dict[str, Any]:
        """Make one retained version the preview and publishing cover."""
        self._load_report(content_item_id)
        with connect() as connection:
            row = connection.execute(
                """
                SELECT id, cover_path, content_hash, visual_brief_json,
                       prompt_metadata_json, created_at
                FROM wechat_report_covers
                WHERE id=? AND content_item_id=?
                """,
                (cover_id, content_item_id),
            ).fetchone()
            if row is None:
                raise LookupError("封面版本不存在")
            path = _validated_local_cover_path(str(row["cover_path"] or ""))
            version = str(row["content_hash"] or "").strip() or str(row["id"])
            cover_url = _local_cover_url(path, version=version[:12])
            now = utc_now_iso()
            connection.execute(
                "UPDATE content_items SET cover_url=?, updated_at=? WHERE id=?",
                (cover_url, now, content_item_id),
            )
            connection.execute(
                """
                UPDATE wechat_reports
                SET cover_status='qwen_generated', cover_path=?,
                    cover_plan_json=?, cover_prompt_metadata_json=?,
                    cover_last_error='', cover_generated_at=?
                WHERE content_item_id=?
                """,
                (
                    str(path),
                    str(row["visual_brief_json"] or "{}"),
                    str(row["prompt_metadata_json"] or "{}"),
                    str(row["created_at"] or now),
                    content_item_id,
                ),
            )
            connection.commit()
        result = self.list_report_covers(content_item_id)
        result["cover_url"] = cover_url
        return result

    def plan_report_cover(
        self,
        content_item_id: str,
        *,
        title: str = "",
        cover_style: str = COVER_STYLE_MINIMAL_ZINE,
        provider: LLMProvider | None = None,
    ) -> dict[str, Any]:
        """Select one evidence-backed visual theme without generating an image."""
        report = self._load_report(content_item_id)
        markdown = get_markdown_state(content_item_id).markdown
        article_title = str(title or report.get("title") or "报告").strip()
        selected_style = _normalize_cover_style(cover_style)
        prompt = self._active_cover_prompt(WECHAT_COVER_PLANNER_TASK_TYPE)
        report_label = _report_type_label(str(report.get("report_type") or "range"))
        resolved_planner_prompt = _resolve_required_prompt_inputs(
            _select_cover_style_block(prompt.template, selected_style),
            {
                "{article_title}": ("文章标题", article_title),
                "{report_type}": ("报告类型", report_label),
                "{report_markdown}": ("完整报告正文", markdown),
                "{cover_style}": ("封面风格", selected_style),
            },
        )
        messages = [
            LLMMessage(role="system", content=resolved_planner_prompt),
            LLMMessage(role="user", content="请根据以上文章完成视觉策划，并只返回规定的 JSON。"),
        ]
        llm = tracked_llm_provider(
            provider or default_llm_provider(),
            call_type=WECHAT_COVER_PLANNER_TASK_TYPE,
            content_item_id=content_item_id,
        )
        try:
            response = llm.chat(messages, temperature=0.2, response_format="json_object")
            visual_brief = _parse_visual_brief(response.content).model_copy(
                update={"cover_style": selected_style}
            )
        except WeChatPublishingError:
            raise
        except Exception as exc:
            raise WeChatPublishingError(f"封面主题策划失败：{exc}") from exc
        image_prompt, image_template = self._resolved_image_prompt(
            report,
            visual_brief,
            title=article_title,
        )
        return {
            "content_item_id": content_item_id,
            "cover_style": selected_style,
            "cover_style_label": COVER_STYLE_LABELS[selected_style],
            "visual_brief": visual_brief.model_dump(),
            "resolved_image_prompt": image_prompt,
            "planner_model": str(getattr(llm, "model", "")),
            "planner_prompt_version": prompt.version,
            "image_prompt_version": image_template.version,
        }

    def preview_report_cover_prompt(
        self,
        content_item_id: str,
        *,
        visual_brief: dict[str, Any],
        title: str = "",
    ) -> dict[str, Any]:
        report = self._load_report(content_item_id)
        brief = _parse_visual_brief(visual_brief)
        resolved, template = self._resolved_image_prompt(
            report,
            brief,
            title=str(title or report.get("title") or "报告").strip(),
        )
        return {
            "content_item_id": content_item_id,
            "resolved_image_prompt": resolved,
            "image_prompt_version": template.version,
        }

    def queue_report_cover(
        self,
        content_item_id: str,
        *,
        title: str = "",
        digest: str = "",
        visual_brief: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist the approved brief and enqueue one explicit image request."""
        report = self._load_report(content_item_id)
        if not self.cover_settings()["configured"]:
            raise WeChatPublishingError("请先在“AI 服务”设置中配置图像模型 API Key")
        brief = _parse_visual_brief(visual_brief or _stored_visual_brief(report))
        article_title = str(title or report.get("title") or "报告").strip()
        with connect() as connection:
            existing = connection.execute(
                """SELECT id FROM tasks
                   WHERE task_type=? AND content_item_id=?
                     AND status IN ('queued', 'running', 'paused')
                   ORDER BY created_at DESC LIMIT 1""",
                (WECHAT_COVER_QUEUE_TASK_TYPE, content_item_id),
            ).fetchone()
            if existing:
                raise WeChatPublishingError("该报告已有封面生成任务，请等待完成后再试")
            planner_template = PromptTemplateRepository(connection).get_active_template(
                WECHAT_COVER_PLANNER_TASK_TYPE
            )
            image_template = PromptTemplateRepository(connection).get_active_template(
                WECHAT_COVER_IMAGE_TASK_TYPE
            )
            previous_metadata = _json_object(report.get("cover_prompt_metadata_json"))
            metadata = {
                **previous_metadata,
                "cover_style": brief.cover_style,
                "cover_style_label": COVER_STYLE_LABELS[brief.cover_style],
                "planner_prompt_id": planner_template.id if planner_template else "",
                "planner_prompt_version": planner_template.version if planner_template else "",
                "image_prompt_id": image_template.id if image_template else "",
                "image_prompt_version": image_template.version if image_template else "",
                "approved_at": utc_now_iso(),
            }
            connection.execute(
                """UPDATE wechat_reports
                   SET cover_plan_json=?, cover_prompt_metadata_json=?,
                       cover_plan_updated_at=?, cover_last_error=''
                   WHERE content_item_id=?""",
                (
                    json.dumps(brief.model_dump(), ensure_ascii=False),
                    json.dumps(metadata, ensure_ascii=False),
                    utc_now_iso(),
                    content_item_id,
                ),
            )
            connection.commit()

        from services.pipeline_runner import PipelineRequest
        from services.task_manager import task_manager

        task = task_manager.create(
            PipelineRequest(
                content_item_id=content_item_id,
                source_title=f"{article_title} · 公众号封面",
                processing_mode="wechat_cover",
                execution_mode="foreground",
                cover_title=article_title,
                cover_digest=str(digest or "").strip(),
                cover_visual_brief=brief.model_dump(),
            ),
            task_type=WECHAT_COVER_QUEUE_TASK_TYPE,
        )
        return _cover_task_dict(task)

    def create_draft(
        self,
        content_item_id: str,
        *,
        title: str = "",
        digest: str = "",
        author: str = "",
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> dict[str, Any]:
        def update(stage: str, progress: float) -> None:
            if progress_callback is not None:
                progress_callback(stage, progress)

        # Do this before rendering, exporting, or deploying the public report.
        # A residential IP can change at any time; catching that condition here
        # avoids spending a minute on work that WeChat would reject anyway.
        update("checking_wechat_ip", 8)
        preflight = self.public_ip_preflight()
        access_token = self._ensure_wechat_ip_ready(
            current_ip=str(preflight.get("current_ip") or ""),
            previous_ip=str(preflight.get("last_verified_ip") or ""),
            allow_changed_ip=False,
        )

        update("preparing_report", 14)
        report = self._load_report(content_item_id)
        state = get_markdown_state(content_item_id)
        article_title = str(title or report["title"] or "报告").strip()
        if not article_title:
            raise WeChatPublishingError("草稿标题不能为空")
        if len(article_title) > 64:
            raise WeChatPublishingError("草稿标题不能超过 64 个字符")

        article_digest = _wechat_digest(str(digest or _default_digest(state.markdown)).strip())
        body_html = self._render_report_html(
            report,
            state.markdown,
            article_digest,
            title=article_title,
        )
        if not _plain_text(body_html):
            raise WeChatPublishingError("报告正文为空，无法创建公众号草稿")
        article_author = str(author or "").strip()
        publishing_settings = self.settings()
        try:
            update("exporting_public_report", 20)
            public_report = export_public_report(
                content_item_id,
                public_base_url=str(publishing_settings.get("public_site_base_url") or ""),
            )
        except PublicReportExportError as exc:
            raise WeChatPublishingError(str(exc)) from exc
        public_report_url = str(public_report["public_url"])
        if str(publishing_settings.get("public_site_provider") or "") == "github_pages":
            try:
                update("deploying_public_site", 36)
                deploy_github_pages(str(publishing_settings.get("public_site_repository") or ""))
                update("verifying_public_link", 68)
                verify_github_pages_url(public_report_url)
            except GitHubPagesDeploymentError as exc:
                raise WeChatPublishingError(str(exc)) from exc
        update("wechat_connection_verified", 76)
        # Cover generation is deliberately explicit: publishing never makes a
        # surprise billable model request. It only reuses the locally persisted
        # image that the editor has already reviewed.
        cover_url = str(report.get("cover_url") or "")
        cover_path = str(report.get("cover_path") or "")
        if not _has_persisted_cover(cover_url, cover_path):
            raise WeChatPublishingError("请先从报告右上角的内容操作中生成并确认文章封面")
        update("uploading_cover", 86)
        thumb_media_id = self._upload_cover(access_token, cover_url, cover_path=cover_path)
        payload = {
            "articles": [
                {
                    "title": article_title,
                    "author": article_author,
                    "digest": article_digest,
                    "content": body_html,
                    "content_source_url": public_report_url,
                    "thumb_media_id": thumb_media_id,
                    "need_open_comment": 0,
                    "only_fans_can_comment": 0,
                }
            ]
        }
        # ``requests.post(json=...)`` serializes Chinese as ``\\uXXXX`` by
        # default.  Although this is valid JSON, the WeChat draft endpoint
        # persists those escape sequences literally in title and content.
        # Send an explicit UTF-8 JSON body instead.
        article_body = _encode_wechat_json(payload)
        try:
            update("creating_wechat_draft", 96)
            response = self._wechat_request_post(
                f"{WECHAT_API_BASE}/draft/add",
                params={"access_token": access_token},
                data=article_body,
                headers={"Content-Type": "application/json; charset=utf-8"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise WeChatPublishingError("连接微信公众平台失败，请检查网络后重试") from exc
        data = _response_json(response, "创建公众号草稿失败")
        draft_media_id = str(data.get("media_id") or "").strip()
        if not draft_media_id:
            raise WeChatPublishingError("公众号未返回草稿标识，请稍后重试")

        now = utc_now_iso()
        publication = {
            "id": new_id(),
            "content_item_id": content_item_id,
            "report_title": article_title,
            "digest": article_digest,
            "author": article_author,
            "source_markdown_hash": hashlib.sha256(state.markdown.encode("utf-8")).hexdigest(),
            "draft_media_id": draft_media_id,
            "thumb_media_id": thumb_media_id,
            "public_report_slug": str(public_report["slug"]),
            "public_report_url": public_report_url,
            "status": "draft_created",
            "error_message": "",
            "created_at": now,
            "updated_at": now,
        }
        initialize_database()
        with connect() as connection:
            connection.execute(
                """INSERT INTO wechat_publications
                   (id, content_item_id, report_title, digest, author, source_markdown_hash,
                    draft_media_id, thumb_media_id, public_report_slug, public_report_url,
                    status, error_message, created_at, updated_at)
                   VALUES (:id, :content_item_id, :report_title, :digest, :author, :source_markdown_hash,
                           :draft_media_id, :thumb_media_id, :public_report_slug, :public_report_url,
                           :status, :error_message, :created_at, :updated_at)""",
                publication,
            )
            connection.execute(
                """UPDATE wechat_publishing_accounts
                   SET status='active', last_verified_at=?, last_error='', updated_at=? WHERE id=1""",
                (now, now),
            )
            connection.commit()
        return publication

    def latest_publication(self, content_item_id: str) -> dict[str, Any] | None:
        initialize_database()
        with connect() as connection:
            row = connection.execute(
                "SELECT * FROM wechat_publications WHERE content_item_id=? ORDER BY created_at DESC LIMIT 1",
                (content_item_id,),
            ).fetchone()
        return dict(row) if row else None

    def confirm_publication(
        self,
        publication_id: str,
        *,
        wechat_article_url: str = "",
    ) -> dict[str, Any]:
        """Archive only a publication an editor has confirmed in WeChat."""
        cleaned_id = str(publication_id or "").strip()
        article_url = str(wechat_article_url or "").strip()
        if not cleaned_id:
            raise WeChatPublishingError("缺少公众号草稿标识")
        if article_url and not article_url.startswith("https://"):
            raise WeChatPublishingError("公众号文章链接必须使用 HTTPS")
        initialize_database()
        now = utc_now_iso()
        with connect() as connection:
            row = connection.execute(
                "SELECT * FROM wechat_publications WHERE id=?",
                (cleaned_id,),
            ).fetchone()
            if row is None:
                raise LookupError("未找到对应的公众号草稿记录")
            publication = dict(row)
            if not str(publication.get("public_report_url") or ""):
                raise WeChatPublishingError("该草稿没有公开报告地址，不能写入历史档案")
            connection.execute(
                """UPDATE wechat_publications
                   SET status='published', wechat_article_url=?, published_at=?,
                       error_message='', updated_at=? WHERE id=?""",
                (article_url, now, now, cleaned_id),
            )
            connection.commit()
        refresh_published_manifest()
        settings_value = self.settings()
        if str(settings_value.get("public_site_provider") or "") == "github_pages":
            try:
                deploy_github_pages(str(settings_value.get("public_site_repository") or ""))
            except GitHubPagesDeploymentError as exc:
                raise WeChatPublishingError(
                    f"公众号已确认发表，但历史档案尚未同步到 GitHub Pages：{exc}"
                ) from exc
        return self.latest_publication(str(publication["content_item_id"])) or {}

    def run_cover_task(
        self,
        *,
        content_item_id: str,
        title: str,
        digest: str,
        visual_brief: dict[str, Any] | None,
        task_id: str,
        on_update: Callable[[PipelineResponse], None],
        cancel_check: Callable[[], bool],
    ) -> PipelineResponse:
        """Execute a queued image request while preserving the previous cover."""
        response = PipelineResponse(
            success=False,
            task_id=task_id,
            content_item_id=content_item_id,
            display_title=f"{title or '报告'} · 公众号封面",
            step="cover_generate",
            progress={"cover_generate": 0.0},
            overall_progress=0.0,
        )

        def update(step: str, message: str, progress: float, level: str = "info") -> None:
            response.step = step
            response.progress = {"cover_generate": progress}
            response.overall_progress = progress
            response.logs.append(
                PipelineLog(
                    step=step,
                    message=message,
                    level=level,
                    created_at=utc_now_iso(),
                )
            )
            on_update(response.model_copy(deep=True))

        try:
            if not content_item_id:
                raise WeChatPublishingError("封面任务缺少报告标识")
            report = self._load_report(content_item_id)
            brief = _parse_visual_brief(visual_brief or _stored_visual_brief(report))
            update(
                "cover_generate",
                f"正在根据已确认的视觉策划生成{COVER_STYLE_LABELS[brief.cover_style]}封面",
                12.0,
            )
            if cancel_check():
                response.step = "cancelled"
                return response
            cover_url, cover_path, metadata = self._generate_report_cover_file(
                report,
                brief,
                title=str(title or report.get("title") or "报告").strip(),
                task_id=task_id,
            )
            if cancel_check():
                _remove_uncommitted_cover(cover_path)
                response.step = "cancelled"
                return response
            update("cover_save", "封面已生成，正在写入本地并设为当前版本", 88.0)
            now = utc_now_iso()
            with connect() as connection:
                previous_metadata = _json_object(report.get("cover_prompt_metadata_json"))
                merged_metadata = {**previous_metadata, **metadata}
                connection.execute(
                    """
                    INSERT INTO wechat_report_covers (
                        id, content_item_id, cover_path, content_hash,
                        visual_brief_json, prompt_metadata_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(content_item_id, cover_path) DO UPDATE SET
                        content_hash=excluded.content_hash,
                        visual_brief_json=excluded.visual_brief_json,
                        prompt_metadata_json=excluded.prompt_metadata_json,
                        created_at=excluded.created_at
                    """,
                    (
                        new_id(),
                        content_item_id,
                        cover_path,
                        str(metadata["content_hash"]),
                        json.dumps(brief.model_dump(), ensure_ascii=False),
                        json.dumps(merged_metadata, ensure_ascii=False),
                        now,
                    ),
                )
                connection.execute(
                    """UPDATE content_items SET cover_url=?, updated_at=? WHERE id=?""",
                    (cover_url, now, content_item_id),
                )
                connection.execute(
                    """UPDATE wechat_reports
                       SET cover_status='qwen_generated', cover_path=?,
                           cover_plan_json=?, cover_prompt_metadata_json=?,
                           cover_last_error='', cover_generated_at=?
                       WHERE content_item_id=?""",
                    (
                        cover_path,
                        json.dumps(brief.model_dump(), ensure_ascii=False),
                        json.dumps(merged_metadata, ensure_ascii=False),
                        now,
                        content_item_id,
                    ),
                )
                connection.commit()
            response.success = True
            response.step = "save"
            response.progress = {"cover_generate": 100.0}
            response.overall_progress = 100.0
            response.logs.append(
                PipelineLog(
                    step="save",
                    message="新封面已设为当前版本，旧封面仍保留在本机",
                    level="success",
                    created_at=utc_now_iso(),
                )
            )
            on_update(response.model_copy(deep=True))
            return response
        except Exception as exc:
            message = str(exc) if isinstance(exc, WeChatPublishingError) else f"生成公众号封面失败：{exc}"
            with connect() as connection:
                connection.execute(
                    "UPDATE wechat_reports SET cover_last_error=? WHERE content_item_id=?",
                    (message, content_item_id),
                )
                connection.commit()
            response.success = False
            response.step = "cover_generate"
            response.error = message
            response.error_info = PipelineErrorInfo(
                stage="cover_generate",
                category="provider_error",
                retryable=True,
                retry_scope="full",
                message=message,
            )
            response.logs.append(
                PipelineLog(
                    step="cover_generate",
                    message=message,
                    level="error",
                    created_at=utc_now_iso(),
                )
            )
            on_update(response.model_copy(deep=True))
            return response

    def _active_cover_prompt(self, task_type: str) -> PromptTemplateRecord:
        initialize_database()
        with connect() as connection:
            prompt = PromptTemplateRepository(connection).get_active_template(task_type)
        if prompt is None:
            label = "主题策划" if task_type == WECHAT_COVER_PLANNER_TASK_TYPE else "图像生成"
            raise WeChatPublishingError(f"没有可用的公众号封面{label}提示词")
        return prompt

    def _resolved_image_prompt(
        self,
        report: dict[str, Any],
        visual_brief: CoverVisualBrief,
        *,
        title: str,
    ) -> tuple[str, PromptTemplateRecord]:
        template = self._active_cover_prompt(WECHAT_COVER_IMAGE_TASK_TYPE)
        selected_template = _select_cover_style_block(template.template, visual_brief.cover_style)
        inputs = {
            "{cover_style}": ("封面风格", visual_brief.cover_style),
            "{visual_brief}": ("视觉执行简报", _image_visual_brief(visual_brief)),
        }
        if "{article_title}" in selected_template:
            inputs["{article_title}"] = ("文章标题", title)
        if "{report_type}" in selected_template:
            inputs["{report_type}"] = (
                "报告类型",
                _report_type_label(str(report.get("report_type") or "range")),
            )
        resolved = _resolve_required_prompt_inputs(
            selected_template,
            inputs,
        )
        return resolved.strip(), template

    def _generate_report_cover_file(
        self,
        report: dict[str, Any],
        visual_brief: CoverVisualBrief,
        *,
        title: str,
        task_id: str,
    ) -> tuple[str, str, dict[str, Any]]:
        settings_value = self.cover_settings()
        if not settings_value["configured"]:
            raise WeChatPublishingError("请先在“AI 服务”设置中配置图像模型 API Key")
        credentials = self._secret_store.load_qwen_cover(
            str(report.get("cover_keychain_ref") or QWEN_COVER_KEYCHAIN_ACCOUNT)
        )
        prompt, image_template = self._resolved_image_prompt(
            report,
            visual_brief,
            title=title,
        )
        negative_prompt = _cover_negative_prompt(visual_brief.cover_style)
        request_started_at = perf_counter()
        try:
            response = self._request_post(
                str(settings_value["endpoint"]),
                headers={
                    "Authorization": f"Bearer {credentials.api_key}",
                    "Content-Type": "application/json",
                },
                data=json.dumps(
                    {
                        "model": str(settings_value["model"]),
                        "input": {
                            "messages": [
                                {
                                    "role": "user",
                                    "content": [{"text": prompt}],
                                }
                            ]
                        },
                        "parameters": {
                            "size": "2688*1536",
                            "n": 1,
                            "prompt_extend": False,
                            "watermark": False,
                            "negative_prompt": negative_prompt,
                        },
                    },
                    ensure_ascii=False,
                ).encode("utf-8"),
                timeout=QWEN_REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise WeChatPublishingError("调用千问生成封面失败，请检查网络和 API 配置") from exc
        data = _response_json(response, "千问未返回有效封面")
        image_url = _qwen_image_url(data)
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        requested_width, requested_height = 2688, 1536
        image_count = _positive_int(usage.get("image_count"), default=1)
        image_width = _positive_int(usage.get("width"), default=requested_width)
        image_height = _positive_int(usage.get("height"), default=requested_height)
        usage_record = record_image_generation_call(
            call_type=WECHAT_COVER_IMAGE_TASK_TYPE,
            provider=str(settings_value["provider"]),
            model=str(settings_value["model"]),
            endpoint=str(settings_value["endpoint"]),
            image_count=image_count,
            input_chars=len(prompt),
            elapsed_seconds=perf_counter() - request_started_at,
            task_id=task_id,
            content_item_id=str(report["id"]),
            request_id=str(data.get("request_id") or "").strip() or None,
            image_width=image_width,
            image_height=image_height,
        )
        try:
            image_response = self._request_get(
                image_url,
                timeout=QWEN_REQUEST_TIMEOUT_SECONDS,
            )
            image_response.raise_for_status()
            image_bytes = bytes(image_response.content)
        except requests.RequestException as exc:
            raise WeChatPublishingError("下载千问生成的封面失败，请重试") from exc
        if not image_bytes:
            raise WeChatPublishingError("千问生成的封面为空，请重试")
        normalized = _normalized_cover_jpeg_bytes(image_bytes)
        cover_path = _write_local_cover(str(report["id"]), normalized)
        digest = hashlib.sha256(normalized).hexdigest()
        cover_url = _local_cover_url(cover_path, version=digest[:12])
        return (
            cover_url,
            str(cover_path),
            {
                "image_prompt_id": image_template.id,
                "image_prompt_version": image_template.version,
                "cover_style": visual_brief.cover_style,
                "cover_style_label": COVER_STYLE_LABELS[visual_brief.cover_style],
                "resolved_image_prompt": prompt,
                "provider": str(settings_value["provider"]),
                "model": str(settings_value["model"]),
                "size": "2688*1536",
                "output_size": "900*383",
                "prompt_extend": False,
                "watermark": False,
                "negative_prompt": negative_prompt,
                "content_hash": digest,
                "request_id": usage_record.request_id,
                "image_count": usage_record.image_count,
                "unit_price_cny": usage_record.unit_price_cny,
                "estimated_cost": usage_record.estimated_cost,
                "billing_region": usage_record.billing_region,
                "generated_at": utc_now_iso(),
            },
        )

    def _load_report(self, content_item_id: str) -> dict[str, Any]:
        initialize_database()
        with connect() as connection:
            row = connection.execute(
                """SELECT c.id, c.title, c.cover_url, c.source_provider, c.content_type,
                          r.report_type, r.source_coverage_json, r.cover_status,
                          r.cover_path, r.cover_plan_json, r.cover_prompt_metadata_json,
                          r.cover_last_error, r.cover_plan_updated_at, r.cover_generated_at,
                          p.cover_keychain_ref
                   FROM content_items c
                   LEFT JOIN wechat_reports r ON r.content_item_id=c.id
                   LEFT JOIN wechat_publishing_accounts p ON p.id=1
                  WHERE c.id=? AND c.deleted_at IS NULL""",
                (content_item_id,),
            ).fetchone()
        if row is None:
            raise LookupError("报告不存在或已移入回收站")
        report = dict(row)
        if report["source_provider"] != "wechat_report" and report["content_type"] != "report":
            raise WeChatPublishingError("只有日报、周报和区间报告可以存入公众号草稿箱")
        return report

    def _render_report_html(
        self,
        report: dict[str, Any],
        markdown: str,
        digest: str,
        *,
        title: str | None = None,
    ) -> str:
        return render_wechat_report(
            title=str(title or report.get("title") or "报告"),
            markdown=markdown,
            digest=digest,
            report_type=str(report.get("report_type") or "range"),
            sources=self._report_sources(report),
        )

    def _report_sources(self, report: dict[str, Any]) -> list[ReportSource]:
        try:
            coverage = json.loads(str(report.get("source_coverage_json") or "[]"))
        except json.JSONDecodeError:
            coverage = []
        entries = [entry for entry in coverage if isinstance(entry, dict) and entry.get("citation_id") and entry.get("content_item_id")]
        if not entries:
            return []
        ids = [str(entry["content_item_id"]) for entry in entries]
        placeholders = ",".join("?" for _ in ids)
        with connect() as connection:
            rows = connection.execute(
                f"""SELECT c.id, c.title, c.source_url, c.published_at,
                           COALESCE(NULLIF(c.source_name, ''), ws.mp_name, rss.title, '') AS publisher
                      FROM content_items c
                      LEFT JOIN wechat_subscription_items wsi ON wsi.content_item_id=c.id
                      LEFT JOIN wechat_subscriptions ws ON ws.id=wsi.subscription_id
                      LEFT JOIN rss_source_items rsi ON rsi.content_item_id=c.id
                      LEFT JOIN rss_sources rss ON rss.id=rsi.source_id
                     WHERE c.id IN ({placeholders})""",
                ids,
            ).fetchall()
        by_id = {str(row["id"]): dict(row) for row in rows}
        return [
            ReportSource(
                citation_id=str(entry["citation_id"]),
                title=str((by_id.get(str(entry["content_item_id"])) or {}).get("title") or "原始文章"),
                url=str((by_id.get(str(entry["content_item_id"])) or {}).get("source_url") or ""),
                publisher=str((by_id.get(str(entry["content_item_id"])) or {}).get("publisher") or ""),
                published_at=str((by_id.get(str(entry["content_item_id"])) or {}).get("published_at") or ""),
            )
            for entry in entries
        ]

    def _current_public_ipv4(self) -> str:
        """Return the direct IPv4 that will be used for the WeChat route."""
        try:
            response = self._public_ip_get(
                PUBLIC_IPV4_ENDPOINT,
                timeout=PUBLIC_IP_REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise WeChatPublishingError("无法查询当前公网 IP；提交时仍会先连接微信验证") from exc
        try:
            payload = response.json()
        except Exception as exc:
            raise WeChatPublishingError("无法识别当前公网 IP；提交时仍会先连接微信验证") from exc
        value = str(payload.get("ip") or "").strip() if isinstance(payload, dict) else ""
        try:
            parsed = ipaddress.ip_address(value)
        except ValueError as exc:
            raise WeChatPublishingError("无法识别当前公网 IPv4；提交时仍会先连接微信验证") from exc
        if parsed.version != 4:
            raise WeChatPublishingError("当前网络未返回公网 IPv4；提交时仍会先连接微信验证")
        return str(parsed)

    def _ensure_wechat_ip_ready(
        self,
        *,
        current_ip: str,
        previous_ip: str,
        allow_changed_ip: bool,
    ) -> str:
        if current_ip and previous_ip and current_ip != previous_ip and not allow_changed_ip:
            raise WeChatIpWhitelistError(
                f"当前公网 IP 已从 {previous_ip} 变为 {current_ip}。"
                "请先在微信公众平台 IP 白名单中加入当前 IP，再重新验证后提交。",
                current_ip=current_ip,
            )
        try:
            token = self._get_access_token(force_refresh=True)
        except WeChatPublishingError as exc:
            if "invalid ip" in str(exc).lower() or "whitelist" in str(exc).lower():
                wechat_reported_ip = _wechat_error_ipv4(str(exc))
                resolved_ip = wechat_reported_ip or current_ip
                suffix = f"当前公网 IP：{resolved_ip}。" if resolved_ip else ""
                raise WeChatIpWhitelistError(
                    f"公众号 IP 白名单未通过。{suffix}"
                    "请在微信公众平台 IP 白名单中加入该 IP 后重新验证。",
                    current_ip=resolved_ip,
                ) from exc
            raise
        if current_ip:
            self._record_verified_public_ip(current_ip)
        return token

    def _record_verified_public_ip(self, public_ip: str) -> None:
        now = utc_now_iso()
        initialize_database()
        with connect() as connection:
            connection.execute(
                """UPDATE wechat_publishing_accounts
                   SET last_verified_public_ip=?, last_verified_public_ip_at=?,
                       last_verified_at=?, last_error='', updated_at=?
                   WHERE id=1""",
                (public_ip, now, now, now),
            )
            connection.commit()

    def _get_access_token(self, *, force_refresh: bool = False) -> str:
        now = datetime.now(timezone.utc)
        if (
            not force_refresh
            and self._access_token
            and self._access_token_expires_at
            and now < self._access_token_expires_at
        ):
            return self._access_token
        initialize_database()
        with connect() as connection:
            row = connection.execute("SELECT keychain_ref FROM wechat_publishing_accounts WHERE id=1").fetchone()
        if row is None:
            raise WeChatPublishingError("请先在设置中配置订阅号 AppID 和 AppSecret")
        credentials = self._secret_store.load(str(row["keychain_ref"]))
        try:
            response = self._wechat_request_get(
                f"{WECHAT_API_BASE}/token",
                params={"grant_type": "client_credential", "appid": credentials.app_id, "secret": credentials.app_secret},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise WeChatPublishingError("连接微信公众平台失败，请检查网络后重试") from exc
        data = _response_json(response, "获取公众号 access_token 失败")
        token = str(data.get("access_token") or "").strip()
        if not token:
            raise WeChatPublishingError("公众号未返回 access_token")
        expires_in = max(300, int(data.get("expires_in") or 7200) - 300)
        self._access_token = token
        self._access_token_expires_at = now + timedelta(seconds=expires_in)
        return token

    def _upload_cover(
        self,
        access_token: str,
        cover_url: str,
        *,
        cover_path: str = "",
    ) -> str:
        image_bytes, filename, mime_type = _cover_bytes(
            cover_url,
            cover_path=cover_path,
        )
        try:
            response = self._wechat_request_post(
                f"{WECHAT_API_BASE}/material/add_material",
                params={"access_token": access_token, "type": "image"},
                files={"media": (filename, image_bytes, mime_type)},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            raise WeChatPublishingError("连接微信公众平台失败，请检查网络后重试") from exc
        data = _response_json(response, "上传公众号封面失败")
        media_id = str(data.get("media_id") or "").strip()
        if not media_id:
            raise WeChatPublishingError("公众号未返回封面素材标识")
        return media_id


def _cover_version_payload(
    row: dict[str, Any],
    *,
    current_path: str,
) -> dict[str, Any] | None:
    try:
        path = _validated_local_cover_path(str(row.get("cover_path") or ""))
    except WeChatPublishingError:
        return None
    content_hash = str(row.get("content_hash") or "").strip()
    version = content_hash or str(row.get("id") or "")
    brief = _json_object(row.get("visual_brief_json"))
    metadata = _json_object(row.get("prompt_metadata_json"))
    style = str(
        brief.get("cover_style")
        or metadata.get("cover_style")
        or COVER_STYLE_MINIMAL_ZINE
    )
    try:
        normalized_current = (
            Path(current_path).expanduser().resolve() if current_path else None
        )
    except OSError:
        normalized_current = None
    return {
        "id": str(row.get("id") or ""),
        "url": _local_cover_url(path, version=version[:12]),
        "selected": bool(normalized_current and path == normalized_current),
        "created_at": str(row.get("created_at") or ""),
        "cover_style": style,
        "cover_style_label": COVER_STYLE_LABELS.get(style, style),
    }


def _resolve_required_prompt_inputs(
    template: str,
    inputs: dict[str, tuple[str, str]],
) -> str:
    """Resolve managed variables and retain required runtime inputs if removed."""
    source = str(template or "")
    resolved = source
    missing: list[tuple[str, str]] = []
    for variable, (label, value) in inputs.items():
        if variable in source:
            resolved = resolved.replace(variable, value)
        else:
            missing.append((label, value))
    if missing:
        fallback = "\n\n".join(f"{label}：\n{value}" for label, value in missing)
        resolved = f"{resolved.rstrip()}\n\n运行时必要输入：\n{fallback}"
    return resolved.strip()


def _image_visual_brief(visual_brief: CoverVisualBrief) -> str:
    """Keep editorial reasoning out of the image model's attention budget."""
    def line(label: str, value: str) -> str | None:
        cleaned = " ".join(str(value or "").split())
        return f"{label}：{cleaned}" if cleaned else None

    visual_elements = [
        item
        for item in visual_brief.supporting_elements
        if not str(item).strip().startswith("微型排字：")
    ]
    lines = [
        line("唯一主题", visual_brief.core_theme),
        line("主视觉主体", visual_brief.primary_subject),
        line("场景与动作", visual_brief.scene),
        line("视觉隐喻", visual_brief.visual_metaphor),
        line("辅助视觉元素", "；".join(visual_elements)),
        line("表现媒介", visual_brief.rendering_style),
        line("画面情绪", visual_brief.mood),
        line("色彩", visual_brief.palette),
        line("横版构图", visual_brief.composition),
        line("避免", "；".join(visual_brief.must_avoid)),
    ]
    microcopy = visual_brief.decorative_microcopy
    if microcopy and visual_brief.cover_style in TEXT_PERMITTED_COVER_STYLES:
        lines.append(f"允许的唯一装饰微文案：{microcopy}")
    else:
        lines.append("允许的唯一装饰微文案：无")
    return "\n".join(item for item in lines if item)


def _normalize_cover_style(value: Any) -> str:
    style = str(value or COVER_STYLE_MINIMAL_ZINE).strip()
    if style not in COVER_STYLE_LABELS:
        raise WeChatPublishingError("不支持的公众号封面风格")
    return style


def _select_cover_style_block(template: str, cover_style: str) -> str:
    """Keep common prompt text and only the explicitly selected style block."""
    style = _normalize_cover_style(cover_style)
    source = str(template or "")
    matches = list(_COVER_STYLE_BLOCK.finditer(source))
    if not matches:
        # Custom prompts created before style presets remain usable. The
        # selected key is still available through the managed variable.
        return source
    available = {match.group(1) for match in matches}
    if style not in available:
        raise WeChatPublishingError(
            f"当前提示词缺少“{COVER_STYLE_LABELS[style]}”风格区块"
        )
    return _COVER_STYLE_BLOCK.sub(
        lambda match: match.group(2).strip() if match.group(1) == style else "",
        source,
    )


def _cover_negative_prompt(cover_style: str) -> str:
    style = _normalize_cover_style(cover_style)
    return QWEN_COVER_NEGATIVE_PROMPTS[style]


def _cover_task_dict(task: Any) -> dict[str, Any]:
    result = getattr(task, "result", None)
    return {
        "task_id": str(task.task_id),
        "task_type": str(getattr(task, "task_type", WECHAT_COVER_QUEUE_TASK_TYPE)),
        "content_item_id": str(task.content_item_id or ""),
        "status": str(task.status),
        "step": str(getattr(result, "step", "") or ""),
        "error": str(getattr(result, "error", "") or ""),
    }


def _report_type_label(report_type: str) -> str:
    return {
        "daily": "日报",
        "weekly": "周报",
        "range": "专题汇总",
    }.get(report_type, "报告")


def _response_json(response: Any, fallback: str) -> dict[str, Any]:
    try:
        data = response.json()
    except Exception as exc:
        raise WeChatPublishingError(fallback) from exc
    if not isinstance(data, dict):
        raise WeChatPublishingError(fallback)
    errcode = data.get("errcode")
    if errcode not in (None, 0, "0"):
        message = str(data.get("errmsg") or fallback)
        raise WeChatPublishingError(f"{fallback}：{message}")
    return data


def _wechat_error_ipv4(message: str) -> str:
    """Extract WeChat's authoritative client IPv4 from an ``invalid ip`` error."""
    match = re.search(r"invalid\s+ip\s+(?:::ffff:)?((?:\d{1,3}\.){3}\d{1,3})", message, re.IGNORECASE)
    if match is None:
        return ""
    try:
        parsed = ipaddress.ip_address(match.group(1))
    except ValueError:
        return ""
    return str(parsed) if parsed.version == 4 else ""


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _encode_wechat_json(payload: dict[str, Any]) -> bytes:
    """Serialize WeChat request bodies as literal UTF-8, never ``\\u`` text."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _normalize_qwen_endpoint(value: str) -> str:
    """Turn a workspace's OpenAI-compatible base URL into Qwen Image's native URL."""
    endpoint = str(value or "").strip().rstrip("/")
    compatible_suffix = "/compatible-mode/v1"
    if endpoint.endswith(compatible_suffix):
        return endpoint[: -len(compatible_suffix)] + "/api/v1/services/aigc/multimodal-generation/generation"
    return endpoint


def _qwen_image_url(data: dict[str, Any]) -> str:
    try:
        content = data["output"]["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        message = str(data.get("message") or data.get("code") or "千问未返回封面图片")
        raise WeChatPublishingError(f"千问生成封面失败：{message}") from exc
    for item in content if isinstance(content, list) else []:
        if isinstance(item, dict) and str(item.get("image") or "").startswith("https://"):
            return str(item["image"])
    raise WeChatPublishingError("千问未返回封面图片")


def _mask_app_id(value: str) -> str:
    if len(value) <= 8:
        return "已配置" if value else ""
    return f"{value[:4]}…{value[-4:]}"


wechat_publishing_service = WeChatPublishingService()

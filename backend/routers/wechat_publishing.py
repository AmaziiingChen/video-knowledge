from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.wechat_draft_tasks import wechat_draft_task_manager
from services.wechat_publishing import WeChatPublishingError, wechat_publishing_service


router = APIRouter()


class PublishingSettingsRequest(BaseModel):
    display_name: str = Field(default="订阅号", min_length=1, max_length=120)
    app_id: str = Field(min_length=6, max_length=128)
    app_secret: str = Field(min_length=8, max_length=256)
    public_site_base_url: str = Field(default="", max_length=500)


class GitHubPagesRequest(BaseModel):
    repository: str = Field(min_length=3, max_length=300)


class CreateDraftRequest(BaseModel):
    title: str = Field(default="", max_length=64)
    digest: str = Field(default="", max_length=120)
    author: str = Field(default="", max_length=64)


class ConfirmPublicationRequest(BaseModel):
    wechat_article_url: str = Field(default="", max_length=2000)


class GenerateCoverRequest(BaseModel):
    title: str = Field(default="", max_length=64)
    digest: str = Field(default="", max_length=240)
    visual_brief: dict[str, Any] | None = None


class PlanCoverRequest(BaseModel):
    title: str = Field(default="", max_length=64)
    cover_style: str = Field(default="minimal_zine", max_length=40)


class PreviewCoverPromptRequest(BaseModel):
    title: str = Field(default="", max_length=64)
    visual_brief: dict[str, Any]


class QwenCoverSettingsRequest(BaseModel):
    api_key: str | None = Field(default=None, max_length=500)
    endpoint: str = Field(default="https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation", max_length=500)
    model: str = Field(default="qwen-image-2.0", max_length=120)


def _raise_error(exc: Exception) -> None:
    if isinstance(exc, LookupError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, WeChatPublishingError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise HTTPException(status_code=500, detail="公众号草稿服务异常") from exc


@router.get("/wechat-publishing/settings", response_model=dict[str, Any])
def get_publishing_settings():
    return wechat_publishing_service.settings()


@router.get("/wechat-publishing/ip-preflight", response_model=dict[str, Any])
def get_publishing_ip_preflight():
    try:
        return wechat_publishing_service.public_ip_preflight()
    except Exception as exc:
        _raise_error(exc)


@router.post("/wechat-publishing/ip-preflight/verify", response_model=dict[str, Any])
def verify_publishing_ip_preflight():
    try:
        return wechat_publishing_service.verify_public_ip_whitelist()
    except Exception as exc:
        _raise_error(exc)


@router.put("/wechat-publishing/settings", response_model=dict[str, Any])
def save_publishing_settings(req: PublishingSettingsRequest):
    try:
        return wechat_publishing_service.save_settings(
            display_name=req.display_name,
            app_id=req.app_id,
            app_secret=req.app_secret,
            public_site_base_url=req.public_site_base_url,
        )
    except Exception as exc:
        _raise_error(exc)


@router.post("/wechat-publishing/github-pages", response_model=dict[str, Any])
def configure_github_pages(req: GitHubPagesRequest):
    try:
        return wechat_publishing_service.configure_github_pages(req.repository)
    except Exception as exc:
        _raise_error(exc)


@router.get("/wechat-publishing/cover-settings", response_model=dict[str, Any])
def get_qwen_cover_settings():
    return wechat_publishing_service.cover_settings()


@router.post("/wechat-publishing/cover-settings/reveal", response_model=dict[str, str])
def reveal_qwen_cover_api_key():
    return {"secret": wechat_publishing_service.reveal_cover_api_key()}


@router.put("/wechat-publishing/cover-settings", response_model=dict[str, Any])
def save_qwen_cover_settings(req: QwenCoverSettingsRequest):
    try:
        return wechat_publishing_service.save_cover_settings(
            api_key=req.api_key,
            endpoint=req.endpoint,
            model=req.model,
        )
    except Exception as exc:
        _raise_error(exc)


@router.post("/wechat-publishing/cover-settings/test", response_model=dict[str, Any])
def test_qwen_cover_settings(req: QwenCoverSettingsRequest):
    try:
        return wechat_publishing_service.test_cover_connection(
            api_key=req.api_key,
            endpoint=req.endpoint,
            model=req.model,
        )
    except Exception as exc:
        _raise_error(exc)


@router.get("/wechat-publishing/reports/{content_item_id}", response_model=dict[str, Any])
def get_report_draft_defaults(content_item_id: str):
    try:
        return wechat_publishing_service.draft_defaults(content_item_id)
    except Exception as exc:
        _raise_error(exc)


@router.get(
    "/wechat-publishing/reports/{content_item_id}/covers",
    response_model=dict[str, Any],
)
def list_report_covers(content_item_id: str):
    try:
        return wechat_publishing_service.list_report_covers(content_item_id)
    except Exception as exc:
        _raise_error(exc)


@router.post(
    "/wechat-publishing/reports/{content_item_id}/covers/{cover_id}/select",
    response_model=dict[str, Any],
)
def select_report_cover(content_item_id: str, cover_id: str):
    try:
        return wechat_publishing_service.select_report_cover(
            content_item_id,
            cover_id,
        )
    except Exception as exc:
        _raise_error(exc)


@router.post("/wechat-publishing/reports/{content_item_id}/cover", response_model=dict[str, Any])
def generate_report_cover(content_item_id: str, req: GenerateCoverRequest):
    try:
        return wechat_publishing_service.queue_report_cover(
            content_item_id,
            title=req.title,
            digest=req.digest,
            visual_brief=req.visual_brief,
        )
    except Exception as exc:
        _raise_error(exc)


@router.post("/wechat-publishing/reports/{content_item_id}/cover-plan", response_model=dict[str, Any])
def plan_report_cover(content_item_id: str, req: PlanCoverRequest):
    try:
        return wechat_publishing_service.plan_report_cover(
            content_item_id,
            title=req.title,
            cover_style=req.cover_style,
        )
    except Exception as exc:
        _raise_error(exc)


@router.post("/wechat-publishing/reports/{content_item_id}/cover-prompt", response_model=dict[str, Any])
def preview_report_cover_prompt(content_item_id: str, req: PreviewCoverPromptRequest):
    try:
        return wechat_publishing_service.preview_report_cover_prompt(
            content_item_id,
            visual_brief=req.visual_brief,
            title=req.title,
        )
    except Exception as exc:
        _raise_error(exc)


@router.post("/wechat-publishing/reports/{content_item_id}/draft", response_model=dict[str, Any])
def create_report_draft(content_item_id: str, req: CreateDraftRequest):
    try:
        return wechat_draft_task_manager.create(
            content_item_id=content_item_id,
            title=req.title,
            digest=req.digest,
            author=req.author,
        )
    except Exception as exc:
        _raise_error(exc)


@router.get("/wechat-publishing/reports/{content_item_id}/draft-task", response_model=dict[str, Any] | None)
def get_latest_report_draft_task(content_item_id: str):
    try:
        return wechat_draft_task_manager.latest_for_content(content_item_id)
    except Exception as exc:
        _raise_error(exc)


@router.get("/wechat-publishing/draft-tasks/{task_id}", response_model=dict[str, Any])
def get_report_draft_task(task_id: str):
    try:
        return wechat_draft_task_manager.get(task_id)
    except Exception as exc:
        _raise_error(exc)


@router.post("/wechat-publishing/publications/{publication_id}/confirm", response_model=dict[str, Any])
def confirm_report_publication(publication_id: str, req: ConfirmPublicationRequest):
    try:
        return wechat_publishing_service.confirm_publication(
            publication_id,
            wechat_article_url=req.wechat_article_url,
        )
    except Exception as exc:
        _raise_error(exc)

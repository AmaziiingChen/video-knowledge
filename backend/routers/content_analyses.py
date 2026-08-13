from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from services.content_analysis import ContentAnalysisRecord, create_content_analysis, list_content_analyses
from services.llm_settings import text_model_configured


router = APIRouter()


class CreateContentAnalysisRequest(BaseModel):
    template_id: str | None = None
    ai_model: str | None = None


class ContentAnalysisResponse(BaseModel):
    id: str
    content_item_id: str
    prompt_template_id: str | None = None
    prompt_template_name: str
    prompt_version: str
    model: str
    content: str
    created_at: str


def _to_response(record: ContentAnalysisRecord) -> ContentAnalysisResponse:
    return ContentAnalysisResponse(
        id=record.id,
        content_item_id=record.content_item_id,
        prompt_template_id=record.prompt_template_id,
        prompt_template_name=record.prompt_template_name,
        prompt_version=record.prompt_version,
        model=record.model,
        content=record.content,
        created_at=record.created_at,
    )


@router.get("/content/{item_id}/analyses", response_model=list[ContentAnalysisResponse])
async def get_content_analyses(item_id: str, limit: int = Query(default=20, ge=1, le=100)):
    try:
        return [_to_response(record) for record in list_content_analyses(item_id, limit=limit)]
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="内容不存在") from exc


@router.post("/content/{item_id}/analyses", response_model=ContentAnalysisResponse)
def run_content_analysis(item_id: str, req: CreateContentAnalysisRequest):
    if not text_model_configured(req.ai_model):
        raise HTTPException(status_code=400, detail="请先在设置中配置所选文本模型的 API Key")
    try:
        record = create_content_analysis(
            item_id,
            template_id=req.template_id,
            model=req.ai_model,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="内容或分析模板不存在") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _to_response(record)

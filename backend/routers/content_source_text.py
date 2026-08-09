from fastapi import APIRouter, HTTPException

from services.content_presentation import ContentTextReadinessResponse, readiness_response
from services.content_source_text import inspect_content_text_readiness, load_content_source_text
from services.database import connect, initialize_database
from services.repository import ContentRepository


router = APIRouter()


def _require_content_item(content_item_id: str):
    initialize_database()
    with connect() as connection:
        try:
            return ContentRepository(connection).get_content_item(content_item_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="内容不存在") from exc


@router.get("/content/{item_id}/text-readiness", response_model=ContentTextReadinessResponse)
async def get_content_text_readiness(item_id: str):
    return readiness_response(inspect_content_text_readiness(_require_content_item(item_id)))


@router.post("/content/{item_id}/source-text/refresh", response_model=ContentTextReadinessResponse)
def refresh_content_source_text(item_id: str):
    """Retry article text capture on an explicit user action, never via listing."""
    item = _require_content_item(item_id)
    if item.source_provider not in {"wechat", "campus", "rss"} or item.content_type != "article":
        raise HTTPException(status_code=400, detail="仅已支持的文章来源可以重新抓取正文")
    try:
        load_content_source_text(item.id, refresh=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return readiness_response(inspect_content_text_readiness(item))

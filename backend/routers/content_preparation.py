from fastapi import APIRouter, HTTPException

from services.article_ingest_preparation import (
    article_image_ocr_status,
    article_source_preparation_status,
    prioritize_article_image_ocr,
)


router = APIRouter()


@router.get("/content/article-preparation-status", response_model=dict)
async def get_article_preparation_status():
    """Expose the real background body-capture/OCR queue to the desktop UI."""
    return article_source_preparation_status()


@router.get("/content/{content_item_id}/article-ocr-status", response_model=dict)
async def get_article_ocr_status(content_item_id: str):
    """Report whether this article's image text is ready for later AI requests."""
    return article_image_ocr_status(content_item_id)


@router.post("/content/{content_item_id}/prioritize-article-ocr", response_model=dict)
async def prioritize_article_ocr(content_item_id: str):
    """Promote one article's pending image OCR without issuing duplicate jobs."""
    status = prioritize_article_image_ocr(content_item_id)
    if status["status"] == "unavailable":
        raise HTTPException(status_code=404, detail="未找到可识别图片的文章")
    return status

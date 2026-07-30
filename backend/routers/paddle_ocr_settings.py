from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.paddle_ocr_settings import (
    paddle_ocr_settings_status,
    reveal_paddle_ocr_access_token,
    save_paddle_ocr_settings,
)


router = APIRouter()


class PaddleOcrSettingsRequest(BaseModel):
    access_token: str | None = Field(default=None, max_length=1000)
    base_url: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=160)


@router.get("/paddle-ocr-settings")
async def get_paddle_ocr_settings():
    return paddle_ocr_settings_status()


@router.put("/paddle-ocr-settings")
async def put_paddle_ocr_settings(req: PaddleOcrSettingsRequest):
    try:
        return save_paddle_ocr_settings(
            access_token=req.access_token,
            base_url=req.base_url,
            model=req.model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/paddle-ocr-settings/reveal")
async def post_reveal_paddle_ocr_access_token():
    return {"secret": reveal_paddle_ocr_access_token()}

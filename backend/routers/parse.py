from fastapi import APIRouter
from pydantic import BaseModel
from services.url_parser import parse_share_text

router = APIRouter()

class ParseRequest(BaseModel):
    text: str

class ParseResponse(BaseModel):
    success: bool
    url: str | None = None
    platform: str | None = None
    error: str | None = None

@router.post("/parse", response_model=ParseResponse)
async def parse_url(req: ParseRequest):
    result = parse_share_text(req.text)
    if result:
        return ParseResponse(success=True, url=result.url, platform=result.platform)
    return ParseResponse(success=False, error="未识别到有效链接")

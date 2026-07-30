from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from services.summarizer import summarize, generate_markdown
from config import settings
from datetime import datetime
from services.obsidian_settings import automatic_markdown_write_enabled

router = APIRouter()

class SummarizeRequest(BaseModel):
    transcript: str
    video_title: str = ""
    video_info: dict = Field(default_factory=dict)
    source_url: str = ""

class SummarizeResponse(BaseModel):
    success: bool
    summary: str | None = None
    markdown: str | None = None
    obsidian_path: str | None = None
    error: str | None = None

@router.post("/summarize", response_model=SummarizeResponse)
def summarize_transcript(req: SummarizeRequest):
    if not settings.deepseek_api_key:
        raise HTTPException(status_code=500, detail="未配置 DeepSeek API Key")
    
    try:
        ai_title, summary = summarize(req.transcript, req.video_title)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not summary:
        raise HTTPException(status_code=500, detail="总结生成失败")
    
    video_info = {**req.video_info, "transcript": req.transcript}
    markdown = generate_markdown(summary, video_info, req.source_url)
    
    safe_title = "".join(c if c.isalnum() or c in " -_" else "_" for c in ai_title)[:80]
    if not safe_title:
        safe_title = f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    obsidian_path = settings.obsidian_vault / f"{safe_title}.md"
    written_path = None
    if automatic_markdown_write_enabled():
        obsidian_path.parent.mkdir(parents=True, exist_ok=True)
        obsidian_path.write_text(markdown, encoding="utf-8")
        written_path = str(obsidian_path)
    
    return SummarizeResponse(
        success=True,
        summary=summary,
        markdown=markdown,
        obsidian_path=written_path
    )

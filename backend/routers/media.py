from __future__ import annotations

import mimetypes
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response

from config import settings
from services.database import connect, initialize_database
from services.knowledge_library import attachments_root


router = APIRouter()


def _is_allowed_media_path(path: Path) -> bool:
    """Expose data media plus originals that the library explicitly owns."""
    try:
        path.relative_to(settings.data_dir.expanduser().resolve())
        return True
    except ValueError:
        pass
    try:
        path.relative_to(attachments_root().resolve())
        return True
    except ValueError:
        pass
    try:
        initialize_database()
        with connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM media_assets WHERE asset_type='original_file' AND path=? LIMIT 1",
                (str(path),),
            ).fetchone()
        return row is not None
    except Exception:
        return False


@router.get("/media")
async def get_media(request: Request, path: str = Query(..., min_length=1)):
    media_path = Path(path).expanduser().resolve()
    if not _is_allowed_media_path(media_path):
        raise HTTPException(status_code=403, detail="只能访问应用管理的媒体文件")
    if not media_path.exists() or not media_path.is_file():
        raise HTTPException(status_code=404, detail="媒体文件不存在")
    if media_path.suffix.lower() == ".vtt":
        content = media_path.read_text(encoding="utf-8")
        content = re.sub(
            r"(?m)^/api/media\?",
            f"{str(request.base_url).rstrip('/')}/api/media?",
            content,
        )
        return Response(content, media_type="text/vtt")
    media_type = mimetypes.guess_type(str(media_path))[0] or "application/octet-stream"
    return FileResponse(media_path, media_type=media_type, filename=media_path.name, content_disposition_type="inline")

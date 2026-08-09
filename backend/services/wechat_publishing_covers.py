from __future__ import annotations

import base64
import hashlib
import io
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import quote

from config import settings
from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError

from services.wechat_publishing_secrets import WeChatPublishingError


def cover_bytes(
    cover_url: str,
    *,
    cover_path: str = "",
) -> tuple[bytes, str, str]:
    if cover_path:
        path = Path(cover_path).expanduser().resolve()
        try:
            path.relative_to(settings.data_dir.expanduser().resolve())
        except ValueError as exc:
            raise WeChatPublishingError("本地封面路径不在 KnowledgeHub 数据目录中") from exc
        if path.is_file():
            mime_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
            return path.read_bytes(), path.name, mime_type
    value = str(cover_url or "").strip()
    if value.startswith(("data:image/jpeg;base64,", "data:image/jpg;base64,")) and "," in value:
        _, encoded = value.split(",", 1)
        try:
            return base64.b64decode(encoded, validate=True), "report-cover.jpg", "image/jpeg"
        except (ValueError, TypeError):
            pass
    if value.startswith("data:image/png;base64,") and "," in value:
        _, encoded = value.split(",", 1)
        try:
            return base64.b64decode(encoded, validate=True), "report-cover.png", "image/png"
        except (ValueError, TypeError):
            pass
    image = Image.new("RGB", (900, 500), "#FDF6E3")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((54, 54, 846, 446), radius=34, fill="#E8DECB")
    draw.rectangle((104, 130, 620, 154), fill="#3D3A32")
    draw.rectangle((104, 190, 760, 206), fill="#8E877A")
    draw.rectangle((104, 226, 690, 242), fill="#8E877A")
    draw.rectangle((104, 338, 370, 354), fill="#8E877A")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue(), "knowledgehub-report-cover.png", "image/png"


def normalized_cover_jpeg_bytes(image_bytes: bytes) -> bytes:
    """Return a compact, predictable cover ready for local persistence."""
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            normalized = ImageOps.fit(
                image.convert("RGB"),
                (900, 383),
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
            buffer = io.BytesIO()
            normalized.save(buffer, format="JPEG", quality=88, optimize=True)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise WeChatPublishingError("千问返回的封面不是有效图片，请重试") from exc
    return buffer.getvalue()


def write_local_cover(content_item_id: str, image_bytes: bytes) -> Path:
    """Atomically replace the current local file only after normalization."""
    safe_id = "".join(character for character in content_item_id if character.isalnum() or character in "-_")
    if not safe_id:
        raise WeChatPublishingError("报告标识无效，无法保存封面")
    directory = settings.data_dir / "report_covers" / safe_id
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"cover-{hashlib.sha256(image_bytes).hexdigest()[:16]}.jpg"
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="wb",
            prefix="cover-",
            suffix=".jpg.tmp",
            dir=directory,
            delete=False,
        ) as handle:
            handle.write(image_bytes)
            handle.flush()
            os.fsync(handle.fileno())
            temporary_path = Path(handle.name)
        os.replace(temporary_path, target)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink(missing_ok=True)
    return target.resolve()


def remove_uncommitted_cover(cover_path: str) -> None:
    path = Path(cover_path).expanduser().resolve()
    try:
        path.relative_to((settings.data_dir / "report_covers").resolve())
    except ValueError:
        return
    if path.is_file():
        path.unlink(missing_ok=True)


def validated_local_cover_path(cover_path: str) -> Path:
    path = Path(cover_path).expanduser().resolve()
    try:
        path.relative_to((settings.data_dir / "report_covers").resolve())
    except ValueError as exc:
        raise WeChatPublishingError("封面版本不在 KnowledgeHub 数据目录中") from exc
    if not path.is_file():
        raise WeChatPublishingError("本地封面文件已不存在")
    return path


def local_cover_url(path: Path, *, version: str) -> str:
    return (
        "http://127.0.0.1:8000/api/media?"
        f"path={quote(str(path), safe='')}&v={quote(str(version), safe='')}"
    )


def has_persisted_cover(cover_url: str, cover_path: str) -> bool:
    if cover_path and Path(cover_path).expanduser().is_file():
        return True
    return str(cover_url or "").startswith("data:image/")

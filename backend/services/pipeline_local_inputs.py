"""Prepare authorized local subtitle and media inputs for the pipeline."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.cache import (
    cache_dir_for_url,
    media_duration_seconds,
    write_cached_subtitle_transcript,
)
from services.pipeline_contracts import TextSourceInfo
from services.pipeline_local_media_policy import is_managed_local_media
from services.subtitles import SUBTITLE_EXTENSIONS, parse_subtitle_text

LOCAL_AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg", ".opus"}


class LocalInputError(ValueError):
    def __init__(self, step: str, message: str) -> None:
        super().__init__(message)
        self.step = step


@dataclass(frozen=True)
class LocalPipelineSource:
    url: str
    platform: str


@dataclass(frozen=True)
class PreparedLocalSubtitle:
    path: Path
    source: LocalPipelineSource
    cache_dir: Path
    transcript: str
    video_info: dict[str, Any]
    text_source: TextSourceInfo


@dataclass(frozen=True)
class PreparedLocalMedia:
    path: Path
    source: LocalPipelineSource
    cache_dir: Path
    video_info: dict[str, Any]
    is_audio: bool


def prepare_local_subtitle(
    local_subtitle_path: str,
    *,
    source_url: str | None,
    source_title: str | None,
    content_item_id: str | None,
    authorize: Callable[..., bool] = is_managed_local_media,
    parse_subtitle: Callable[[str, str], str] = parse_subtitle_text,
    resolve_cache_dir: Callable[[str], Path] = cache_dir_for_url,
    cache_subtitle: Callable[[Path, str], None] = write_cached_subtitle_transcript,
) -> PreparedLocalSubtitle:
    path = Path(local_subtitle_path).expanduser().resolve()
    if not authorize(path, content_item_id=content_item_id):
        raise LocalInputError("parse", "本地字幕必须位于 data 目录下")
    if not path.exists() or not path.is_file():
        raise LocalInputError("parse", "本地字幕文件不存在")
    if path.suffix.lower() not in SUBTITLE_EXTENSIONS:
        raise LocalInputError("parse", f"不支持的字幕格式: {path.suffix}")

    transcript = parse_subtitle(
        path.read_text(encoding="utf-8", errors="replace"),
        path.suffix,
    )
    if not transcript:
        raise LocalInputError("transcribe", "字幕文件为空或无法解析")

    source = LocalPipelineSource(
        url=source_url or f"local://{path.name}",
        platform="subtitle",
    )
    cache_dir = resolve_cache_dir(source.url)
    cache_subtitle(cache_dir, transcript)
    return PreparedLocalSubtitle(
        path=path,
        source=source,
        cache_dir=cache_dir,
        transcript=transcript,
        video_info={
            "title": source_title or path.stem,
            "platform": "subtitle",
            "duration": 0,
        },
        text_source=TextSourceInfo(
            kind="subtitle",
            source="manual",
            detail=path.name,
        ),
    )


def prepare_local_media(
    local_media_path: str,
    *,
    source_url: str | None,
    source_title: str | None,
    content_item_id: str | None,
    authorize: Callable[..., bool] = is_managed_local_media,
    resolve_cache_dir: Callable[[str], Path] = cache_dir_for_url,
    read_duration: Callable[[Path], float | None] = media_duration_seconds,
) -> PreparedLocalMedia:
    path = Path(local_media_path).expanduser().resolve()
    if not authorize(path, content_item_id=content_item_id):
        raise LocalInputError("parse", "本地媒体不在应用管理的 data 或附件目录中")
    if not path.exists() or not path.is_file():
        raise LocalInputError("parse", "本地视频文件不存在")

    source = LocalPipelineSource(
        url=source_url or f"local://{path.name}",
        platform="local",
    )
    cache_dir = resolve_cache_dir(source.url)
    cache_dir.mkdir(parents=True, exist_ok=True)
    return PreparedLocalMedia(
        path=path,
        source=source,
        cache_dir=cache_dir,
        video_info={
            "title": source_title or path.stem,
            "platform": "local",
            "duration": read_duration(path) or 0,
        },
        is_audio=path.suffix.lower() in LOCAL_AUDIO_EXTENSIONS,
    )

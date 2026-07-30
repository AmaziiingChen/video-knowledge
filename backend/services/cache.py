from __future__ import annotations

import hashlib
import json
import sqlite3
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from urllib.parse import quote

from config import settings
from services.database import connect
from services.ffmpeg_runner import run_ffmpeg
from services.media_tools import resolve_tool
from services.text_normalizer import normalize_transcript_segments, normalize_transcript_text


MEDIA_EXTENSIONS = {".mp4", ".mkv", ".webm", ".flv"}
THUMBNAIL_SPRITE_NAME = "preview_sprite.jpg"
THUMBNAIL_VTT_NAME = "preview_thumbnails.vtt"
THUMBNAIL_WIDTH = 160
THUMBNAIL_HEIGHT = 90
THUMBNAIL_COLUMNS = 5
THUMBNAIL_MAX_ITEMS = 80
_cache_meta_lock = RLock()


def cache_key_for_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def cache_dir_for_url(url: str) -> Path:
    return settings.data_dir / "cache" / cache_key_for_url(url)


def cache_meta_path(cache_dir: Path) -> Path:
    return cache_dir / "metadata.json"


def read_cache_meta(cache_dir: Path) -> dict:
    with _cache_meta_lock:
        path = cache_meta_path(cache_dir)
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}


def write_cache_meta(cache_dir: Path, updates: dict) -> dict:
    """Merge metadata under one lock and atomically replace the JSON file.

    Pipeline stages, the article preview, and OCR may all update the same cache
    directory. A direct overwrite can lose another stage's data or leave a
    truncated JSON file after an interrupted write.
    """
    with _cache_meta_lock:
        cache_dir.mkdir(parents=True, exist_ok=True)
        data = read_cache_meta(cache_dir)
        data.update(updates)
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        path = cache_meta_path(cache_dir)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=cache_dir,
            prefix=f".{path.stem}-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            temp_path = Path(handle.name)
        temp_path.replace(path)
    return data


def find_cached_video(cache_dir: Path) -> Path | None:
    if not cache_dir.exists():
        return None
    candidates = [
        path for path in cache_dir.iterdir()
        if path.is_file()
        and path.suffix.lower() in MEDIA_EXTENSIONS
        and not path.stem.endswith("_audio")
        and not path.stem.endswith("_video")
        and path.stat().st_size > 10000
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def transcript_path(cache_dir: Path, model_name: str) -> Path:
    safe_model = "".join(c if c.isalnum() or c in "-_" else "_" for c in model_name)
    return cache_dir / f"transcript_{safe_model}.txt"


def subtitle_transcript_path(cache_dir: Path) -> Path:
    return cache_dir / "transcript_subtitle.txt"


def read_cached_transcript(cache_dir: Path, model_name: str) -> str | None:
    path = transcript_path(cache_dir, model_name)
    if not path.exists():
        return None
    text = normalize_transcript_text(path.read_text(encoding="utf-8"))
    return text or None


def write_cached_transcript(cache_dir: Path, model_name: str, transcript: str) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = transcript_path(cache_dir, model_name)
    path.write_text(normalize_transcript_text(transcript), encoding="utf-8")
    write_cache_meta(
        cache_dir,
        {
            "transcripts": {
                **read_cache_meta(cache_dir).get("transcripts", {}),
                model_name: path.name,
            }
        },
    )
    return path


def read_cached_subtitle_transcript(cache_dir: Path) -> str | None:
    path = subtitle_transcript_path(cache_dir)
    if not path.exists():
        return None
    text = normalize_transcript_text(path.read_text(encoding="utf-8"))
    return text or None


def write_cached_subtitle_transcript(cache_dir: Path, transcript: str) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = subtitle_transcript_path(cache_dir)
    path.write_text(normalize_transcript_text(transcript), encoding="utf-8")
    write_cache_meta(
        cache_dir,
        {
            "subtitle_transcript": path.name,
            "transcripts": {
                **read_cache_meta(cache_dir).get("transcripts", {}),
                "subtitle": path.name,
            },
        },
    )
    return path


def directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(file.stat().st_size for file in path.rglob("*") if file.is_file())


def media_duration_seconds(path: Path | None) -> float | None:
    if not path or not path.exists():
        return None
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=nw=1:nk=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    try:
        value = float((result.stdout or "").strip())
    except ValueError:
        return None
    return value if value > 0 else None


def media_api_url(path: Path | None) -> str | None:
    if not path:
        return None
    return f"/api/media?path={quote(str(path), safe='')}"


def thumbnail_vtt_path(cache_dir: Path) -> Path:
    return cache_dir / THUMBNAIL_VTT_NAME


def cached_thumbnail_vtt_url(cache_dir: Path) -> str | None:
    path = thumbnail_vtt_path(cache_dir)
    if not path.exists():
        return None
    return media_api_url(path)


def ensure_preview_thumbnails(cache_dir: Path, video_path: Path | None) -> Path | None:
    if not video_path or not video_path.exists():
        return None

    cache_dir.mkdir(parents=True, exist_ok=True)
    sprite_path = cache_dir / THUMBNAIL_SPRITE_NAME
    vtt_path = thumbnail_vtt_path(cache_dir)
    if sprite_path.exists() and vtt_path.exists():
        return vtt_path

    duration = media_duration_seconds(video_path)
    if not duration:
        return None

    interval = max(5, int(duration / THUMBNAIL_MAX_ITEMS) + 1)
    item_count = max(1, min(THUMBNAIL_MAX_ITEMS, int(duration / interval) + 1))
    rows = max(1, (item_count + THUMBNAIL_COLUMNS - 1) // THUMBNAIL_COLUMNS)
    vf = (
        f"fps=1/{interval},"
        f"scale={THUMBNAIL_WIDTH}:{THUMBNAIL_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={THUMBNAIL_WIDTH}:{THUMBNAIL_HEIGHT}:(ow-iw)/2:(oh-ih)/2,"
        f"tile={THUMBNAIL_COLUMNS}x{rows}"
    )

    temporary_sprite_path = sprite_path.with_name(f"{sprite_path.stem}.partial{sprite_path.suffix}")
    temporary_sprite_path.unlink(missing_ok=True)
    try:
        result = run_ffmpeg(
            [
                resolve_tool("ffmpeg") or "ffmpeg",
                "-y",
                "-i",
                str(video_path),
                "-vf",
                vf,
                "-frames:v",
                "1",
                "-q:v",
                "5",
                str(temporary_sprite_path),
            ],
            output_path=temporary_sprite_path,
            duration_seconds=duration,
        )
    except Exception:
        temporary_sprite_path.unlink(missing_ok=True)
        return None
    if not result.success or not temporary_sprite_path.exists():
        temporary_sprite_path.unlink(missing_ok=True)
        return None
    temporary_sprite_path.replace(sprite_path)

    sprite_url = media_api_url(sprite_path)
    if not sprite_url:
        return None
    vtt_path.write_text(
        _build_thumbnail_vtt(
            sprite_url=sprite_url,
            duration=duration,
            interval=interval,
            item_count=item_count,
        ),
        encoding="utf-8",
    )
    write_cache_meta(cache_dir, {"thumbnail_vtt": vtt_path.name, "thumbnail_sprite": sprite_path.name})
    return vtt_path


def _build_thumbnail_vtt(*, sprite_url: str, duration: float, interval: int, item_count: int) -> str:
    lines = ["WEBVTT", ""]
    for index in range(item_count):
        start = index * interval
        end = min((index + 1) * interval, duration)
        if end <= start:
            end = start + 1
        x = (index % THUMBNAIL_COLUMNS) * THUMBNAIL_WIDTH
        y = (index // THUMBNAIL_COLUMNS) * THUMBNAIL_HEIGHT
        lines.extend([
            f"{_format_vtt_time(start)} --> {_format_vtt_time(end)}",
            f"{sprite_url}#xywh={x},{y},{THUMBNAIL_WIDTH},{THUMBNAIL_HEIGHT}",
            "",
        ])
    return "\n".join(lines)


def _format_vtt_time(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}.{millis:03}"


def transcript_segments_path(cache_dir: Path, model_name: str) -> Path:
    safe_model = "".join(c if c.isalnum() or c in "-_" else "_" for c in model_name)
    return cache_dir / f"transcript_{safe_model}_segments.json"


def write_cached_transcript_segments(cache_dir: Path, model_name: str, segments: list[dict]) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = transcript_segments_path(cache_dir, model_name)
    path.write_text(json.dumps(normalize_transcript_segments(segments), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_cached_transcript_segments(
    cache_dir: Path,
    *,
    preferred_model: str | None = None,
    duration: float | None = None,
) -> list[dict]:
    model_names = [preferred_model] if preferred_model else []
    model_names.extend(
        path.name.replace("transcript_", "").removesuffix(".txt")
        for path in sorted(cache_dir.glob("transcript_*.txt"))
        if path.is_file() and not path.name.endswith("_segments.json")
    )

    seen = set()
    for model in model_names:
        if not model or model in seen:
            continue
        seen.add(model)
        segments_path = transcript_segments_path(cache_dir, model)
        segments = _read_segment_file(segments_path)
        if segments:
            return segments
        transcript = read_cached_transcript(cache_dir, model)
        if transcript:
            return approximate_transcript_segments(transcript, duration=duration)
    return []


def _read_segment_file(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = []
    return _normalize_segments(data)


def approximate_transcript_segments(transcript: str, *, duration: float | None = None) -> list[dict]:
    lines = [line.strip() for line in transcript.splitlines() if line.strip()]
    if not lines:
        return []
    usable_duration = max(float(duration or 0), 0.0)
    step = usable_duration / max(len(lines), 1) if usable_duration else 0.0
    segments = []
    for index, line in enumerate(lines):
        start = index * step if step else None
        end = (index + 1) * step if step else None
        segments.append({
            "start_seconds": start,
            "end_seconds": end,
            "text": line,
            "position": index,
            "approximate": True,
        })
    return segments


def _normalize_segments(data: list[dict]) -> list[dict]:
    segments = []
    for index, item in enumerate(data if isinstance(data, list) else []):
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        segments.append({
            "start_seconds": item.get("start_seconds"),
            "end_seconds": item.get("end_seconds"),
            "text": text,
            "position": int(item.get("position") or index),
            "approximate": bool(item.get("approximate", False)),
        })
    return segments


def list_cache_entries(
    *,
    include_size: bool = True,
) -> list[dict]:
    """List cache metadata for internal content-index backfill."""
    cache_root = settings.data_dir / "cache"
    if not cache_root.exists():
        return []

    wechat_source_names = _wechat_source_names_by_url()
    entries = []
    for cache_dir in cache_root.iterdir():
        if not cache_dir.is_dir():
            continue
        entry = _cache_entry_from_directory(
            cache_dir,
            wechat_source_names=wechat_source_names,
            include_size=include_size,
        )
        if entry:
            entries.append(entry)

    return sorted(entries, key=lambda item: item.get("updated_at") or "", reverse=True)


def cache_entry_for_url(source_url: str, *, include_size: bool = True) -> dict | None:
    source_url = str(source_url or "").strip()
    if not source_url:
        return None
    return _cache_entry_from_directory(cache_dir_for_url(source_url), include_size=include_size)


def _cache_entry_from_directory(
    cache_dir: Path,
    *,
    wechat_source_names: dict[str, str] | None = None,
    include_size: bool = True,
) -> dict | None:
    if not cache_dir.exists() or not cache_dir.is_dir():
        return None
    meta = read_cache_meta(cache_dir)
    video = find_cached_video(cache_dir)
    transcripts = sorted(
        path.name.replace("transcript_", "").removesuffix(".txt")
        for path in cache_dir.glob("transcript_*.txt")
        if path.is_file()
    )
    video_info = meta.get("video_info") or {}
    article_info = meta.get("article_info") or {}
    is_article = bool(article_info.get("body_text") or meta.get("platform") in {"wechat", "campus"})
    image_ocr = article_info.get("image_ocr") or {}
    duration = 0 if is_article else (video_info.get("duration") or media_duration_seconds(video) or 0)
    source_url = str(meta.get("source_url") or "")
    platform = str(meta.get("platform") or "unknown")
    source_name = str(
        article_info.get("author")
        or video_info.get("uploader")
        or video_info.get("author")
        or ((wechat_source_names or {}).get(source_url) if platform == "wechat" else "")
        or ""
    ).strip()
    return {
        "cache_key": cache_dir.name,
        "source_url": source_url,
        "platform": platform,
        "source_name": source_name,
        "title": (
            article_info.get("title")
            or video_info.get("title")
            or meta.get("title")
            or ("未命名文章" if is_article else "未命名视频")
        ),
        "content_kind": "article" if is_article else "video",
        "article_body_characters": len(str(article_info.get("body_text") or "")),
        "article_image_count": int(image_ocr.get("image_count") or len(article_info.get("images") or [])),
        "article_cached_image_count": int(image_ocr.get("cached_image_count") or 0),
        "article_ocr_recognized_count": int(image_ocr.get("recognized_count") or 0),
        "duration": duration,
        "updated_at": meta.get("updated_at", ""),
        "video_path": str(video) if video else None,
        "video_cache_status": "available" if video else str(meta.get("video_cache_status") or "missing"),
        "video_cache_expires_at": meta.get("video_cache_expires_at"),
        "video_cache_expired_at": meta.get("video_cache_expired_at"),
        "thumbnail_vtt_url": cached_thumbnail_vtt_url(cache_dir),
        "obsidian_path": meta.get("obsidian_path"),
        "transcripts": transcripts,
        "size_bytes": directory_size(cache_dir) if include_size else 0,
    }


def _wechat_source_names_by_url() -> dict[str, str]:
    try:
        with connect() as connection:
            rows = connection.execute(
                """
                SELECT item.source_url, subscription.mp_name
                FROM wechat_subscription_items AS item
                JOIN wechat_subscriptions AS subscription ON subscription.id = item.subscription_id
                WHERE TRIM(item.source_url) <> '' AND TRIM(subscription.mp_name) <> ''
                ORDER BY item.discovered_at DESC
                """
            ).fetchall()
    except (OSError, sqlite3.Error):
        return {}

    names: dict[str, str] = {}
    for row in rows:
        source_url = str(row["source_url"] or "").strip()
        source_name = str(row["mp_name"] or "").strip()
        if source_url and source_name:
            names.setdefault(source_url, source_name)
    return names


def delete_cache_entry(cache_key: str) -> bool:
    if not cache_key or "/" in cache_key or "\\" in cache_key or ".." in cache_key:
        return False

    cache_root = (settings.data_dir / "cache").resolve()
    cache_dir = (cache_root / cache_key).resolve()
    if cache_root not in cache_dir.parents or not cache_dir.exists() or not cache_dir.is_dir():
        return False

    shutil.rmtree(cache_dir)
    return True

"""Compact, local-only article image previews.

Article reading needs local images for a fast, offline first render, but the
source-sized files are not part of the Markdown knowledge record.  This module
keeps a single WebP preview per cached article image and provides a cautious
one-time compaction pass for older cache entries.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

from PIL import Image, ImageOps, UnidentifiedImageError

from config import settings
from services.cache import read_cache_meta, write_cache_meta


ARTICLE_IMAGE_PREVIEW_MAX_EDGE = 1440
ARTICLE_IMAGE_PREVIEW_QUALITY = 76
ARTICLE_IMAGE_PREVIEW_MAX_SOURCE_PIXELS = 10_000_000
_RASTER_EXTENSIONS = {".avif", ".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}


def write_article_image_preview(
    image_bytes: bytes,
    *,
    filename_stem: str,
    image_cache_dir: Path | None,
) -> str:
    """Write a WebP preview and return its absolute path.

    The original bytes are used by OCR before this function is called.  If an
    uncommon or animated format cannot be safely converted, retain a local
    source-sized fallback instead of leaving the article preview without an
    image.
    """
    if image_cache_dir is None or not image_bytes:
        return ""
    image_cache_dir.mkdir(parents=True, exist_ok=True)
    target = image_cache_dir / f"{filename_stem}.webp"
    preview = _webp_preview_bytes(image_bytes)
    if preview is None:
        return ""
    _atomic_write_bytes(target, preview)
    return str(target)


def compact_cached_article_images() -> dict[str, int]:
    """Replace legacy source-sized cached images with WebP previews.

    Metadata HTML stores absolute local image paths, so each successful rename
    updates those paths atomically before the old source image is removed.
    """
    root = settings.data_dir / "cache"
    stats = {"scanned": 0, "compressed": 0, "skipped": 0, "bytes_before": 0, "bytes_after": 0}
    if not root.exists():
        return stats

    for cache_dir in root.iterdir():
        image_dir = cache_dir / "article_images"
        if not cache_dir.is_dir() or not image_dir.is_dir():
            continue
        replacements: dict[str, str] = {}
        for source in image_dir.iterdir():
            if not source.is_file() or source.suffix.lower() not in _RASTER_EXTENSIONS:
                continue
            # A WebP file is already the canonical compact preview. Do not
            # re-encode it on a later maintenance run.
            if source.suffix.lower() == ".webp":
                continue
            stats["scanned"] += 1
            before = source.stat().st_size
            target = source.with_suffix(".webp")
            if not _write_cached_preview(source, target):
                stats["skipped"] += 1
                stats["bytes_before"] += before
                stats["bytes_after"] += before
                continue
            after = target.stat().st_size
            stats["bytes_before"] += before
            stats["bytes_after"] += after
            stats["compressed"] += 1
            if source.resolve() != target.resolve():
                replacements[str(source)] = str(target)
                source.unlink(missing_ok=True)

        if replacements:
            _replace_cached_html_paths(cache_dir, replacements)
    return stats


def _replace_cached_html_paths(cache_dir: Path, replacements: dict[str, str]) -> None:
    metadata = read_cache_meta(cache_dir)
    article = metadata.get("article_info")
    if not isinstance(article, dict):
        return
    changed = False
    next_article = dict(article)
    for key in ("body_html", "normalized_html"):
        html = next_article.get(key)
        if not isinstance(html, str):
            continue
        next_html = html
        for source, target in replacements.items():
            next_html = next_html.replace(source, target)
        if next_html != html:
            next_article[key] = next_html
            changed = True
    if changed:
        write_cache_meta(cache_dir, {"article_info": next_article})


def _webp_preview_bytes(image_bytes: bytes) -> bytes | None:
    try:
        with Image.open(BytesIO(image_bytes)) as opened:
            if getattr(opened, "is_animated", False):
                return None
            width, height = opened.size
            # Loading a very large poster or stitched long image can consume
            # hundreds of MB before Pillow gets a chance to downscale it.
            # Keeping that rare source file is safer than destabilising the
            # ingestion process; ordinary images still take the compact path.
            if width * height > ARTICLE_IMAGE_PREVIEW_MAX_SOURCE_PIXELS:
                return None
            image = ImageOps.exif_transpose(opened)
            image.load()
            image.thumbnail((ARTICLE_IMAGE_PREVIEW_MAX_EDGE, ARTICLE_IMAGE_PREVIEW_MAX_EDGE), Image.Resampling.LANCZOS)
            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGBA" if "transparency" in image.info else "RGB")
            output = BytesIO()
            # Method 4 is substantially faster than the maximum-compression
            # mode while producing previews that are visually indistinguishable
            # at the reading workspace's display size.
            image.save(output, format="WEBP", quality=ARTICLE_IMAGE_PREVIEW_QUALITY, method=4)
            return output.getvalue()
    except (OSError, UnidentifiedImageError, ValueError):
        return None


def _write_cached_preview(source: Path, target: Path) -> bool:
    """Write a compact preview, using cwebp when the local tool is available."""
    try:
        with Image.open(source) as image:
            if getattr(image, "is_animated", False):
                return False
            width, height = image.size
            if width * height > ARTICLE_IMAGE_PREVIEW_MAX_SOURCE_PIXELS:
                return False
    except (OSError, UnidentifiedImageError, ValueError):
        return False

    cwebp = shutil.which("cwebp")
    if cwebp:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix=f".{target.stem}-", suffix=".webp", delete=False) as handle:
            temporary = Path(handle.name)
        try:
            command = [cwebp, "-quiet", "-q", str(ARTICLE_IMAGE_PREVIEW_QUALITY), "-m", "4"]
            if max(width, height) > ARTICLE_IMAGE_PREVIEW_MAX_EDGE:
                scale = ARTICLE_IMAGE_PREVIEW_MAX_EDGE / max(width, height)
                command.extend(["-resize", str(max(1, round(width * scale))), str(max(1, round(height * scale)))])
            command.extend([str(source), "-o", str(temporary)])
            result = subprocess.run(command, capture_output=True, timeout=45)
            if result.returncode == 0 and temporary.is_file() and temporary.stat().st_size > 0:
                os.replace(temporary, target)
                return True
        except (OSError, subprocess.SubprocessError):
            pass
        finally:
            temporary.unlink(missing_ok=True)

    try:
        preview = _webp_preview_bytes(source.read_bytes())
        if preview is None:
            return False
        _atomic_write_bytes(target, preview)
        return True
    except OSError:
        return False


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=f".{path.stem}-", suffix=".tmp", delete=False) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    os.replace(temporary, path)

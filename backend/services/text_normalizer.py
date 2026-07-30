from __future__ import annotations

from functools import lru_cache

from opencc import OpenCC


@lru_cache(maxsize=1)
def _simplified_converter() -> OpenCC:
    return OpenCC("t2s")


def normalize_transcript_text(text: str) -> str:
    if not text:
        return ""
    return _simplified_converter().convert(str(text)).strip()


def normalize_transcript_segments(segments: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    for segment in segments or []:
        item = dict(segment)
        item["text"] = normalize_transcript_text(str(item.get("text") or ""))
        normalized.append(item)
    return normalized

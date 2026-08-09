"""Pure source identity helpers for campus digest clustering."""
from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def canonical_url(value: str) -> str:
    parsed = urlsplit(str(value or "").strip())
    query = [
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in {"scene", "from", "isappinstalled", "share_token", "timestamp"}
    ]
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), urlencode(query), ""))


def normalize_identity(value: Any) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", str(value or "")).lower()


def source_hash(material: str) -> str:
    return hashlib.sha256(str(material or "").encode("utf-8")).hexdigest()


def text_shingle_similarity(left: str, right: str) -> float:
    def shingles(value: str) -> set[str]:
        normalized = normalize_identity(value)[:12_000]
        if len(normalized) < 8:
            return {normalized} if normalized else set()
        return {normalized[index : index + 8] for index in range(0, len(normalized) - 7, 3)}

    left_set = shingles(left)
    right_set = shingles(right)
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)

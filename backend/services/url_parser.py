import re
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel

class ParsedURL(BaseModel):
    url: str
    platform: str
    original_text: str

# Creator collections return canonical work URLs instead of share short links.
# Both forms must enter the same download/transcription pipeline.
DOUYIN_PATTERN = re.compile(r'https?://(?:v\.|www\.)?douyin\.com/(?:[A-Za-z0-9_/-]+|video/\d+)')
BILIBILI_PATTERN = re.compile(r'https?://(?:www\.)?bilibili\.com/video/[A-Za-z0-9]+(?:\?p=\d+)?')
BILIBILI_SHORT_PATTERN = re.compile(r'https?://b23\.tv/[A-Za-z0-9]+')
WECHAT_PATTERN = re.compile(r'https?://mp\.weixin\.qq\.com/[^\s]+')
XIAOHONGSHU_PATTERN = re.compile(
    r'https?://(?:www\.)?xiaohongshu\.com/(?:explore|discovery/item|search_result)/[^\s]+',
    re.IGNORECASE,
)
XIAOHONGSHU_SHORT_PATTERN = re.compile(r'https?://(?:www\.)?xhslink\.com/[^\s]+', re.IGNORECASE)

def parse_share_text(text: str) -> Optional[ParsedURL]:
    text = text.strip()
    
    if match := DOUYIN_PATTERN.search(text):
        return ParsedURL(url=match.group(), platform="douyin", original_text=text)
    
    if match := BILIBILI_PATTERN.search(text):
        return ParsedURL(url=match.group(), platform="bilibili", original_text=text)
    
    if match := BILIBILI_SHORT_PATTERN.search(text):
        return ParsedURL(url=match.group(), platform="bilibili", original_text=text)

    if match := WECHAT_PATTERN.search(text):
        return ParsedURL(url=match.group().rstrip('，,。)'), platform="wechat", original_text=text)

    if match := XIAOHONGSHU_PATTERN.search(text):
        return ParsedURL(url=match.group().rstrip('，,。)'), platform="xiaohongshu", original_text=text)

    if match := XIAOHONGSHU_SHORT_PATTERN.search(text):
        return ParsedURL(url=match.group().rstrip('，,。)'), platform="xiaohongshu", original_text=text)
    
    return None


def redact_sensitive_url(url: str) -> str:
    """Keep expiring access parameters out of task logs."""
    parsed = urlsplit(url or "")
    query = [
        (key, "[已隐藏]" if key.lower() == "xsec_token" else value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
    ]
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))

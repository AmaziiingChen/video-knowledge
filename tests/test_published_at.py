import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services.published_at import extract_published_at
from services.article_fetcher import _wechat_publish_time
from services.wechat_subscription import _published_at


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("日期：2026/07/15", "2026-07-15"),
        ("发布时间：2026-07-13 10:39", "2026-07-13 10:39"),
        ("2026/06/16 10:08:07", "2026-06-16 10:08:07"),
        ("2026年07月16日 16:07", "2026-07-16 16:07"),
        ("2026年7月18日10时08分07秒", "2026-07-18 10:08:07"),
        ("July 15, 2026", "2026-07-15"),
        ("July 15, 2026 9:05", "2026-07-15 09:05"),
    ],
)
def test_extract_published_at_preserves_source_precision(source, expected):
    assert extract_published_at(source) == expected


def test_extract_published_at_rejects_invalid_calendar_dates():
    assert extract_published_at("2026-02-30 10:00") == ""


def test_wechat_prefers_the_visible_time_and_keeps_its_precision():
    html = '<em id="publish_time">2026年7月18日 09:05</em><script>var ct="1";</script>'

    assert _wechat_publish_time(html, BeautifulSoup(html, "html.parser")) == "2026-07-18 09:05"


def test_wechat_epoch_fallback_uses_china_time_and_minute_precision():
    china_standard_time = timezone(timedelta(hours=8))
    timestamp = int(datetime(2026, 7, 18, 9, 5, 47, tzinfo=china_standard_time).timestamp())
    html = f'<script>var ct="{timestamp}";</script>'

    assert _wechat_publish_time(html, BeautifulSoup(html, "html.parser")) == "2026-07-18 09:05"
    assert _published_at(timestamp) == "2026-07-18 09:05"

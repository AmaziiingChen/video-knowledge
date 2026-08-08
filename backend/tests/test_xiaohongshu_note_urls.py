from services.providers.xiaohongshu import XiaohongshuProvider
from services.clipboard_watcher import extract_supported_links
from services.url_parser import parse_share_text
from services.xiaohongshu_links import resolve_xiaohongshu_share_url


SEARCH_RESULT_NOTE_URL = (
    "https://www.xiaohongshu.com/search_result/6a6a14c7000000000e035eb6"
    "?xsec_token=token-value&xsec_source=pc_search"
)


def test_search_result_note_url_enters_the_same_xiaohongshu_note_pipeline():
    parsed = parse_share_text(SEARCH_RESULT_NOTE_URL)
    provider = XiaohongshuProvider()

    assert parsed is not None
    assert parsed.platform == "xiaohongshu"
    assert provider.can_handle(parsed.url)

    resolved = provider.resolve(parsed.url)
    assert resolved.content_type == "article"
    assert resolved.canonical_source_id == "6a6a14c7000000000e035eb6"
    assert resolved.source_url == (
        "https://www.xiaohongshu.com/explore/6a6a14c7000000000e035eb6"
        "?xsec_token=token-value&xsec_source=pc_search"
    )


def test_xhslink_cn_share_text_enters_the_same_safe_note_pipeline():
    share_text = (
        "国内航线燃油附加费8月5日起再下调 7月31日，去哪儿接... "
        "http://xhslink.cn/o/8PYiaAw8RtE\n去【小红书】逛逛，这篇笔记超有料！"
    )
    parsed = parse_share_text(share_text)

    assert parsed is not None
    assert parsed.platform == "xiaohongshu"
    assert parsed.url == "http://xhslink.cn/o/8PYiaAw8RtE"

    class Response:
        status_code = 302
        headers = {
            "location": (
                "https://www.xiaohongshu.com/explore/6a666e2b000000001c0108b4"
                "?xsec_token=token-value&xsec_source=pc_feed"
            )
        }

    resolved_url = resolve_xiaohongshu_share_url(
        parsed.url,
        request_get=lambda *_args, **_kwargs: Response(),
    )
    assert resolved_url == Response.headers["location"]


def test_clipboard_listener_extracts_xhslink_cn_from_full_share_text():
    share_text = (
        "国内航线燃油附加费8月5日起再下调 7月31日，去哪儿接... "
        "http://xhslink.cn/o/8PYiaAw8RtE\n去【小红书】逛逛，这篇笔记超有料！"
    )

    assert extract_supported_links(share_text) == ["http://xhslink.cn/o/8PYiaAw8RtE"]

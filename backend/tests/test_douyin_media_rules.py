from services import douyin_media_rules, downloader


def _payload() -> dict:
    return {
        "item_list": [
            {
                "aweme_id": "123",
                "video": {
                    "bit_rate": [
                        {
                            "bit_rate": 500_000,
                            "gear_name": "low",
                            "play_addr": {"url_list": ["https://cdn.example/low"]},
                        },
                        {
                            "bit_rate": 1_600_000,
                            "gear_name": "standard",
                            "play_addr": {"url_list": ["https://cdn.example/standard"]},
                        },
                        {
                            "bit_rate": 3_200_000,
                            "gear_name": "high",
                            "play_addr": {"url_list": ["https://cdn.example/high"]},
                        },
                    ]
                },
            }
        ]
    }


def test_downloader_keeps_douyin_rule_compatibility_aliases():
    assert downloader._looks_like_douyin_video_url is douyin_media_rules.looks_like_video_url
    assert downloader._browser_media_headers is douyin_media_rules.browser_media_headers
    assert downloader._select_douyin_video_variant is douyin_media_rules.select_video_variant
    assert downloader._find_douyin_aweme is douyin_media_rules.find_aweme


def test_media_host_requires_an_exact_domain_or_real_subdomain_boundary():
    assert douyin_media_rules.is_media_host("https://v3-web.douyinvod.com/video/tos/example.mp4")
    assert douyin_media_rules.is_media_host("https://www.douyin.com/aweme/v1/play/")
    assert not douyin_media_rules.is_media_host("https://douyin.com.evil.example/video_id=attack")
    assert not douyin_media_rules.looks_like_video_url(
        "https://douyin.com.evil.example/video_id=attack"
    )


def test_media_headers_exclude_credentials_and_transport_metadata():
    headers = douyin_media_rules.browser_media_headers(
        {
            "user-agent": "browser",
            "referer": "https://www.douyin.com/",
            "cookie": "session=private",
            "authorization": "Bearer private",
            "host": "cdn.example",
        }
    )

    assert headers == {
        "user-agent": "browser",
        "referer": "https://www.douyin.com/",
        "accept": "*/*",
        "accept-encoding": "identity",
    }


def test_variant_selection_preserves_low_standard_high_policy_and_legacy_fallback():
    payload = _payload()
    legacy = {
        "aweme_detail": {
            "aweme_id": "legacy",
            "video": {"play_addr": {"url_list": ["https://cdn.example/default"]}},
        }
    }

    assert douyin_media_rules.select_video_variant(payload, "123", "low")[0].endswith("/low")
    assert douyin_media_rules.select_video_variant(payload, "123", "standard")[0].endswith(
        "/standard"
    )
    assert douyin_media_rules.select_video_variant(payload, "123", "high")[0].endswith("/high")
    assert douyin_media_rules.select_video_variant(legacy, "legacy", "standard") == (
        "https://cdn.example/default",
        0,
        "默认",
    )

import json

from services.wechat_subscription_client import (
    WECHAT_MP_BASE_URL,
    WECHAT_REMOTE_CONNECT_TIMEOUT_SECONDS,
    WECHAT_REMOTE_READ_TIMEOUT_SECONDS,
    WECHAT_USER_AGENT,
    WeChatAdminClient,
    canonical_article_id,
)
from services.wechat_subscription_secrets import SessionCredentials


class _Response:
    def __init__(self, payload: dict):
        self.content = json.dumps(payload).encode("utf-8")

    def raise_for_status(self) -> None:
        return None


def test_admin_client_uses_the_bounded_authenticated_transport_without_putting_credentials_in_the_url():
    calls: list[dict] = []

    def request_get(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return _Response(
            {
                "base_resp": {"ret": 0},
                "publish_page": json.dumps({"biz_list": [{"fakeid": "fakeid-1", "nickname": "知识星球"}]}),
            }
        )

    accounts = WeChatAdminClient(request_get=request_get).search_accounts(
        SessionCredentials(token="123", cookie="session=private"),
        "知识",
    )

    assert [account.fakeid for account in accounts] == ["fakeid-1"]
    assert calls == [{
        "url": f"{WECHAT_MP_BASE_URL}/cgi-bin/searchbiz",
        "headers": {"Cookie": "session=private", "User-Agent": WECHAT_USER_AGENT},
        "params": {
            "action": "search_biz",
            "begin": 0,
            "count": 10,
            "query": "知识",
            "token": "123",
            "lang": "zh_CN",
            "f": "json",
            "ajax": "1",
        },
        "timeout": (WECHAT_REMOTE_CONNECT_TIMEOUT_SECONDS, WECHAT_REMOTE_READ_TIMEOUT_SECONDS),
        "stream": True,
    }]
    assert "private" not in calls[0]["url"]


def test_canonical_article_identity_is_stable_when_query_parameter_order_changes():
    first = canonical_article_id("https://mp.weixin.qq.com/s?__biz=Yml6&mid=100&idx=1&sn=signature")
    second = canonical_article_id("https://mp.weixin.qq.com/s?sn=signature&idx=1&mid=100&__biz=Yml6")

    assert first == second == "wechat:Yml6:100:1:signature"

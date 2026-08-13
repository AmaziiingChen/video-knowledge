from __future__ import annotations

from services.wechat_subscription_secrets import WeChatSubscriptionError


class WeChatRemoteError(WeChatSubscriptionError):
    category = "remote"


class WeChatRateLimitError(WeChatRemoteError):
    category = "rate_limit"

    def __init__(self, message: str, *, retry_at: str | None = None) -> None:
        super().__init__(message)
        self.retry_at = retry_at

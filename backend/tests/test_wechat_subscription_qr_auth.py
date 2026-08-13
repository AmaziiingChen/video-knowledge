import pytest

from services.wechat_subscription_qr_auth import WeChatQrAuthService
from services.wechat_subscription_secrets import WeChatAuthorizationError


def test_missing_qr_login_id_is_rejected_without_creating_a_network_session():
    service = WeChatQrAuthService(session_factory=lambda: pytest.fail("polling a missing login id must not open a session"))

    with pytest.raises(WeChatAuthorizationError, match="过期"):
        service.poll("missing-login-id")

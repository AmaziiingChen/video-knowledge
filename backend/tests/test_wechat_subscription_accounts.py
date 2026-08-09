from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from config import settings
from services.database import connect
from services.wechat_subscription_accounts import WeChatSubscriptionAccountService
from services.wechat_subscription_errors import WeChatRateLimitError
from services.wechat_subscription_secrets import SessionCredentials


class MemorySessionStore:
    def __init__(self) -> None:
        self.values: dict[str, SessionCredentials] = {}

    def save(self, keychain_ref: str, credentials: SessionCredentials) -> None:
        self.values[keychain_ref] = credentials

    def load(self, keychain_ref: str) -> SessionCredentials:
        return self.values[keychain_ref]

    def delete(self, keychain_ref: str) -> None:
        self.values.pop(keychain_ref, None)


class ValidatingClient:
    def __init__(self) -> None:
        self.validate_calls = 0

    def validate(self, credentials: SessionCredentials) -> bool:
        self.validate_calls += 1
        return credentials.token.startswith("valid-token") and credentials.cookie.startswith("valid-cookie")


class WeChatSubscriptionAccountServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_data_dir = settings.data_dir
        settings.data_dir = Path(self.temp_dir.name)
        self.store = MemorySessionStore()
        self.client = ValidatingClient()
        self.service = WeChatSubscriptionAccountService(
            session_store=self.store,
            admin_client=self.client,
        )

    def tearDown(self) -> None:
        settings.data_dir = self.original_data_dir
        self.temp_dir.cleanup()

    def test_reauthorization_replaces_only_keychain_credentials(self) -> None:
        account = self.service.connect_account(
            display_name="测试账号",
            token="valid-token",
            cookie="valid-cookie",
        )
        self.service.reauthorize_account(
            account["id"],
            token="valid-token-2",
            cookie="valid-cookie-2",
        )

        self.assertEqual(self.service.get_account(account["id"])["status"], "active")
        self.assertEqual(len(self.store.values), 1)
        self.assertEqual(next(iter(self.store.values.values())).token, "valid-token-2")
        self.assertEqual(self.client.validate_calls, 2)

    def test_request_budget_blocks_the_remote_call_before_it_is_issued(self) -> None:
        account = self.service.connect_account(
            display_name="测试账号",
            token="valid-token",
            cookie="valid-cookie",
        )
        with connect() as connection:
            connection.execute(
                """
                UPDATE wechat_accounts
                SET request_window_started_at = ?, request_count = 50
                WHERE id = ?
                """,
                (datetime.now().astimezone().isoformat(), account["id"]),
            )
            connection.commit()

        with self.assertRaises(WeChatRateLimitError):
            self.service.consume_request_budget(account["id"])


if __name__ == "__main__":
    unittest.main()

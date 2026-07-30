from __future__ import annotations

import sys
import tempfile
import time
import unittest
import json
from datetime import date, datetime
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from config import settings
from services.content_index import backfill_wechat_subscription_folders
from services.database import (
    _migration_079_backfill_wechat_source_names,
    _migration_086_wechat_collection_guardrails,
    connect,
    initialize_database,
)
from services.repository import ContentRepository, new_id
from services.wechat_subscription import (
    SessionCredentials,
    WeChatAdminClient,
    WeChatAccountCandidate,
    WeChatArticleCandidate,
    WeChatAuthorizationError,
    WeChatBulkSyncQueue,
    WeChatQrAuthService,
    WeChatRateLimitError,
    WeChatInitialSyncQueue,
    WeChatSubscriptionService,
    canonical_article_id,
)


class FakeInitialSyncService:
    def __init__(self) -> None:
        self._lock = Lock()
        self.active = 0
        self.max_active = 0
        self.calls: list[str] = []
        self.statuses: dict[str, str | None] = {}

    def get_subscription(self, subscription_id: str) -> dict:
        return {"id": subscription_id, "last_run_status": self.statuses.get(subscription_id)}

    def sync_subscription(self, subscription_id: str, **_kwargs) -> dict:
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.calls.append(subscription_id)
        time.sleep(0.04)
        with self._lock:
            self.active -= 1
            self.statuses[subscription_id] = "succeeded"
        return {"status": "succeeded"}


class StubResponse:
    def __init__(
        self,
        payload: dict,
        *,
        text: str = "",
        content: bytes = b"",
        url: str = "https://mp.weixin.qq.com/cgi-bin/home",
    ) -> None:
        self._payload = payload
        self.text = text
        self.content = content
        self.url = url

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class MemorySessionStore:
    def __init__(self) -> None:
        self.values: dict[str, SessionCredentials] = {}

    def save(self, keychain_ref: str, credentials: SessionCredentials) -> None:
        self.values[keychain_ref] = credentials

    def load(self, keychain_ref: str) -> SessionCredentials:
        return self.values[keychain_ref]

    def delete(self, keychain_ref: str) -> None:
        self.values.pop(keychain_ref, None)


class StubCookieJar:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    def get_dict(self) -> dict[str, str]:
        return dict(self.values)


class StubQrSession:
    def __init__(self, *, get_responses: list[StubResponse], post_responses: list[StubResponse]) -> None:
        self.headers: dict[str, str] = {}
        self.cookies = StubCookieJar({"session": "authorized"})
        self.get_responses = get_responses
        self.post_responses = post_responses
        self.get_calls: list[tuple[str, dict]] = []
        self.post_calls: list[tuple[str, dict]] = []

    def get(self, url: str, **kwargs):
        self.get_calls.append((url, kwargs))
        return self.get_responses.pop(0)

    def post(self, url: str, **kwargs):
        self.post_calls.append((url, kwargs))
        return self.post_responses.pop(0)


class FakeWeChatAdminClient:
    def __init__(self) -> None:
        self.validate_calls = 0
        self.list_calls = 0
        self.articles = [
            WeChatArticleCandidate(
                remote_article_id=canonical_article_id(
                    "https://mp.weixin.qq.com/s?__biz=Yml6&mid=100&idx=1&sn=signature"
                ),
                source_url="https://mp.weixin.qq.com/s?__biz=Yml6&mid=100&idx=1&sn=signature",
                title="第一篇订阅文章",
                cover_url="https://example.com/cover.jpg",
                published_at="2026-07-13T00:00:00+00:00",
            )
        ]

    def validate(self, credentials: SessionCredentials) -> bool:
        self.validate_calls += 1
        return credentials.token == "valid-token" and credentials.cookie == "valid-cookie"

    def search_accounts(self, credentials: SessionCredentials, query: str, *, limit: int = 10):
        return [WeChatAccountCandidate(fakeid="fakeid-1", name=f"{query}公众号")]

    def list_articles(self, credentials: SessionCredentials, fakeid: str, *, max_pages: int = 2, page_size: int = 10, **options):
        self.list_calls += 1
        before_request = options.get("before_request")
        if before_request:
            before_request()
        self.last_list_options = {"max_pages": max_pages, "page_size": page_size}
        return list(self.articles)


class WeChatSubscriptionServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_data_dir = settings.data_dir
        settings.data_dir = Path(self.temp_dir.name)
        self.store = MemorySessionStore()
        self.client = FakeWeChatAdminClient()
        self.service = WeChatSubscriptionService(session_store=self.store, admin_client=self.client)

    def tearDown(self) -> None:
        settings.data_dir = self.original_data_dir
        self.temp_dir.cleanup()

    def test_database_migrates_subscription_tables(self):
        initialize_database()
        with connect() as connection:
            table_names = {
                row["name"]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
            }

        self.assertTrue(
            {"wechat_accounts", "wechat_subscriptions", "wechat_subscription_items", "wechat_sync_runs"}
            .issubset(table_names)
        )

    def test_guardrail_migration_staggers_legacy_hourly_subscriptions(self):
        account = self.service.connect_account(
            display_name="测试账号",
            token="valid-token",
            cookie="valid-cookie",
        )
        subscription = self.service.create_subscription(
            account_id=account["id"],
            fakeid="legacy-hourly",
            mp_name="旧版每小时订阅",
        )
        with connect() as connection:
            connection.execute(
                "UPDATE wechat_subscriptions SET sync_interval_minutes=60, next_sync_at=NULL WHERE id=?",
                (subscription["id"],),
            )
            connection.commit()
            _migration_086_wechat_collection_guardrails(connection)
            connection.commit()
            restored = connection.execute(
                "SELECT sync_interval_minutes, next_sync_at FROM wechat_subscriptions WHERE id=?",
                (subscription["id"],),
            ).fetchone()

        self.assertEqual(restored["sync_interval_minutes"], 1440)
        self.assertGreater(datetime.fromisoformat(restored["next_sync_at"]).timestamp(), time.time())

    def test_sync_imports_an_article_once_and_writes_it_to_content_library(self):
        account = self.service.connect_account(
            display_name="测试账号",
            token="valid-token",
            cookie="valid-cookie",
        )
        subscription = self.service.create_subscription(
            account_id=account["id"],
            fakeid="fakeid-1",
            mp_name="测试公众号",
            auto_process=False,
            sync_interval_minutes=60,
        )

        first = self.service.sync_subscription(subscription["id"], max_items=10, force=True)
        second = self.service.sync_subscription(subscription["id"], max_items=10, force=True)

        self.assertEqual(first["status"], "succeeded")
        self.assertEqual(first["found_count"], 1)
        self.assertEqual(first["imported_count"], 1)
        self.assertEqual(first["queued_for_analysis"], 0)
        self.assertEqual(second["imported_count"], 0)
        self.assertEqual(self.client.last_list_options, {"max_pages": 1, "page_size": 10})

        with connect() as connection:
            mapped = connection.execute("SELECT * FROM wechat_subscription_items").fetchall()
            self.assertEqual(len(mapped), 1)
            item = ContentRepository(connection).get_content_item(mapped[0]["content_item_id"])
        self.assertEqual(item.source_provider, "wechat")
        self.assertEqual(item.content_type, "article")
        self.assertEqual(item.title, "第一篇订阅文章")
        self.assertEqual(item.source_name, "测试公众号")
        self.assertEqual(item.status, "to_read")
        self.assertIsNotNone(item.library_folder_id)
        with connect() as connection:
            listed_item = ContentRepository(connection).list_content_items()[0]
        self.assertEqual(listed_item.published_at, "2026-07-13T00:00:00+00:00")
        with connect() as connection:
            publisher_folder = connection.execute(
                "SELECT * FROM library_folders WHERE id = ?",
                (item.library_folder_id,),
            ).fetchone()
            root_folder = connection.execute(
                "SELECT * FROM library_folders WHERE id = ?",
                (publisher_folder["parent_folder_id"],),
            ).fetchone()
        self.assertEqual(publisher_folder["name"], "测试公众号")
        self.assertEqual(root_folder["name"], "微信公众号")

        with connect() as connection:
            connection.execute(
                "UPDATE content_items SET library_folder_id = ? WHERE id = ?",
                (root_folder["id"], item.id),
            )
            connection.commit()
        self.assertEqual(backfill_wechat_subscription_folders(), 1)
        with connect() as connection:
            restored = ContentRepository(connection).get_content_item(item.id)
        self.assertEqual(restored.library_folder_id, publisher_folder["id"])

    def test_source_name_backfill_uses_existing_subscription_mapping(self):
        account = self.service.connect_account(
            display_name="测试账号",
            token="valid-token",
            cookie="valid-cookie",
        )
        subscription = self.service.create_subscription(
            account_id=account["id"],
            fakeid="fakeid-1",
            mp_name="可回填公众号",
        )
        with connect() as connection:
            item = ContentRepository(connection).create_content_item(
                source_provider="wechat",
                source_url="https://mp.weixin.qq.com/s?__biz=test&mid=101",
                canonical_source_id="legacy-wechat-article",
                title="历史文章",
                content_type="article",
            )
            connection.execute(
                """
                INSERT INTO wechat_subscription_items (
                    id, subscription_id, remote_article_id, source_url, content_item_id,
                    title, discovered_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id(),
                    subscription["id"],
                    "legacy-wechat-article",
                    item.source_url,
                    item.id,
                    item.title,
                    datetime.now().astimezone().isoformat(),
                ),
            )
            connection.commit()

        with connect() as connection:
            _migration_079_backfill_wechat_source_names(connection)
            connection.commit()
            restored = ContentRepository(connection).get_content_item(item.id)

        self.assertEqual(restored.source_name, "可回填公众号")

    def test_new_subscription_waits_for_its_initial_sync_queue(self):
        account = self.service.connect_account(display_name="测试账号", token="valid-token", cookie="valid-cookie")
        subscription = self.service.create_subscription(
            account_id=account["id"],
            fakeid="fakeid-1",
            mp_name="测试公众号",
            sync_interval_minutes=60,
        )

        self.assertGreater(
            datetime.fromisoformat(subscription["next_sync_at"]).timestamp(),
            datetime.fromisoformat(subscription["created_at"]).timestamp(),
        )

    def test_creating_subscription_creates_its_empty_library_folder_immediately(self):
        account = self.service.connect_account(
            display_name="测试账号",
            token="valid-token",
            cookie="valid-cookie",
        )

        subscription = self.service.create_subscription(
            account_id=account["id"],
            fakeid="empty-folder-source",
            mp_name="尚未发布文章的公众号",
        )

        with connect() as connection:
            folder = connection.execute(
                """
                SELECT folder.name, parent.name AS parent_name
                FROM library_source_folder_bindings AS binding
                JOIN library_folders AS folder ON folder.id = binding.folder_id
                JOIN library_folders AS parent ON parent.id = folder.parent_folder_id
                WHERE binding.source_type = 'wechat_subscription' AND binding.source_key = ?
                """,
                (subscription["id"],),
            ).fetchone()
        self.assertIsNotNone(folder)
        self.assertEqual(folder["name"], "尚未发布文章的公众号")
        self.assertEqual(folder["parent_name"], "微信公众号")

    def test_search_and_subscription_state_are_exposed_without_credentials(self):
        account = self.service.connect_account(
            display_name="测试账号",
            token="valid-token",
            cookie="valid-cookie",
        )

        results = self.service.search_accounts(account["id"], "知识")
        subscription = self.service.create_subscription(
            account_id=account["id"],
            fakeid=results[0].fakeid,
            mp_name=results[0].name,
            auto_process=True,
        )
        listed_account = self.service.get_account(account["id"])
        listed_subscription = self.service.get_subscription(subscription["id"])

        self.assertEqual(results[0].name, "知识公众号")
        self.assertNotIn("cookie", listed_account)
        self.assertEqual(listed_subscription["account_name"], "测试账号")
        self.assertTrue(listed_subscription["auto_process"])

    def test_reauthorization_preserves_existing_subscriptions(self):
        account = self.service.connect_account(display_name="测试账号", token="valid-token", cookie="valid-cookie")
        subscription = self.service.create_subscription(
            account_id=account["id"],
            fakeid="fakeid-1",
            mp_name="测试公众号",
        )

        updated = self.service.reauthorize_account(
            account["id"],
            token="valid-token",
            cookie="valid-cookie",
        )

        self.assertEqual(updated["id"], account["id"])
        self.assertEqual(updated["status"], "active")
        self.assertEqual(self.service.get_subscription(subscription["id"])["account_id"], account["id"])
        self.assertEqual(self.service.list_accounts()[0]["subscription_count"], 1)

    def test_remote_authorization_failure_marks_account_for_reauthorization(self):
        account = self.service.connect_account(display_name="测试账号", token="valid-token", cookie="valid-cookie")
        subscription = self.service.create_subscription(
            account_id=account["id"],
            fakeid="fakeid-1",
            mp_name="测试公众号",
        )

        def expired_list_articles(*_args, **_kwargs):
            raise WeChatAuthorizationError("微信公众平台登录态已失效，请重新授权")

        self.client.list_articles = expired_list_articles
        with self.assertRaises(WeChatAuthorizationError):
            self.service.sync_subscription(subscription["id"], force=True)

        self.assertEqual(self.service.get_account(account["id"])["status"], "requires_reauth")

    def test_rate_limit_keeps_authorization_active_and_persists_account_cooldown(self):
        account = self.service.connect_account(display_name="测试账号", token="valid-token", cookie="valid-cookie")
        subscription = self.service.create_subscription(
            account_id=account["id"],
            fakeid="fakeid-1",
            mp_name="测试公众号",
        )

        def rate_limited_list(*_args, **_kwargs):
            self.client.list_calls += 1
            raise WeChatRateLimitError("微信公众平台触发访问频控，已暂停自动检查")

        self.client.list_articles = rate_limited_list
        with self.assertRaises(WeChatRateLimitError):
            self.service.sync_subscription(subscription["id"], force=True)

        cooled_account = self.service.get_account(account["id"])
        cooled_subscription = self.service.get_subscription(subscription["id"])
        self.assertEqual(cooled_account["status"], "active")
        self.assertIsNotNone(cooled_account["rate_limited_until"])
        self.assertEqual(cooled_subscription["last_error_category"], "rate_limit")

        with self.assertRaises(WeChatRateLimitError):
            self.service.sync_subscription(subscription["id"], force=True)
        self.assertEqual(self.client.list_calls, 1)

    def test_successful_sync_reuses_recent_session_validation(self):
        account = self.service.connect_account(display_name="测试账号", token="valid-token", cookie="valid-cookie")
        subscription = self.service.create_subscription(
            account_id=account["id"],
            fakeid="fakeid-1",
            mp_name="测试公众号",
        )

        self.service.sync_subscription(subscription["id"], force=True)
        self.service.sync_subscription(subscription["id"], force=True)

        self.assertEqual(self.client.validate_calls, 1)

    def test_scheduler_queues_only_one_due_subscription_per_account(self):
        account = self.service.connect_account(display_name="测试账号", token="valid-token", cookie="valid-cookie")
        subscriptions = [
            self.service.create_subscription(
                account_id=account["id"],
                fakeid=f"fakeid-{index}",
                mp_name=f"测试公众号 {index}",
            )
            for index in range(2)
        ]
        with connect() as connection:
            connection.execute(
                "UPDATE wechat_subscriptions SET next_sync_at='2020-01-01T00:00:00+00:00'"
            )
            connection.commit()

        created: list[dict] = []

        def create_source_sync(request, **_kwargs):
            created.append(request)
            return SimpleNamespace(task_id=f"task-{len(created)}", status="queued")

        with patch("services.task_manager.task_manager.create_source_sync", side_effect=create_source_sync):
            queued = self.service.sync_due_subscriptions()

        self.assertEqual(len(queued), 1)
        self.assertEqual(len(created), 1)
        self.assertIn(created[0]["subscription_id"], {item["id"] for item in subscriptions})

    def test_local_daily_request_budget_opens_the_same_account_circuit_breaker(self):
        account = self.service.connect_account(display_name="测试账号", token="valid-token", cookie="valid-cookie")
        subscription = self.service.create_subscription(
            account_id=account["id"],
            fakeid="budgeted-source",
            mp_name="预算保护公众号",
        )
        with connect() as connection:
            connection.execute(
                """
                UPDATE wechat_accounts
                SET request_window_started_at=?, request_count=50
                WHERE id=?
                """,
                (datetime.now().astimezone().isoformat(), account["id"]),
            )
            connection.commit()

        with self.assertRaisesRegex(WeChatRateLimitError, "安全调用预算"):
            self.service.sync_subscription(subscription["id"], force=True)

        protected = self.service.get_account(account["id"])
        self.assertEqual(protected["status"], "active")
        self.assertIsNotNone(protected["rate_limited_until"])

    def test_transfer_preserves_subscription_and_blocks_source_deletion_until_moved(self):
        source = self.service.connect_account(display_name="旧账号", token="valid-token", cookie="valid-cookie")
        target = self.service.connect_account(display_name="新账号", token="valid-token", cookie="valid-cookie")
        subscription = self.service.create_subscription(
            account_id=source["id"],
            fakeid="fakeid-1",
            mp_name="测试公众号",
        )

        with self.assertRaisesRegex(ValueError, "仍关联 1 个公众号订阅"):
            self.service.delete_account(source["id"])
        transferred = self.service.transfer_subscriptions(source["id"], target["id"])

        self.assertEqual(transferred["moved_count"], 1)
        self.assertEqual(self.service.get_subscription(subscription["id"])["account_id"], target["id"])
        self.service.delete_account(source["id"])
        self.assertEqual([item["id"] for item in self.service.list_accounts()], [target["id"]])

    def test_article_canonical_id_ignores_url_parameter_order(self):
        first = canonical_article_id("https://mp.weixin.qq.com/s?__biz=Yml6&mid=100&idx=1&sn=signature")
        second = canonical_article_id("https://mp.weixin.qq.com/s?sn=signature&idx=1&mid=100&__biz=Yml6")

        self.assertEqual(first, second)

    def test_manual_backfill_expands_the_fixed_article_window(self):
        account = self.service.connect_account(display_name="测试账号", token="valid-token", cookie="valid-cookie")
        subscription = self.service.create_subscription(account_id=account["id"], fakeid="fakeid-1", mp_name="测试公众号")
        self.service.sync_subscription(subscription["id"], mode="count", max_items=50, force=True)
        self.assertEqual(self.client.last_list_options, {"max_pages": 5, "page_size": 10})

    def test_latest_sync_is_limited_to_ten_articles_even_for_older_clients(self):
        account = self.service.connect_account(display_name="测试账号", token="valid-token", cookie="valid-cookie")
        subscription = self.service.create_subscription(account_id=account["id"], fakeid="fakeid-1", mp_name="测试公众号")
        self.client.articles.extend(
            WeChatArticleCandidate(
                remote_article_id=f"wechat:initial-{index}",
                source_url=f"https://mp.weixin.qq.com/s?mid={index}",
                title=f"初始文章 {index}",
                published_at="2026-07-13T00:00:00+00:00",
            )
            for index in range(12)
        )

        result = self.service.sync_subscription(subscription["id"], mode="latest", max_items=50, force=True)

        self.assertEqual(self.client.last_list_options, {"max_pages": 1, "page_size": 10})
        self.assertEqual(result["found_count"], 10)
        self.assertEqual(result["imported_count"], 10)

    def test_incremental_latest_sync_stays_on_the_newest_page(self):
        account = self.service.connect_account(display_name="测试账号", token="valid-token", cookie="valid-cookie")
        subscription = self.service.create_subscription(account_id=account["id"], fakeid="fakeid-1", mp_name="测试公众号")
        self.service.sync_subscription(subscription["id"], mode="latest", max_items=10, force=True)

        self.service.sync_subscription(subscription["id"], mode="latest", max_items=10, force=True)

        self.assertEqual(self.client.last_list_options, {"max_pages": 1, "page_size": 10})

    def test_recover_interrupted_initial_sync_marks_run_and_returns_subscription(self):
        account = self.service.connect_account(display_name="测试账号", token="valid-token", cookie="valid-cookie")
        subscription = self.service.create_subscription(account_id=account["id"], fakeid="fakeid-1", mp_name="测试公众号")
        with connect() as connection:
            connection.execute(
                "INSERT INTO wechat_sync_runs (id, subscription_id, status, started_at) VALUES (?, ?, 'running', ?)",
                ("interrupted-run", subscription["id"], datetime.now().isoformat()),
            )
            connection.commit()

        self.assertEqual(self.service.recover_interrupted_initial_syncs(), [subscription["id"]])
        recovered = self.service.get_subscription(subscription["id"])
        self.assertEqual(recovered["last_run_status"], "failed")
        self.assertIn("重新检查", recovered["last_error"])

    def test_catch_up_does_not_cut_multi_article_publication_at_item_limit(self):
        self.client.articles.append(
            WeChatArticleCandidate(
                remote_article_id="wechat:second-card",
                source_url="https://mp.weixin.qq.com/s?__biz=Yml6&mid=100&idx=2&sn=second",
                title="同次推送的第二篇文章",
                published_at="2026-07-13T00:00:00+00:00",
            )
        )
        account = self.service.connect_account(display_name="测试账号", token="valid-token", cookie="valid-cookie")
        subscription = self.service.create_subscription(account_id=account["id"], fakeid="fakeid-1", mp_name="测试公众号")

        result = self.service.sync_subscription(subscription["id"], mode="catch_up", max_items=1, force=True)

        self.assertEqual(result["imported_count"], 2)

    def test_date_range_backfill_filters_candidates_before_importing(self):
        self.client.articles.append(
            WeChatArticleCandidate(
                remote_article_id="wechat:older",
                source_url="https://mp.weixin.qq.com/s?__biz=Yml6&mid=101&idx=1&sn=older",
                title="旧文章",
                published_at="2025-01-01T00:00:00+00:00",
            )
        )
        account = self.service.connect_account(display_name="测试账号", token="valid-token", cookie="valid-cookie")
        subscription = self.service.create_subscription(account_id=account["id"], fakeid="fakeid-1", mp_name="测试公众号")
        result = self.service.sync_subscription(
            subscription["id"],
            mode="date_range",
            published_after=date(2026, 1, 1),
            published_before=date(2026, 12, 31),
            force=True,
        )
        self.assertEqual(result["found_count"], 2)
        self.assertEqual(result["eligible_count"], 1)
        self.assertEqual(result["imported_count"], 1)
        self.assertEqual(self.client.last_list_options, {"max_pages": 100, "page_size": 10})


class WeChatAdminClientTests(unittest.TestCase):
    def test_frequency_control_is_not_reported_as_expired_authorization(self):
        client = WeChatAdminClient(
            request_get=lambda *_args, **_kwargs: StubResponse(
                {"base_resp": {"ret": 200013, "err_msg": "freq control"}}
            )
        )

        with self.assertRaisesRegex(WeChatRateLimitError, "频控"):
            client.list_articles(
                SessionCredentials(token="123", cookie="foo=bar"),
                "fakeid-1",
                max_pages=1,
            )

    def test_parses_search_and_article_list_from_nested_wechat_payloads(self):
        responses = [
            StubResponse(
                {
                    "base_resp": {"ret": 0},
                    "publish_page": json.dumps(
                        {
                            "biz_list": [
                                {
                                    "fakeid": "fakeid-1",
                                    "nickname": "知识星球",
                                    "headimgurl": "https://example.com/avatar.jpg",
                                    "signature": "测试简介",
                                }
                            ]
                        }
                    ),
                }
            ),
            StubResponse(
                {
                    "base_resp": {"ret": 0},
                    "publish_page": json.dumps(
                        {
                            "publish_list": [
                                {
                                    "publish_info": json.dumps(
                                        {
                                            "appmsgex": [
                                                {
                                                    "title": "新文章\n这段内容属于正文摘要，不应进入标题",
                                                    "link": "https://mp.weixin.qq.com/s?__biz=Yml6&amp;mid=9&idx=1&sn=sig",
                                                    "cover": "https://example.com/cover.jpg",
                                                    "update_time": 1_789_000_000,
                                                }
                                            ]
                                        }
                                    )
                                }
                            ]
                        }
                    ),
                }
            ),
        ]

        def request_get(*args, **kwargs):
            return responses.pop(0)

        client = WeChatAdminClient(request_get=request_get)
        credentials = SessionCredentials(token="123", cookie="foo=bar")
        accounts = client.search_accounts(credentials, "知识")
        articles = client.list_articles(credentials, "fakeid-1", max_pages=1)

        self.assertEqual(accounts[0].name, "知识星球")
        self.assertEqual(accounts[0].fakeid, "fakeid-1")
        self.assertEqual(articles[0].title, "新文章")
        self.assertEqual(articles[0].source_url, "https://mp.weixin.qq.com/s?__biz=Yml6&mid=9&idx=1&sn=sig")
        self.assertEqual(articles[0].remote_article_id, "wechat:Yml6:9:1:sig")

    def test_catch_up_pagination_stops_after_finishing_page_with_known_article(self):
        calls: list[dict] = []

        def article_payload(mid: str) -> StubResponse:
            return StubResponse({
                "base_resp": {"ret": 0},
                "publish_page": json.dumps({
                    "publish_list": [{
                        "publish_info": json.dumps({
                            "appmsgex": [{
                                "title": f"文章 {mid}",
                                "link": f"https://mp.weixin.qq.com/s?__biz=Yml6&mid={mid}&idx=1&sn=sig",
                            }]
                        })
                    }]
                }),
            })

        responses = [article_payload("11"), article_payload("10"), article_payload("9")]

        def request_get(*args, **kwargs):
            calls.append(kwargs.get("params") or {})
            return responses.pop(0)

        client = WeChatAdminClient(request_get=request_get)
        credentials = SessionCredentials(token="123", cookie="foo=bar")
        articles = client.list_articles(
            credentials,
            "fakeid-1",
            max_pages=10,
            page_size=1,
            stop_when=lambda article: ":10:" in article.remote_article_id,
        )

        self.assertEqual([item.title for item in articles], ["文章 11", "文章 10"])
        self.assertEqual([call["begin"] for call in calls], [0, 1])


class WeChatInitialSyncQueueTests(unittest.TestCase):
    def test_queue_keeps_first_sync_work_bounded_and_reports_per_subscription_state(self):
        service = FakeInitialSyncService()
        queue = WeChatInitialSyncQueue(service, max_workers=2)

        for index in range(4):
            result = queue.enqueue(f"subscription-{index}", max_items=10)
            self.assertEqual(result["status"], "queued")

        self.assertIn(queue.status("subscription-0")["status"], {"queued", "running", "succeeded"})
        queue.shutdown(wait=True)

        self.assertEqual(set(service.calls), {f"subscription-{index}" for index in range(4)})
        self.assertLessEqual(service.max_active, 2)
        self.assertEqual(queue.status("subscription-0")["status"], "succeeded")


class FakeBulkSyncService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def list_subscriptions(self) -> list[dict]:
        return [
            {"id": "enabled-1", "mp_name": "公众号一", "enabled": True},
            {"id": "paused", "mp_name": "暂停公众号", "enabled": False},
            {"id": "enabled-2", "mp_name": "公众号二", "enabled": True},
        ]

    def sync_subscription(self, subscription_id: str, **options) -> dict:
        self.calls.append((subscription_id, options))
        return {"imported_count": 1, "coverage_complete": True}


class WeChatBulkSyncQueueTests(unittest.TestCase):
    def test_bulk_queue_is_serial_paced_and_skips_paused_subscriptions(self):
        service = FakeBulkSyncService()
        delays: list[float] = []
        waiting_states: list[dict] = []
        queue = WeChatBulkSyncQueue(
            service,
            delay_range=(4.0, 7.0),
            sleep=lambda delay: (delays.append(delay), waiting_states.append(queue.status())),
            uniform=lambda lower, upper: (lower + upper) / 2,
        )

        queued = queue.enqueue()
        self.assertEqual(queued["total"], 2)
        queue.shutdown(wait=True)
        state = queue.status()

        self.assertEqual(state["status"], "succeeded")
        self.assertEqual(state["completed"], 2)
        self.assertEqual(state["imported_count"], 2)
        self.assertEqual([call[0] for call in service.calls], ["enabled-1", "enabled-2"])
        self.assertTrue(all(call[1] == {"mode": "latest", "max_items": 10, "force": False} for call in service.calls))
        self.assertEqual(delays, [5.5])
        self.assertEqual(waiting_states[0]["completed"], 1)
        self.assertEqual(waiting_states[0]["current_subscription_id"], "")


class WeChatQrAuthServiceTests(unittest.TestCase):
    def test_current_dynamic_login_flow_creates_qr_and_finishes_after_confirmation(self):
        session = StubQrSession(
            get_responses=[
                StubResponse({}, text="<html>登录页不内嵌二维码</html>"),
                StubResponse({}, content=b"png-data"),
                StubResponse({"base_resp": {"ret": 0}, "status": 4}),
                StubResponse({"base_resp": {"ret": 0}, "status": 1}),
            ],
            post_responses=[
                StubResponse({"base_resp": {"ret": 0}, "uuid": "unused-by-current-flow"}),
                StubResponse({"redirect_url": "/cgi-bin/home?token=123456"}),
            ],
        )
        service = WeChatQrAuthService(session_factory=lambda: session)

        started = service.start()
        scanned = service.poll(started.login_id)
        confirmed = service.poll(started.login_id)

        self.assertEqual(started.status, "pending")
        self.assertTrue(started.qr_image_data_url.startswith("data:image/png;base64,"))
        self.assertEqual(scanned.status, "scanned")
        self.assertEqual(confirmed.status, "confirmed")
        self.assertEqual(confirmed.credentials, SessionCredentials(token="123456", cookie="session=authorized"))
        self.assertEqual(session.post_calls[0][1]["params"], {"action": "startlogin"})
        self.assertEqual(session.post_calls[0][1]["data"]["login_type"], 3)
        self.assertEqual(session.get_calls[1][1]["params"]["action"], "getqrcode")
        self.assertEqual(session.get_calls[2][1]["params"], {"action": "ask"})
        self.assertEqual(session.post_calls[1][1]["params"], {"action": "login"})

    def test_expired_qr_stops_the_pending_login(self):
        session = StubQrSession(
            get_responses=[
                StubResponse({}, text="<html></html>"),
                StubResponse({}, content=b"png-data"),
                StubResponse({"base_resp": {"ret": 0}, "status": 2}),
            ],
            post_responses=[StubResponse({"base_resp": {"ret": 0}})],
        )
        service = WeChatQrAuthService(session_factory=lambda: session)

        started = service.start()
        expired = service.poll(started.login_id)

        self.assertEqual(expired.status, "expired")
        self.assertIn("重新", expired.message)

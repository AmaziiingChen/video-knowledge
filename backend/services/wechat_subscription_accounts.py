"""Local account, credential and request-budget policy for WeChat subscriptions."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Callable

from services.database import connect, initialize_database, utc_now_iso
from services.repository import new_id
from services.wechat_subscription_client import WeChatAdminClient
from services.wechat_subscription_errors import WeChatRateLimitError
from services.wechat_subscription_secrets import (
    MacOSKeychainSessionStore,
    SessionCredentials,
    WeChatAuthorizationError,
)

if TYPE_CHECKING:
    from services.wechat_subscription_qr_auth import QrLoginStatus


WECHAT_SESSION_VALIDATION_TTL_SECONDS = 60 * 60
WECHAT_ACCOUNT_REQUEST_WINDOW_HOURS = 24
WECHAT_ACCOUNT_REQUEST_LIMIT = 50
WECHAT_RATE_LIMIT_COOLDOWN_HOURS = 24


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso_datetime(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or ""))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class WeChatSubscriptionAccountService:
    """Own local account records, Keychain credentials and remote-use guardrails.

    Remote requests remain the subscription service's responsibility so its
    single shared request lane still serializes manual and background work.
    """

    def __init__(
        self,
        *,
        session_store: Any | None = None,
        admin_client: WeChatAdminClient | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._session_store = session_store or MacOSKeychainSessionStore()
        self._admin_client = admin_client or WeChatAdminClient()
        self._monotonic = monotonic
        self._validated_until: dict[str, float] = {}

    def connect_account(self, *, display_name: str, token: str, cookie: str) -> dict[str, Any]:
        credentials = SessionCredentials(token=token.strip(), cookie=cookie.strip())
        if not credentials.token or not credentials.cookie:
            raise WeChatAuthorizationError("需要同时提供微信公众平台 token 与 Cookie")
        if not self._admin_client.validate(credentials):
            raise WeChatAuthorizationError("微信公众平台登录态不可用，请重新授权")
        initialize_database()
        account_id = new_id()
        keychain_ref = f"wechat-subscription:{account_id}"
        self._session_store.save(keychain_ref, credentials)
        now = utc_now_iso()
        try:
            with connect() as connection:
                connection.execute(
                    """
                    INSERT INTO wechat_accounts (
                        id, display_name, keychain_ref, status, last_validated_at, created_at, updated_at
                    ) VALUES (?, ?, ?, 'active', ?, ?, ?)
                    """,
                    (account_id, display_name.strip() or "微信公众平台账号", keychain_ref, now, now, now),
                )
                connection.commit()
        except Exception:
            self._session_store.delete(keychain_ref)
            raise
        self._validated_until[account_id] = self._monotonic() + WECHAT_SESSION_VALIDATION_TTL_SECONDS
        return self.get_account(account_id)

    def complete_qr_login(self, status: QrLoginStatus, display_name: str = "") -> dict[str, Any]:
        if status.status != "confirmed" or not status.credentials:
            raise WeChatAuthorizationError("微信扫码授权尚未完成")
        return self.connect_account(
            display_name=display_name or "微信公众平台账号",
            token=status.credentials.token,
            cookie=status.credentials.cookie,
        )

    def reauthorize_account(self, account_id: str, *, token: str, cookie: str) -> dict[str, Any]:
        """Replace an existing account's local login state without touching subscriptions."""
        credentials = SessionCredentials(token=token.strip(), cookie=cookie.strip())
        if not credentials.token or not credentials.cookie:
            raise WeChatAuthorizationError("需要同时提供微信公众平台 token 与 Cookie")
        if not self._admin_client.validate(credentials):
            raise WeChatAuthorizationError("微信公众平台登录态不可用，请重新授权")
        initialize_database()
        with connect() as connection:
            row = connection.execute(
                "SELECT keychain_ref FROM wechat_accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
            if not row:
                raise LookupError("微信授权账号不存在")
            keychain_ref = str(row["keychain_ref"])
        self._session_store.save(keychain_ref, credentials)
        self.mark_account_valid(account_id)
        self._validated_until[account_id] = self._monotonic() + WECHAT_SESSION_VALIDATION_TTL_SECONDS
        return self.get_account(account_id)

    def complete_qr_reauthorization(self, account_id: str, status: QrLoginStatus) -> dict[str, Any]:
        if status.status != "confirmed" or not status.credentials:
            raise WeChatAuthorizationError("微信扫码授权尚未完成")
        return self.reauthorize_account(
            account_id,
            token=status.credentials.token,
            cookie=status.credentials.cookie,
        )

    def list_accounts(self) -> list[dict[str, Any]]:
        initialize_database()
        with connect() as connection:
            rows = connection.execute(
                """
                SELECT a.id, a.display_name, a.status, a.last_validated_at, a.reauth_required_at,
                       a.rate_limited_until, a.rate_limit_reason, a.last_rate_limited_at,
                       a.created_at, a.updated_at, COUNT(s.id) AS subscription_count
                FROM wechat_accounts a
                LEFT JOIN wechat_subscriptions s ON s.account_id = a.id
                GROUP BY a.id
                ORDER BY a.created_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_account(self, account_id: str) -> dict[str, Any]:
        initialize_database()
        with connect() as connection:
            row = connection.execute(
                """
                SELECT id, display_name, status, last_validated_at, reauth_required_at,
                       rate_limited_until, rate_limit_reason, last_rate_limited_at,
                       created_at, updated_at
                FROM wechat_accounts WHERE id = ?
                """,
                (account_id,),
            ).fetchone()
        if not row:
            raise LookupError("微信授权账号不存在")
        return dict(row)

    def delete_account(self, account_id: str) -> None:
        initialize_database()
        with connect() as connection:
            row = connection.execute("SELECT keychain_ref FROM wechat_accounts WHERE id = ?", (account_id,)).fetchone()
            if not row:
                raise LookupError("微信授权账号不存在")
            subscription_count = int(connection.execute(
                "SELECT COUNT(*) FROM wechat_subscriptions WHERE account_id = ?",
                (account_id,),
            ).fetchone()[0])
            if subscription_count:
                raise ValueError(
                    f"该授权账号仍关联 {subscription_count} 个公众号订阅，请先重新授权或迁移订阅后再移除"
                )
            keychain_ref = str(row["keychain_ref"])
            connection.execute("DELETE FROM wechat_accounts WHERE id = ?", (account_id,))
            connection.commit()
        self._session_store.delete(keychain_ref)

    def transfer_subscriptions(self, source_account_id: str, target_account_id: str) -> dict[str, Any]:
        """Move subscriptions, their groups and history mappings to another valid authorization."""
        if source_account_id == target_account_id:
            raise ValueError("请选择另一个授权账号接管订阅")
        initialize_database()
        now = utc_now_iso()
        with connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            source = connection.execute(
                "SELECT display_name FROM wechat_accounts WHERE id = ?",
                (source_account_id,),
            ).fetchone()
            target = connection.execute(
                "SELECT display_name, status FROM wechat_accounts WHERE id = ?",
                (target_account_id,),
            ).fetchone()
            if not source or not target:
                raise LookupError("微信授权账号不存在")
            if str(target["status"]) != "active":
                raise ValueError("接管订阅的授权账号需要处于有效状态")
            duplicates = connection.execute(
                """
                SELECT source.mp_name
                FROM wechat_subscriptions AS source
                JOIN wechat_subscriptions AS target
                  ON target.account_id = ? AND target.fakeid = source.fakeid
                WHERE source.account_id = ?
                ORDER BY source.mp_name
                """,
                (target_account_id, source_account_id),
            ).fetchall()
            if duplicates:
                names = "、".join(str(row["mp_name"]) for row in duplicates[:3])
                suffix = "等" if len(duplicates) > 3 else ""
                raise ValueError(f"目标账号已订阅 {names}{suffix}，请先取消重复订阅后再迁移")
            moved_count = connection.execute(
                """
                UPDATE wechat_subscriptions
                SET account_id = ?, last_error = NULL, updated_at = ?
                WHERE account_id = ?
                """,
                (target_account_id, now, source_account_id),
            ).rowcount
            connection.commit()
        return {
            "source_account_id": source_account_id,
            "target_account_id": target_account_id,
            "moved_count": int(moved_count),
        }

    def credentials_for_request(self, account_id: str, *, force_validation: bool = False) -> SessionCredentials:
        self.raise_if_rate_limited(account_id)
        credentials = self._credentials_for_account(account_id)
        self.ensure_account_session(account_id, credentials, force=force_validation)
        return credentials

    def raise_if_rate_limited(self, account_id: str) -> None:
        with connect() as connection:
            row = connection.execute(
                "SELECT rate_limited_until, rate_limit_reason FROM wechat_accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
        if not row:
            raise LookupError("微信授权账号不存在")
        retry_at = _parse_iso_datetime(row["rate_limited_until"])
        if retry_at and retry_at > _utc_now():
            raise WeChatRateLimitError(
                str(row["rate_limit_reason"] or "微信公众平台正在频控冷却，暂不继续请求"),
                retry_at=retry_at.isoformat(),
            )

    def consume_request_budget(self, account_id: str) -> None:
        now = _utc_now()
        window_duration = timedelta(hours=WECHAT_ACCOUNT_REQUEST_WINDOW_HOURS)
        with connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT request_window_started_at, request_count
                FROM wechat_accounts WHERE id = ?
                """,
                (account_id,),
            ).fetchone()
            if not row:
                raise LookupError("微信授权账号不存在")
            window_started_at = _parse_iso_datetime(row["request_window_started_at"])
            request_count = int(row["request_count"] or 0)
            if window_started_at is None or now - window_started_at >= window_duration:
                window_started_at = now
                request_count = 0
            if request_count >= WECHAT_ACCOUNT_REQUEST_LIMIT:
                retry_at = window_started_at + window_duration
                raise WeChatRateLimitError(
                    "微信公众号自动检查已达到本机安全调用预算，稍后自动恢复",
                    retry_at=retry_at.isoformat(),
                )
            connection.execute(
                """
                UPDATE wechat_accounts
                SET request_window_started_at = ?, request_count = ?, updated_at = ?
                WHERE id = ?
                """,
                (window_started_at.isoformat(), request_count + 1, now.isoformat(), account_id),
            )
            connection.commit()

    def mark_rate_limited(self, account_id: str, error: WeChatRateLimitError) -> None:
        now = _utc_now()
        retry_at = _parse_iso_datetime(error.retry_at) or (
            now + timedelta(hours=WECHAT_RATE_LIMIT_COOLDOWN_HOURS)
        )
        message = str(error) or "微信公众平台触发访问频控，已暂停自动检查"
        with connect() as connection:
            connection.execute(
                """
                UPDATE wechat_accounts
                SET status = 'active', reauth_required_at = NULL,
                    rate_limited_until = ?, rate_limit_reason = ?,
                    last_rate_limited_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (retry_at.isoformat(), message, now.isoformat(), now.isoformat(), account_id),
            )
            connection.commit()

    def clear_rate_limit(self, account_id: str) -> None:
        now = utc_now_iso()
        with connect() as connection:
            connection.execute(
                """
                UPDATE wechat_accounts
                SET status = 'active', reauth_required_at = NULL,
                    rate_limited_until = NULL, rate_limit_reason = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, account_id),
            )
            connection.commit()

    def mark_account_valid(self, account_id: str) -> None:
        now = utc_now_iso()
        with connect() as connection:
            connection.execute(
                """
                UPDATE wechat_accounts
                SET status = 'active', last_validated_at = ?, reauth_required_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (now, now, account_id),
            )
            connection.commit()

    def mark_account_reauth(self, account_id: str) -> None:
        self._validated_until.pop(account_id, None)
        now = utc_now_iso()
        with connect() as connection:
            connection.execute(
                """
                UPDATE wechat_accounts
                SET status = 'requires_reauth', reauth_required_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (now, now, account_id),
            )
            connection.commit()

    def _credentials_for_account(self, account_id: str) -> SessionCredentials:
        initialize_database()
        with connect() as connection:
            row = connection.execute("SELECT keychain_ref FROM wechat_accounts WHERE id = ?", (account_id,)).fetchone()
        if not row:
            raise LookupError("微信授权账号不存在")
        try:
            return self._session_store.load(str(row["keychain_ref"]))
        except WeChatAuthorizationError:
            self.mark_account_reauth(account_id)
            raise

    def ensure_account_session(
        self,
        account_id: str,
        credentials: SessionCredentials,
        *,
        force: bool = False,
    ) -> None:
        if not force and self._validated_until.get(account_id, 0.0) > self._monotonic():
            return
        if not self._admin_client.validate(credentials):
            self._validated_until.pop(account_id, None)
            self.mark_account_reauth(account_id)
            raise WeChatAuthorizationError("微信公众平台登录态已失效，请重新授权")
        self._validated_until[account_id] = self._monotonic() + WECHAT_SESSION_VALIDATION_TTL_SECONDS
        self.mark_account_valid(account_id)

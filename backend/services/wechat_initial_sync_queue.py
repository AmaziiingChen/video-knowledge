from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from typing import TYPE_CHECKING, Any

from config import settings

if TYPE_CHECKING:
    from services.wechat_subscription import WeChatSubscriptionService


WECHAT_INITIAL_SYNC_TIMEOUT_SECONDS = 75


class WeChatInitialSyncQueue:
    """Run first-time subscription checks without blocking subscription creation."""

    def __init__(
        self,
        service: WeChatSubscriptionService,
        max_workers: int = 2,
        sync_timeout_seconds: float = WECHAT_INITIAL_SYNC_TIMEOUT_SECONDS,
    ) -> None:
        self._service = service
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, int(max_workers)),
            thread_name_prefix="wechat-initial-sync",
        )
        self._lock = Lock()
        self._states: dict[str, dict[str, Any]] = {}
        self._sync_timeout_seconds = max(1.0, float(sync_timeout_seconds))

    def enqueue(
        self,
        subscription_id: str,
        *,
        max_items: int = settings.wechat_subscription_default_initial_limit,
    ) -> dict[str, Any]:
        self._service.get_subscription(subscription_id)
        with self._lock:
            current = self._states.get(subscription_id)
            if current and current.get("status") in {"queued", "running"}:
                return dict(current)
            self._states[subscription_id] = {
                "status": "queued",
                "subscription_id": subscription_id,
                "found_count": 0,
                "eligible_count": 0,
                "imported_count": 0,
            }
            future = self._executor.submit(self._run, subscription_id, max(1, int(max_items)))
        future.add_done_callback(lambda completed, item_id=subscription_id: self._complete(item_id, completed))
        return {"status": "queued", "subscription_id": subscription_id, "found_count": 0, "eligible_count": 0, "imported_count": 0}

    def status(self, subscription_id: str) -> dict[str, Any]:
        subscription = self._service.get_subscription(subscription_id)
        with self._lock:
            active_status = self._states.get(subscription_id)
        if active_status:
            return dict(active_status)
        return {
            "status": subscription.get("last_run_status") or "idle",
            "subscription_id": subscription_id,
            "found_count": int(subscription.get("last_run_found_count") or 0),
            "imported_count": int(subscription.get("last_run_imported_count") or 0),
        }

    def shutdown(self, *, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=False)

    def _run(self, subscription_id: str, max_items: int) -> dict[str, Any]:
        with self._lock:
            self._states.setdefault(subscription_id, {"subscription_id": subscription_id})["status"] = "running"

        def report_progress(progress: dict[str, int]) -> None:
            with self._lock:
                state = self._states.setdefault(subscription_id, {"subscription_id": subscription_id})
                state.update(progress)
                state["status"] = "running"

        # This compatibility queue is no longer used by API flows (they use
        # persistent source tasks), but it must never turn a healthy remote
        # sync into a failure solely because an arbitrary wall-clock elapsed.
        return self._service.sync_subscription(
            subscription_id,
            max_items=max_items,
            mode="latest",
            force=True,
            on_progress=report_progress,
        )

    def _complete(self, subscription_id: str, future: Future[dict[str, Any]]) -> None:
        try:
            future.exception()
        finally:
            with self._lock:
                self._states.pop(subscription_id, None)

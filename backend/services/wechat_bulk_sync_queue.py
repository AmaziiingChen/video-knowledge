from __future__ import annotations

import random
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import TYPE_CHECKING, Any, Callable

from config import settings

from services.repository import new_id
from services.wechat_subscription_errors import WeChatRemoteError
from services.wechat_subscription_secrets import (
    WeChatAuthorizationError,
    WeChatSubscriptionError,
)

if TYPE_CHECKING:
    from services.wechat_subscription import WeChatSubscriptionService


WECHAT_CHECK_DELAY_RANGE = (15.0, 30.0)


class WeChatBulkSyncQueue:
    """Serial, paced newest-window checks for every enabled subscription."""

    def __init__(
        self,
        service: WeChatSubscriptionService,
        *,
        delay_range: tuple[float, float] = WECHAT_CHECK_DELAY_RANGE,
        check_limit: int = settings.wechat_subscription_default_initial_limit,
        sleep: Callable[[float], None] = time.sleep,
        uniform: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self._service = service
        self._delay_range = delay_range
        self._check_limit = max(1, min(int(check_limit), 10))
        self._sleep = sleep
        self._uniform = uniform
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wechat-bulk-sync")
        self._lock = Lock()
        self._state: dict[str, Any] = self._idle_state()

    @staticmethod
    def _idle_state() -> dict[str, Any]:
        return {
            "job_id": "",
            "status": "idle",
            "total": 0,
            "completed": 0,
            "succeeded": 0,
            "failed": 0,
            "skipped": 0,
            "imported_count": 0,
            "incomplete_count": 0,
            "current_subscription_id": "",
            "current_name": "",
            "message": "",
        }

    def enqueue(self) -> dict[str, Any]:
        subscriptions = [item for item in self._service.list_subscriptions() if item.get("enabled")]
        with self._lock:
            if self._state.get("status") in {"queued", "running"}:
                return dict(self._state)
            self._state = {
                **self._idle_state(),
                "job_id": new_id(),
                "status": "queued",
                "total": len(subscriptions),
                "message": "等待开始",
            }
            snapshot = dict(self._state)
        if subscriptions:
            self._executor.submit(self._run, subscriptions)
        else:
            with self._lock:
                self._state.update(status="succeeded", message="没有已启用的公众号需要更新")
                snapshot = dict(self._state)
        return snapshot

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def shutdown(self, *, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=False)

    def _update(self, **values: Any) -> None:
        with self._lock:
            self._state.update(values)

    def _run(self, subscriptions: list[dict[str, Any]]) -> None:
        self._update(status="running", message="正在逐个检查公众号")
        stopped = False
        for index, subscription in enumerate(subscriptions):
            if index:
                lower, upper = self._delay_range
                self._sleep(self._uniform(max(0.0, lower), max(lower, upper)))
            self._update(
                current_subscription_id=str(subscription["id"]),
                current_name=str(subscription.get("mp_name") or "公众号"),
                message="正在检查最新文章",
            )
            try:
                result = self._service.sync_subscription(
                    str(subscription["id"]),
                    mode="latest",
                    max_items=self._check_limit,
                    force=False,
                )
                state = self.status()
                self._update(
                    completed=state["completed"] + 1,
                    succeeded=state["succeeded"] + 1,
                    imported_count=state["imported_count"] + int(result.get("imported_count") or 0),
                    incomplete_count=state["incomplete_count"] + (0 if result.get("coverage_complete", True) else 1),
                    current_subscription_id="",
                    current_name="",
                    message="等待检查下一个公众号",
                )
            except (WeChatAuthorizationError, WeChatRemoteError) as exc:
                state = self.status()
                self._update(
                    completed=state["completed"] + 1,
                    failed=state["failed"] + 1,
                    skipped=len(subscriptions) - index - 1,
                    status="stopped",
                    message=f"已停止：{exc}",
                )
                stopped = True
                break
            except WeChatSubscriptionError:
                state = self.status()
                self._update(
                    completed=state["completed"] + 1,
                    failed=state["failed"] + 1,
                    current_subscription_id="",
                    current_name="",
                    message="等待检查下一个公众号",
                )
        if not stopped:
            state = self.status()
            final_status = "succeeded" if not state["failed"] else "completed_with_errors"
            self._update(status=final_status, current_subscription_id="", current_name="", message="全部检查完成")

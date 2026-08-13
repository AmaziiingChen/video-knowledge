from __future__ import annotations

from services.creator_sync_models import CreatorSyncError


ALLOWED_SYNC_INTERVAL_MINUTES = {30, 60, 180, 360, 720, 1440}
CREATOR_PROCESSING_MODES = {"metadata", "transcript", "full"}
MAX_CREATOR_QUEUE_LIMIT = 500


def valid_interval(value: object) -> int:
    try:
        interval = int(value)
    except (TypeError, ValueError) as exc:
        raise CreatorSyncError("检查频率无效") from exc
    if interval not in ALLOWED_SYNC_INTERVAL_MINUTES:
        choices = "、".join(str(item) for item in sorted(ALLOWED_SYNC_INTERVAL_MINUTES))
        raise CreatorSyncError(f"检查频率必须是 {choices} 分钟之一")
    return interval


def valid_processing_mode(value: object) -> str:
    mode = str(value or "").strip().lower()
    if mode not in CREATOR_PROCESSING_MODES:
        raise CreatorSyncError("处理方式必须是 metadata、transcript 或 full")
    return mode


def valid_queue_limit(value: object) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError) as exc:
        raise CreatorSyncError("每轮入队上限无效") from exc
    if not 1 <= limit <= MAX_CREATOR_QUEUE_LIMIT:
        raise CreatorSyncError(f"每轮入队上限必须在 1 到 {MAX_CREATOR_QUEUE_LIMIT} 之间")
    return limit


def effective_processing_mode(source_row, requested_mode: str | None, requested_auto_process: bool | None) -> str:
    if requested_mode is not None:
        return valid_processing_mode(requested_mode)
    if requested_auto_process is not None:
        return "full" if requested_auto_process else "metadata"
    if source_row:
        stored_mode = source_row["processing_mode"] if "processing_mode" in source_row.keys() else None
        if stored_mode:
            return valid_processing_mode(stored_mode)
        return "full" if bool(source_row["auto_process"]) else "metadata"
    return "full"


def creator_error_category(message: str) -> str:
    text = str(message or "").lower()
    if any(token in text for token in ("错误码 -352", "error code -352", "风控", "风险校验", "risk control")):
        return "remote"
    if any(token in text for token in ("cookie", "登录", "403", "412", "授权")):
        return "authorization"
    if any(token in text for token in ("timeout", "超时", "暂时", "网络", "拒绝")):
        return "remote"
    if any(token in text for token in ("chromium", "浏览器组件", "内置浏览器")):
        return "runtime"
    return "unknown"


def creator_retry_minutes(category: str, failures: int, configured_interval: int) -> int:
    if category == "authorization":
        return max(configured_interval, 360)
    base = 30 if category == "remote" else 60
    return min(720, max(configured_interval, base * (2 ** min(max(0, failures - 1), 4))))

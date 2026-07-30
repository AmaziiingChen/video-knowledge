from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from threading import Event, Lock, Thread
import time
from typing import Any

from config import settings
from services.forum_capture_parser import (
    FeedCandidate,
    detail_matches_candidate,
    detect_feed_candidates,
    feed_candidates_equivalent,
    latest_tab_position,
    looks_like_deleted_post,
    looks_like_detail_bottom,
    looks_like_detail_page,
    looks_like_feed_page,
    looks_like_transient_overlay,
    measure_ocr_vertical_displacement,
    parse_detail_capture,
    parse_feed_candidate,
)
from services.forum_capture_repository import ForumCaptureRepository
from services.macos_miniprogram import (
    DEFAULT_WINDOW_PATTERN,
    MacOSMiniProgramDriver,
    MiniProgramDriverError,
    feed_top_button_position,
    image_perceptual_hash,
)


logger = logging.getLogger(__name__)


TOP_BUTTON_MAX_CLICKS = 3
FEED_SCROLL_WHEEL_ATTEMPTS = (4, 5, 6)
DETAIL_SCROLL_WHEEL_ATTEMPTS = (3, 4, 5)
MIN_SCROLL_DISPLACEMENT = 12.0
PAGE_FRAME_RETRIES = 3
FUZZY_DEDUPE_WINDOW = 250


class DeletedForumPost(RuntimeError):
    """Expected control flow for a stale feed card whose post was deleted."""


class MiniProgramForumCollector:
    def __init__(
        self,
        *,
        driver: MacOSMiniProgramDriver | None = None,
        repository: ForumCaptureRepository | None = None,
    ) -> None:
        self.driver = driver or MacOSMiniProgramDriver()
        self.repository = repository or ForumCaptureRepository()
        self._lock = Lock()
        self._thread: Thread | None = None
        self._stop = Event()
        self._pause = Event()
        self._active_run_id = ""
        self._last_image_width = 1.0
        self._last_image_height = 1.0

    def recover_stale_runs(self) -> None:
        latest = self.repository.latest_run()
        if latest and latest.get("status") in {"running", "paused", "stopping"}:
            self.repository.update_run(
                str(latest["id"]),
                status="interrupted",
                current_stage="interrupted",
                last_error="应用退出导致采集中断，可重新开始增量采集",
                finished_at=datetime.now(timezone.utc).isoformat(),
            )
        try:
            self.repository.backfill_run_documents()
            self.repository.consolidate_posts_into_run_documents()
        except Exception:
            logger.exception("unable to promote historical mini-program captures into the library")

    def permission_status(self, window_pattern: str, *, prompt: bool = False) -> dict[str, Any]:
        return self.driver.status(window_pattern, prompt=prompt)

    def start(self, options: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise RuntimeError("已有小程序采集任务正在运行")
            source_key = str(options.get("source_key") or "campus_forum").strip()
            mode = str(options.get("mode") or "incremental").strip()
            window_pattern = str(options.get("window_pattern") or DEFAULT_WINDOW_PATTERN).strip()
            run = self.repository.create_run(
                source_key=source_key,
                mode=mode,
                window_pattern=window_pattern,
                options=options,
            )
            self._active_run_id = str(run["id"])
            self._stop.clear()
            self._pause.clear()
            self._thread = Thread(
                target=self._run,
                args=(self._active_run_id, options),
                name="miniprogram-forum-capture",
                daemon=True,
            )
            self._thread.start()
            return run

    def pause(self) -> dict[str, Any]:
        run_id = self._require_active()
        self._pause.set()
        return self.repository.update_run(run_id, status="paused", current_stage="paused")

    def resume(self) -> dict[str, Any]:
        run_id = self._require_active()
        self._pause.clear()
        return self.repository.update_run(run_id, status="running", current_stage="resuming")

    def stop(self) -> dict[str, Any]:
        run_id = self._require_active()
        self._stop.set()
        self._pause.clear()
        return self.repository.update_run(run_id, status="stopping", current_stage="stopping")

    def current_status(self, window_pattern: str = DEFAULT_WINDOW_PATTERN) -> dict[str, Any]:
        with self._lock:
            active = bool(self._thread and self._thread.is_alive())
            active_run_id = self._active_run_id if active else ""
        run = self.repository.get_run(active_run_id) if active_run_id else self.repository.latest_run()
        try:
            environment = self.driver.status(window_pattern, prompt=False)
        except Exception as exc:
            environment = {"available": False, "error": str(exc), "selected_window": None}
        return {"active": active, "run": run, "environment": environment}

    def is_active(self) -> bool:
        with self._lock:
            return bool(self._thread and self._thread.is_alive())

    def _require_active(self) -> str:
        with self._lock:
            if not self._thread or not self._thread.is_alive() or not self._active_run_id:
                raise RuntimeError("当前没有运行中的小程序采集任务")
            return self._active_run_id

    def _run(self, run_id: str, options: dict[str, Any]) -> None:
        counters = {"posts_seen": 0, "posts_created": 0, "comments_captured": 0, "frames_captured": 0}
        try:
            self.repository.update_run(run_id, current_stage="checking_permissions")
            pattern = str(options.get("window_pattern") or DEFAULT_WINDOW_PATTERN)
            environment = self.driver.status(pattern, prompt=bool(options.get("prompt_permissions", True)))
            if not environment.get("accessibility_granted"):
                raise MiniProgramDriverError("需要在系统设置中允许辅助功能控制")
            window = environment.get("selected_window")
            if not window:
                raise MiniProgramDriverError("未找到微信小程序窗口，请先打开目标论坛并停留在帖子列表")
            self.driver.activate(window)
            time.sleep(0.8)
            self._crawl_feed(run_id, options, window, counters)
            final_status = "stopped" if self._stop.is_set() else "succeeded"
            self.repository.update_run(
                run_id,
                status=final_status,
                current_stage=final_status,
                last_error="",
                finished_at=datetime.now(timezone.utc).isoformat(),
                **counters,
            )
        except Exception as exc:
            logger.exception("mini-program forum capture failed")
            self.repository.update_run(
                run_id,
                status="failed",
                current_stage="failed",
                last_error=str(exc)[:500],
                finished_at=datetime.now(timezone.utc).isoformat(),
                **counters,
            )
        finally:
            with self._lock:
                if self._active_run_id == run_id:
                    self._active_run_id = ""

    def _crawl_feed(
        self,
        run_id: str,
        options: dict[str, Any],
        window: dict[str, Any],
        counters: dict[str, int],
    ) -> None:
        max_posts = max(1, min(int(options.get("max_posts") or 300), 5000))
        max_feed_scrolls = max(1, min(int(options.get("max_feed_scrolls") or 500), 5000))
        known_stop = max(1, min(int(options.get("known_post_stop") or 20), 200))
        page_wait = max(0.4, min(float(options.get("page_wait_seconds") or 1.2), 8.0))
        mode = str(options.get("mode") or "incremental")
        source_key = str(options.get("source_key") or "campus_forum")
        processed_signatures: set[str] = set()
        processed_cards: list[FeedCandidate] = []
        documented_posts: set[str] = set()
        known_streak = 0
        consecutive_errors = 0
        pending_feed_frame: dict[str, Any] | None = None

        self._ensure_feed(window, page_wait, run_id=run_id)
        if not self._scroll_feed_to_top(window, page_wait, run_id=run_id):
            raise MiniProgramDriverError("点击置顶按钮后仍无法确认到达帖子列表顶部")

        feed_scroll = 0
        while feed_scroll < max_feed_scrolls:
            self._checkpoint(run_id, counters, "scanning_feed", feed_scroll=feed_scroll)
            if not self._cooperate(run_id):
                return
            if pending_feed_frame is not None:
                frame = pending_feed_frame
                pending_feed_frame = None
            else:
                frame = self._capture_expected_page_frame(
                    run_id,
                    window,
                    "feed",
                    counters,
                    page_wait,
                    page="feed",
                )
            candidates = detect_feed_candidates(frame["ocr"])
            candidate = next(
                (
                    item
                    for item in candidates
                    if item.signature not in processed_signatures
                    and not any(
                        feed_candidates_equivalent(item, previous)
                        for previous in processed_cards[-FUZZY_DEDUPE_WINDOW:]
                    )
                ),
                None,
            )
            self._record_action(
                run_id,
                "recognize_feed",
                feed_scroll=feed_scroll,
                candidates=len(candidates),
                selected=bool(candidate),
                ignored_talent_recommendation=any(
                    "达人推荐" in line.get("text", "")
                    for line in frame["ocr"].get("lines", [])
                    if isinstance(line, dict)
                ),
            )

            # Coordinates are valid for this frame only. Process exactly one
            # card, then recapture before selecting another one.
            if candidate is not None:
                if counters["posts_seen"] >= max_posts or not self._cooperate(run_id):
                    return
                detail_reason = []
                if candidate.truncated:
                    detail_reason.append("truncated")
                if candidate.has_comments:
                    detail_reason.append("comments")
                if candidate.needs_detail and not detail_reason:
                    detail_reason.append("partially_visible")
                self._checkpoint(
                    run_id,
                    counters,
                    "opening_post" if candidate.needs_detail else "parsing_visible_post",
                    feed_scroll=feed_scroll,
                )
                try:
                    if candidate.needs_detail:
                        self._record_action(
                            run_id,
                            "click_post",
                            x=round(candidate.click_x / self._last_image_width, 4),
                            y=round(candidate.click_y / self._last_image_height, 4),
                            reason=detail_reason,
                            author=candidate.author_hint,
                            display_time=candidate.display_time,
                        )
                        parsed, frame_ids, detail_path = self._capture_post_detail(
                            run_id, options, window, candidate, counters, page_wait
                        )
                    else:
                        self._record_action(
                            run_id,
                            "parse_post_from_feed",
                            reason="full_body_visible_without_comments",
                            author=candidate.author_hint,
                            display_time=candidate.display_time,
                        )
                        parsed = parse_feed_candidate(
                            candidate,
                            captured_at=datetime.now().astimezone(),
                        )
                        frame_ids = [str(frame["id"])]
                        detail_path = str(frame["path"])
                    post, created = self.repository.upsert_post(
                        source_key=source_key,
                        parsed=parsed,
                        detail_frame_path=detail_path,
                    )
                    self.repository.attach_frames(frame_ids, str(post["id"]))
                    counters["posts_seen"] += 1
                    counters["posts_created"] += int(created)
                    counters["comments_captured"] += len(parsed.get("comments") or [])
                    post_id = str(post["id"])
                    if post_id not in documented_posts:
                        self.repository.append_run_post(
                            run_id,
                            post,
                            ordinal=len(documented_posts) + 1,
                            captured_at=datetime.now(timezone.utc).isoformat(),
                        )
                        documented_posts.add(post_id)
                    processed_signatures.add(candidate.signature)
                    parsed_body = str(parsed.get("body_text") or "").strip()
                    parsed_author = str(parsed.get("author_label") or "").strip()
                    processed_cards.append(
                        replace(
                            candidate,
                            body_text=parsed_body or candidate.body_text,
                            author_hint=parsed_author or candidate.author_hint,
                        )
                    )
                    known_streak = 0 if created else known_streak + 1
                    consecutive_errors = 0
                except DeletedForumPost:
                    processed_signatures.add(candidate.signature)
                    processed_cards.append(candidate)
                    consecutive_errors = 0
                except Exception as exc:
                    # Do not click the same stale coordinates five times. A
                    # failed card is skipped for this run so the next capture
                    # can process another card or advance the feed.
                    processed_signatures.add(candidate.signature)
                    processed_cards.append(candidate)
                    consecutive_errors += 1
                    self.repository.update_run(run_id, last_error=f"单篇采集失败：{str(exc)[:300]}")
                    self._record_action(run_id, "post_error", error=str(exc)[:300])
                    self._record_action(
                        run_id,
                        "skip_failed_post",
                        author=candidate.author_hint,
                        display_time=candidate.display_time,
                    )
                    self._ensure_feed(window, page_wait, run_id=run_id)
                    if consecutive_errors >= 5:
                        raise MiniProgramDriverError("连续 5 篇帖子无法打开或识别，已停止以避免误操作") from exc
                self._checkpoint(run_id, counters, "returned_to_feed", feed_scroll=feed_scroll)
                if mode == "incremental" and known_streak >= known_stop:
                    return
                continue

            if counters["posts_seen"] >= max_posts:
                return
            pending_feed_frame = self._scroll_down_verified(
                run_id,
                window,
                counters,
                page_wait,
                page="feed",
                before=frame,
                scroll_index=feed_scroll + 1,
            )
            feed_scroll += 1

    def _capture_post_detail(
        self,
        run_id: str,
        options: dict[str, Any],
        window: dict[str, Any],
        candidate,
        counters: dict[str, int],
        page_wait: float,
    ) -> tuple[dict[str, Any], list[str], str]:
        self.driver.click_pixel(window, {"width": self._last_image_width, "height": self._last_image_height}, candidate.click_x, candidate.click_y)
        time.sleep(page_wait)
        first_frame = self._capture_frame(run_id, window, "detail", counters)
        first_frame = self._recover_detail_overlay(
            run_id, window, page_wait, counters, first_frame
        )
        frames = [first_frame]
        if not looks_like_detail_page(frames[0]["ocr"]):
            time.sleep(page_wait)
            retry = self._capture_frame(run_id, window, "detail_retry", counters)
            frames.append(
                self._recover_detail_overlay(run_id, window, page_wait, counters, retry)
            )
        if not looks_like_detail_page(frames[-1]["ocr"]):
            raise MiniProgramDriverError("点击帖子后未识别到详情页")
        if looks_like_deleted_post(frames[-1]["ocr"]):
            self._record_action(
                run_id,
                "skip_deleted_post",
                author=candidate.author_hint,
                display_time=candidate.display_time,
            )
            self._return_to_feed(window, page_wait, run_id=run_id)
            raise DeletedForumPost("帖子已删除，已跳过")
        if not detail_matches_candidate(frames[-1]["ocr"], candidate):
            self._record_action(
                run_id,
                "detail_mismatch",
                author=candidate.author_hint,
                display_time=candidate.display_time,
            )
            self._return_to_feed(window, page_wait, run_id=run_id)
            raise MiniProgramDriverError("详情页与当前列表帖子不匹配，已放弃本次解析")

        max_detail_scrolls = max(1, min(int(options.get("max_detail_scrolls") or 120), 1000))
        hit_bottom = False
        latest_clicked = False
        for detail_scroll in range(max_detail_scrolls + 1):
            if not self._cooperate(run_id):
                break
            latest = latest_tab_position(frames[-1]["ocr"])
            if latest and not latest_clicked:
                self._record_action(
                    run_id,
                    "click_latest_comments",
                    x=round(latest[0] / float(frames[-1]["ocr"].get("width") or 1), 4),
                    y=round(latest[1] / float(frames[-1]["ocr"].get("height") or 1), 4),
                )
                self.driver.click_pixel(window, frames[-1]["ocr"], latest[0], latest[1])
                latest_clicked = True
                time.sleep(page_wait)
                latest_frame = self._capture_frame(run_id, window, "detail_latest", counters)
                frames.append(
                    self._recover_detail_overlay(
                        run_id, window, page_wait, counters, latest_frame
                    )
                )
                continue
            if looks_like_detail_bottom(frames[-1]["ocr"]):
                hit_bottom = True
                self._record_action(
                    run_id,
                    "detail_bottom_detected",
                    detail_scroll=detail_scroll,
                    marker="长按评论可赞赏，遇到热心猹友可以给TA一点鼓励",
                )
                break
            if detail_scroll >= max_detail_scrolls:
                break
            next_frame = self._scroll_down_verified(
                run_id,
                window,
                counters,
                page_wait,
                page="detail",
                before=frames[-1],
                scroll_index=detail_scroll + 1,
            )
            frames.append(next_frame)

        parsed = parse_detail_capture(
            [frame["ocr"] for frame in frames],
            captured_at=datetime.now().astimezone(),
            author_hint=candidate.author_hint,
            display_time_hint=candidate.display_time,
        )
        expected_comments = parsed.get("comment_count")
        stored_comments = len(parsed.get("comments") or [])
        comments_complete = expected_comments is None or stored_comments >= int(expected_comments)
        parsed["capture_complete"] = bool(
            parsed.get("capture_complete") and hit_bottom and comments_complete
        )
        reasons = []
        if not hit_bottom:
            reasons.append("未识别到详情页底部提示")
        if expected_comments is not None and not comments_complete:
            reasons.append(
                f"界面显示 {expected_comments} 条评论，结构化取得 {stored_comments} 条"
            )
        if reasons:
            parsed["incomplete_reason"] = "；".join(reasons) + "；原始详情帧已保留待补采或重新解析"
        self._return_to_feed(window, page_wait, run_id=run_id)
        return parsed, [str(frame["id"]) for frame in frames], str(frames[0]["path"])

    def _scroll_down_verified(
        self,
        run_id: str,
        window: dict[str, Any],
        counters: dict[str, int],
        page_wait: float,
        *,
        page: str,
        before: dict[str, Any],
        scroll_index: int,
    ) -> dict[str, Any]:
        origin = before
        current = before
        action = f"scroll_{page}"
        wheel_attempts = (
            FEED_SCROLL_WHEEL_ATTEMPTS
            if page == "feed"
            else DETAIL_SCROLL_WHEEL_ATTEMPTS
        )
        for attempt, ticks in enumerate(wheel_attempts, start=1):
            self._record_action(
                run_id,
                action,
                direction="down",
                unit="wheel_tick",
                requested_ticks=ticks,
                attempt=attempt,
                scroll_index=scroll_index,
            )
            # The native helper translates logical page-down ticks using the
            # current macOS natural-scroll preference. The observed OCR
            # displacement below is still the authority; a reverse result
            # aborts immediately.
            self.driver.scroll(window, ticks)
            time.sleep(page_wait)
            after = self._capture_expected_page_frame(
                run_id,
                window,
                f"{page}_scroll",
                counters,
                page_wait,
                page=page,
            )
            step_displacement = measure_ocr_vertical_displacement(
                current["ocr"], after["ocr"]
            )
            total_displacement = measure_ocr_vertical_displacement(
                origin["ocr"], after["ocr"]
            )
            effective = (
                total_displacement
                if total_displacement is not None
                else step_displacement
            )
            hit_bottom = page == "detail" and looks_like_detail_bottom(after["ocr"])
            verified = bool(
                hit_bottom
                or (effective is not None and effective <= -MIN_SCROLL_DISPLACEMENT)
            )
            self._record_action(
                run_id,
                f"{action}_result",
                attempt=attempt,
                scroll_index=scroll_index,
                step_displacement=round(step_displacement, 2) if step_displacement is not None else None,
                total_displacement=round(total_displacement, 2) if total_displacement is not None else None,
                verified=verified,
                hit_bottom=hit_bottom,
            )
            if verified:
                return after
            if effective is not None and effective >= MIN_SCROLL_DISPLACEMENT:
                raise MiniProgramDriverError(
                    "滚轮产生了反向位移，已停止以避免上下往返滚动"
                )
            current = after
        page_label = "帖子列表" if page == "feed" else "详情页"
        raise MiniProgramDriverError(
            f"{page_label}连续 {len(wheel_attempts)} 次滚轮未产生有效向下位移"
        )

    def _capture_expected_page_frame(
        self,
        run_id: str,
        window: dict[str, Any],
        kind: str,
        counters: dict[str, int],
        page_wait: float,
        *,
        page: str,
    ) -> dict[str, Any]:
        last_frame: dict[str, Any] | None = None
        for attempt in range(1, PAGE_FRAME_RETRIES + 1):
            frame_kind = kind if attempt == 1 else f"{kind}_retry"
            frame = self._capture_frame(run_id, window, frame_kind, counters)
            last_frame = frame
            if looks_like_transient_overlay(frame["ocr"]):
                if page == "detail":
                    try:
                        frame = self._recover_detail_overlay(
                            run_id, window, page_wait, counters, frame
                        )
                    except MiniProgramDriverError:
                        if attempt >= PAGE_FRAME_RETRIES:
                            raise
                        time.sleep(page_wait)
                        continue
                else:
                    self._record_action(
                        run_id, "dismiss_overlay", page="feed", method="escape"
                    )
                    self.driver.escape()
                    time.sleep(page_wait)
                    continue
            expected = (
                looks_like_feed_page(frame["ocr"])
                if page == "feed"
                else looks_like_detail_page(frame["ocr"])
            )
            if expected:
                return frame
            if page == "feed" and looks_like_detail_page(frame["ocr"]):
                self._return_to_feed(window, page_wait, run_id=run_id)
            self._record_action(
                run_id,
                "page_frame_retry",
                page=page,
                attempt=attempt,
                ocr_lines=len(frame["ocr"].get("lines") or []),
            )
            if attempt < PAGE_FRAME_RETRIES:
                time.sleep(page_wait)
        page_label = "“本校”帖子列表" if page == "feed" else "详情页"
        line_count = len(last_frame["ocr"].get("lines") or []) if last_frame else 0
        raise MiniProgramDriverError(
            f"连续 {PAGE_FRAME_RETRIES} 帧未识别到{page_label}（最后一帧 OCR {line_count} 行）"
        )

    def _recover_detail_overlay(
        self,
        run_id: str,
        window: dict[str, Any],
        page_wait: float,
        counters: dict[str, int],
        frame: dict[str, Any],
    ) -> dict[str, Any]:
        if not looks_like_transient_overlay(frame["ocr"]):
            return frame
        self._record_action(run_id, "dismiss_overlay", page="detail", method="escape")
        self.driver.escape()
        time.sleep(page_wait)
        recovered = self._capture_frame(run_id, window, "detail_overlay_recovery", counters)
        if looks_like_transient_overlay(recovered["ocr"]):
            self._record_action(run_id, "dismiss_overlay", page="detail", method="back")
            self.driver.click_normalized(window, 0.065, 0.055)
            time.sleep(page_wait)
            recovered = self._capture_frame(run_id, window, "detail_overlay_back", counters)
        if looks_like_transient_overlay(recovered["ocr"]):
            raise MiniProgramDriverError("详情页分享弹层无法安全关闭")
        if not looks_like_detail_page(recovered["ocr"]):
            raise MiniProgramDriverError("关闭分享弹层后未回到详情页")
        return recovered

    def _return_to_feed(
        self,
        window: dict[str, Any],
        page_wait: float,
        *,
        run_id: str = "",
    ) -> None:
        self._record_action(run_id, "return_to_feed", method="back")
        self.driver.click_normalized(window, 0.065, 0.055)
        time.sleep(page_wait)
        probe_path = settings.data_dir / "miniprogram_forum" / "return-probe.png"
        try:
            back_retried = False
            escape_sent = False
            last_probe: dict[str, Any] = {}
            for attempt in range(1, PAGE_FRAME_RETRIES * 2 + 1):
                self.driver.capture_window(window, probe_path)
                probe = self.driver.recognize(probe_path)
                probe_path.unlink(missing_ok=True)
                last_probe = probe
                if looks_like_feed_page(probe):
                    return
                is_detail = looks_like_detail_page(probe)
                is_overlay = looks_like_transient_overlay(probe)
                self._record_action(
                    run_id,
                    "return_probe_retry",
                    attempt=attempt,
                    ocr_lines=len(probe.get("lines") or []),
                    detail=is_detail,
                    overlay=is_overlay,
                )
                if is_detail and attempt >= 2 and not back_retried:
                    self._record_action(run_id, "return_to_feed", method="back_retry")
                    self.driver.click_normalized(window, 0.065, 0.055)
                    back_retried = True
                elif (
                    is_overlay
                    or (is_detail and back_retried and attempt >= 4)
                ) and not escape_sent:
                    self._record_action(run_id, "return_to_feed", method="escape_fallback")
                    self.driver.escape()
                    escape_sent = True
                if attempt < PAGE_FRAME_RETRIES * 2:
                    time.sleep(page_wait)
            raise MiniProgramDriverError(
                "返回后连续多帧未识别到“本校”帖子列表"
                f"（最后一帧 OCR {len(last_probe.get('lines') or [])} 行）"
            )
        except MiniProgramDriverError:
            raise
        except Exception as exc:
            raise MiniProgramDriverError(f"无法确认已返回帖子列表：{exc}") from exc
        finally:
            probe_path.unlink(missing_ok=True)

    def _ensure_feed(
        self,
        window: dict[str, Any],
        page_wait: float,
        *,
        run_id: str = "",
    ) -> None:
        try:
            probe_path = settings.data_dir / "miniprogram_forum" / "ensure-feed-probe.png"
            self.driver.capture_window(window, probe_path)
            probe = self.driver.recognize(probe_path)
            probe_path.unlink(missing_ok=True)
            if looks_like_transient_overlay(probe):
                self._record_action(run_id, "dismiss_overlay", page="ensure_feed", method="escape")
                self.driver.escape()
                time.sleep(page_wait)
                self.driver.capture_window(window, probe_path)
                probe = self.driver.recognize(probe_path)
                probe_path.unlink(missing_ok=True)
            if looks_like_detail_page(probe):
                self._return_to_feed(window, page_wait, run_id=run_id)
                return
            if not looks_like_feed_page(probe):
                raise MiniProgramDriverError("异常恢复后未识别到“本校”帖子列表")
        except MiniProgramDriverError:
            raise
        except Exception as exc:
            raise MiniProgramDriverError(f"无法恢复到帖子列表：{exc}") from exc

    def _scroll_feed_to_top(
        self,
        window: dict[str, Any],
        page_wait: float,
        *,
        run_id: str = "",
    ) -> bool:
        """Use the feed's floating up button; never send an upward wheel event."""
        probe_path = settings.data_dir / "miniprogram_forum" / "feed-top-probe.png"
        try:
            for attempt in range(TOP_BUTTON_MAX_CLICKS + 1):
                self.driver.capture_window(window, probe_path)
                position = feed_top_button_position(probe_path)
                if position is None:
                    self._record_action(
                        run_id,
                        "feed_top_confirmed",
                        method="top_button_absent",
                        attempts=attempt,
                    )
                    return True
                if attempt >= TOP_BUTTON_MAX_CLICKS:
                    break
                self._record_action(
                    run_id,
                    "click_feed_top",
                    x=round(position[0], 4),
                    y=round(position[1], 4),
                    attempt=attempt + 1,
                )
                self.driver.click_normalized(window, position[0], position[1])
                time.sleep(page_wait)
            return False
        finally:
            probe_path.unlink(missing_ok=True)

    def _capture_frame(
        self,
        run_id: str,
        window: dict[str, Any],
        kind: str,
        counters: dict[str, int],
    ) -> dict[str, Any]:
        sequence = counters["frames_captured"] + 1
        run_dir = settings.data_dir / "miniprogram_forum" / "runs" / run_id
        path = run_dir / f"{sequence:06d}-{kind}.png"
        self.driver.capture_window(window, path)
        ocr = self.driver.recognize(path)
        self._last_image_width = float(ocr.get("width") or 1)
        self._last_image_height = float(ocr.get("height") or 1)
        image_hash = image_perceptual_hash(path)
        frame_id = self.repository.save_frame(
            run_id=run_id,
            frame_kind=kind,
            sequence=sequence,
            image_path=str(path),
            image_hash=image_hash,
            ocr=ocr,
        )
        counters["frames_captured"] = sequence
        return {"id": frame_id, "path": path, "hash": image_hash, "ocr": ocr}

    @staticmethod
    def _record_action(run_id: str, action: str, **details: Any) -> None:
        if not run_id:
            return
        path = (
            settings.data_dir
            / "miniprogram_forum"
            / "runs"
            / run_id
            / "actions.jsonl"
        )
        payload = {
            "at": datetime.now().astimezone().isoformat(),
            "action": action,
            **details,
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        except OSError:
            logger.exception("unable to write mini-program action audit")

    def _checkpoint(self, run_id: str, counters: dict[str, int], stage: str, **checkpoint: Any) -> None:
        self.repository.update_run(
            run_id,
            status="paused" if self._pause.is_set() else "running",
            current_stage=stage,
            checkpoint_json=checkpoint,
            **counters,
        )

    def _cooperate(self, run_id: str) -> bool:
        if self._stop.is_set():
            return False
        announced = False
        while self._pause.is_set() and not self._stop.is_set():
            if not announced:
                self.repository.update_run(run_id, status="paused", current_stage="paused")
                announced = True
            self._stop.wait(0.4)
        if announced and not self._stop.is_set():
            self.repository.update_run(run_id, status="running", current_stage="resuming")
        return not self._stop.is_set()


miniprogram_forum_collector = MiniProgramForumCollector()


__all__ = ["MiniProgramForumCollector", "miniprogram_forum_collector"]

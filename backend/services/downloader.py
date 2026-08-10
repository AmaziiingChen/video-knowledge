import subprocess
import json
import re
import time
import threading
import httpx
from pathlib import Path
from queue import Empty, Queue
from typing import Optional
from config import settings
from services.media_tools import resolve_tool
from services.ffmpeg_runner import FfmpegProgress, probe_media_duration, run_ffmpeg
from services.bilibili_auth import bilibili_yt_dlp_cookie_args
from services.bilibili_native import resolve_progressive_media
from services.http_media_download import download_browser_context_media, download_http_media
from services.network_policy import direct_browser_launch_options, direct_network_environment
from services.runtime_components import browser_executable
from services.source_context import (
    build_source_context,
    douyin_comments_from_payload,
    source_context_from_douyin_aweme,
)
from services.douyin_media_rules import (
    browser_media_headers as _browser_media_headers,
    find_aweme as _find_douyin_aweme,
    is_comment_payload_url as _is_douyin_comment_payload_url,
    is_media_host as _is_douyin_media_host,  # noqa: F401 - compatibility alias
    is_preferred_bitrate as _is_preferred_douyin_bitrate,
    is_work_payload_url as _is_douyin_work_payload_url,
    looks_like_audio_url as _looks_like_douyin_audio_url,
    looks_like_video_url as _looks_like_douyin_video_url,
    lowest_video_variant as _lowest_douyin_video_variant,  # noqa: F401 - compatibility alias
    needs_media_refresh as _needs_douyin_media_refresh,
    quality_label as _douyin_quality_label,
    select_video_variant as _select_douyin_video_variant,
    video_variants as _douyin_video_variants,  # noqa: F401 - compatibility alias
)
from services.download_contracts import (
    CancelCheck,
    DownloadLogCallback,
    DownloadProgress,
    DownloadResult,
    ProgressCallback,
    activity_timeout_error as _activity_timeout_error,
    append_download_log as _append_download_log,
    media_transfer_error as _media_transfer_error,
    report_phase as _report_phase,
    report_progress as _report,
    report_transfer as _report_transfer,
    report_transfer_percent as _report_transfer_percent,
    yt_dlp_bytes_per_second as _yt_dlp_bytes_per_second,
)
from services.video_download_settings import douyin_video_quality as _load_douyin_video_quality
BILIBILI_1080P_FORMAT = "bv*[height<=1080]+ba/b[height<=1080]/best[height<=1080]"
YTDLP_ACTIVITY_TIMEOUT_SECONDS = 300
# A Douyin work page commonly renders the player after the document commit.
# Six seconds was shorter than normal delayed page hydration on constrained
# networks and caused a false "no media request" result.
DOUYIN_MEDIA_CAPTURE_WAIT_SECONDS = 15
# ``play()`` is only a network trigger.  Never wait for its promise: on some
# Douyin pages it remains pending in headless Chromium even after the media
# requests have already been issued.
DOUYIN_AUDIO_CAPTURE_SETTLE_SECONDS = 1.5
# Browser navigation and each HTTP transfer already have their own bounded
# deadlines. The outer guard detects a worker that has stopped reporting any
# activity; it is deliberately not a total runtime limit.
DOUYIN_BROWSER_WATCHDOG_SECONDS = 420

def download_video(
    url: str,
    platform: str,
    output_dir: Path,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
    log_callback: DownloadLogCallback | None = None,
) -> DownloadResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if platform == "bilibili":
        return _download_bilibili(url, output_dir, progress_callback, cancel_check)
    
    if platform == "douyin":
        return _download_douyin(url, output_dir, progress_callback, cancel_check, log_callback)
    
    return DownloadResult(success=False, error=f"不支持的平台: {platform}")

def _stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)
    except OSError:
        # The process may have exited between poll() and terminate().
        return


def _download_bilibili(
    url: str,
    output_dir: Path,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> DownloadResult:
    try:
        with bilibili_yt_dlp_cookie_args() as cookie_args:
            compatibility_result = _download_bilibili_with_cookie_args(
                url,
                output_dir,
                progress_callback,
                cookie_args,
                cancel_check,
            )
    except Exception as e:
        compatibility_result = DownloadResult(success=False, error=f"yt-dlp 异常: {str(e)}")
    if compatibility_result.success:
        return compatibility_result
    if compatibility_result.error == "下载已取消":
        return compatibility_result

    native_result = _download_bilibili_progressive(url, output_dir, progress_callback, cancel_check)
    if native_result.success:
        native_result.logs = [*compatibility_result.logs, "[B站] 兼容下载器不可用，已切换项目内直链下载", *native_result.logs]
        return native_result
    return compatibility_result


def _download_bilibili_progressive(
    url: str,
    output_dir: Path,
    progress_callback: ProgressCallback | None,
    cancel_check: CancelCheck | None = None,
) -> DownloadResult:
    logs: list[str] = ["[B站] 尝试项目内直链下载..."]
    try:
        media = resolve_progressive_media(url)
        target = output_dir / f"{media.bvid}.native.part"
        transfer_started = time.monotonic()
        _report_phase(progress_callback, "transfer", "正在传输视频")
        transfer = download_http_media(
            media.url,
            target,
            headers=media.headers,
            progress_callback=lambda received, total: _report_transfer(
                progress_callback,
                received,
                total,
                started_at=transfer_started,
                detail="正在传输视频",
            ),
            cancel_check=cancel_check,
        )
        if not transfer.success:
            return DownloadResult(success=False, logs=logs, error=f"B站直链下载失败: {transfer.error}")
        _report_phase(progress_callback, "validating", "正在校验媒体文件")
        if not _is_valid_video_file(target):
            return DownloadResult(success=False, logs=logs, error="B站直链媒体校验失败")
        final_path = output_dir / f"{media.bvid}.mp4"
        target.replace(final_path)
        _report_phase(progress_callback, "finalizing", "正在整理视频文件")
        logs.append(f"[B站] 项目内直链下载完成: {final_path.name}")
        return DownloadResult(
            success=True,
            video_path=final_path,
            video_info={
                "id": media.bvid,
                "title": media.title,
                "platform": "bilibili",
                "cid": media.cid,
                "page_number": media.page_number,
            },
            logs=logs,
        )
    except Exception as exc:
        return DownloadResult(success=False, logs=logs, error=f"B站直链解析失败: {exc}")


def _download_bilibili_with_cookie_args(
    url: str,
    output_dir: Path,
    progress_callback: ProgressCallback | None,
    cookie_args: list[str],
    cancel_check: CancelCheck | None = None,
) -> DownloadResult:
    output_template = str(output_dir / "%(id)s.%(ext)s")
    video_format = BILIBILI_1080P_FORMAT
    _report_phase(progress_callback, "resolving", "正在解析视频地址")
    cmd = [
        resolve_tool("yt-dlp") or "yt-dlp",
        "--newline",
        "--no-playlist",
        "-f",
        video_format,
        "--merge-output-format",
        "mp4",
        "-o",
        output_template,
        "--write-info-json",
        *cookie_args,
        url,
    ]
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=direct_network_environment(),
    )
    logs: list[str] = []
    last_activity_at = time.monotonic()
    output_lines: Queue[str] = Queue()

    def output_signature() -> tuple[tuple[str, int, int], ...]:
        signature: list[tuple[str, int, int]] = []
        try:
            candidates = output_dir.iterdir()
            for candidate in candidates:
                try:
                    stat = candidate.stat()
                except OSError:
                    continue
                if candidate.is_file():
                    signature.append((candidate.name, stat.st_size, stat.st_mtime_ns))
        except OSError:
            return ()
        return tuple(sorted(signature))

    last_output_signature = output_signature()

    def read_output() -> None:
        if not process.stdout:
            return
        for line in process.stdout:
            output_lines.put(line)

    output_reader = threading.Thread(target=read_output, daemon=True)
    output_reader.start()

    def record_output(line: str) -> None:
        nonlocal last_activity_at
        clean = line.strip()
        if clean:
            logs.append(clean)
            last_activity_at = time.monotonic()
        match = re.search(r"\[download\]\s+(\d+(?:\.\d+)?)%", clean)
        if match:
            _report_transfer_percent(
                progress_callback,
                float(match.group(1)),
                "正在传输媒体流",
                bytes_per_second=_yt_dlp_bytes_per_second(clean),
            )

    while process.poll() is None:
        if cancel_check and cancel_check():
            _stop_process(process)
            output_reader.join(timeout=1)
            return DownloadResult(success=False, logs=logs, error="下载已取消")

        try:
            record_output(output_lines.get(timeout=0.5))
            while True:
                record_output(output_lines.get_nowait())
        except Empty:
            pass

        if process.poll() is not None:
            break
        current_output_signature = output_signature()
        if current_output_signature != last_output_signature:
            last_activity_at = time.monotonic()
            last_output_signature = current_output_signature
        timeout_error = _activity_timeout_error(
            now=time.monotonic(),
            last_activity_at=last_activity_at,
            stall_seconds=YTDLP_ACTIVITY_TIMEOUT_SECONDS,
            operation="yt-dlp",
        )
        if timeout_error:
            _stop_process(process)
            output_reader.join(timeout=1)
            return DownloadResult(success=False, logs=logs, error=timeout_error)

    output_reader.join(timeout=1)
    while True:
        try:
            record_output(output_lines.get_nowait())
        except Empty:
            break

    return_code = process.wait()

    if return_code == 0:
        _report_phase(progress_callback, "finalizing", "正在合并媒体轨道")
        for f in output_dir.iterdir():
            if f.suffix in ['.mp4', '.mkv', '.webm', '.flv']:
                info = _load_info_json(output_dir, f.stem)
                return DownloadResult(success=True, video_path=f, video_info=info, logs=logs)
        return DownloadResult(success=False, logs=logs, error="下载完成但未找到视频文件")

    error_msg = logs[-1] if logs else f"yt-dlp 退出码: {return_code}"
    return DownloadResult(success=False, logs=logs, error=error_msg)

def _download_douyin(
    url: str,
    output_dir: Path,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
    log_callback: DownloadLogCallback | None = None,
) -> DownloadResult:
    logs = []
    
    _report_phase(progress_callback, "expanding_link", "正在展开抖音分享链接")
    _append_download_log(logs, "[短链展开] 正在解析抖音链接...", log_callback)
    video_id = _extract_douyin_video_id(url)
    if not video_id:
        _append_download_log(logs, "[短链展开] 直连展开未返回作品地址，切换项目内浏览器...", log_callback)
        video_id = _extract_douyin_video_id_via_browser(url)
    if not video_id:
        return DownloadResult(success=False, logs=logs, error="无法从链接中提取视频ID")
    _append_download_log(logs, f"[短链展开] 视频ID: {video_id}", log_callback)

    # Prefer the lightweight public metadata response.  It avoids starting a
    # Chromium process for an ordinary public work.  The browser provider is
    # retained as an authenticated, page-compatible fallback when the direct
    # response changes or a signed address requires a normal player session.
    _report_phase(progress_callback, "resolving_media", "正在解析抖音媒体地址")
    _append_download_log(logs, "[地址解析] 尝试直连获取作品媒体信息...", log_callback)
    result = _download_douyin_via_public_metadata(
        video_id,
        output_dir,
        logs,
        progress_callback,
        cancel_check,
        log_callback,
    )
    if not result.success and result.error != "下载已取消":
        _append_download_log(logs, f"[地址解析] 直连不可用，切换项目内浏览器: {result.error or '未返回可用媒体地址'}", log_callback)
        result = _download_douyin_via_browser(video_id, output_dir, logs, progress_callback, cancel_check, log_callback)
    if result.success:
        result.video_info = {**result.video_info, "id": video_id, "platform": "douyin"}
    return result


def _ensure_browser_playable_mp4(
    video_path: Path,
    logs: list[str],
    *,
    cancel_check: CancelCheck | None = None,
) -> Path:
    codec = _probe_video_codec(video_path)
    if codec in {"h264", "avc1"}:
        return video_path

    temp_path = video_path.with_name(f"{video_path.stem}_h264_tmp.mp4")
    temp_path.unlink(missing_ok=True)

    logs.append(f"[兼容] 当前视频编码为 {codec or '未知'}，转换为 H.264 以支持内嵌播放器...")
    cmd = [
        resolve_tool("ffmpeg") or "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-vf",
        "scale=-2:min(1080\\,ih)",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(temp_path),
    ]
    try:
        result = run_ffmpeg(
            cmd,
            output_path=temp_path,
            duration_seconds=probe_media_duration(video_path),
            cancel_check=cancel_check,
        )
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        logs.append(f"[兼容] 转码异常，保留原视频: {exc}")
        return video_path

    if result.cancelled:
        temp_path.unlink(missing_ok=True)
        logs.append("[兼容] 转码已取消，保留原视频")
        return video_path
    if result.stalled:
        temp_path.unlink(missing_ok=True)
        logs.append("[兼容] 转码连续 5 分钟没有进度，保留原视频")
        return video_path
    if not result.success or not temp_path.exists() or temp_path.stat().st_size <= 10000:
        temp_path.unlink(missing_ok=True)
        logs.append(f"[兼容] 转码失败，保留原视频: {result.stderr[-200:]}")
        return video_path

    temp_path.replace(video_path)
    logs.append("[兼容] 已生成 H.264 播放版本")
    return video_path


def _probe_video_codec(video_path: Path) -> str | None:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name",
                "-of",
                "default=nw=1:nk=1",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return (result.stdout or "").strip().lower() or None


def _is_valid_video_file(video_path: Path) -> bool:
    codec = _probe_video_codec(video_path)
    if not codec:
        return False
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=format_name,duration",
                "-of",
                "json",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception:
        return False
    if result.returncode != 0:
        return False
    try:
        payload = json.loads(result.stdout or "{}")
        format_name = str(payload.get("format", {}).get("format_name") or "")
        duration = float(payload.get("format", {}).get("duration") or 0)
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    return duration > 0 and not format_name.startswith("jpeg_pipe")

def _extract_douyin_video_id(url: str) -> Optional[str]:
    import httpx
    
    patterns = [
        r'/video/(\d+)',
        r'modal_id=(\d+)',
        r'/note/(\d+)',
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    
    try:
        with httpx.Client(follow_redirects=True, timeout=15, trust_env=False) as client:
            resp = client.get(url, headers={
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15',
                'Accept-Encoding': 'gzip, deflate',
            })
            final_url = str(resp.url)
            for p in patterns:
                m = re.search(p, final_url)
                if m:
                    return m.group(1)
    except Exception:
        pass
    
    return None


def _extract_douyin_video_id_via_browser(url: str) -> Optional[str]:
    """Expand a share link in the same browser provider used for downloads.

    Short-link redirects can be gated differently from the work page API.  A
    direct HTTP expansion is still the inexpensive first path, but failure
    must not prevent the browser provider from handling an otherwise valid
    user-supplied share link.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    browser_binary = browser_executable()
    if not browser_binary:
        return None

    browser = None
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                executable_path=browser_binary,
                **direct_browser_launch_options(
                    "--autoplay-policy=no-user-gesture-required",
                    "--disable-blink-features=AutomationControlled",
                ),
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
                locale="zh-CN",
            )
            page = context.new_page()
            page.goto(url, wait_until="commit", timeout=15_000)
            for _ in range(20):
                for pattern in (r"/video/(\d+)", r"/note/(\d+)", r"modal_id=(\d+)"):
                    match = re.search(pattern, page.url)
                    if match:
                        return match.group(1)
                page.wait_for_timeout(250)
    except Exception:
        return None
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
    return None


def _download_douyin_via_public_metadata(
    video_id: str,
    output_dir: Path,
    logs: list[str],
    progress_callback: ProgressCallback | None,
    cancel_check: CancelCheck | None,
    log_callback: DownloadLogCallback | None = None,
) -> DownloadResult:
    """Try the unauthenticated public work metadata before launching Chromium.

    This is intentionally a small, best-effort resolver: it neither fabricates
    anti-bot signatures nor sends login cookies outside the browser session.
    If the endpoint declines a work, the authenticated browser provider below
    remains the compatibility path.
    """
    if cancel_check and cancel_check():
        return DownloadResult(success=False, logs=logs, error="下载已取消")
    _append_download_log(logs, "[地址解析] 正在请求直连作品信息...", log_callback)
    comment_payload: object = {}
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=15,
            trust_env=False,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://www.douyin.com/",
            },
        ) as client:
            response = client.get(
                "https://www.iesdouyin.com/web/api/v2/aweme/iteminfo/",
                params={"item_ids": video_id},
            )
            if response.status_code == 200:
                try:
                    comment_response = client.get(
                        "https://www.iesdouyin.com/web/api/v2/comment/list/",
                        params={"aweme_id": video_id, "cursor": 0, "count": 20},
                        timeout=5,
                    )
                    if comment_response.status_code == 200:
                        comment_payload = comment_response.json()
                except (httpx.HTTPError, ValueError):
                    comment_payload = {}
        if response.status_code != 200:
            return DownloadResult(success=False, logs=logs, error=f"直连元数据请求返回 HTTP {response.status_code}")
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return DownloadResult(success=False, logs=logs, error=f"直连元数据请求失败: {exc}")

    quality = _load_douyin_video_quality()
    variant = _select_douyin_video_variant(payload, video_id, quality)
    if not variant:
        return DownloadResult(success=False, logs=logs, error="直连元数据未提供可用视频地址")

    media_url, bitrate, gear_name = variant
    aweme = _find_douyin_aweme(payload, video_id) or {}
    comments, comments_complete = douyin_comments_from_payload(comment_payload)
    source_context = source_context_from_douyin_aweme(
        aweme,
        comments=comments,
        comments_complete=comments_complete,
    )
    title = str(aweme.get("desc") or aweme.get("title") or "").strip()
    detail = f"{_douyin_quality_label(quality)}档位"
    if bitrate:
        detail += f" · {gear_name or bitrate // 1000}（约 {bitrate // 1000}kbps）"
    _append_download_log(logs, f"[地址解析] 直连已获取媒体地址（{detail}）", log_callback)
    _report_phase(progress_callback, "resolving_media", "已获取抖音媒体地址")

    target = output_dir / f"{video_id}.direct.part"
    started = time.monotonic()
    _append_download_log(logs, "[媒体传输] 正在下载直连视频流...", log_callback)
    _report_phase(progress_callback, "transfer", "正在传输视频")
    transfer = download_http_media(
        media_url,
        target,
        headers={"referer": "https://www.douyin.com/", "accept": "*/*", "accept-encoding": "identity"},
        progress_callback=lambda received, total: _report_transfer(
            progress_callback,
            received,
            total,
            started_at=started,
            detail="正在传输视频",
        ),
        cancel_check=cancel_check,
    )
    if not transfer.success:
        error = _media_transfer_error(transfer)
        _append_download_log(logs, f"[媒体传输] 直连视频流失败: {error}", log_callback)
        return DownloadResult(success=False, logs=logs, error=error)
    _report_phase(progress_callback, "validating", "正在校验视频流")
    if not _is_valid_video_file(target):
        return DownloadResult(success=False, logs=logs, error="直连媒体校验失败，将尝试浏览器兼容下载")

    final_path = output_dir / f"{video_id}.mp4"
    target.replace(final_path)
    _report_phase(progress_callback, "caching", "正在整理视频缓存")
    final_path = _compress_video_for_storage(
        final_path,
        logs,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )
    if cancel_check and cancel_check():
        return DownloadResult(success=False, logs=logs, error="下载已取消")
    _append_download_log(logs, f"[完成] 视频已保存: {final_path.name} ({final_path.stat().st_size // 1024 // 1024}MB)", log_callback)
    return DownloadResult(
        success=True,
        video_path=final_path,
        video_info={
            "id": video_id,
            "title": title,
            "platform": "douyin",
            "provider": "direct",
            "uploader": source_context.get("author") or "",
            "upload_date": source_context.get("published_at") or "",
            "source_context": source_context,
        },
        logs=logs,
    )


def _trigger_douyin_playback(page: object) -> None:
    """Ask the page player to issue media requests without awaiting playback.

    A normal browser returns the promise from ``HTMLMediaElement.play()`` only
    after playback can begin.  In a headless player that promise can remain
    pending indefinitely while the request listeners have already captured
    the signed video and audio URLs.  Capturing must therefore be independent
    from playback readiness.
    """
    try:
        page.evaluate(
            """() => {
                for (const video of document.querySelectorAll('video')) {
                    video.muted = true;
                    video.setAttribute('playsinline', '');
                    const playAttempt = video.play();
                    if (playAttempt && typeof playAttempt.catch === 'function') {
                        playAttempt.catch(() => {});
                    }
                }
            }"""
        )
    except Exception:
        # Missing/late player elements are normal while the work page is
        # hydrating. The bounded capture loop will try again.
        return


def _download_douyin_via_browser(
    video_id: str,
    output_dir: Path,
    logs: list,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
    log_callback: DownloadLogCallback | None = None,
) -> DownloadResult:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return DownloadResult(success=False, logs=logs, error="需要安装 Playwright: pip install playwright && playwright install chromium")
    
    cookies = _load_cookies_for_playwright()
    browser_binary = browser_executable()
    video_url = None
    audio_url = None
    video_headers = {}
    audio_headers = {}
    selected_video_bitrate: int | None = None
    selected_quality = _load_douyin_video_quality()
    video_completed = False
    audio_completed = False
    title = ""
    page_url = ""
    page_signals = ""
    aweme_detail: dict[str, object] = {}
    comment_sample: list[dict[str, object]] = []
    comments_complete = False
    browser_error = ""
    video_transfer_error = ""
    done = threading.Event()
    watchdog_cancelled = threading.Event()
    last_activity_at = time.monotonic()

    def should_cancel() -> bool:
        return watchdog_cancelled.is_set() or bool(cancel_check and cancel_check())

    def report_active_progress(progress: DownloadProgress) -> None:
        nonlocal last_activity_at
        last_activity_at = time.monotonic()
        _report(progress_callback, progress)
    
    def capture_video(
        url: str,
        headers: dict[str, str],
        source: str,
        *,
        bitrate: int | None = None,
        gear_name: str = "",
    ) -> None:
        nonlocal video_url, video_headers, selected_video_bitrate
        replace = bitrate is not None and _is_preferred_douyin_bitrate(
            bitrate,
            selected_video_bitrate,
            selected_quality,
        )
        if (not video_url or replace) and url.startswith(("https://", "http://")):
            video_url = url
            video_headers = headers
            selected_video_bitrate = bitrate
            quality = f"，{gear_name or bitrate // 1000}（约 {bitrate // 1000}kbps）" if bitrate else ""
            _append_download_log(logs, f"[浏览器] 捕获视频流（{source}{quality}）", log_callback)

    def capture_audio(url: str, headers: dict[str, str], source: str) -> None:
        nonlocal audio_url, audio_headers
        if not audio_url and url.startswith(("https://", "http://")):
            audio_url = url
            audio_headers = headers
            _append_download_log(logs, f"[浏览器] 捕获音频流（{source}）", log_callback)

    def on_request(request):
        nonlocal video_url, audio_url, video_headers, audio_headers
        url = request.url
        request_headers = dict(request.headers)
        if _looks_like_douyin_audio_url(url):
            capture_audio(url, request_headers, "网络请求")
        elif _looks_like_douyin_video_url(url) or request.resource_type == "media":
            capture_video(url, request_headers, "网络请求")

    def on_response(response) -> None:
        nonlocal aweme_detail, comment_sample, comments_complete
        try:
            if _is_douyin_work_payload_url(response.url):
                payload = response.json()
                matched_aweme = _find_douyin_aweme(payload, video_id)
                if matched_aweme:
                    aweme_detail = matched_aweme
                variant = _select_douyin_video_variant(payload, video_id, selected_quality)
                if variant:
                    variant_url, bitrate, gear_name = variant
                    capture_video(
                        variant_url,
                        {},
                        f"作品{_douyin_quality_label(selected_quality)}档位",
                        bitrate=bitrate,
                        gear_name=gear_name,
                    )
                return
            if _is_douyin_comment_payload_url(response.url):
                comments, complete = douyin_comments_from_payload(response.json())
                known_ids = {str(item.get("comment_id") or "") for item in comment_sample}
                comment_sample.extend(
                    item
                    for item in comments
                    if str(item.get("comment_id") or "") not in known_ids
                )
                comment_sample = comment_sample[:24]
                comments_complete = comments_complete or complete
                return
            content_type = response.headers.get("content-type", "").lower()
            request = response.request
            if content_type.startswith("video/"):
                capture_video(response.url, dict(request.headers), "视频响应")
            elif content_type.startswith("audio/"):
                capture_audio(response.url, dict(request.headers), "音频响应")
        except Exception:
            # Response inspection is an additional capture signal; failures
            # must not interrupt page playback or the primary request listener.
            return
    
    def _run_browser():
        nonlocal title, page_url, page_signals, browser_error, video_completed, audio_completed, video_transfer_error
        try:
            with sync_playwright() as p:
                if not browser_binary:
                    browser_error = "未找到浏览器组件。请在设置 > 设备准备中下载 Chromium，或安装 Google Chrome 后重试。"
                    return
                _append_download_log(logs, "[浏览器] 正在启动 Chromium...", log_callback)
                browser = p.chromium.launch(
                    headless=True,
                    executable_path=browser_binary,
                    **direct_browser_launch_options(
                        "--autoplay-policy=no-user-gesture-required",
                        "--disable-blink-features=AutomationControlled",
                    ),
                )
                context = browser.new_context(
                    user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                    viewport={"width": 1440, "height": 900},
                    locale="zh-CN",
                )
                context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
                )
                if cookies:
                    context.add_cookies(cookies)
                    _append_download_log(logs, "[浏览器] 已加载本机抖音登录态", log_callback)
                else:
                    _append_download_log(logs, "[浏览器] 未读取到登录态，将以匿名页面继续", log_callback)
                page = context.new_page()
                page.on('request', on_request)
                page.on('response', on_response)

                target_url = f'https://www.douyin.com/video/{video_id}'

                def capture_media_requests(*, refresh: bool = False) -> None:
                    nonlocal video_url, audio_url, video_headers, audio_headers, selected_video_bitrate
                    if refresh:
                        video_url = None
                        audio_url = None
                        video_headers = {}
                        audio_headers = {}
                        selected_video_bitrate = None
                        _append_download_log(logs, "[浏览器] CDN 拒绝旧签名，刷新页面获取新的媒体请求（2/2）...", log_callback)
                        page.reload(wait_until='commit', timeout=15000)

                    # Headless Chromium does not always start Douyin playback
                    # by itself. Playback is a request trigger only; its
                    # promise must not gate media capture or transmission.
                    try:
                        # ``commit`` deliberately keeps navigation quick, but
                        # the player is only mounted after the document is
                        # hydrated.  Give that stage a bounded chance to
                        # finish before treating the missing media request as
                        # a download failure.
                        page.wait_for_load_state("domcontentloaded", timeout=5000)
                    except Exception:
                        pass

                    capture_deadline = time.monotonic() + DOUYIN_MEDIA_CAPTURE_WAIT_SECONDS
                    while time.monotonic() < capture_deadline:
                        if should_cancel():
                            return
                        if video_url:
                            # A detail response can expose the video URL a
                            # little before the player asks for its companion
                            # audio stream. Give that request a small bounded
                            # window without delaying the usable video path.
                            _trigger_douyin_playback(page)
                            audio_deadline = min(
                                capture_deadline,
                                time.monotonic() + DOUYIN_AUDIO_CAPTURE_SETTLE_SECONDS,
                            )
                            while not audio_url and time.monotonic() < audio_deadline:
                                if should_cancel():
                                    return
                                page.wait_for_timeout(100)
                            if not audio_url:
                                _append_download_log(logs, "[浏览器] 未在等待窗口捕获音频流，将先保存可播放视频", log_callback)
                            return
                        _trigger_douyin_playback(page)
                        page.wait_for_timeout(250)

                    # Some player versions load media through a worker where
                    # Playwright labels the request as fetch. Performance
                    # entries retain the final signed URL and offer a safe
                    # last capture signal without depending on CDN host names.
                    try:
                        resource_urls = page.evaluate(
                            "performance.getEntriesByType('resource').map(entry => entry.name)"
                        )
                        for resource_url in reversed(resource_urls):
                            if _looks_like_douyin_video_url(resource_url):
                                capture_video(resource_url, {}, "性能资源")
                                break
                    except Exception:
                        pass

                _append_download_log(logs, "[浏览器] 打开页面...", log_callback)
                _report_phase(report_active_progress, "resolving_media", "正在打开抖音页面")
                navigation_started = time.monotonic()
                # Douyin commonly defers DOMContentLoaded with analytics and
                # challenge resources.  We only need the first document in
                # order to observe the video request, so waiting for the full
                # DOM can waste the entire 30-second timeout.
                page.goto(target_url, wait_until='commit', timeout=15000)
                _append_download_log(logs, "[浏览器] 页面首帧已打开，等待播放器发起媒体请求...", log_callback)
                capture_media_requests()
                _append_download_log(logs, f"[浏览器] 媒体请求捕获耗时 {time.monotonic() - navigation_started:.1f}s", log_callback)
                _report_phase(report_active_progress, "resolving_media", "正在捕获媒体地址")
                try:
                    page.mouse.wheel(0, 1_600)
                    page.wait_for_timeout(500)
                    page.mouse.wheel(0, 1_600)
                    page.wait_for_timeout(500)
                except Exception:
                    pass

                try:
                    page_url = page.url
                    title = (page.title() or "").replace(" - 抖音", "").strip()
                    page_signals = page.locator("body").inner_text(timeout=2000)[:2000].lower()
                except Exception:
                    pass

                # Keep incomplete browser transfers visibly separate from a
                # playable artifact.  The browser-context transfer resumes
                # this file with bounded Range requests on retry.
                video_path = output_dir / f"{video_id}_video.mp4.part"
                for attempt in range(2):
                    if should_cancel():
                        return
                    if not video_url:
                        break
                    _append_download_log(logs, "[媒体传输] 正在下载视频流...", log_callback)
                    transfer_started = time.monotonic()
                    _report_phase(report_active_progress, "transfer", "正在传输视频")
                    transfer = download_browser_context_media(
                        context.request,
                        video_url,
                        video_path,
                        headers=_browser_media_headers(video_headers),
                        progress_callback=lambda received, total: _report_transfer(
                            report_active_progress,
                            received,
                            total,
                            started_at=transfer_started,
                            detail="正在传输视频",
                        ),
                        cancel_check=should_cancel,
                    )
                    if transfer.success:
                        video_completed = True
                        _report_phase(report_active_progress, "validating", "正在校验视频流")
                        _append_download_log(
                            logs,
                            f"[媒体传输] 视频: {transfer.downloaded_bytes // 1024 // 1024}MB，"
                            f"{transfer.elapsed_seconds:.1f}s，"
                            f"{transfer.average_bytes_per_second / 1024 / 1024:.2f}MB/s",
                            log_callback,
                        )
                        break
                    if _needs_douyin_media_refresh(transfer.status_code) and attempt == 0:
                        capture_media_requests(refresh=True)
                        continue
                    video_transfer_error = _media_transfer_error(transfer)
                    _append_download_log(logs, f"[媒体传输] 视频下载失败: {video_transfer_error}", log_callback)
                    break

                audio_path = output_dir / f"{video_id}_audio.mp4.part"
                for attempt in range(2):
                    if should_cancel():
                        return
                    if not audio_url:
                        break
                    _append_download_log(logs, "[媒体传输] 正在下载音频流...", log_callback)
                    transfer_started = time.monotonic()
                    _report_phase(report_active_progress, "transfer", "正在传输音频")
                    transfer = download_browser_context_media(
                        context.request,
                        audio_url,
                        audio_path,
                        headers=_browser_media_headers(audio_headers),
                        progress_callback=lambda received, total: _report_transfer(
                            report_active_progress,
                            received,
                            total,
                            started_at=transfer_started,
                            detail="正在传输音频",
                        ),
                        cancel_check=should_cancel,
                    )
                    if transfer.success:
                        audio_completed = True
                        _report_phase(report_active_progress, "validating", "正在校验音频流")
                        _append_download_log(
                            logs,
                            f"[媒体传输] 音频: {transfer.downloaded_bytes // 1024 // 1024}MB，"
                            f"{transfer.elapsed_seconds:.1f}s，"
                            f"{transfer.average_bytes_per_second / 1024 / 1024:.2f}MB/s",
                            log_callback,
                        )
                        break
                    if _needs_douyin_media_refresh(transfer.status_code) and attempt == 0:
                        capture_media_requests(refresh=True)
                        continue
                    _append_download_log(logs, f"[媒体传输] 音频下载失败: {_media_transfer_error(transfer)}", log_callback)
                    break

                browser.close()
        except Exception as exc:
            browser_error = str(exc)
            _append_download_log(logs, f"[浏览器] 访问失败: {browser_error}", log_callback)
        finally:
            done.set()
    
    try:
        thread = threading.Thread(target=_run_browser, daemon=True)
        thread.start()
        while not done.is_set():
            thread.join(timeout=0.2)
            if cancel_check and cancel_check():
                # The browser worker and the stream downloader both observe
                # this callback.  Return promptly while leaving any partial
                # media file intact for Range resumption on retry.
                watchdog_cancelled.set()
                thread.join(timeout=2)
                return DownloadResult(success=False, logs=logs, error="下载已取消")

            timeout_error = _activity_timeout_error(
                now=time.monotonic(),
                last_activity_at=last_activity_at,
                stall_seconds=DOUYIN_BROWSER_WATCHDOG_SECONDS,
                operation="浏览器下载",
            )
            if timeout_error:
                watchdog_cancelled.set()
                thread.join(timeout=2)
                return DownloadResult(success=False, logs=logs, error=timeout_error)

        if cancel_check and cancel_check():
            return DownloadResult(success=False, logs=logs, error="下载已取消")

        if browser_error:
            return DownloadResult(success=False, logs=logs, error=f"浏览器下载失败: {browser_error}")
        
        video_path = output_dir / f"{video_id}_video.mp4.part"
        audio_path = output_dir / f"{video_id}_audio.mp4.part"
        final_path = output_dir / f"{video_id}.mp4"
        
        if video_transfer_error:
            return DownloadResult(success=False, logs=logs, error=video_transfer_error)

        if not video_completed or not video_path.exists():
            error = _browser_capture_failure_message(page_url, page_signals, bool(cookies))
            _append_download_log(logs, f"[浏览器] {error}", log_callback)
            return DownloadResult(success=False, logs=logs, error=error)
        
        # Merge video + audio with ffmpeg
        if audio_completed and audio_path.exists():
            _append_download_log(logs, "[合并] 正在合并音视频...", log_callback)
            _report_phase(report_active_progress, "merging", "正在合并音视频")
            merge_cmd = [
                resolve_tool("ffmpeg") or "ffmpeg", "-y",
                "-i", str(video_path),
                "-i", str(audio_path),
                "-c:v", "copy", "-c:a", "copy",
                str(final_path)
            ]
            merge_duration = probe_media_duration(video_path)

            def report_merge_progress(progress: FfmpegProgress) -> None:
                detail = "正在合并音视频"
                if progress.percent is not None:
                    detail += f"（{progress.percent:.0f}%）"
                _report_phase(report_active_progress, "merging", detail)

            result = run_ffmpeg(
                merge_cmd,
                output_path=final_path,
                duration_seconds=merge_duration,
                progress_callback=report_merge_progress,
                cancel_check=should_cancel,
            )
            if result.cancelled:
                return DownloadResult(success=False, logs=logs, error="下载已取消")
            if result.stalled:
                _append_download_log(logs, "[合并] ffmpeg 连续 5 分钟没有进度，保留媒体分片", log_callback)
                return DownloadResult(success=False, logs=logs, error="音视频合并停滞")
            if not result.success or not final_path.exists() or final_path.stat().st_size <= 10000:
                _append_download_log(logs, f"[合并] ffmpeg 合并失败: {result.stderr[:200]}", log_callback)
                return DownloadResult(success=False, logs=logs, error="音视频合并失败")
            # Only discard resumable media fragments after the merged output
            # has been proven usable.  A non-zero FFmpeg exit used to delete
            # both inputs and made a retry download everything again.
            video_path.unlink(missing_ok=True)
            audio_path.unlink(missing_ok=True)
            _append_download_log(logs, "[合并] 完成", log_callback)
        else:
            _append_download_log(logs, "[合并] 未捕获音频流，仅保存视频", log_callback)
            video_path.rename(final_path)
        
        if final_path.stat().st_size < 10000:
            final_path.unlink(missing_ok=True)
            return DownloadResult(success=False, logs=logs, error="下载文件过小，视频可能已失效")
        
        _report_phase(report_active_progress, "caching", "正在整理视频缓存")
        final_path = _compress_video_for_storage(
            final_path,
            logs,
            progress_callback=report_active_progress,
            cancel_check=should_cancel,
        )
        if should_cancel():
            return DownloadResult(success=False, logs=logs, error="下载已取消")
        size_mb = final_path.stat().st_size // 1024 // 1024
        _append_download_log(logs, f"[完成] 视频已保存: {final_path.name} ({size_mb}MB)", log_callback)
        if aweme_detail:
            source_context = source_context_from_douyin_aweme(
                aweme_detail,
                comments=comment_sample,
                comments_complete=comments_complete,
            )
        elif comment_sample:
            source_context = build_source_context(
                provider="douyin",
                comments=comment_sample,
                comments_complete=comments_complete,
            )
        else:
            source_context = {}
        return DownloadResult(
            success=True,
            video_path=final_path,
            video_info={
                "id": video_id,
                "title": title,
                "platform": "douyin",
                "uploader": source_context.get("author") or "",
                "upload_date": source_context.get("published_at") or "",
                "source_context": source_context,
            },
            logs=logs
        )
    except Exception as e:
        return DownloadResult(success=False, logs=logs, error=f"浏览器下载异常: {str(e)}")


def _browser_capture_failure_message(page_url: str, page_signals: str, has_cookies: bool) -> str:
    page_state = f"{page_url}\n{page_signals}".lower()
    auth_markers = ("login", "captcha", "verify", "登录", "安全验证", "滑块", "访问频繁")
    if any(marker in page_state for marker in auth_markers):
        return "浏览器被重定向到登录或安全验证页，请更新 Cookie 后重试"
    if not has_cookies:
        return "浏览器未加载抖音 Cookie，且页面未发起媒体请求"
    return "浏览器已打开抖音页面但未捕获媒体请求（可能是无头播放受限、页面风控或页面改版；并非已确认 Cookie 失效）"


def _compress_video_for_storage(
    video_path: Path,
    logs: list[str],
    *,
    progress_callback: ProgressCallback | None = None,
    cancel_check: CancelCheck | None = None,
) -> Path:
    if not settings.compress_downloaded_video:
        return video_path

    if not video_path.exists() or video_path.stat().st_size <= 10000:
        return video_path

    original_size = video_path.stat().st_size
    temp_path = video_path.with_name(f"{video_path.stem}_compact_tmp.mp4")
    final_path = video_path.with_name(f"{video_path.stem}_compact.mp4")
    temp_path.unlink(missing_ok=True)

    cmd = [
        resolve_tool("ffmpeg") or "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-vf",
        (
            f"scale=-2:min({settings.storage_video_max_height}\\,ih),"
            "scale=trunc(iw/2)*2:trunc(ih/2)*2"
        ),
        "-c:v",
        "libx264",
        "-preset",
        settings.storage_video_preset,
        "-crf",
        str(settings.storage_video_crf),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        "-movflags",
        "+faststart",
        str(temp_path),
    ]

    logs.append(
        f"[压缩] 降低视频画质到约 {settings.storage_video_max_height}p，音频保留原码流..."
    )
    def report_compression_progress(progress: FfmpegProgress) -> None:
        detail = "正在压缩视频缓存"
        if progress.percent is not None:
            detail += f"（{progress.percent:.0f}%）"
        _report_phase(progress_callback, "caching", detail)

    try:
        result = run_ffmpeg(
            cmd,
            output_path=temp_path,
            duration_seconds=probe_media_duration(video_path),
            progress_callback=report_compression_progress,
            cancel_check=cancel_check,
        )
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        logs.append(f"[压缩] ffmpeg 异常，保留原视频: {exc}")
        return video_path
    if result.cancelled:
        temp_path.unlink(missing_ok=True)
        logs.append("[压缩] 已取消，保留原视频")
        return video_path
    if result.stalled:
        temp_path.unlink(missing_ok=True)
        logs.append("[压缩] ffmpeg 连续 5 分钟没有进度，保留原视频")
        return video_path

    if not result.success or not temp_path.exists() or temp_path.stat().st_size <= 10000:
        temp_path.unlink(missing_ok=True)
        logs.append(f"[压缩] 失败，保留原视频: {result.stderr[-200:]}")
        return video_path

    compressed_size = temp_path.stat().st_size
    if compressed_size >= original_size:
        temp_path.unlink(missing_ok=True)
        logs.append("[压缩] 原视频已足够小，保留原文件")
        return video_path

    final_path.unlink(missing_ok=True)
    temp_path.replace(final_path)
    if final_path != video_path:
        video_path.unlink(missing_ok=True)

    saved_mb = (original_size - compressed_size) / 1024 / 1024
    logs.append(f"[压缩] 完成，节省约 {saved_mb:.1f}MB")
    return final_path

def _load_cookies_for_playwright() -> list:
    cookie_file = settings.data_dir / "douyin_cookies.txt"
    cookies: list[dict[str, str | bool]] = []
    if cookie_file.exists():
        try:
            lines = cookie_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        for line in lines:
            # Netscape cookies can encode HttpOnly rows as #HttpOnly_.  They
            # are still real cookies and must not be mistaken for comments.
            if not line.strip() or (line.startswith("#") and not line.startswith("#HttpOnly_")):
                continue
            parts = line.removeprefix("#HttpOnly_").split("\t")
            if len(parts) >= 7 and parts[0] and parts[5] and parts[6]:
                cookies.append({
                    "name": parts[5],
                    "value": parts[6],
                    "domain": parts[0],
                    "path": parts[2] or "/",
                    "secure": parts[3].upper() == "TRUE",
                })

    return cookies

def _load_info_json(output_dir: Path, video_id: str) -> dict:
    info_file = output_dir / f"{video_id}.info.json"
    if info_file.exists():
        return json.loads(info_file.read_text())
    return {}

def get_video_info(url: str, platform: str = "") -> dict:
    if platform == "bilibili":
        cmd = [resolve_tool("yt-dlp") or "yt-dlp", "--dump-json", "--no-playlist", url]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                env=direct_network_environment(),
            )
            if result.returncode == 0:
                return json.loads(result.stdout)
        except Exception:
            pass
    return {}

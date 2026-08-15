import os
import time
import multiprocessing as mp
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from collections.abc import Callable
from queue import Empty
from threading import BoundedSemaphore
from typing import Any, Optional

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from config import settings
from services.media_tools import resolve_tool
from services.ffmpeg_runner import FfmpegProgress, probe_media_duration, run_ffmpeg
from services.runtime_components import (
    MLX_WHISPER_REPOS,
    faster_whisper_cache_dir,
    is_model_available,
    mlx_whisper_model_dir,
    model_storage_path,
    preferred_asr_backend,
)
from services.text_normalizer import normalize_transcript_segments, normalize_transcript_text


logger = logging.getLogger(__name__)

_model = None
_models: dict[str, Any] = {}
# ASR is the one CPU/GPU-heavy stage in the desktop media pipeline.  Keep it
# serial even when a legacy environment file still contains a higher value;
# downloads and model summaries can proceed independently in other workers.
_asr_semaphore = BoundedSemaphore(1)

ASR_BACKENDS = {"auto", "mlx", "faster_whisper"}
@dataclass
class AudioExtractionResult:
    success: bool
    error: str = ""
    stderr: str = ""
    elapsed_seconds: float = 0.0
    cancelled: bool = False
    stalled: bool = False


@dataclass
class TranscriptionResult:
    success: bool
    transcript: str = ""
    segments: list[dict] = field(default_factory=list)
    error: str = ""
    timings: dict[str, float] = field(default_factory=dict)
    backend: str = ""


def get_model(model_name: str | None = None):
    global _model
    selected_model = model_name or settings.whisper_model
    if not is_model_available(selected_model, "faster_whisper"):
        raise RuntimeError(
            f"Faster-Whisper 模型 {selected_model} 尚未下载；请在设置 > 本机处理 > 模型存储中下载当前模型。"
        )
    if selected_model not in _models:
        # faster-whisper pulls in the largest local inference stack.  Import it
        # only when a task actually reaches transcription, not while the
        # desktop server is merely starting or listing the library.
        from faster_whisper import WhisperModel

        direct_model = model_storage_path(selected_model, "faster_whisper")
        model_path_or_name = str(direct_model) if (
            (direct_model / "config.json").is_file()
            and (direct_model / "model.bin").is_file()
        ) else selected_model
        _models[selected_model] = WhisperModel(
            model_path_or_name,
            device=settings.whisper_device,
            compute_type="int8",
            download_root=str(faster_whisper_cache_dir()),
        )
    _model = _models[selected_model]
    return _model


def extract_audio_with_details(
    video_path: Path,
    audio_path: Path,
    *,
    progress_callback: Callable[[float], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> AudioExtractionResult:
    start = time.perf_counter()
    cmd = [
        resolve_tool("ffmpeg") or "ffmpeg", "-i", str(video_path),
        "-vn", "-acodec", "pcm_s16le",
        "-ar", "16000", "-ac", "1",
        "-y", str(audio_path)
    ]
    duration_seconds = probe_media_duration(video_path)

    def report_progress(progress: FfmpegProgress) -> None:
        if progress_callback and progress.percent is not None:
            progress_callback(progress.percent)

    try:
        result = run_ffmpeg(
            cmd,
            output_path=audio_path,
            duration_seconds=duration_seconds,
            progress_callback=report_progress,
            cancel_check=cancel_check,
        )
    except Exception as exc:
        return AudioExtractionResult(
            success=False,
            error=f"ffmpeg 音频提取异常: {exc}",
            elapsed_seconds=time.perf_counter() - start,
        )
    if result.cancelled:
        return AudioExtractionResult(
            success=False,
            error="音频提取已取消",
            stderr=result.stderr,
            elapsed_seconds=result.elapsed_seconds,
            cancelled=True,
        )
    if result.stalled:
        return AudioExtractionResult(
            success=False,
            error="ffmpeg 音频提取连续 5 分钟没有进度或输出文件变化",
            stderr=result.stderr,
            elapsed_seconds=result.elapsed_seconds,
            stalled=True,
        )

    stderr = result.stderr
    success = result.success and audio_path.exists()
    error = "" if success else f"ffmpeg 音频提取失败，退出码 {result.returncode}"
    return AudioExtractionResult(
        success=success,
        error=error,
        stderr=stderr[-2000:],
        elapsed_seconds=result.elapsed_seconds,
    )


def extract_audio(video_path: Path, audio_path: Path) -> bool:
    return extract_audio_with_details(video_path, audio_path).success


def transcribe_with_details(
    audio_path: Path,
    model_name: str | None = None,
    progress_callback: Callable[[float], None] | None = None,
    *,
    backend: str | None = None,
    beam_size: int | None = None,
    vad_filter: bool | None = None,
    fallback_enabled: bool | None = None,
) -> TranscriptionResult:
    with _asr_semaphore:
        selected_backend = _resolve_backend(backend)
        if selected_backend == "mlx":
            result = _transcribe_mlx(
                audio_path,
                model_name=model_name,
                progress_callback=progress_callback,
            )
            if result.success or not (fallback_enabled if fallback_enabled is not None else settings.asr_fallback_enabled):
                return result
            fallback = _transcribe_faster_whisper(
                audio_path,
                model_name=model_name,
                progress_callback=progress_callback,
                beam_size=beam_size,
                vad_filter=vad_filter,
            )
            fallback.error = fallback.error or result.error
            fallback.timings["mlx_error"] = 0.0
            return fallback

        return _transcribe_faster_whisper(
            audio_path,
            model_name=model_name,
            progress_callback=progress_callback,
            beam_size=beam_size,
            vad_filter=vad_filter,
        )


def _resolve_backend(backend: str | None) -> str:
    # The settings API only exposes the native runtime.  Normalise a stale
    # saved cross-platform selection too, rather than letting it re-create a
    # second model cache behind the user's back.
    return preferred_asr_backend()


def _transcribe_faster_whisper(
    audio_path: Path,
    model_name: str | None = None,
    progress_callback: Callable[[float], None] | None = None,
    *,
    beam_size: int | None = None,
    vad_filter: bool | None = None,
) -> TranscriptionResult:
    timings: dict[str, float] = {}

    def report(percent: float) -> None:
        if progress_callback:
            progress_callback(percent)

    try:
        model_start = time.perf_counter()
        report(5)
        model = get_model(model_name)
        timings["whisper_model_load"] = time.perf_counter() - model_start
        report(12)

        decode_start = time.perf_counter()
        segments, info = model.transcribe(
            str(audio_path),
            language="zh",
            beam_size=max(1, int(beam_size or settings.asr_beam_size or 1)),
            vad_filter=settings.asr_vad_filter if vad_filter is None else bool(vad_filter),
            condition_on_previous_text=False,
        )
        text_parts = []
        transcript_segments = []
        duration = max(float(getattr(info, "duration", 0.0) or 0.0), 0.0)
        for position, segment in enumerate(segments):
            text = normalize_transcript_text(segment.text or "")
            if not text:
                continue
            text_parts.append(text)
            transcript_segments.append({
                "start_seconds": float(segment.start or 0.0),
                "end_seconds": float(segment.end or 0.0),
                "text": text,
                "position": position,
            })
            if duration:
                report(12 + min(float(segment.end or 0.0) / duration, 1.0) * 86)
        timings["whisper_decode"] = time.perf_counter() - decode_start

        transcript = normalize_transcript_text("\n".join(text_parts))
        if not transcript:
            return TranscriptionResult(
                success=False,
                error="Whisper 未返回转写文本",
                timings=timings,
                backend="faster_whisper",
            )

        report(100)
        return TranscriptionResult(
            success=True,
            transcript=transcript,
            segments=transcript_segments,
            timings=timings,
            backend="faster_whisper",
        )
    except Exception as exc:
        return TranscriptionResult(
            success=False,
            error=f"Whisper 转写异常: {exc}",
            timings=timings,
            backend="faster_whisper",
        )


def _transcribe_mlx(
    audio_path: Path,
    model_name: str | None = None,
    progress_callback: Callable[[float], None] | None = None,
) -> TranscriptionResult:
    """Run MLX in a disposable child process, never inside the API worker."""
    timings: dict[str, float] = {}

    def report(percent: float) -> None:
        if progress_callback:
            progress_callback(percent)

    result_queue = None
    worker = None
    try:
        started_at = time.perf_counter()
        context = mp.get_context("spawn")
        result_queue = context.Queue(maxsize=1)
        worker = context.Process(
            target=_mlx_transcription_worker,
            args=(str(audio_path), model_name, result_queue),
            name="knowledgehub-mlx-transcribe",
        )
        worker.start()
        report(8)
        while worker.is_alive():
            worker.join(timeout=0.25)
        worker.join()
        timings["mlx_worker"] = time.perf_counter() - started_at
        if worker.exitcode not in (0, None):
            return TranscriptionResult(
                success=False,
                error=f"MLX 转写进程异常退出（退出码 {worker.exitcode}）",
                timings=timings,
                backend="mlx",
            )
        try:
            payload = result_queue.get(timeout=1.0)
        except Empty:
            return TranscriptionResult(
                success=False,
                error="MLX 转写进程未返回结果",
                timings=timings,
                backend="mlx",
            )
        result = TranscriptionResult(**payload)
        result.timings = {**timings, **result.timings}
        report(100 if result.success else 95)
        return result
    except Exception as exc:
        return TranscriptionResult(
            success=False,
            error=f"MLX 转写进程启动失败: {exc}",
            timings=timings,
            backend="mlx",
        )
    finally:
        if worker and worker.is_alive():
            worker.terminate()
            worker.join(timeout=1.0)
        if result_queue is not None:
            result_queue.close()
            result_queue.join_thread()


def _mlx_transcription_worker(audio_path: str, model_name: str | None, result_queue) -> None:
    """Child-process entry point; all MLX imports remain outside the API process."""
    result_queue.put(asdict(_transcribe_mlx_inline(Path(audio_path), model_name)))


def _transcribe_mlx_inline(
    audio_path: Path,
    model_name: str | None = None,
) -> TranscriptionResult:
    """Worker-only MLX implementation."""
    timings: dict[str, float] = {}
    selected_model = model_name or settings.whisper_model
    if selected_model in MLX_WHISPER_REPOS and not is_model_available(selected_model, "mlx"):
        return TranscriptionResult(
            success=False,
            error=f"MLX 模型 {selected_model} 尚未下载；请在设置 > 本机处理 > 模型存储中下载当前模型。",
            timings=timings,
            backend="mlx",
        )
    try:
        import mlx_whisper
    except Exception as exc:
        # The short task error must remain safe for the UI, while the backend
        # log retains the native-extension traceback needed to distinguish a
        # transient Metal/session issue from a packaging or compatibility bug.
        logger.exception("MLX Whisper extension initialization failed")
        return TranscriptionResult(
            success=False,
            error=f"MLX Whisper 不可用: {exc}",
            timings=timings,
            backend="mlx",
        )

    model_path_or_repo = str(mlx_whisper_model_dir(selected_model))
    try:
        decode_start = time.perf_counter()
        result = mlx_whisper.transcribe(
            str(audio_path),
            path_or_hf_repo=model_path_or_repo,
            language="zh",
            verbose=False,
            condition_on_previous_text=False,
        )
        timings["whisper_decode"] = time.perf_counter() - decode_start

        transcript = normalize_transcript_text(str(result.get("text") or ""))
        segments = []
        for position, segment in enumerate(result.get("segments") or []):
            text = normalize_transcript_text(str(segment.get("text") or ""))
            if not text:
                continue
            segments.append({
                "start_seconds": float(segment.get("start") or 0.0),
                "end_seconds": float(segment.get("end") or 0.0),
                "text": text,
                "position": position,
            })

        if not transcript:
            return TranscriptionResult(
                success=False,
                error="MLX Whisper 未返回转写文本",
                timings=timings,
                backend="mlx",
            )

        return TranscriptionResult(
            success=True,
            transcript=transcript,
            segments=normalize_transcript_segments(segments),
            timings=timings,
            backend="mlx",
        )
    except Exception as exc:
        logger.exception("MLX Whisper transcription failed")
        return TranscriptionResult(
            success=False,
            error=f"MLX Whisper 转写异常: {exc}",
            timings=timings,
            backend="mlx",
        )


def transcribe(audio_path: Path) -> Optional[str]:
    result = transcribe_with_details(audio_path)
    return result.transcript if result.success else None

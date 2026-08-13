"""Restore durable subtitle or ASR text into an active pipeline response."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from services.cache import read_cached_transcript_segments
from services.pipeline_content_updates import prepare_preview_thumbnails
from services.pipeline_contracts import PipelineResponse, TextSourceInfo


def _read_segments(cache_dir: Path, preferred_model: str) -> list[dict]:
    return read_cached_transcript_segments(cache_dir, preferred_model=preferred_model)


class PipelineCachedTextRestorer:
    def __init__(
        self,
        *,
        response: PipelineResponse,
        cache_dir: Path,
        cached_video: Path | None,
        publish_video_artifact: Callable[[], None],
        set_many_complete: Callable[[list[str]], None],
        add_log: Callable[[str, str, str, float | None], None],
        read_segments: Callable[[Path, str], list[dict]] = _read_segments,
        prepare_previews: Callable[
            [Path | None, Path | None, Callable[[str, str, str, float | None], None]],
            None,
        ] = prepare_preview_thumbnails,
    ) -> None:
        self.response = response
        self.cache_dir = cache_dir
        self.cached_video = cached_video
        self.publish_video_artifact = publish_video_artifact
        self.set_many_complete = set_many_complete
        self.add_log = add_log
        self.read_segments = read_segments
        self.prepare_previews = prepare_previews

    def restore_subtitle(self, transcript: str) -> tuple[str, list[dict]]:
        return self._restore(
            transcript=transcript,
            preferred_model="subtitle",
            text_source=TextSourceInfo(
                kind="subtitle",
                source="cache",
                cached=True,
                detail="已缓存字幕文本",
            ),
            cache_hit="subtitle",
            log_messages=(
                "复用字幕缓存，跳过下载",
                "复用字幕缓存，跳过音频提取",
                f"复用字幕文本（{len(transcript)} 字）",
            ),
        )

    def restore_asr(self, transcript: str, model: str) -> tuple[str, list[dict]]:
        return self._restore(
            transcript=transcript,
            preferred_model=model,
            text_source=TextSourceInfo(
                kind="asr",
                source="cache",
                cached=True,
                detail=f"Whisper {model} 转写缓存",
            ),
            cache_hit="transcript",
            log_messages=(
                "复用转写缓存，跳过下载",
                "复用转写缓存，跳过音频提取",
                f"复用转写缓存（模型: {model}，{len(transcript)} 字）",
            ),
        )

    def _restore(
        self,
        *,
        transcript: str,
        preferred_model: str,
        text_source: TextSourceInfo,
        cache_hit: str,
        log_messages: tuple[str, str, str],
    ) -> tuple[str, list[dict]]:
        segments = self.read_segments(self.cache_dir, preferred_model)
        self.response.transcript = transcript
        self.response.text_source = text_source
        self.response.cache_hits.append(cache_hit)
        if self.cached_video:
            self.response.video_path = str(self.cached_video)
            self.publish_video_artifact()
            self.prepare_previews(self.cache_dir, self.cached_video, self.add_log)
        self.response.timings.update({
            "download": 0.0,
            "extract_audio": 0.0,
            "transcribe": 0.0,
            "whisper_model_load": 0.0,
            "whisper_decode": 0.0,
        })
        self.set_many_complete(["download", "extract_audio", "transcribe"])
        for step, message in zip(("download", "extract_audio", "transcribe"), log_messages, strict=True):
            self.add_log(step, message, "success", 0.0)
        return transcript, segments

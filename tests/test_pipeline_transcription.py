from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from services.pipeline_contracts import PipelineCancelled, PipelineResponse
from services.pipeline_run_reporter import PipelineRunReporter
from services.pipeline_transcription import (
    PipelineTranscriptionError,
    transcribe_pipeline_media,
)

ASR_OPTIONS = {
    "backend": "faster_whisper",
    "beam_size": 5,
    "vad_filter": True,
    "fallback_enabled": True,
}


def test_local_audio_skips_extraction_and_keeps_the_retained_original(tmp_path: Path) -> None:
    audio = tmp_path / "retained.wav"
    audio.write_bytes(b"original")
    response = PipelineResponse(success=False, task_id="task-audio", asr_backend="auto")
    reporter = PipelineRunReporter(response, None)
    transcribe = Mock(
        return_value=SimpleNamespace(
            success=True,
            error="",
            transcript="转写正文",
            segments=[{"start": 0, "text": "转写正文"}],
            backend="mlx",
            timings={"whisper_decode": 1.234},
        )
    )

    with (
        patch("services.pipeline_transcription.write_cached_transcript") as cache_text,
        patch("services.pipeline_transcription.write_cached_transcript_segments") as cache_segments,
    ):
        transcript, segments = transcribe_pipeline_media(
            audio,
            local_media_is_audio=True,
            selected_model="base",
            asr_options=ASR_OPTIONS,
            subtitle_fallback_reason="无字幕",
            cache_dir=tmp_path / "cache",
            response=response,
            reporter=reporter,
            check_cancel=Mock(),
            provider_cancel_check=None,
            extract_audio=Mock(side_effect=AssertionError("audio must not run ffmpeg")),
            transcribe=transcribe,
        )

    assert transcript == "转写正文"
    assert segments == [{"start": 0, "text": "转写正文"}]
    assert audio.read_bytes() == b"original"
    assert response.timings["extract_audio"] == 0.0
    assert response.timings["whisper_decode"] == 1.23
    assert response.asr_backend == "mlx"
    assert response.text_source and response.text_source.source == "mlx"
    transcribe.assert_called_once()
    assert transcribe.call_args.args[0] == audio
    cache_text.assert_called_once_with(tmp_path / "cache", "base", "转写正文")
    cache_segments.assert_called_once_with(
        tmp_path / "cache",
        "base",
        [{"start": 0, "text": "转写正文"}],
    )


def test_video_extracts_audio_and_removes_the_temporary_wav(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    response = PipelineResponse(success=False, task_id="task-video")

    def extract(_video, audio_path, **_kwargs):
        audio_path.write_bytes(b"temporary")
        return SimpleNamespace(success=True, error="", cancelled=False, elapsed_seconds=0.25)

    with (
        patch("services.pipeline_transcription.write_cached_transcript"),
        patch("services.pipeline_transcription.write_cached_transcript_segments"),
    ):
        transcript, _segments = transcribe_pipeline_media(
            video,
            local_media_is_audio=False,
            selected_model="small",
            asr_options=ASR_OPTIONS,
            subtitle_fallback_reason="",
            cache_dir=tmp_path / "cache",
            response=response,
            reporter=PipelineRunReporter(response, None),
            check_cancel=Mock(),
            provider_cancel_check=lambda: False,
            extract_audio=extract,
            transcribe=Mock(
                return_value=SimpleNamespace(
                    success=True,
                    error="",
                    transcript="视频正文",
                    segments=[],
                    backend="faster_whisper",
                    timings={},
                )
            ),
        )

    assert transcript == "视频正文"
    assert not video.with_suffix(".wav").exists()


def test_extraction_failure_uses_the_extract_audio_error_contract(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    response = PipelineResponse(success=False, task_id="task-failure")

    with pytest.raises(PipelineTranscriptionError, match="ffmpeg failed") as error:
        transcribe_pipeline_media(
            video,
            local_media_is_audio=False,
            selected_model="base",
            asr_options=ASR_OPTIONS,
            subtitle_fallback_reason="",
            cache_dir=tmp_path / "cache",
            response=response,
            reporter=PipelineRunReporter(response, None),
            check_cancel=Mock(),
            provider_cancel_check=None,
            extract_audio=Mock(
                return_value=SimpleNamespace(
                    success=False,
                    error="ffmpeg failed",
                    cancelled=False,
                    elapsed_seconds=0.1,
                )
            ),
            transcribe=Mock(),
        )

    assert error.value.step == "extract_audio"


def test_transcription_failure_removes_temporary_audio_and_uses_transcribe_error(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    response = PipelineResponse(success=False, task_id="task-transcribe-failure")

    def extract(_video, audio_path, **_kwargs):
        audio_path.write_bytes(b"temporary")
        return SimpleNamespace(success=True, error="", cancelled=False, elapsed_seconds=0.1)

    with pytest.raises(PipelineTranscriptionError, match="model failed") as error:
        transcribe_pipeline_media(
            video,
            local_media_is_audio=False,
            selected_model="base",
            asr_options=ASR_OPTIONS,
            subtitle_fallback_reason="",
            cache_dir=tmp_path / "cache",
            response=response,
            reporter=PipelineRunReporter(response, None),
            check_cancel=Mock(),
            provider_cancel_check=None,
            extract_audio=extract,
            transcribe=Mock(
                return_value=SimpleNamespace(
                    success=False,
                    error="model failed",
                    transcript="",
                    timings={},
                )
            ),
        )

    assert error.value.step == "transcribe"
    assert not video.with_suffix(".wav").exists()


def test_provider_cancellation_after_extraction_keeps_pipeline_cancel_contract(tmp_path: Path) -> None:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"video")
    response = PipelineResponse(success=False, task_id="task-cancel")

    with pytest.raises(PipelineCancelled):
        transcribe_pipeline_media(
            video,
            local_media_is_audio=False,
            selected_model="base",
            asr_options=ASR_OPTIONS,
            subtitle_fallback_reason="",
            cache_dir=tmp_path / "cache",
            response=response,
            reporter=PipelineRunReporter(response, None),
            check_cancel=Mock(),
            provider_cancel_check=lambda: True,
            extract_audio=Mock(
                return_value=SimpleNamespace(
                    success=True,
                    error="",
                    cancelled=False,
                    elapsed_seconds=0.1,
                )
            ),
            transcribe=Mock(),
        )

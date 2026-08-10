from pathlib import Path

from services.pipeline_cached_text import PipelineCachedTextRestorer
from services.pipeline_contracts import PipelineResponse


def make_restorer(*, cached_video: Path | None = None):
    response = PipelineResponse(success=False)
    calls = {
        "segments": [],
        "published": [],
        "completed": [],
        "logs": [],
        "previews": [],
    }

    def read_segments(cache_dir: Path, preferred_model: str) -> list[dict]:
        calls["segments"].append((cache_dir, preferred_model))
        return [{"start": 0, "end": 1, "text": preferred_model}]

    restorer = PipelineCachedTextRestorer(
        response=response,
        cache_dir=Path("/cache/item"),
        cached_video=cached_video,
        publish_video_artifact=lambda: calls["published"].append(response.video_path),
        set_many_complete=lambda steps: calls["completed"].append(steps),
        add_log=lambda *args: calls["logs"].append(args),
        read_segments=read_segments,
        prepare_previews=lambda *args: calls["previews"].append(args),
    )
    return restorer, response, calls


def test_restores_subtitle_cache_and_republishes_an_available_video() -> None:
    video_path = Path("/cache/item/video.mp4")
    restorer, response, calls = make_restorer(cached_video=video_path)

    transcript, segments = restorer.restore_subtitle("缓存字幕")

    assert transcript == "缓存字幕"
    assert segments == [{"start": 0, "end": 1, "text": "subtitle"}]
    assert response.transcript == "缓存字幕"
    assert response.text_source.model_dump() == {
        "kind": "subtitle",
        "source": "cache",
        "cached": True,
        "detail": "已缓存字幕文本",
        "fallback_reason": None,
    }
    assert response.cache_hits == ["subtitle"]
    assert response.video_path == str(video_path)
    assert calls["published"] == [str(video_path)]
    assert calls["previews"][0][0:2] == (Path("/cache/item"), video_path)
    assert calls["completed"] == [["download", "extract_audio", "transcribe"]]
    assert calls["logs"] == [
        ("download", "复用字幕缓存，跳过下载", "success", 0.0),
        ("extract_audio", "复用字幕缓存，跳过音频提取", "success", 0.0),
        ("transcribe", "复用字幕文本（4 字）", "success", 0.0),
    ]
    assert response.timings == {
        "download": 0.0,
        "extract_audio": 0.0,
        "transcribe": 0.0,
        "whisper_model_load": 0.0,
        "whisper_decode": 0.0,
    }


def test_restores_model_scoped_asr_cache_without_inventing_video_state() -> None:
    restorer, response, calls = make_restorer()

    transcript, segments = restorer.restore_asr("转写缓存", "small")

    assert transcript == "转写缓存"
    assert segments == [{"start": 0, "end": 1, "text": "small"}]
    assert calls["segments"] == [(Path("/cache/item"), "small")]
    assert response.text_source.kind == "asr"
    assert response.text_source.detail == "Whisper small 转写缓存"
    assert response.cache_hits == ["transcript"]
    assert response.video_path is None
    assert calls["published"] == []
    assert calls["previews"] == []
    assert calls["logs"][-1] == (
        "transcribe",
        "复用转写缓存（模型: small，4 字）",
        "success",
        0.0,
    )

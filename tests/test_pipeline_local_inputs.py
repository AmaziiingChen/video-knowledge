from pathlib import Path

import pytest
from services.pipeline_local_inputs import (
    LocalInputError,
    prepare_local_media,
    prepare_local_subtitle,
)


def test_prepares_local_subtitle_and_writes_its_compact_cache(tmp_path: Path) -> None:
    subtitle = tmp_path / "captions.vtt"
    subtitle.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n正文", encoding="utf-8")
    cache_dir = tmp_path / "cache"
    writes = []

    prepared = prepare_local_subtitle(
        str(subtitle),
        source_url=None,
        source_title="自定义标题",
        content_item_id="item-1",
        authorize=lambda path, **kwargs: path == subtitle and kwargs == {"content_item_id": "item-1"},
        parse_subtitle=lambda text, suffix: "解析后的正文" if text.startswith("WEBVTT") and suffix == ".vtt" else "",
        resolve_cache_dir=lambda url: cache_dir if url == "local://captions.vtt" else Path("unexpected"),
        cache_subtitle=lambda path, transcript: writes.append((path, transcript)),
    )

    assert prepared.path == subtitle
    assert prepared.source.url == "local://captions.vtt"
    assert prepared.source.platform == "subtitle"
    assert prepared.cache_dir == cache_dir
    assert prepared.transcript == "解析后的正文"
    assert prepared.video_info == {"title": "自定义标题", "platform": "subtitle", "duration": 0}
    assert prepared.text_source.detail == "captions.vtt"
    assert writes == [(cache_dir, "解析后的正文")]


@pytest.mark.parametrize(
    ("authorize", "filename", "expected_step", "expected_message"),
    [
        (False, "captions.vtt", "parse", "本地字幕必须位于 data 目录下"),
        (True, "missing.vtt", "parse", "本地字幕文件不存在"),
        (True, "captions.txt", "parse", "不支持的字幕格式: .txt"),
    ],
)
def test_rejects_unauthorized_missing_or_unsupported_local_subtitles(
    tmp_path: Path,
    authorize: bool,
    filename: str,
    expected_step: str,
    expected_message: str,
) -> None:
    path = tmp_path / filename
    if filename != "missing.vtt":
        path.write_text("text", encoding="utf-8")

    with pytest.raises(LocalInputError, match=expected_message) as error:
        prepare_local_subtitle(
            str(path),
            source_url=None,
            source_title=None,
            content_item_id=None,
            authorize=lambda *_args, **_kwargs: authorize,
        )

    assert error.value.step == expected_step


def test_rejects_an_empty_parsed_subtitle_before_writing_cache(tmp_path: Path) -> None:
    subtitle = tmp_path / "empty.vtt"
    subtitle.write_text("WEBVTT\n", encoding="utf-8")
    writes = []

    with pytest.raises(LocalInputError, match="字幕文件为空或无法解析") as error:
        prepare_local_subtitle(
            str(subtitle),
            source_url=None,
            source_title=None,
            content_item_id=None,
            authorize=lambda *_args, **_kwargs: True,
            parse_subtitle=lambda *_args: "",
            cache_subtitle=lambda *args: writes.append(args),
        )

    assert error.value.step == "transcribe"
    assert writes == []


def test_prepares_audio_as_managed_local_media_and_creates_cache_dir(tmp_path: Path) -> None:
    audio = tmp_path / "interview.wav"
    audio.write_bytes(b"audio")
    cache_dir = tmp_path / "nested" / "cache"

    prepared = prepare_local_media(
        str(audio),
        source_url="local://retained-interview",
        source_title=None,
        content_item_id="item-2",
        authorize=lambda *_args, **_kwargs: True,
        resolve_cache_dir=lambda _url: cache_dir,
        read_duration=lambda path: 42.5 if path == audio else None,
    )

    assert prepared.path == audio
    assert prepared.source.url == "local://retained-interview"
    assert prepared.is_audio is True
    assert prepared.video_info == {"title": "interview", "platform": "local", "duration": 42.5}
    assert cache_dir.is_dir()

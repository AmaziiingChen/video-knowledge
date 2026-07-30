from services.video_timestamps import (
    normalize_video_summary_timestamps,
    timestamped_video_transcript,
)


def test_timestamped_video_transcript_uses_only_precise_segments():
    material, valid_seconds = timestamped_video_transcript(
        "原始转写",
        [
            {"start_seconds": 5.8, "text": "第一段", "position": 0},
            {"start_seconds": 65, "text": "第二段", "position": 1},
            {"start_seconds": 120, "text": "估算段", "approximate": True},
        ],
    )

    assert material == "[00:05](#video-t=5) 第一段\n[01:05](#video-t=65) 第二段"
    assert valid_seconds == {5, 65}


def test_timestamp_normalization_rejects_hallucinated_time_links():
    normalized = normalize_video_summary_timestamps(
        "关键观点 [01:05](#t=65)，错误位置 [09:59](#video-t=599)，以及 [00:05]。",
        {5, 65},
    )

    assert "[01:05](#video-t=65)" in normalized
    assert "错误位置 09:59" in normalized
    assert "[00:05](#video-t=5)" in normalized

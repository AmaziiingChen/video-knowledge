from unittest.mock import patch

from config import settings
from routers.qa import QARequest, _timestamped_qa_transcript, ask_video_note
from services.ai_response_envelope import AIResponseEnvelope
from services.summarizer import build_qa_messages


def test_video_qa_uses_the_same_precise_timestamped_material_as_summary():
    with patch(
        "routers.qa._video_timestamp_segments",
        return_value=[
            {"start_seconds": 5, "text": "开场观点"},
            {"start_seconds": 75, "text": "关键结论"},
            {"start_seconds": 120, "text": "估算位置", "approximate": True},
        ],
    ):
        material, valid_seconds = _timestamped_qa_transcript("video-1", "纯文本不应覆盖分段")

    assert material == "[00:05](#video-t=5) 开场观点\n[01:15](#video-t=75) 关键结论"
    assert valid_seconds == {5, 75}


def test_qa_prompt_keeps_timestamp_material_and_prohibits_invented_times():
    messages, _ = build_qa_messages(
        question="关键结论在哪里？",
        summary="已有总结",
        transcript="[01:15](#video-t=75) 关键结论",
        video_title="测试视频",
    )

    source_context = next(message.content for message in messages if message.role == "user" and "当前内容资料" in message.content)
    assert "[01:15](#video-t=75) 关键结论" in source_context
    assert "不得编造、估算或改写时间" in source_context


def test_normal_video_qa_sends_timestamped_material_and_normalizes_valid_answer_time():
    previous_api_key = settings.deepseek_api_key
    settings.deepseek_api_key = "test-key"
    try:
        with (
            patch(
                "routers.qa._resolve_qa_source",
                return_value=("已有总结", "纯文本转写", "测试视频"),
            ),
            patch(
                "routers.qa._timestamped_qa_transcript",
                return_value=("[01:15](#video-t=75) 关键结论", {75}),
            ),
            patch("routers.qa.answer_question_envelope", return_value=AIResponseEnvelope(answer="答案见 [01:15]。")) as answer_question,
            patch("routers.qa._save_content_qa_exchange", return_value=None),
        ):
            response = ask_video_note(QARequest(question="结论在哪里？", content_item_id="video-1"))

        assert answer_question.call_args.kwargs["transcript"] == "[01:15](#video-t=75) 关键结论"
        assert response.answer == "答案见 [01:15](#video-t=75)。"
    finally:
        settings.deepseek_api_key = previous_api_key

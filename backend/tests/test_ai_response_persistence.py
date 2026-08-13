from __future__ import annotations

from config import settings
from services.database import initialize_database
from services.knowledge_conversation_context import conversation_context_messages
from services.knowledge_conversations import (
    conversation_detail,
    finish_exchange,
    start_exchange,
)


def test_knowledge_response_metadata_stays_out_of_archive_and_prompt(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    initialize_database()
    conversation = start_exchange(
        question="证据是什么？",
        scope={"version": "v2", "sources": [{"provider": "wechat", "name": "资料"}]},
    )
    finished = finish_exchange(
        conversation["id"],
        answer="仅有正文。",
        citations=[],
        reasoning_content="内部推理",
        suggested_questions=["还可验证什么？"],
    )

    assistant = finished["messages"][-1]
    assert assistant["content"] == "仅有正文。"
    assert assistant["reasoning_content"] == "内部推理"
    assert assistant["suggested_questions"] == ["还可验证什么？"]
    prompt = "\n".join(
        message.content
        for message in conversation_context_messages(finished["messages"])
    )
    assert "仅有正文" in prompt
    assert "内部推理" not in prompt
    assert "还可验证什么" not in prompt
    archive_path = (
        settings.data_dir / "knowledge_conversations" / f"{conversation['id']}.md"
    )
    archive = archive_path.read_text(encoding="utf-8")
    assert "仅有正文" in archive
    assert "内部推理" not in archive
    assert "还可验证什么" not in archive

    reopened = conversation_detail(conversation["id"])
    assert reopened["messages"][-1]["suggested_questions"] == ["还可验证什么？"]

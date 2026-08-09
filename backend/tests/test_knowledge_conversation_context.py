from __future__ import annotations

from services.knowledge_conversation_context import conversation_context_messages
from services.knowledge_v2 import _conversation_context_messages


def test_legacy_knowledge_v2_context_entry_reexports_the_focused_policy():
    messages = [
        {"role": "user", "content": "前一问"},
        {"role": "assistant", "content": "前一答"},
    ]

    assert _conversation_context_messages is conversation_context_messages
    assert [message.content for message in conversation_context_messages(messages)] == [
        "用户问题：前一问",
        "前一答",
    ]

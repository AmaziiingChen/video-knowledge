"""Provider-neutral response metadata and strict follow-up trailer parsing."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

SUGGESTIONS_OPEN = "\n<<<KNOWLEDGEHUB_FOLLOWUPS_V1>>>\n"
SUGGESTIONS_CLOSE = "\n<<<END_KNOWLEDGEHUB_FOLLOWUPS_V1>>>"
MAX_SUGGESTION_LENGTH = 120
MAX_SUGGESTIONS = 3
MAX_TRAILER_CHARS = 8192

@dataclass(frozen=True)
class AIResponseEnvelope:
    answer: str
    reasoning_content: str = ""
    suggested_questions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AIResponseStreamEvent:
    kind: str
    text: str = ""
    envelope: AIResponseEnvelope | None = None


def normalize_suggested_questions(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        if any(ord(character) < 32 or ord(character) == 127 for character in item):
            continue
        question = " ".join(item.split()).strip()
        if not question or len(question) > MAX_SUGGESTION_LENGTH:
            continue
        key = question.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(question)
        if len(result) == MAX_SUGGESTIONS:
            break
    return result


def suggested_questions_json(value: object) -> str:
    return json.dumps(
        normalize_suggested_questions(value), ensure_ascii=False, separators=(",", ":")
    )


def suggested_questions_from_json(value: object) -> list[str]:
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return normalize_suggested_questions(parsed)


class SuggestionTrailerParser:
    """Hide a strict trailer; malformed metadata is discarded after pure body."""

    def __init__(self) -> None:
        self._answer_parts: list[str] = []
        self._pending = ""
        self._trailer = ""
        self._in_trailer = False
        self._overflowed = False

    def feed(self, value: str) -> str:
        text = str(value or "")
        if not text:
            return ""
        if self._in_trailer:
            remaining = MAX_TRAILER_CHARS - len(self._trailer)
            if remaining > 0:
                self._trailer += text[:remaining]
            if len(text) > max(0, remaining):
                self._overflowed = True
            return ""
        self._pending += text
        marker_index = self._pending.find(SUGGESTIONS_OPEN)
        if marker_index >= 0:
            visible = self._pending[:marker_index]
            prior = "".join(self._answer_parts) + visible
            if prior.count("```") % 2:
                literal = visible + SUGGESTIONS_OPEN
                self._answer_parts.append(literal)
                self._pending = self._pending[marker_index + len(SUGGESTIONS_OPEN):]
                return literal
            if visible:
                self._answer_parts.append(visible)
            self._trailer = self._pending[marker_index + len(SUGGESTIONS_OPEN):]
            if len(self._trailer) > MAX_TRAILER_CHARS:
                self._trailer = self._trailer[:MAX_TRAILER_CHARS]
                self._overflowed = True
            self._pending = ""
            self._in_trailer = True
            return visible
        keep = len(SUGGESTIONS_OPEN) - 1
        if len(self._pending) <= keep:
            return ""
        visible = self._pending[:-keep]
        self._pending = self._pending[-keep:]
        self._answer_parts.append(visible)
        return visible

    def finish(self) -> AIResponseEnvelope:
        if not self._in_trailer:
            if self._pending:
                self._answer_parts.append(self._pending)
                self._pending = ""
            return AIResponseEnvelope(answer="".join(self._answer_parts))

        raw_trailer = self._trailer
        close_index = raw_trailer.find(SUGGESTIONS_CLOSE)
        trailer_suffix = raw_trailer[close_index + len(SUGGESTIONS_CLOSE) :]
        valid_close = close_index >= 0 and not trailer_suffix.strip()
        if valid_close and not self._overflowed:
            payload = raw_trailer[:close_index].strip()
            try:
                parsed = json.loads(payload)
            except (TypeError, ValueError, json.JSONDecodeError):
                parsed = None
            valid_payload = (
                isinstance(parsed, dict)
                and set(parsed) == {"questions"}
                and isinstance(parsed["questions"], list)
            )
            if valid_payload:
                questions = normalize_suggested_questions(parsed["questions"])
                return AIResponseEnvelope(
                    answer="".join(self._answer_parts), suggested_questions=questions
                )

        # Keep the user-visible answer that preceded the protocol boundary;
        # malformed machine metadata is never projected into Markdown or DB.
        return AIResponseEnvelope(answer="".join(self._answer_parts))

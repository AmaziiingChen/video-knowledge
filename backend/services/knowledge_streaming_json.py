"""Safe visible-text extraction for structured knowledge-answer streams."""
from __future__ import annotations

import re


class IncrementalAnswerJson:
    """Extract the ``answer`` string from a streaming JSON-object response."""

    _answer_start = re.compile(r'"answer"\s*:\s*"')

    def __init__(self) -> None:
        self._prefix = ""
        self._started = False
        self._finished = False
        self._escape = False
        self._unicode_digits: str | None = None

    def feed(self, value: str) -> str:
        if self._finished:
            return ""
        text = str(value or "")
        if not self._started:
            self._prefix += text
            match = self._answer_start.search(self._prefix)
            if not match:
                # Keep a bounded suffix so a malformed upstream response does
                # not grow memory before validation rejects it.
                self._prefix = self._prefix[-96:]
                return ""
            self._started = True
            text = self._prefix[match.end():]
            self._prefix = ""
        output: list[str] = []
        for character in text:
            if self._unicode_digits is not None:
                self._unicode_digits += character
                if len(self._unicode_digits) == 4:
                    try:
                        output.append(chr(int(self._unicode_digits, 16)))
                    except ValueError:
                        output.append("\\u" + self._unicode_digits)
                    self._unicode_digits = None
                    self._escape = False
                continue
            if self._escape:
                if character == "u":
                    self._unicode_digits = ""
                    continue
                output.append({"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f"}.get(character, character))
                self._escape = False
                continue
            if character == "\\":
                self._escape = True
            elif character == '"':
                self._finished = True
                break
            else:
                output.append(character)
        return "".join(output)

"""Shared data contracts for the group report generation pipeline."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from threading import Lock

from services.ai_call_logger import AICallRecord


@dataclass(frozen=True)
class GroupReportSource:
    citation_id: str
    content_item_id: str
    title: str
    source_url: str
    published_at: str
    publisher: str
    source_kind: str
    material: str


@dataclass(frozen=True)
class GroupReportContext:
    """Immutable period metadata shared by every editorial stage."""

    report_type: str
    group_name: str
    window_start: datetime
    window_end: datetime
    status_as_of: datetime | None = None


@dataclass(frozen=True)
class GroupReportGeneration:
    markdown: str
    source_coverage: list[dict[str, str]]
    cited_source_count: int
    section_count: int
    summary_cache_hits: int
    classification_retries: int
    repair_call_count: int = 0
    report_strategy: str = ""
    planner_diagnostics: dict[str, object] | None = None


@dataclass(frozen=True)
class _Section:
    title: str
    source_ids: tuple[str, ...]
    supporting_sources: tuple["_SupportingSource", ...] = ()
    writing_brief: str = ""


@dataclass(frozen=True)
class _SupportingSource:
    source_id: str
    use_scope: str


class _ProgressUsage:
    """Thread-safe, in-memory usage totals for report progress events."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._call_count = 0
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._input_chars = 0
        self._output_chars = 0
        self._elapsed_seconds = 0.0
        self._estimated_cost = 0.0
        self._unreported_count = 0
        self._models: set[str] = set()

    def remember(self, record: AICallRecord) -> None:
        with self._lock:
            self._call_count += 1
            self._input_chars += max(0, int(record.input_chars or 0))
            self._output_chars += max(0, int(record.output_chars or 0))
            self._elapsed_seconds += max(0.0, float(record.elapsed_seconds or 0))
            if record.estimated_cost is not None:
                self._estimated_cost += max(0.0, float(record.estimated_cost))
            if record.prompt_tokens is None or record.completion_tokens is None:
                self._unreported_count += 1
            else:
                self._prompt_tokens += max(0, int(record.prompt_tokens))
                self._completion_tokens += max(0, int(record.completion_tokens))
            if record.model:
                self._models.add(str(record.model))

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "call_count": self._call_count,
                "prompt_tokens": self._prompt_tokens,
                "completion_tokens": self._completion_tokens,
                "total_tokens": self._prompt_tokens + self._completion_tokens,
                "input_chars": self._input_chars,
                "output_chars": self._output_chars,
                "elapsed_seconds": round(self._elapsed_seconds, 2),
                "estimated_cost": round(self._estimated_cost, 8),
                "unreported_count": self._unreported_count,
                "model": " / ".join(sorted(self._models)),
            }


ProgressCallback = Callable[[dict[str, object]], None]

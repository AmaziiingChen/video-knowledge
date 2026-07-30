from __future__ import annotations

from services.prompt_file_store import managed_prompt_text
from services.source_context import (
    DEFAULT_SOURCE_CONTEXT_ANALYSIS_PROMPT,
    SOURCE_CONTEXT_CORE_GUARDRAIL,
)


SOURCE_CONTEXT_PROMPT_TASK_TYPE = "source_context_analysis"


def active_source_context_system_prompt() -> str:
    """Compose fixed injection protection with the user's active analysis rules."""
    analysis_rules = managed_prompt_text(
        SOURCE_CONTEXT_PROMPT_TASK_TYPE,
        DEFAULT_SOURCE_CONTEXT_ANALYSIS_PROMPT,
    ).strip()
    return f"{SOURCE_CONTEXT_CORE_GUARDRAIL}\n\n{analysis_rules}".strip()

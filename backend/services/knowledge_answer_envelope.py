"""Validate the model-facing Knowledge answer envelope."""

from __future__ import annotations

from dataclasses import dataclass

from services.ai_response_envelope import normalize_suggested_questions
from services.knowledge_answer_evidence import validated_evidence_quotes
from services.knowledge_query_rewrite import parse_json_object
from services.llm_provider import LLMResponse


@dataclass(frozen=True)
class GroundedAnswer:
    answer: str
    citations: list[dict[str, object]]
    insufficient_evidence: bool
    reasoning_content: str = ""
    suggested_questions: list[str] | None = None


def parse_grounded_answer(
    response: LLMResponse,
    evidence: list[dict[str, object]],
) -> GroundedAnswer:
    """Validate citations and optional suggestions without exposing raw JSON."""
    parsed = parse_json_object(response.content)
    answer = str(parsed.get("answer") or "").strip()
    evidence_ids = parsed.get("evidence_ids")
    evidence_quotes = parsed.get("evidence_quotes")
    permitted_ids = {str(item["evidence_id"]) for item in evidence}
    insufficient = bool(parsed.get("insufficient_evidence")) and not bool(evidence_ids)
    if not isinstance(evidence_ids, list) or any(
        not isinstance(value, str) or value not in permitted_ids
        for value in evidence_ids
    ):
        raise ValueError("模型返回了范围外或格式错误的证据引用")
    if not answer:
        raise ValueError("模型没有返回答案")
    if not insufficient and not evidence_ids:
        raise ValueError("模型回答缺少证据引用")
    quotes_by_id = validated_evidence_quotes(
        evidence_quotes,
        evidence_ids=evidence_ids,
        evidence=evidence,
        insufficient=insufficient,
    )
    selected = [
        {**item, "excerpt": quotes_by_id[str(item["evidence_id"])]}
        for item in evidence
        if item["evidence_id"] in evidence_ids
    ]
    return GroundedAnswer(
        answer=answer,
        citations=selected,
        insufficient_evidence=insufficient,
        reasoning_content=response.reasoning_content,
        suggested_questions=normalize_suggested_questions(parsed.get("suggested_questions")),
    )

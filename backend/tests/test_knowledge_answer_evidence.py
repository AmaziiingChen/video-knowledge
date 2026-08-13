import pytest

from services.knowledge_answer_evidence import (
    ANSWER_CONTEXT_CHAR_BUDGET,
    ANSWER_EVIDENCE_MAX_CANDIDATES,
    validated_evidence_quotes,
)
from services.knowledge_v2 import (
    ANSWER_CONTEXT_CHAR_BUDGET as LEGACY_ANSWER_CONTEXT_CHAR_BUDGET,
    ANSWER_EVIDENCE_MAX_CANDIDATES as LEGACY_ANSWER_EVIDENCE_MAX_CANDIDATES,
    _validated_evidence_quotes,
)


def test_validated_evidence_quotes_rejects_model_paraphrases():
    evidence = [{
        "evidence_id": "E001",
        "child_text": "RRF 融合两个召回通道。",
        "parent_text": "",
        "excerpt": "RRF 融合两个召回通道。",
    }]

    with pytest.raises(ValueError, match="不在原文证据"):
        validated_evidence_quotes(
            [{"evidence_id": "E001", "quote": "RRF 以不同方式组合多个检索渠道。"}],
            evidence_ids=["E001"],
            evidence=evidence,
            insufficient=False,
        )


def test_knowledge_v2_keeps_private_evidence_validator_compatibility_alias():
    assert _validated_evidence_quotes is validated_evidence_quotes
    assert LEGACY_ANSWER_CONTEXT_CHAR_BUDGET == ANSWER_CONTEXT_CHAR_BUDGET
    assert LEGACY_ANSWER_EVIDENCE_MAX_CANDIDATES == ANSWER_EVIDENCE_MAX_CANDIDATES

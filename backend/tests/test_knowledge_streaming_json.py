from services.knowledge_streaming_json import IncrementalAnswerJson
from services.knowledge_v2 import _IncrementalAnswerJson


def test_incremental_answer_json_emits_only_answer_before_structured_suffix():
    extractor = IncrementalAnswerJson()

    visible = "".join(
        extractor.feed(chunk)
        for chunk in (
            '{"reasoning":"never visible","answer":"RRF ',
            '融合 [E001]","evidence_ids":["E001"]}',
            'raw trailing content must not be visible',
        )
    )

    assert visible == "RRF 融合 [E001]"


def test_incremental_answer_json_preserves_split_json_escapes():
    extractor = IncrementalAnswerJson()

    visible = "".join(
        extractor.feed(chunk)
        for chunk in ('{"answer":"first\\n\\u4e2d', '文 \\"quoted\\""}')
    )

    assert visible == 'first\n中文 "quoted"'


def test_knowledge_v2_keeps_private_stream_extractor_compatibility_alias():
    assert _IncrementalAnswerJson is IncrementalAnswerJson

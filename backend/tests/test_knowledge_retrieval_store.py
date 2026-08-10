from services import knowledge_v2
from services.knowledge_retrieval_store import source_scope_clause, tokenize_searchable


def test_scope_clause_keeps_untrusted_scope_values_out_of_sql_text():
    provider = "wechat"
    source_name = "name' OR 1=1 --"

    clause, params = source_scope_clause([(provider, source_name)])

    assert clause == "((content.source_provider=? AND content.source_name=?))"
    assert params == [provider, source_name]
    assert source_name not in clause


def test_search_tokenizer_removes_fts_operators_but_retains_cjk_and_words():
    tokens = tokenize_searchable('RRF OR "drop" * 召回融合')

    assert '"' not in tokens
    assert "*" not in tokens
    assert "rrf" in tokens.split()
    assert "召回" in tokens.split()
    assert "融合" in tokens.split()


def test_knowledge_v2_keeps_scope_clause_compatibility_alias():
    assert knowledge_v2._source_scope_clause is source_scope_clause

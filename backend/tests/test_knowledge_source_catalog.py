from services import knowledge_source_catalog as catalog
from services import knowledge_v2


def test_scope_readiness_requires_all_documents_and_embeddings():
    assert not catalog.ScopeReadiness(0, 0, 0, 0).ready
    assert not catalog.ScopeReadiness(2, 1, 2, 2).ready
    assert not catalog.ScopeReadiness(2, 2, 3, 2).ready
    assert catalog.ScopeReadiness(2, 2, 3, 3).ready


def test_index_stats_binds_source_scope_values(monkeypatch):
    captured: dict[str, object] = {}
    source_name = "name' OR 1=1 --"

    class FakeDatabase:
        def execute(self, query, params):
            captured["query"] = query
            captured["params"] = params
            return self

        def fetchone(self):
            return {
                "indexed_documents": 0,
                "parent_chunks": 0,
                "child_chunks": 0,
                "embedded_children": 0,
            }

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(catalog, "connect", lambda: FakeDatabase())

    assert catalog.index_stats(source_specs=[("wechat", source_name)]) == {
        "indexed_documents": 0,
        "parent_chunks": 0,
        "child_chunks": 0,
        "embedded_children": 0,
    }
    assert source_name not in captured["query"]
    assert captured["params"] == ["wechat", source_name]


def test_knowledge_v2_reexports_source_catalog_contracts():
    assert knowledge_v2.ScopeReadiness is catalog.ScopeReadiness
    assert knowledge_v2.list_source_sets is catalog.list_source_sets
    assert knowledge_v2.validate_source_document_ids is catalog.validate_source_document_ids

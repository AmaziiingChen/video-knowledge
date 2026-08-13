from services import knowledge_source_loader as loader
from services import knowledge_v2


def test_source_documents_binds_untrusted_scope_and_document_ids(monkeypatch):
    captured: dict[str, object] = {}
    source_name = "name' OR 1=1 --"
    document_id = "item' OR 1=1 --"

    class FakeDatabase:
        def execute(self, query, params):
            captured["query"] = query
            captured["params"] = params
            return self

        def fetchall(self):
            return []

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(loader, "ensure_database_initialized", lambda: None)
    monkeypatch.setattr(loader, "connect", lambda: FakeDatabase())

    assert loader.source_documents(
        source_specs=[("wechat", source_name)],
        content_item_ids=[document_id],
    ) == []
    assert source_name not in captured["query"]
    assert document_id not in captured["query"]
    assert captured["params"] == ["wechat", source_name, document_id]


def test_knowledge_v2_reexports_source_loader_entry_point():
    assert knowledge_v2.source_documents is loader.source_documents

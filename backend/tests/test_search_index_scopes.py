from contextlib import contextmanager

from services import search_index


def _row(content_item_id: str, title: str) -> dict[str, str]:
    return {
        "content_item_id": content_item_id,
        "title": title,
        "summary": "",
        "transcript": "",
    }


def test_all_scope_merges_fts_and_substring_matches(monkeypatch):
    @contextmanager
    def fake_connect():
        yield object()

    monkeypatch.setattr(search_index, "ensure_database_initialized", lambda: None)
    monkeypatch.setattr(search_index, "connect", fake_connect)
    monkeypatch.setattr(search_index, "_search_fts", lambda *_args, **_kwargs: [_row("fts", "FTS 命中")])
    monkeypatch.setattr(search_index, "_search_like", lambda *_args, **_kwargs: [_row("substring", "子串命中")])

    results = search_index.search_documents("命中", limit=20)

    assert [result.content_key for result in results] == ["fts", "substring"]


def test_scoped_search_uses_its_dedicated_database_lookup(monkeypatch):
    @contextmanager
    def fake_connect():
        yield object()

    monkeypatch.setattr(search_index, "ensure_database_initialized", lambda: None)
    monkeypatch.setattr(search_index, "connect", fake_connect)
    monkeypatch.setattr(search_index, "_search_title", lambda *_args, **_kwargs: [_row("title", "标题")])
    monkeypatch.setattr(search_index, "_search_source", lambda *_args, **_kwargs: [_row("source", "来源")])

    assert [result.content_key for result in search_index.search_documents("资料", scope="title")] == ["title"]
    assert [result.content_key for result in search_index.search_documents("资料", scope="source")] == ["source"]

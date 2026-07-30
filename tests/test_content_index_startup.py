from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from config import settings
from services import content_index
from services.database import connect, initialize_database
from services.repository import ContentRepository


def test_content_index_ready_marker_skips_legacy_cache_backfill_after_restart(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    settings.data_dir.mkdir(parents=True)
    (settings.data_dir / "content_index_ready.version").write_text(
        content_index._CONTENT_INDEX_READY_VERSION + "\n",
        encoding="utf-8",
    )
    content_index._CONTENT_INDEX_READY_ROOTS.clear()

    with patch("services.content_index.backfill_content_items_from_cache", side_effect=AssertionError("must not scan cache")):
        content_index.ensure_content_index_ready()

    assert str(settings.data_dir.resolve()) in content_index._CONTENT_INDEX_READY_ROOTS


def test_external_import_repair_assigns_unfiled_local_files_to_external_root():
    initialize_database()
    with connect() as connection:
        orphan = ContentRepository(connection).create_content_item(
            source_provider="local_file",
            canonical_source_id="local-file:test-orphan",
            title="监听导入资料",
            content_type="document",
            status="to_read",
        )
        connection.commit()

    assert content_index.ensure_external_markdown_library() == 1

    with connect() as connection:
        repaired = ContentRepository(connection).get_content_item(orphan.id)
        external_root_id = content_index.ensure_external_markdown_folder(connection)

    assert repaired.library_folder_id == external_root_id

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from config import settings
from services.database import connect, initialize_database
from services.markdown_sync import save_markdown_draft_and_sync
from services.repository import ContentRepository
from services.search_index import search_documents
from services.search_index_scheduler import SearchIndexScheduler


class SearchIndexSchedulerTests(unittest.TestCase):
    def test_background_startup_never_forces_a_full_rebuild(self):
        scheduler = SearchIndexScheduler(interval_seconds=0.25)
        scheduler._stop_event.set()

        with patch.object(scheduler, "sync_once") as sync_once:
            scheduler._run()

        sync_once.assert_called_once_with()

    def test_incrementally_reindexes_a_changed_local_markdown_document(self):
        old_data_dir = settings.data_dir
        old_vault = settings.obsidian_vault
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                settings.data_dir = root / "data"
                settings.obsidian_vault = root / "vault"
                settings.obsidian_vault.mkdir(parents=True)
                initialize_database()
                with connect() as connection:
                    item = ContentRepository(connection).create_content_item(
                        source_provider="local",
                        canonical_source_id="scheduler-test",
                        title="自动索引测试",
                    )
                    connection.commit()

                state = save_markdown_draft_and_sync(
                    markdown="# 自动索引测试\n\n旧关键词\n",
                    title=item.title,
                    obsidian_path=settings.obsidian_vault / "自动索引测试.md",
                    content_item_id=item.id,
                )
                scheduler = SearchIndexScheduler(interval_seconds=0.25, debounce_seconds=0)
                scheduler.sync_once(force=True)
                self.assertEqual(search_documents("旧关键词")[0].content_key, item.id)

                Path(state.markdown_draft_path).write_text("# 自动索引测试\n\n新关键词\n", encoding="utf-8")
                scheduler.sync_once()

                self.assertEqual(search_documents("新关键词")[0].content_key, item.id)
                self.assertEqual(search_documents("旧关键词"), [])
        finally:
            settings.data_dir = old_data_dir
            settings.obsidian_vault = old_vault

    def test_incremental_sync_limits_each_writer_batch(self):
        scheduler = SearchIndexScheduler(
            interval_seconds=0.25,
            debounce_seconds=0,
            max_updates_per_sync=2,
        )
        documents = [
            type("Document", (), {"content_key": str(index), "markdown_path": None})()
            for index in range(5)
        ]

        with (
            patch("services.search_index_scheduler.local_markdown_documents", return_value=documents),
            patch("services.search_index_scheduler.index_local_markdown_document", return_value=True) as index_document,
        ):
            first = scheduler.sync_once()
            second = scheduler.sync_once()
            third = scheduler.sync_once()

        self.assertEqual([first["updated_count"], second["updated_count"], third["updated_count"]], [2, 2, 1])
        self.assertEqual(index_document.call_count, 5)

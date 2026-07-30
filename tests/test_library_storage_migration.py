import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from config import settings
from services.database import connect, initialize_database, utc_now_iso
from services.knowledge_library import attachments_root, library_root, sync_library_folder_directories
from services.obsidian_settings import save_obsidian_settings
from services.repository import ContentRepository


def test_enabled_library_directory_becomes_canonical_document_root(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "obsidian_vault", tmp_path / "old-vault")

    library_dir = tmp_path / "Knowledge"
    save_obsidian_settings(library_dir, export_path=tmp_path / "exports", auto_write=True)

    assert library_root() == library_dir.resolve() / "library"
    assert attachments_root() == library_dir.resolve() / "attachments"


def test_switching_library_directory_moves_only_indexed_content_and_attachments(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "obsidian_vault", tmp_path / "old-vault")
    initialize_database()
    with connect() as connection:
        now = utc_now_iso()
        connection.execute(
            "INSERT INTO library_folders (id, name, parent_folder_id, sort_order, created_at, updated_at) VALUES (?, ?, NULL, 0, ?, ?)",
            ("wechat-root", "微信公众号", now, now),
        )
        connection.execute(
            "INSERT INTO library_folders (id, name, parent_folder_id, sort_order, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
            ("wechat-account", "示例公众号", "wechat-root", now, now),
        )
        item = ContentRepository(connection).create_content_item(
            source_provider="wechat",
            content_type="article",
            source_url="https://example.com/article/1",
            canonical_source_id="article-1",
            title="入库文章",
            library_folder_id="wechat-account",
        )
        old_document = settings.data_dir / "library" / "wechat" / "2026-07" / "示例公众号" / f"入库文章--{item.id}.md"
        old_document.parent.mkdir(parents=True)
        old_document.write_text("# 入库文章\n", encoding="utf-8")
        old_attachment = settings.data_dir / "attachments" / item.id / "image-001.jpg"
        old_attachment.parent.mkdir(parents=True)
        old_attachment.write_bytes(b"image")
        unmanaged = settings.data_dir / "library" / "manual.md"
        unmanaged.write_text("不要移动", encoding="utf-8")
        connection.execute(
            "INSERT INTO content_documents (content_item_id, markdown_path, content_hash, updated_at) VALUES (?, ?, ?, ?)",
            (item.id, str(old_document), "hash", utc_now_iso()),
        )
        connection.commit()

    library_dir = tmp_path / "Knowledge"
    saved = save_obsidian_settings(library_dir, export_path=tmp_path / "exports", auto_write=True)
    expected_document = library_dir / "library" / "微信公众号" / "示例公众号" / old_document.name
    expected_attachment = library_dir / "attachments" / item.id / "image-001.jpg"

    assert saved["migrated_documents"] == 1
    assert saved["migrated_attachments"] == 1
    assert expected_document.read_text(encoding="utf-8") == "# 入库文章\n"
    assert expected_attachment.read_bytes() == b"image"
    assert not old_document.exists()
    assert not old_attachment.exists()
    assert unmanaged.read_text(encoding="utf-8") == "不要移动"
    with connect() as connection:
        stored_path = connection.execute(
            "SELECT markdown_path FROM content_documents WHERE content_item_id=?", (item.id,)
        ).fetchone()["markdown_path"]
    assert Path(stored_path) == expected_document


def test_sync_library_folder_directories_creates_empty_rss_and_nested_folders(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "obsidian_vault", tmp_path / "old-vault")
    save_obsidian_settings(tmp_path / "Knowledge", export_path=tmp_path / "exports", auto_write=True)
    initialize_database()
    with connect() as connection:
        now = utc_now_iso()
        connection.execute(
            "INSERT INTO library_folders (id, name, parent_folder_id, sort_order, created_at, updated_at) VALUES (?, ?, NULL, 0, ?, ?)",
            ("rss-root", "RSS订阅", now, now),
        )
        connection.execute(
            "INSERT INTO library_folders (id, name, parent_folder_id, sort_order, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
            ("rss-source", "AI Brief", "rss-root", now, now),
        )
        connection.execute(
            "INSERT INTO library_folders (id, name, parent_folder_id, sort_order, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
            ("empty-child", "待整理", "rss-source", now, now),
        )
        connection.commit()

    created = sync_library_folder_directories()

    assert created == 3
    assert (library_root() / "RSS订阅" / "AI Brief" / "待整理").is_dir()

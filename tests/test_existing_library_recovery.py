from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from config import settings
from services.database import connect
from services.existing_library_recovery import recover_existing_library
from services.obsidian_settings import save_obsidian_settings


def _write_document(
    path: Path,
    *,
    item_id: str,
    provider: str,
    source_url: str,
    title: str,
) -> None:
    body = f"# {title}\n\n## 原文内容\n\n旧资料正文\n"
    source_hash = hashlib.sha256("旧资料正文".encode()).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "---",
                f'id: "{item_id}"',
                f'source_type: "{provider}"',
                'source_name: "旧资料来源"',
                f'source_url: "{source_url}"',
                'published_at: "2026-01-02 03:04"',
                'fetched_at: "2026-01-03T04:05:06+00:00"',
                f'content_hash: "{source_hash}"',
                "---",
                "",
                body,
            ]
        ),
        encoding="utf-8",
    )


def test_selecting_existing_library_restores_strict_documents_and_folder_tree(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "obsidian_vault", tmp_path / "old-vault")
    vault = tmp_path / "Learning"
    first_id = "1" * 32
    second_id = "2" * 32
    first_path = (
        vault / "library" / "微信公众号" / "示例来源" / f"旧公众号--{first_id}.md"
    )
    second_path = vault / "library" / "Bilibili" / f"旧视频--{second_id}.md"
    root_id = "3" * 32
    root_path = vault / "library" / f"根目录资料--{root_id}.md"
    _write_document(
        first_path,
        item_id=first_id,
        provider="wechat",
        source_url="https://mp.weixin.qq.com/s/example-one",
        title="旧公众号",
    )
    _write_document(
        second_path,
        item_id=second_id,
        provider="bilibili",
        source_url="https://www.bilibili.com/video/BV1Example123",
        title="旧视频",
    )
    _write_document(
        root_path,
        item_id=root_id,
        provider="rss",
        source_url="https://example.com/feed/item-one",
        title="根目录资料",
    )
    ordinary_note = vault / "library" / "私人笔记.md"
    ordinary_note.write_text("# 不应自动导入\n", encoding="utf-8")

    saved = save_obsidian_settings(
        vault,
        export_path=tmp_path / "exports",
        auto_write=True,
        recover_existing=True,
    )

    assert saved["scanned_markdown"] == 4
    assert saved["recognized_documents"] == 3
    assert saved["restored_documents"] == 3
    assert saved["existing_documents"] == 0
    assert saved["skipped_documents"] == 1
    assert saved["restored_folders"] == 4
    with connect() as connection:
        items = connection.execute(
            "SELECT id, title, source_provider, library_folder_id FROM content_items ORDER BY id"
        ).fetchall()
        documents = connection.execute(
            "SELECT content_item_id, markdown_path FROM content_documents ORDER BY content_item_id"
        ).fetchall()
        folders = connection.execute(
            "SELECT name, parent_folder_id FROM library_folders WHERE deleted_at IS NULL ORDER BY name"
        ).fetchall()
    assert [(row["id"], row["title"], row["source_provider"]) for row in items] == [
        (first_id, "旧公众号", "wechat"),
        (second_id, "旧视频", "bilibili"),
        (root_id, "根目录资料", "rss"),
    ]
    assert [Path(row["markdown_path"]) for row in documents] == [
        first_path,
        second_path,
        root_path,
    ]
    assert {row["name"] for row in folders} == {
        "微信公众号",
        "示例来源",
        "Bilibili",
        "RSS订阅",
    }
    assert ordinary_note.read_text(encoding="utf-8") == "# 不应自动导入\n"

    repeated = recover_existing_library(vault)
    assert repeated["restored_documents"] == 0
    assert repeated["existing_documents"] == 3
    assert repeated["skipped_documents"] == 1


def test_recovery_skips_duplicate_sources_and_does_not_overwrite_files(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    vault = tmp_path / "Learning"
    first = vault / "library" / "微信公众号" / f"第一份--{'a' * 32}.md"
    duplicate = vault / "library" / "微信公众号" / f"重复来源--{'b' * 32}.md"
    source_url = "https://mp.weixin.qq.com/s/same-article"
    _write_document(
        first,
        item_id="a" * 32,
        provider="wechat",
        source_url=source_url,
        title="第一份",
    )
    _write_document(
        duplicate,
        item_id="b" * 32,
        provider="wechat",
        source_url=source_url,
        title="重复来源",
    )
    before = {path: path.read_bytes() for path in (first, duplicate)}

    result = recover_existing_library(vault)

    assert result["recognized_documents"] == 2
    assert result["restored_documents"] == 1
    assert result["conflicted_documents"] == 1
    assert {path: path.read_bytes() for path in (first, duplicate)} == before
    with connect() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM content_items").fetchone()[0] == 1
        )


def test_disabled_external_writes_do_not_recover_the_selected_directory(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "obsidian_vault", tmp_path / "old-vault")
    vault = tmp_path / "Learning"
    _write_document(
        vault / "library" / "校园官网" / f"旧通知--{'c' * 32}.md",
        item_id="c" * 32,
        provider="campus",
        source_url="https://example.edu/notice/1",
        title="旧通知",
    )

    saved = save_obsidian_settings(
        vault,
        export_path=tmp_path / "exports",
        auto_write=False,
        recover_existing=True,
    )

    assert saved["recognized_documents"] == 0
    assert saved["restored_documents"] == 0
    with connect() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM content_items").fetchone()[0] == 0
        )

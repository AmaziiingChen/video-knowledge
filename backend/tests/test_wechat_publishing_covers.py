from __future__ import annotations

import io

import pytest
from PIL import Image
from services.wechat_publishing_covers import (
    cover_bytes,
    normalized_cover_jpeg_bytes,
    remove_uncommitted_cover,
    write_local_cover,
)
from services.wechat_publishing_secrets import WeChatPublishingError


def test_cover_normalization_produces_expected_jpeg_dimensions():
    source = io.BytesIO()
    Image.new("RGB", (400, 120), "#e7aa53").save(source, format="PNG")

    normalized = normalized_cover_jpeg_bytes(source.getvalue())

    with Image.open(io.BytesIO(normalized)) as image:
        assert image.format == "JPEG"
        assert image.size == (900, 383)


def test_cover_storage_keeps_files_inside_configured_data_root(monkeypatch, tmp_path):
    monkeypatch.setattr("services.wechat_publishing_covers.settings.data_dir", tmp_path)
    written = write_local_cover("report_1", b"normalized-cover")
    outside = tmp_path.parent / "outside-cover.jpg"
    outside.write_bytes(b"do-not-delete")

    assert written.is_file()
    assert written.is_relative_to(tmp_path / "report_covers")
    remove_uncommitted_cover(str(outside))
    assert outside.read_bytes() == b"do-not-delete"

    with pytest.raises(WeChatPublishingError, match="不在 KnowledgeHub 数据目录中"):
        cover_bytes("", cover_path=str(outside))

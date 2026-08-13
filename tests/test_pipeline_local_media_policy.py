from __future__ import annotations

from contextlib import nullcontext

from services import pipeline_local_media_policy


class AssetLookupConnection:
    def __init__(self, row):
        self.row = row
        self.calls = []

    def execute(self, statement, parameters):
        self.calls.append((statement, parameters))
        return self

    def fetchone(self):
        return self.row


def configure_roots(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    attachment_dir = tmp_path / "attachments"
    data_dir.mkdir()
    attachment_dir.mkdir()
    monkeypatch.setattr(pipeline_local_media_policy.settings, "data_dir", data_dir)
    monkeypatch.setattr(pipeline_local_media_policy, "attachments_root", lambda: attachment_dir)
    return data_dir, attachment_dir


def test_managed_roots_accept_normal_descendants(monkeypatch, tmp_path):
    data_dir, attachment_dir = configure_roots(monkeypatch, tmp_path)

    assert pipeline_local_media_policy.is_managed_local_media(data_dir / "cache" / "video.mp4")
    assert pipeline_local_media_policy.is_managed_local_media(attachment_dir / "item" / "original.mp4")


def test_parent_traversal_and_escaping_symlink_are_not_managed(monkeypatch, tmp_path):
    data_dir, _attachment_dir = configure_roots(monkeypatch, tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    link = data_dir / "escaped"
    link.symlink_to(outside, target_is_directory=True)

    assert pipeline_local_media_policy.is_under_data_dir(data_dir / ".." / "outside" / "video.mp4") is False
    assert pipeline_local_media_policy.is_under_data_dir(link / "video.mp4") is False


def test_exact_database_owned_original_is_scoped_to_the_content_item(monkeypatch, tmp_path):
    configure_roots(monkeypatch, tmp_path)
    external_path = tmp_path / "legacy" / "original.mp4"
    connection = AssetLookupConnection((1,))
    initialized = []
    monkeypatch.setattr(pipeline_local_media_policy, "initialize_database", lambda: initialized.append(True))
    monkeypatch.setattr(pipeline_local_media_policy, "connect", lambda: nullcontext(connection))

    assert pipeline_local_media_policy.is_managed_local_media(
        external_path,
        content_item_id="item-1",
    ) is True
    statement, parameters = connection.calls[0]
    assert "asset_type='original_file'" in statement
    assert parameters == ("item-1", str(external_path))
    assert initialized == [True]


def test_unowned_or_unavailable_database_path_fails_closed(monkeypatch, tmp_path):
    configure_roots(monkeypatch, tmp_path)
    external_path = tmp_path / "outside.mp4"
    monkeypatch.setattr(
        pipeline_local_media_policy,
        "initialize_database",
        lambda: (_ for _ in ()).throw(OSError("database unavailable")),
    )

    assert pipeline_local_media_policy.is_managed_local_media(external_path) is False
    assert pipeline_local_media_policy.is_managed_local_media(
        external_path,
        content_item_id="item-1",
    ) is False

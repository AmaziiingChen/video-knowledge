from __future__ import annotations

from types import SimpleNamespace

from services import download_contracts


def test_transfer_progress_uses_elapsed_time_and_clamps_provider_overflow(monkeypatch):
    updates = []
    monkeypatch.setattr(download_contracts.time, "monotonic", lambda: 12.0)

    download_contracts.report_transfer(
        updates.append,
        received_bytes=150,
        total_bytes=100,
        started_at=10.0,
        detail="正在传输视频",
    )

    assert updates == [
        download_contracts.DownloadProgress(
            phase="transfer",
            detail="正在传输视频",
            received_bytes=150,
            total_bytes=100,
            bytes_per_second=75.0,
            percent=100.0,
        )
    ]


def test_unknown_total_keeps_percentage_absent_and_percent_updates_are_bounded(monkeypatch):
    updates = []
    monkeypatch.setattr(download_contracts.time, "monotonic", lambda: 5.0)

    download_contracts.report_transfer(
        updates.append,
        received_bytes=20,
        total_bytes=None,
        started_at=4.0,
        detail="正在传输音频",
    )
    download_contracts.report_transfer_percent(
        updates.append,
        percent=-3,
        detail="yt-dlp",
        bytes_per_second=2048,
    )

    assert updates[0].percent is None
    assert updates[0].bytes_per_second == 20.0
    assert updates[1].percent == 0.0
    assert updates[1].bytes_per_second == 2048


def test_log_projection_keeps_durable_entry_when_live_callback_fails():
    logs = []

    def reject_live_update(_message):
        raise RuntimeError("renderer unavailable")

    download_contracts.append_download_log(logs, "已保存", reject_live_update)

    assert logs == ["已保存"]


def test_media_error_preserves_http_status_and_has_a_stable_empty_fallback():
    assert download_contracts.media_transfer_error(
        SimpleNamespace(status_code=403, error="访问被拒绝")
    ) == "HTTP 403: 访问被拒绝"
    assert download_contracts.media_transfer_error(SimpleNamespace()) == "媒体传输失败"

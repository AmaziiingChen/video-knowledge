from pathlib import Path

import pytest
from services.download_contracts import DownloadProgress, DownloadResult
from services.pipeline_media_download import download_media_with_live_logs


class FakeDownloadSlot:
    def __init__(self, acquire_results: list[bool]) -> None:
        self.acquire_results = iter(acquire_results)
        self.timeouts: list[float] = []
        self.release_count = 0

    def acquire(self, *, timeout: float) -> bool:
        self.timeouts.append(timeout)
        return next(self.acquire_results)

    def release(self) -> None:
        self.release_count += 1


def test_waits_on_the_shared_slot_and_deduplicates_live_provider_logs() -> None:
    slot = FakeDownloadSlot([False, False, True])
    logs = []
    transfers = []
    cancellations = []
    provider_cancel_check = lambda: False

    def downloader(url, platform, output_dir, *, progress_callback, cancel_check, log_callback):
        assert (url, platform, output_dir) == ("https://example.test/video", "bilibili", Path("/tmp/output"))
        assert cancel_check is provider_cancel_check
        progress_callback(DownloadProgress("transfer", "下载中", percent=50))
        log_callback("分片下载完成")
        return DownloadResult(success=True, logs=["分片下载完成", "分片下载完成", "正在校验"])

    def check_cancel() -> None:
        cancellations.append("checked")

    result = download_media_with_live_logs(
        "https://example.test/video",
        "bilibili",
        Path("/tmp/output"),
        add_log=lambda *args: logs.append(args),
        set_download_transfer=transfers.append,
        check_cancel=check_cancel,
        provider_cancel_check=provider_cancel_check,
        downloader=downloader,
        download_slot=slot,
    )

    assert result.success is True
    assert slot.timeouts == [0.12, 0.12, 0.12]
    assert slot.release_count == 1
    assert cancellations == ["checked", "checked"]
    assert transfers == [DownloadProgress("transfer", "下载中", percent=50)]
    assert logs == [
        ("download", "等待上一条视频下载完成…", "info", None),
        ("download", "分片下载完成", "success", None),
        ("download", "分片下载完成", "success", None),
        ("download", "正在校验", "info", None),
    ]


def test_releases_the_shared_slot_when_the_provider_raises() -> None:
    slot = FakeDownloadSlot([True])

    def fail_download(*_args, **_kwargs):
        raise RuntimeError("provider failed")

    with pytest.raises(RuntimeError, match="provider failed"):
        download_media_with_live_logs(
            "https://example.test/video",
            "bilibili",
            Path("/tmp/output"),
            add_log=lambda *_args: None,
            set_download_transfer=lambda _progress: None,
            check_cancel=lambda: None,
            provider_cancel_check=None,
            downloader=fail_download,
            download_slot=slot,
        )

    assert slot.release_count == 1

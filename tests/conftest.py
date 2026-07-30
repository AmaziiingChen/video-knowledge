from __future__ import annotations

import sys
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from config import settings
from services.task_manager import task_manager


def _reset_global_task_manager() -> None:
    with task_manager._lock:
        records = list(task_manager._tasks.values())
        for record in records:
            record.cancel_requested = True
        futures = [record.future for record in records if record.future is not None]

    for future in futures:
        future.cancel()
        try:
            future.result(timeout=5)
        except FutureTimeoutError as exc:
            raise AssertionError("测试遗留的后台任务未能在 5 秒内停止") from exc
        except Exception:
            # TaskManager records worker failures on the task itself. Test
            # isolation only needs to ensure the worker is no longer running.
            pass

    # ``Future.result`` may wake before its done callbacks have finished. A
    # barrier on the single worker guarantees callbacks cannot keep writing to
    # a test's TemporaryDirectory after its context starts cleaning up.
    task_manager._executor.submit(lambda: None).result(timeout=5)

    with task_manager._lock:
        task_manager._tasks.clear()
        task_manager._active_task_ids.clear()


@pytest.fixture(autouse=True)
def isolate_runtime_settings(tmp_path, monkeypatch):
    """Keep tests from reading or mutating the user's desktop configuration."""
    _reset_global_task_manager()
    data_dir = tmp_path / "data"
    monkeypatch.setattr(settings, "data_dir", data_dir)
    monkeypatch.setattr(settings, "obsidian_vault", data_dir / "obsidian")
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    monkeypatch.setattr(settings, "deepseek_base_url", "https://api.deepseek.com")
    monkeypatch.setattr(settings, "campus_embedding_api_key", "")
    monkeypatch.setattr(settings, "campus_embedding_api_base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setattr(settings, "paddle_ocr_access_token", "")
    monkeypatch.setattr(settings, "miniprogram_forum_capture_enabled", False)
    yield
    _reset_global_task_manager()

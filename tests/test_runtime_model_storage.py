from __future__ import annotations

import pytest

from services import runtime_components
from services.runtime_components import mlx_whisper_model_dir, model_status, remove_model


def test_removing_model_only_removes_its_registered_mlx_cache():
    model_dir = mlx_whisper_model_dir("small")
    model_dir.mkdir(parents=True)
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    (model_dir / "weights.npz").write_bytes(b"weights")

    before = model_status("small", "mlx")
    assert before["available"] is True
    assert before["installed_bytes"] >= len(b"weights")

    after = remove_model("small", "mlx")

    assert after["available"] is False
    assert after["installed_bytes"] == 0
    assert not model_dir.exists()


def test_download_rejects_a_non_native_backend(monkeypatch):
    monkeypatch.setattr(runtime_components, "preferred_asr_backend", lambda: "mlx")

    with pytest.raises(ValueError, match="当前系统仅支持"):
        runtime_components.download_model("small", "faster_whisper")

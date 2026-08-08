from __future__ import annotations

import pytest

from services import runtime_components
from services.runtime_components import _install_bundled_mlx_model, mlx_whisper_model_dir, model_status, remove_model


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


def test_bundled_mlx_model_can_be_installed_without_the_network(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime_components.settings, "data_dir", tmp_path / "runtime-data")
    bundle = tmp_path / "bundle" / "preloaded_models" / "mlx" / "small"
    bundle.mkdir(parents=True)
    (bundle / "config.json").write_text("{}", encoding="utf-8")
    (bundle / "weights.npz").write_bytes(b"bundled-weights")
    monkeypatch.setattr(runtime_components.sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)

    before = model_status("small", "mlx")
    assert before["available"] is False
    assert before["bundled"] is True
    assert before["state"] == "bundled"

    assert _install_bundled_mlx_model("small", "model:mlx:small") is True
    after = model_status("small", "mlx")
    assert after["available"] is True
    assert (mlx_whisper_model_dir("small") / "weights.npz").read_bytes() == b"bundled-weights"

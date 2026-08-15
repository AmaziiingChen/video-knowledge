from __future__ import annotations

import pytest

from services import runtime_components
from services.runtime_components import (
    _download_model_from_modelscope,
    _install_bundled_mlx_model,
    _job_snapshot,
    mlx_whisper_model_dir,
    model_status,
    remove_model,
)


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


def test_modelscope_download_writes_the_native_model_and_reports_progress(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime_components.settings, "data_dir", tmp_path / "runtime-data")
    files = {"config.json": b"{}", "weights.npz": b"model-weights"}

    class Response:
        def __init__(self, *, payload=None, content=b""):
            self._payload = payload
            self._content = content
            self.status_code = 200
        def raise_for_status(self):
            return None
        def json(self):
            return self._payload
        def iter_content(self, chunk_size):
            yield self._content[:chunk_size]
            yield self._content[chunk_size:]
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return None

    class Session:
        def get(self, url, **kwargs):
            if url.endswith("/repo/files"):
                return Response(payload={
                    "Data": {
                        "Files": [
                            {"Type": "blob", "Path": path, "Size": len(content)}
                            for path, content in files.items()
                        ]
                    }
                })
            return Response(content=files[kwargs["params"]["FilePath"]])
        def close(self):
            return None

    monkeypatch.setattr(runtime_components, "direct_requests_session", Session)
    job_key = "model:mlx:base:modelscope-test"

    _download_model_from_modelscope("mlx-community/whisper-base-mlx", "base", "mlx", job_key)

    model_dir = mlx_whisper_model_dir("base")
    assert (model_dir / "config.json").read_bytes() == files["config.json"]
    assert (model_dir / "weights.npz").read_bytes() == files["weights.npz"]
    job = _job_snapshot(job_key)
    assert job["source"] == "modelscope"
    assert job["downloaded_bytes"] == sum(map(len, files.values()))
    assert job["total_bytes"] == sum(map(len, files.values()))

from __future__ import annotations

import importlib.util
import plistlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "validate_macos_release.py"
SPEC = importlib.util.spec_from_file_location("validate_macos_release", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


def _release_app(volume: Path, *, version: str = "0.1.0") -> Path:
    contents = volume / "KnowledgeHub.app" / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    (contents / "Resources" / "backend" / "knowledgehub-backend").mkdir(parents=True)
    with (contents / "Info.plist").open("wb") as target:
        plistlib.dump(
            {
                "CFBundleIdentifier": release.EXPECTED_BUNDLE_ID,
                "CFBundleShortVersionString": version,
                "CFBundleExecutable": "KnowledgeHub",
                "CFBundleIconFile": "icon.icns",
            },
            target,
        )
    (contents / "MacOS" / "KnowledgeHub").write_bytes(b"app")
    (contents / "Resources" / "app.asar").write_bytes(b"asar")
    (contents / "Resources" / "icon.icns").write_bytes(release.SOURCE_ICON.read_bytes())
    (contents / "Resources" / "backend" / "knowledgehub-backend" / "knowledgehub-backend").write_bytes(b"backend")
    return contents.parent


def test_validate_app_accepts_the_expected_unsigned_arm64_layout(tmp_path, monkeypatch):
    app = _release_app(tmp_path)
    monkeypatch.setattr(release, "executable_architectures", lambda _path: {"arm64"})
    monkeypatch.setattr(release, "validate_no_developer_id", lambda _path: "ad-hoc-or-unsigned")
    monkeypatch.setattr(release, "smoke_test_backend", lambda _path: {"status": "ok"})
    monkeypatch.setattr(
        release,
        "smoke_test_mcp_entry",
        lambda _path: {"status": "ok", "transport": "stdio"},
    )
    monkeypatch.setattr(release, "smoke_test_mlx_import", lambda _path: {"status": "ok"})

    report = release.validate_app(tmp_path, "0.1.0")

    assert report == {
        "app": "KnowledgeHub.app",
        "bundle_id": "com.knowledgehub.desktop",
        "version": "0.1.0",
        "architecture": "arm64",
        "icon": "icon.icns",
        "developer_id": "ad-hoc-or-unsigned",
        "backend_mib": 0.0,
        "backend_smoke": {"status": "ok"},
        "mcp_entry_smoke": {"status": "ok", "transport": "stdio"},
        "mlx_import_smoke": {"status": "ok"},
    }
    assert app.is_dir()


def test_validate_app_rejects_bundled_model_weights(tmp_path, monkeypatch):
    app = _release_app(tmp_path)
    (app / "Contents" / "Resources" / "backend" / "knowledgehub-backend" / "whisper-small.bin").write_bytes(b"model")
    monkeypatch.setattr(release, "executable_architectures", lambda _path: {"arm64"})

    with pytest.raises(RuntimeError, match="model weights"):
        release.validate_app(tmp_path, "0.1.0")


def test_validate_app_rejects_the_default_or_wrong_application_icon(tmp_path, monkeypatch):
    app = _release_app(tmp_path)
    (app / "Contents" / "Resources" / "icon.icns").write_bytes(b"wrong icon")
    monkeypatch.setattr(release, "executable_architectures", lambda _path: {"arm64"})

    with pytest.raises(RuntimeError, match="approved KnowledgeHub application icon"):
        release.validate_app(tmp_path, "0.1.0")

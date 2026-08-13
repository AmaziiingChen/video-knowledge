from __future__ import annotations

import importlib.util
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "build_desktop_backend.py"
SPEC = importlib.util.spec_from_file_location("build_desktop_backend", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def test_host_target_rejects_non_macos_hosts(monkeypatch):
    monkeypatch.setattr(builder.platform, "system", lambda: "Linux")

    try:
        builder.host_target()
    except SystemExit as error:
        assert "仅支持在 macOS 上构建" in str(error)
    else:
        raise AssertionError("non-macOS host unexpectedly accepted")


def test_build_native_tools_compiles_both_app_owned_macos_helpers(tmp_path, monkeypatch):
    native = tmp_path / "backend" / "native"
    native.mkdir(parents=True)
    for name in ("macos_miniprogram_helper.m", "macos_vision_ocr.m"):
        (native / name).write_text("// source", encoding="utf-8")
    compiler = tmp_path / "clang"
    compiler.write_text("", encoding="utf-8")
    output = tmp_path / "native-tools"
    commands = []

    monkeypatch.setattr(builder, "ROOT", tmp_path)
    monkeypatch.setattr(builder, "NATIVE_TOOLS_OUTPUT", output)
    monkeypatch.setattr(builder.shutil, "which", lambda _name: str(compiler))

    def fake_run(command, **_kwargs):
        commands.append(command)
        Path(command[command.index("-o") + 1]).write_bytes(b"binary")

    monkeypatch.setattr(builder.subprocess, "run", fake_run)
    built = builder.build_native_tools("macos")

    assert [path.name for path in built] == ["macos-miniprogram-helper", "macos-vision-ocr"]
    assert all(path.stat().st_mode & 0o111 for path in built)
    assert [command[1] for command in commands] == [
        str(native / "macos_miniprogram_helper.m"),
        str(native / "macos_vision_ocr.m"),
    ]
    assert ["ScreenCaptureKit" in command for command in commands] == [True, False]
    assert ["Vision" in command for command in commands] == [False, True]


def test_build_backend_uses_project_cache_and_excludes_optional_model_stacks(tmp_path, monkeypatch):
    backend = tmp_path / "backend"
    native = backend / "native"
    native.mkdir(parents=True)
    entry = backend / "desktop_server.py"
    entry.write_text("# entry", encoding="utf-8")
    helper = tmp_path / "native-tools" / "helper"
    helper.parent.mkdir()
    helper.write_bytes(b"helper")
    output = tmp_path / "desktop" / "backend"
    commands = []

    monkeypatch.setattr(builder, "ROOT", tmp_path)
    monkeypatch.setattr(builder, "BACKEND_ENTRY", entry)
    monkeypatch.setattr(builder, "DESKTOP_DIR", tmp_path / "desktop")
    monkeypatch.setattr(builder, "BACKEND_OUTPUT", output)
    monkeypatch.setattr(builder, "build_native_tools", lambda _target: [helper])
    monkeypatch.setattr(builder.subprocess, "run", lambda command, **kwargs: commands.append((command, kwargs)))

    builder.build_backend("macos")

    command, kwargs = commands[0]
    assert command[:4] == [builder.sys.executable, "-m", "PyInstaller", "--noconfirm"]
    assert command[command.index("--distpath") + 1] == str(output)
    assert command[command.index("--paths") + 1] == str(backend)
    assert command[command.index("--hidden-import") + 1] == "mcp_server"
    assert command[command.index("--add-data") + 1] == f"{native}{os.pathsep}native"
    assert command[command.index("--add-binary") + 1] == f"{helper}{os.pathsep}native_tools"
    excluded = [command[index + 1] for index, value in enumerate(command) if value == "--exclude-module"]
    assert excluded == ["torch", "mlx_whisper.torch_whisper", "sentence_transformers", "transformers"]
    assert kwargs["cwd"] == tmp_path
    assert kwargs["env"]["PYINSTALLER_CONFIG_DIR"] == str(tmp_path / "desktop" / "build" / "macos" / "pyinstaller-cache")

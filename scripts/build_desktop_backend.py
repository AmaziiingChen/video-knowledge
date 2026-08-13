"""Build the application-owned desktop backend on its target platform."""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ENTRY = ROOT / "backend" / "desktop_server.py"
DESKTOP_DIR = ROOT / "desktop"
BACKEND_OUTPUT = DESKTOP_DIR / "backend"
NATIVE_TOOLS_OUTPUT = DESKTOP_DIR / "native-tools"


def host_target() -> str:
    system = platform.system()
    if system == "Darwin":
        return "macos"
    raise SystemExit(f"KnowledgeHub 当前仅支持在 macOS 上构建；当前主机是 {system}")


def build_native_tools(target: str) -> list[Path]:
    """Build ScreenCaptureKit and Vision helpers while the build SDK exists."""
    compiler = shutil.which("clang") or "/usr/bin/clang"
    if not Path(compiler).exists() and shutil.which(compiler) is None:
        raise SystemExit("未找到 clang，无法构建 macOS 小程序采集组件")
    NATIVE_TOOLS_OUTPUT.mkdir(parents=True, exist_ok=True)
    specifications = [
        (
            ROOT / "backend" / "native" / "macos_miniprogram_helper.m",
            NATIVE_TOOLS_OUTPUT / "macos-miniprogram-helper",
            ["AppKit", "ApplicationServices", "ImageIO", "ScreenCaptureKit"],
        ),
        (
            ROOT / "backend" / "native" / "macos_vision_ocr.m",
            NATIVE_TOOLS_OUTPUT / "macos-vision-ocr",
            ["AppKit", "Vision"],
        ),
    ]
    outputs = []
    for source, output, frameworks in specifications:
        command = [compiler, str(source), "-fobjc-arc", "-fblocks", "-O2"]
        for framework in frameworks:
            command.extend(("-framework", framework))
        command.extend(("-o", str(output)))
        subprocess.run(command, check=True, cwd=ROOT)
        output.chmod(0o755)
        outputs.append(output)
    return outputs


def build_backend(target: str) -> None:
    native_tools = build_native_tools(target)
    native_arguments = []
    for helper in native_tools:
        native_arguments.extend(("--add-binary", f"{helper}{os.pathsep}native_tools"))

    data_arguments: list[str] = ["--add-data", f"{ROOT / 'backend' / 'native'}{os.pathsep}native"]
    build_root = DESKTOP_DIR / "build" / target
    environment = os.environ.copy()
    # Keep PyInstaller's cache inside the project build directory. Its default
    # user-wide cache can be cleaned by another build process concurrently,
    # which makes reproducible packaging unnecessarily flaky.
    environment["PYINSTALLER_CONFIG_DIR"] = str(build_root / "pyinstaller-cache")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--log-level",
            "WARN",
            "--onedir",
            "--name",
            "knowledgehub-backend",
            "--distpath",
            str(BACKEND_OUTPUT),
            "--workpath",
            str(build_root / "work"),
            "--specpath",
            str(build_root / "spec"),
            "--paths",
            str(ROOT / "backend"),
            "--hidden-import",
            "mcp_server",
            # MLX is imported only in the disposable transcription worker, so
            # static analysis can miss its native extension and support files.
            # Do not use ``--collect-all mlx``: that imports every MLX
            # subpackage while packaging and crashes headless macOS builders
            # that have no Metal device.  Collect files without importing them
            # and mark the runtime entry modules explicitly instead.
            "--hidden-import",
            "mlx.core",
            "--hidden-import",
            "mlx.nn",
            "--hidden-import",
            "mlx_whisper",
            "--collect-binaries",
            "mlx",
            "--collect-data",
            "mlx",
            "--collect-data",
            "mlx_whisper",
            # The Apple Silicon MLX path never imports mlx_whisper's legacy
            # PyTorch compatibility implementation. Exclude it so PyInstaller
            # does not turn an optional upstream module into a 400 MB runtime
            # dependency of every desktop installation.
            "--exclude-module",
            "torch",
            "--exclude-module",
            "mlx_whisper.torch_whisper",
            # Campus semantic ranking has a deterministic lexical fallback.
            # Its local transformer stack is optional and must not become part
            # of the default desktop distribution.
            "--exclude-module",
            "sentence_transformers",
            "--exclude-module",
            "transformers",
            *data_arguments,
            *native_arguments,
            str(BACKEND_ENTRY),
        ],
        check=True,
        cwd=ROOT,
        env=environment,
    )

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="构建 KnowledgeHub 桌面后端")
    parser.add_argument("--target", choices=("macos",), default=host_target())
    arguments = parser.parse_args()
    host = host_target()
    if arguments.target != host:
        raise SystemExit(f"{arguments.target} 安装包必须在对应平台构建；当前主机是 {host}")
    build_backend(arguments.target)

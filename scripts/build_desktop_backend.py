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


def build_backend(target: str, *, bundle_local_asr_model: bool = False) -> None:
    native_tools = build_native_tools(target)
    native_arguments = []
    for helper in native_tools:
        native_arguments.extend(("--add-binary", f"{helper}{os.pathsep}native_tools"))

    data_arguments: list[str] = ["--add-data", f"{ROOT / 'backend' / 'native'}{os.pathsep}native"]
    if bundle_local_asr_model:
        model_directory = ROOT / "data" / "models" / "mlx-whisper" / "small"
        if not ((model_directory / "config.json").is_file() and any(model_directory.glob("*.npz"))):
            raise SystemExit("无法预置本机语音模型：未找到 data/models/mlx-whisper/small 的完整模型文件")
        data_arguments.extend((
            "--add-data",
            f"{model_directory}{os.pathsep}preloaded_models/mlx/small",
        ))
    build_root = DESKTOP_DIR / "build" / target
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
            *data_arguments,
            *native_arguments,
            str(BACKEND_ENTRY),
        ],
        check=True,
        cwd=ROOT,
    )

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="构建 KnowledgeHub 桌面后端")
    parser.add_argument("--target", choices=("macos",), default=host_target())
    parser.add_argument("--bundle-local-asr-model", action="store_true", help="将当前 small MLX 语音模型预置到本机 macOS 包")
    arguments = parser.parse_args()
    host = host_target()
    if arguments.target != host:
        raise SystemExit(f"{arguments.target} 安装包必须在对应平台构建；当前主机是 {host}")
    build_backend(arguments.target, bundle_local_asr_model=arguments.bundle_local_asr_model)

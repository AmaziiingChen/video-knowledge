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
    if system == "Windows":
        return "windows"
    raise SystemExit(f"不支持在 {system} 上构建桌面后端；请在 macOS 或 Windows 上执行")


def build_native_tools(target: str) -> list[Path]:
    """Build ScreenCaptureKit and Vision helpers while the build SDK exists."""
    if target != "macos":
        # Windows v1 intentionally excludes the macOS native mini-program
        # collector and Vision OCR helper. The cloud Paddle OCR path remains
        # available through the Python backend.
        return []
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

    data_arguments: list[str] = []
    if target == "macos":
        data_arguments.extend(("--add-data", f"{ROOT / 'backend' / 'native'}{os.pathsep}native"))
    data_arguments.extend(("--add-data", f"{ROOT / 'backend' / 'vendor' / 'Spider_XHS'}{os.pathsep}vendor/Spider_XHS"))

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
            "--paths",
            str(ROOT / "backend" / "vendor" / "Spider_XHS"),
            "--hidden-import",
            "apis.xhs_pc_apis",
            "--hidden-import",
            "xhs_utils.xhs_pc",
            *data_arguments,
            *native_arguments,
            str(BACKEND_ENTRY),
        ],
        check=True,
        cwd=ROOT,
    )

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="构建 KnowledgeHub 桌面后端")
    parser.add_argument("--target", choices=("macos", "windows"), default=host_target())
    arguments = parser.parse_args()
    host = host_target()
    if arguments.target != host:
        raise SystemExit(f"{arguments.target} 安装包必须在对应平台构建；当前主机是 {host}")
    build_backend(arguments.target)

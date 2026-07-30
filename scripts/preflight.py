#!/usr/bin/env python3
from __future__ import annotations

import socket
import subprocess
import sys
import argparse
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from shutil import which


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
DATA_DIR = ROOT / "data"
ENV_FILE = BACKEND / ".env"
OBSIDIAN_VAULT = DATA_DIR / "obsidian"

REQUIRED_COMMANDS = ["ffmpeg", "yt-dlp", "node", "npm"]
REQUIRED_PACKAGES = [
    "fastapi",
    "uvicorn",
    "pydantic-settings",
    "httpx",
    "requests",
    "faster-whisper",
    "openai",
    "playwright",
]
PORTS = [8000, 5173]


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def _env_value(name: str) -> str:
    if not ENV_FILE.exists():
        return ""

    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() == name:
            return value.strip().strip("\"'")
    return ""


def _check_playwright_browser() -> tuple[bool, str]:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        return True, "Playwright Chromium 可启动"
    except Exception as exc:
        return False, f"Playwright Chromium 不可用：{exc}"


def _command_version(command: str) -> str:
    try:
        result = subprocess.run(
            [command, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return ""

    output = (result.stdout or result.stderr).strip().splitlines()
    return output[0] if output else ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Video Knowledge 启动前自检")
    parser.add_argument(
        "--skip-port-check",
        action="store_true",
        help="跳过端口占用检查，交给启动脚本决定复用或报错",
    )
    args = parser.parse_args()

    errors: list[str] = []
    warnings: list[str] = []
    details: list[str] = []

    details.append(f"项目目录：{ROOT}")
    details.append(f"Python：{sys.executable} ({sys.version.split()[0]})")

    for command in REQUIRED_COMMANDS:
        path = which(command)
        if not path:
            errors.append(f"缺少命令：{command}")
            continue
        version_line = _command_version(command)
        details.append(f"{command}：{path}" + (f" | {version_line}" if version_line else ""))

    for package in REQUIRED_PACKAGES:
        try:
            details.append(f"{package}=={version(package)}")
        except PackageNotFoundError:
            errors.append(f"缺少 Python 依赖：{package}")

    browser_ok, browser_message = _check_playwright_browser()
    if browser_ok:
        details.append(browser_message)
    else:
        errors.append(browser_message)

    if not ENV_FILE.exists():
        warnings.append("未找到 backend/.env；DeepSeek 总结会失败，除非通过环境变量提供 API Key")
    elif not _env_value("DEEPSEEK_API_KEY"):
        warnings.append("backend/.env 中没有 DEEPSEEK_API_KEY；只能跑到转写，不能生成总结")
    else:
        details.append("DeepSeek API Key：已配置")

    if not OBSIDIAN_VAULT.exists():
        warnings.append(f"默认笔记目录尚未创建：{OBSIDIAN_VAULT}；启动后会自动创建，也可在设置中改为现有 Obsidian vault")
    else:
        details.append(f"Obsidian 目录：{OBSIDIAN_VAULT}")

    cookie_file = DATA_DIR / "douyin_cookies.txt"
    if not cookie_file.exists() or cookie_file.stat().st_size == 0:
        warnings.append("未配置抖音 Cookie；B站可用，抖音下载大概率失败")
    else:
        details.append("抖音 Cookie 文件：已配置")

    if not (FRONTEND / "node_modules").exists():
        warnings.append("frontend/node_modules 不存在；请先在 frontend 目录运行 npm install")

    if not args.skip_port_check:
        for port in PORTS:
            if not _port_is_free(port):
                errors.append(f"端口 {port} 已被占用；请先停止旧服务或改端口")

    if errors:
        print("自检失败：需要先处理以下问题")
        for item in errors:
            print(f"- {item}")
        if warnings:
            print("\n警告：")
            for item in warnings:
                print(f"- {item}")
        print("\n环境细节：")
        for item in details:
            print(f"- {item}")
        return 1

    print("自检通过：可以启动 Video Knowledge Pipeline")
    if warnings:
        print("\n警告：")
        for item in warnings:
            print(f"- {item}")
    print("\n环境细节：")
    for item in details:
        print(f"- {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

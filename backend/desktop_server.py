"""Desktop entry point bundled by PyInstaller for the Electron shell."""

from __future__ import annotations

import multiprocessing as mp
import os
import sys

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def backend_host() -> str:
    """Keep the desktop-only API private even when an environment leaks in."""
    host = os.environ.get("KNOWLEDGEHUB_BACKEND_HOST", "127.0.0.1").strip()
    if host not in LOOPBACK_HOSTS:
        raise SystemExit("KnowledgeHub 桌面后端仅允许监听本机回环地址")
    return host


def run_api() -> None:
    import uvicorn
    from main import app

    uvicorn.run(
        app,
        host=backend_host(),
        port=int(os.environ.get("KNOWLEDGEHUB_BACKEND_PORT", "8000")),
        log_level="info",
    )


def run_mcp_stdio() -> None:
    from mcp_server import run_stdio

    run_stdio()


def main(arguments: list[str] | None = None) -> None:
    # PyInstaller re-executes this executable for ``spawn`` workers.  Without
    # this call an MLX transcription worker starts Uvicorn again, collides with
    # the desktop backend on port 8000 and exits before returning a result.
    # It is a no-op for normal source runs.
    mp.freeze_support()
    selected = list(sys.argv[1:] if arguments is None else arguments)
    if selected == ["--mcp-stdio"]:
        run_mcp_stdio()
        return
    if selected:
        raise SystemExit(f"KnowledgeHub 桌面后端不支持参数：{' '.join(selected)}")
    run_api()


if __name__ == "__main__":
    main()

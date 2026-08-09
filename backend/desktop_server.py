"""Desktop entry point bundled by PyInstaller for the Electron shell."""

from __future__ import annotations

import os
import multiprocessing as mp

import uvicorn

from main import app


LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def backend_host() -> str:
    """Keep the desktop-only API private even when an environment leaks in."""
    host = os.environ.get("KNOWLEDGEHUB_BACKEND_HOST", "127.0.0.1").strip()
    if host not in LOOPBACK_HOSTS:
        raise SystemExit("KnowledgeHub 桌面后端仅允许监听本机回环地址")
    return host


def main() -> None:
    # PyInstaller re-executes this executable for ``spawn`` workers.  Without
    # this call an MLX transcription worker starts Uvicorn again, collides with
    # the desktop backend on port 8000 and exits before returning a result.
    # It is a no-op for normal source runs.
    mp.freeze_support()
    uvicorn.run(
        app,
        host=backend_host(),
        port=int(os.environ.get("KNOWLEDGEHUB_BACKEND_PORT", "8000")),
        log_level="info",
    )


if __name__ == "__main__":
    main()

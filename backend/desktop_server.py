"""Desktop entry point bundled by PyInstaller for the Electron shell."""

from __future__ import annotations

import os

import uvicorn

from main import app


def main() -> None:
    uvicorn.run(
        app,
        host=os.environ.get("KNOWLEDGEHUB_BACKEND_HOST", "127.0.0.1"),
        port=int(os.environ.get("KNOWLEDGEHUB_BACKEND_PORT", "8000")),
        log_level="info",
    )


if __name__ == "__main__":
    main()

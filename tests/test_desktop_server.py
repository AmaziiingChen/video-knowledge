from __future__ import annotations

import desktop_server


def test_desktop_entrypoint_handles_frozen_multiprocessing_before_uvicorn(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(desktop_server.mp, "freeze_support", lambda: calls.append("freeze"))
    monkeypatch.setattr(desktop_server.uvicorn, "run", lambda *_args, **_kwargs: calls.append("uvicorn"))

    desktop_server.main()

    assert calls == ["freeze", "uvicorn"]

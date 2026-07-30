from __future__ import annotations

from services.github_pages_deployment import _direct_git_command, _direct_network_environment


def test_github_pages_deployment_ignores_inherited_proxy_environment(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7897")
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:7897")
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:7897")
    monkeypatch.setenv("NO_PROXY", "localhost")
    monkeypatch.setenv("GH_TOKEN", "test-token")

    environment = _direct_network_environment()

    assert not {key for key in environment if key.upper().endswith("PROXY")}
    assert environment["GH_TOKEN"] == "test-token"


def test_github_pages_deployment_overrides_git_global_proxy_configuration():
    command = _direct_git_command(["git", "push", "origin", "gh-pages"])

    assert command == [
        "git",
        "-c",
        "http.proxy=",
        "-c",
        "https.proxy=",
        "-c",
        "http.https://github.com.proxy=",
        "push",
        "origin",
        "gh-pages",
    ]

from services.network_policy import (
    direct_browser_launch_options,
    direct_network_environment,
    direct_requests_session,
)


def test_direct_network_environment_removes_proxy_configuration():
    result = direct_network_environment(
        {
            "PATH": "/usr/bin",
            "HTTP_PROXY": "http://127.0.0.1:7897",
            "https_proxy": "http://127.0.0.1:7897",
            "NO_PROXY": "localhost",
        }
    )

    assert result == {"PATH": "/usr/bin"}


def test_direct_requests_session_ignores_environment_proxy():
    session = direct_requests_session()
    try:
        assert session.trust_env is False
    finally:
        session.close()


def test_direct_browser_launch_options_disable_environment_and_os_proxy(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:7897")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7897")

    options = direct_browser_launch_options("--disable-blink-features=AutomationControlled")

    assert "HTTP_PROXY" not in options["env"]
    assert "HTTPS_PROXY" not in options["env"]
    assert options["args"] == [
        "--no-proxy-server",
        "--disable-blink-features=AutomationControlled",
    ]

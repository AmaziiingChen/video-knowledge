"""Network policy shared by local-media download providers.

Media downloads are local-first operations.  They must not silently change
their route because the desktop process happens to have proxy variables in
its environment.  Features that genuinely require a proxy own an explicit,
separate configuration (for example Telegram).
"""

from __future__ import annotations

import os
from collections.abc import Mapping

import requests


_PROXY_ENVIRONMENT_NAMES = (
    "ALL_PROXY",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "all_proxy",
    "http_proxy",
    "https_proxy",
    "no_proxy",
)


def direct_network_environment(environment: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return an environment that cannot implicitly route traffic via a proxy."""
    result = dict(os.environ if environment is None else environment)
    for name in _PROXY_ENVIRONMENT_NAMES:
        result.pop(name, None)
    return result


def direct_requests_session() -> requests.Session:
    """Create a Requests session whose transport is always direct."""
    session = requests.Session()
    session.trust_env = False
    return session


def direct_browser_launch_options(*arguments: str) -> dict[str, object]:
    """Return Playwright launch options that bypass env and OS proxy settings."""
    return {
        "env": direct_network_environment(),
        "args": ["--no-proxy-server", *arguments],
    }

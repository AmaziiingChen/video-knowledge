"""Exercise a packaged KnowledgeHub desktop app with an isolated profile."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from macos_desktop_runtime import (
    CdpClient,
    app_executable,
    free_loopback_port,
    launch_app,
    redact,
    require_port_available,
    terminate,
    wait_for_renderer,
)

FIXTURE_TITLE = "KnowledgeHub 桌面冒烟资料"
FIXTURE_MARKDOWN = f"# {FIXTURE_TITLE}\n\n这是发布候选的隔离本地 Markdown 验证资料。\n"


def renderer_expression(body: str) -> str:
    return f"""(async () => {{
      const desktop = window.knowledgeHubDesktop
      if (!desktop || !desktop.isDesktop) throw new Error('preload bridge 不可用')
      const ready = await desktop.waitForBackend()
      if (!ready) throw new Error('bundled backend 未就绪')
      const token = await desktop.backendAccessToken()
      if (!token) throw new Error('未取得桌面后端 capability')
      {body}
    }})()"""


def import_fixture(client: CdpClient) -> dict[str, str]:
    body = json.dumps(FIXTURE_MARKDOWN, ensure_ascii=False)
    title = json.dumps(FIXTURE_TITLE, ensure_ascii=False)
    value = client.evaluate(renderer_expression(f"""
      const form = new FormData()
      form.append('file', new File([{body}], 'knowledgehub-release-smoke.md', {{ type: 'text/markdown' }}))
      const response = await fetch('http://127.0.0.1:8000/api/content/import-markdown', {{
        method: 'POST', headers: {{ 'X-KnowledgeHub-Token': token }}, body: form,
      }})
      const payload = await response.json()
      if (!response.ok || !payload.id || payload.title !== {title}) {{
        throw new Error(`fixture import failed: ${{response.status}} ${{JSON.stringify(payload)}}`)
      }}
      return {{ id: payload.id, title: payload.title }}
    """))
    if not isinstance(value, dict) or not value.get("id"):
        raise RuntimeError("renderer 未返回导入资料标识")
    return {"id": str(value["id"]), "title": str(value.get("title") or FIXTURE_TITLE)}


def verify_persisted_and_open(client: CdpClient, item: dict[str, str]) -> None:
    item_id = json.dumps(item["id"])
    title = json.dumps(item["title"], ensure_ascii=False)
    value = client.evaluate(renderer_expression(f"""
      const response = await fetch(`http://127.0.0.1:8000/api/content/item/${{encodeURIComponent({item_id})}}`, {{
        headers: {{ 'X-KnowledgeHub-Token': token }},
      }})
      const payload = await response.json()
      if (!response.ok || payload.id !== {item_id} || payload.title !== {title}) {{
        throw new Error(`fixture persistence failed: ${{response.status}} ${{JSON.stringify(payload)}}`)
      }}
      const button = [...document.querySelectorAll('.sidebar-tree-row-main')]
        .find((element) => element.textContent?.trim() === {title})
      if (!button) throw new Error('导入资料未出现在资料库树')
      button.click()
      await new Promise((resolve) => setTimeout(resolve, 250))
      const tab = [...document.querySelectorAll('.workspace-tab-label')]
        .find((element) => element.textContent?.trim() === {title})
      if (!tab) throw new Error('导入资料未在工作区打开')
      return {{ title: tab.textContent?.trim() }}
    """))
    if not isinstance(value, dict) or value.get("title") != item["title"]:
        raise RuntimeError("导入资料未能在工作区打开")


def open_renderer(process, debugging_port: int) -> CdpClient:
    page = wait_for_renderer(debugging_port, process)
    debugger_url = str(page.get("webSocketDebuggerUrl") or "")
    if not debugger_url:
        raise RuntimeError("renderer 未提供调试连接")
    return CdpClient(debugger_url)


def run_smoke(app: Path) -> dict[str, object]:
    executable = app_executable(app)
    require_port_available(8000)
    debugging_port = free_loopback_port()
    report: dict[str, object]
    with tempfile.TemporaryDirectory(prefix="knowledgehub-desktop-smoke-") as temporary:
        profile = Path(temporary) / "profile"
        process = launch_app(executable, profile, debugging_port)
        item: dict[str, str] | None = None
        first_shutdown_clean = False
        try:
            client = open_renderer(process, debugging_port)
            try:
                item = import_fixture(client)
            finally:
                client.close()

            first_shutdown_clean = terminate(process)
            require_port_available(8000)
            process = launch_app(executable, profile, debugging_port)
            client = open_renderer(process, debugging_port)
            try:
                verify_persisted_and_open(client, item)
            finally:
                client.close()
            report = {
                "status": "ok",
                "renderer": "ready",
                "bundled_backend": "ready",
                "fixture_import": "ok",
                "workspace_open": "ok",
                "restart_persistence": "ok",
                "first_shutdown": "graceful" if first_shutdown_clean else "forced-after-timeout",
                "profile": "isolated-temporary",
            }
        finally:
            terminate(process)
            # TemporaryDirectory performs the actual removal. This explicit
            # check makes cleanup a test result, not an undocumented side effect.
            if profile.exists():
                shutil.rmtree(profile, ignore_errors=True)
            require_port_available(8000)
    report["temporary_profile_cleanup"] = "ok"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True, type=Path)
    parser.add_argument("--profile", default="release-smoke", help="evidence label only; data is always temporary")
    parser.add_argument("--report", required=True, type=Path)
    arguments = parser.parse_args()
    report = run_smoke(arguments.app)
    report["profile_label"] = arguments.profile
    destination = arguments.report.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(redact(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

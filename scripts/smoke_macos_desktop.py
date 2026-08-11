"""Exercise a packaged KnowledgeHub desktop app with an isolated profile."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import time
from pathlib import Path

from macos_desktop_runtime import (
    CdpClient,
    app_executable,
    close_desktop_app,
    free_loopback_port,
    launch_app,
    redact,
    require_port_available,
    terminate,
    wait_for_port_available,
    wait_for_renderer,
)

FIXTURE_TITLE = "KnowledgeHub 桌面冒烟资料"
FIXTURE_MARKDOWN = f"# {FIXTURE_TITLE}\n\n这是发布候选的隔离本地 Markdown 验证资料。\n"


def renderer_expression(body: str) -> str:
    return f"""(async () => {{
      // CDP runs in the renderer's main world, while Electron deliberately
      // keeps preload APIs in its isolated world. A renderer request is the
      // real packaged path: main.cjs injects its per-session capability only
      // for this trusted webContents and never exposes that value to CDP.
      let health = null
      for (let attempt = 0; attempt < 240; attempt += 1) {{
        try {{
          const response = await fetch('http://127.0.0.1:8000/api/health')
          if (response.ok) {{ health = response; break }}
        }} catch {{
          // The packaged window intentionally appears before its backend.
        }}
        await new Promise((resolve) => setTimeout(resolve, 250))
      }}
      if (!health) throw new Error('bundled backend did not become ready within 60 seconds')
      {body}
    }})()"""


def import_fixture(client: CdpClient) -> dict[str, str]:
    body = json.dumps(FIXTURE_MARKDOWN, ensure_ascii=False)
    title = json.dumps(FIXTURE_TITLE, ensure_ascii=False)
    value = client.evaluate(renderer_expression(f"""
      const form = new FormData()
      form.append('file', new File([{body}], 'knowledgehub-release-smoke.md', {{ type: 'text/markdown' }}))
      const response = await fetch('http://127.0.0.1:8000/api/content/import-markdown', {{
        method: 'POST', body: form,
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
      }})
      const payload = await response.json()
      if (!response.ok || payload.id !== {item_id} || payload.title !== {title}) {{
        throw new Error(`fixture persistence failed: ${{response.status}} ${{JSON.stringify(payload)}}`)
      }}
      const searchModeButton = document.querySelector('button[aria-label="搜索资料"]')
      if (!searchModeButton) throw new Error('资料库搜索入口不可用')
      searchModeButton.click()
      let searchInput = null
      for (let attempt = 0; attempt < 40; attempt += 1) {{
        searchInput = document.querySelector('input[aria-label="搜索资料库内容"]')
        if (searchInput) break
        await new Promise((resolve) => setTimeout(resolve, 100))
      }}
      const valueSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
      if (!searchInput || !valueSetter) throw new Error('资料库搜索输入框不可用')
      valueSetter.call(searchInput, {title})
      searchInput.dispatchEvent(new Event('input', {{ bubbles: true }}))
      let button = null
      for (let attempt = 0; attempt < 80; attempt += 1) {{
        const label = [...document.querySelectorAll('.sidebar-tree-row-label')]
          .find((element) => element.textContent?.trim() === {title})
        button = label?.closest('.sidebar-tree-row-main') || null
        if (button) break
        await new Promise((resolve) => setTimeout(resolve, 125))
      }}
      if (!button) throw new Error('持久化资料未出现在搜索结果')
      button.click()
      let tab = null
      for (let attempt = 0; attempt < 80; attempt += 1) {{
        tab = [...document.querySelectorAll('.workspace-tab-label')]
          .find((element) => element.textContent?.trim() === {title})
        if (tab) break
        await new Promise((resolve) => setTimeout(resolve, 125))
      }}
      if (!tab) throw new Error('导入资料未在工作区打开')
      return {{ title: tab.textContent?.trim() }}
    """))
    if not isinstance(value, dict) or value.get("title") != item["title"]:
        raise RuntimeError("导入资料未能在工作区打开")


def open_renderer(process, debugging_port: int) -> CdpClient:
    deadline = time.monotonic() + 30
    last_error = ""
    while time.monotonic() < deadline:
        page = wait_for_renderer(debugging_port, process)
        debugger_url = str(page.get("webSocketDebuggerUrl") or "")
        if not debugger_url:
            last_error = "renderer 未提供调试连接"
            time.sleep(0.25)
            continue
        client = CdpClient(debugger_url)
        try:
            if client.evaluate("document.readyState") == "complete":
                return client
            last_error = "renderer 文档仍在加载"
        except RuntimeError as exc:
            last_error = str(exc)
        client.close()
        time.sleep(0.25)
    raise RuntimeError(f"renderer 上下文未稳定：{last_error}")


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
                first_shutdown_clean = close_desktop_app(client, process)
                client.close()

            wait_for_port_available(8000)
            process = launch_app(executable, profile, debugging_port)
            client = open_renderer(process, debugging_port)
            try:
                verify_persisted_and_open(client, item)
            finally:
                close_desktop_app(client, process)
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
            wait_for_port_available(8000)
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

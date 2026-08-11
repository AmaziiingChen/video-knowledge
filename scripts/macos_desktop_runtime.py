"""Small standard-library helpers for isolated packaged macOS desktop checks."""

from __future__ import annotations

import base64
import json
import os
import secrets
import socket
import struct
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen


def app_executable(app: Path) -> Path:
    resolved = app.expanduser().resolve()
    candidate = resolved / "Contents" / "MacOS" / "KnowledgeHub"
    if not candidate.is_file():
        raise RuntimeError("KnowledgeHub.app 缺少主可执行文件")
    return candidate


def free_loopback_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def require_port_available(port: int) -> None:
    with socket.socket() as listener:
        try:
            listener.bind(("127.0.0.1", port))
        except OSError as exc:
            raise RuntimeError(f"本机端口 {port} 已被占用；隔离桌面验证不能复用现有后端") from exc


def wait_for_port_available(port: int, timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    last_error: RuntimeError | None = None
    while time.monotonic() < deadline:
        try:
            require_port_available(port)
            return
        except RuntimeError as exc:
            last_error = exc
            time.sleep(0.1)
    raise last_error or RuntimeError(f"本机端口 {port} 未能释放")


def launch_app(executable: Path, profile: Path, debugging_port: int) -> subprocess.Popen[str]:
    profile.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update({
        "HOME": str(profile / "home"),
        "TMPDIR": str(profile / "tmp"),
        "KNOWLEDGEHUB_USER_DATA_DIR": str(profile / "electron-user-data"),
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
    })
    Path(environment["HOME"]).mkdir(parents=True, exist_ok=True)
    Path(environment["TMPDIR"]).mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(
        [
            str(executable),
            f"--user-data-dir={profile / 'chromium'}",
            f"--remote-debugging-port={debugging_port}",
            "--no-first-run",
        ],
        cwd=executable.parent,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )


def wait_for_renderer(port: int, process: subprocess.Popen[str], timeout: float = 60) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    endpoint = f"http://127.0.0.1:{port}/json/list"
    last_error = ""
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout else ""
            raise RuntimeError(f"桌面应用提前退出：{output[-2000:]}")
        try:
            with urlopen(endpoint, timeout=1) as response:
                pages = json.loads(response.read())
            for page in pages:
                if str(page.get("url", "")).startswith("knowledgehub://app/"):
                    return page
            last_error = "调试端口已就绪，但尚未出现 KnowledgeHub renderer"
        except (OSError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = str(exc)
        time.sleep(0.25)
    raise RuntimeError(f"桌面 renderer 在 {timeout:.0f} 秒内未就绪：{last_error}")


class CdpClient:
    """Minimal CDP WebSocket client; avoids adding a release-only dependency."""

    def __init__(self, debugger_url: str) -> None:
        parsed = urlsplit(debugger_url)
        if parsed.scheme != "ws" or parsed.hostname != "127.0.0.1" or parsed.port is None:
            raise RuntimeError("调试端点不是预期的本机回环 WebSocket")
        self._socket = socket.create_connection((parsed.hostname, parsed.port), timeout=10)
        self._socket.settimeout(20)
        key = base64.b64encode(secrets.token_bytes(16)).decode("ascii")
        request = (
            f"GET {parsed.path or '/'} HTTP/1.1\r\n"
            f"Host: {parsed.hostname}:{parsed.port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self._socket.sendall(request.encode("ascii"))
        response = self._read_headers()
        if not response.startswith("HTTP/1.1 101"):
            self.close()
            raise RuntimeError(f"无法连接 renderer 调试端点：{response.splitlines()[0] if response else '无响应'}")
        self._next_id = 1

    def _read_headers(self) -> str:
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = self._socket.recv(1024)
            if not chunk:
                break
            data += chunk
        return data.decode("iso-8859-1", errors="replace")

    def _read_exactly(self, size: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < size:
            chunk = self._socket.recv(size - len(chunks))
            if not chunk:
                raise RuntimeError("renderer 调试连接意外关闭")
            chunks.extend(chunk)
        return bytes(chunks)

    def _send_text(self, text: str) -> None:
        payload = text.encode("utf-8")
        mask = secrets.token_bytes(4)
        header = bytearray([0x81])
        size = len(payload)
        if size < 126:
            header.append(0x80 | size)
        elif size <= 0xFFFF:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", size))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", size))
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self._socket.sendall(bytes(header) + mask + masked)

    def _receive_text(self) -> str:
        first, second = self._read_exactly(2)
        opcode = first & 0x0F
        size = second & 0x7F
        if size == 126:
            size = struct.unpack("!H", self._read_exactly(2))[0]
        elif size == 127:
            size = struct.unpack("!Q", self._read_exactly(8))[0]
        masked = bool(second & 0x80)
        mask = self._read_exactly(4) if masked else b""
        payload = self._read_exactly(size)
        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        if opcode == 0x8:
            raise RuntimeError("renderer 调试连接已关闭")
        if opcode == 0x9:
            self._socket.sendall(b"\x8a" + bytes([len(payload)]) + payload)
            return self._receive_text()
        if opcode != 0x1:
            return self._receive_text()
        return payload.decode("utf-8")

    def call(self, method: str, params: dict[str, object] | None = None) -> dict[str, object]:
        request_id = self._next_id
        self._next_id += 1
        self._send_text(json.dumps({
            "id": request_id,
            "method": method,
            "params": params or {},
        }))
        while True:
            response = json.loads(self._receive_text())
            if response.get("id") != request_id:
                continue
            if "error" in response:
                raise RuntimeError(f"renderer CDP 请求失败：{response['error']}")
            return response.get("result", {})

    def evaluate(self, expression: str) -> object:
        response = self.call("Runtime.evaluate", {
            "expression": expression, "awaitPromise": True, "returnByValue": True,
        })
        result = response.get("result", {})
        if "exceptionDetails" in response:
            raise RuntimeError(f"renderer 脚本失败：{response['exceptionDetails'].get('text', '未知错误')}")
        return result.get("value")

    def close(self) -> None:
        try:
            self._socket.close()
        except OSError:
            pass


def terminate(process: subprocess.Popen[str], timeout: float = 15) -> bool:
    if process.poll() is not None:
        return True
    process.terminate()
    try:
        process.wait(timeout=timeout)
        return True
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
        return False


def close_desktop_app(client: CdpClient, process: subprocess.Popen[str], timeout: float = 15) -> bool:
    """Request Electron's normal app quit before using a failure-only signal."""
    try:
        client.call("Browser.close")
    except RuntimeError:
        # A socket close after Browser.close is expected from some Chromium versions.
        pass
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return True
        time.sleep(0.1)
    return terminate(process, timeout=5)


def redact(value: object, *secrets_to_remove: str) -> object:
    serialized = json.dumps(value, ensure_ascii=False)
    for secret in secrets_to_remove:
        if secret:
            serialized = serialized.replace(secret, "[redacted]")
    return json.loads(serialized)

"""Create and heartbeat the source launcher's private MCP bridge session."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import signal
import stat
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

TOKEN_FILENAME = "mcp-bridge-token"
LEASE_FILENAME = "mcp-bridge-lease.json"


def secure_run_directory(run_dir: Path) -> Path:
    resolved = run_dir.expanduser()
    if not resolved.is_absolute():
        resolved = (Path.cwd() / resolved).absolute()
    resolved.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = resolved.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise RuntimeError("MCP bridge 运行目录不是安全目录")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise RuntimeError("MCP bridge 运行目录不属于当前用户")
    resolved.chmod(0o700)
    if resolved.lstat().st_mode & 0o077:
        raise RuntimeError("MCP bridge 运行目录权限过宽")
    return resolved


def _safe_existing_file(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise RuntimeError(f"拒绝覆盖不安全的 MCP bridge 文件：{path.name}")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise RuntimeError("MCP bridge 文件不属于当前用户")
    if info.st_mode & 0o077:
        raise RuntimeError("MCP bridge 文件权限过宽")
    return True


def atomic_write(path: Path, content: str) -> None:
    directory = secure_run_directory(path.parent)
    _safe_existing_file(path)
    temporary = directory / f".{path.name}.{secrets.token_hex(12)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", closefd=False) as target:
            target.write(content)
            target.flush()
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def safe_unlink(path: Path) -> None:
    if _safe_existing_file(path):
        path.unlink()


def validated_loopback_api_base(value: str) -> str:
    parsed = urlsplit(value.strip())
    try:
        port = parsed.port
    except ValueError as exc:
        raise RuntimeError("MCP bridge API 地址无效") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != "/api"
        or port is None
    ):
        raise RuntimeError("MCP bridge API 必须是明确端口的本机回环地址")
    host = "[::1]" if parsed.hostname == "::1" else "127.0.0.1"
    return f"http://{host}:{port}/api"


def lease_content(session_id: str, api_base: str) -> str:
    return json.dumps(
        {
            "session_id": session_id,
            "updated_at": time.time(),
            "api_base": validated_loopback_api_base(api_base),
        },
        separators=(",", ":"),
    ) + "\n"


def create_session(
    run_dir: Path,
    api_base: str = "http://127.0.0.1:8000/api",
) -> dict[str, str]:
    directory = secure_run_directory(run_dir)
    token_file = directory / TOKEN_FILENAME
    lease_file = directory / LEASE_FILENAME
    safe_unlink(lease_file)
    safe_unlink(token_file)
    token = secrets.token_urlsafe(32)
    session_id = str(uuid.uuid4())
    try:
        atomic_write(token_file, f"{token}\n")
        atomic_write(lease_file, lease_content(session_id, api_base))
    except Exception:
        safe_unlink(lease_file)
        safe_unlink(token_file)
        raise
    return {
        "token": token,
        "session_id": session_id,
        "token_file": str(token_file),
        "lease_file": str(lease_file),
        "api_base": validated_loopback_api_base(api_base),
    }


def validate_session(run_dir: Path, *, max_age: float = 15.0) -> bool:
    directory = secure_run_directory(run_dir)
    token_file = directory / TOKEN_FILENAME
    lease_file = directory / LEASE_FILENAME
    if not _safe_existing_file(token_file) or not _safe_existing_file(lease_file):
        return False
    token = token_file.read_text(encoding="ascii").strip()
    if not 32 <= len(token) <= 128 or not re.fullmatch(r"[A-Za-z0-9_-]+", token):
        return False
    try:
        lease = json.loads(lease_file.read_text(encoding="utf-8"))
        age = time.time() - float(lease["updated_at"])
        validated_loopback_api_base(str(lease["api_base"]))
    except (KeyError, TypeError, ValueError, RuntimeError, json.JSONDecodeError):
        return False
    return bool(lease.get("session_id")) and -5.0 <= age <= max_age


def cleanup_session(run_dir: Path) -> None:
    directory = secure_run_directory(run_dir)
    safe_unlink(directory / LEASE_FILENAME)
    safe_unlink(directory / TOKEN_FILENAME)


def lease_belongs_to_session(lease_file: Path, session_id: str) -> bool:
    if not _safe_existing_file(lease_file):
        return False
    try:
        payload = json.loads(lease_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return hmac_compare(payload.get("session_id"), session_id)


def hmac_compare(actual: object, expected: str) -> bool:
    return isinstance(actual, str) and secrets.compare_digest(actual, expected)


def heartbeat(lease_file: Path, session_id: str, api_base: str, interval: float) -> None:
    running = True

    def stop(_signum, _frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while running:
        # A newer launcher may have atomically replaced this lease. An old
        # heartbeat must exit instead of overwriting the new session id.
        if not lease_belongs_to_session(lease_file, session_id):
            return
        atomic_write(lease_file, lease_content(session_id, api_base))
        time.sleep(interval)


def main() -> int:
    parser = argparse.ArgumentParser(description="管理 KnowledgeHub MCP bridge 会话")
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--run-dir", required=True, type=Path)
    create.add_argument("--api-base", default="http://127.0.0.1:8000/api")
    validate = subparsers.add_parser("validate")
    validate.add_argument("--run-dir", required=True, type=Path)
    cleanup = subparsers.add_parser("cleanup")
    cleanup.add_argument("--run-dir", required=True, type=Path)
    pulse = subparsers.add_parser("heartbeat")
    pulse.add_argument("--lease-file", required=True, type=Path)
    pulse.add_argument("--session-id", required=True)
    pulse.add_argument("--api-base", default="http://127.0.0.1:8000/api")
    pulse.add_argument("--interval", type=float, default=5.0)
    arguments = parser.parse_args()

    if arguments.command == "create":
        print(
            json.dumps(
                create_session(arguments.run_dir, arguments.api_base),
                separators=(",", ":"),
            )
        )
    elif arguments.command == "validate":
        return 0 if validate_session(arguments.run_dir) else 1
    elif arguments.command == "cleanup":
        cleanup_session(arguments.run_dir)
    else:
        heartbeat(
            arguments.lease_file,
            arguments.session_id,
            arguments.api_base,
            arguments.interval,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

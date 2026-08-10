"""Validate an unsigned Apple Silicon KnowledgeHub DMG and write its checksum."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import re
import socket
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_JSON = ROOT / "frontend" / "package.json"
EXPECTED_BUNDLE_ID = "com.knowledgehub.desktop"
MAX_DMG_BYTES = 1_200 * 1024 * 1024
MAX_BACKEND_BYTES = 650 * 1024 * 1024
MODEL_SUFFIXES = {".ckpt", ".gguf", ".pt", ".pth", ".safetensors"}
MODEL_FILE_PATTERN = re.compile(r"^(ggml-|whisper-).+\.bin$", re.IGNORECASE)


def run(*command: str, capture: bool = False) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        command,
        check=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def mounted_volume(dmg: Path) -> Path:
    result = run(
        "hdiutil",
        "attach",
        str(dmg),
        "-readonly",
        "-nobrowse",
        "-noautoopen",
        "-plist",
        capture=True,
    )
    payload = plistlib.loads(result.stdout)
    mount_points = [
        entity["mount-point"]
        for entity in payload.get("system-entities", [])
        if entity.get("mount-point")
    ]
    if len(mount_points) != 1:
        raise RuntimeError(f"expected one mounted DMG volume, found {mount_points}")
    return Path(mount_points[0])


def executable_architectures(path: Path) -> set[str]:
    result = run("lipo", "-archs", str(path), capture=True)
    return set(result.stdout.decode("utf-8").split())


def validate_no_developer_id(app: Path) -> str:
    result = subprocess.run(
        ["codesign", "-dv", "--verbose=4", str(app)],
        check=False,
        capture_output=True,
        text=True,
    )
    details = f"{result.stdout}\n{result.stderr}"
    has_developer_authority = "Authority=Developer ID Application" in details
    has_team_identifier = (
        "TeamIdentifier=" in details and "TeamIdentifier=not set" not in details
    )
    if has_developer_authority or has_team_identifier:
        raise RuntimeError("release unexpectedly contains a Developer ID identity")
    return "ad-hoc-or-unsigned"


def smoke_test_backend(executable: Path) -> dict[str, object]:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = int(listener.getsockname()[1])

    token = "knowledgehub-release-smoke-token"
    with tempfile.TemporaryDirectory(prefix="knowledgehub-release-smoke-") as temporary:
        temporary_path = Path(temporary)
        environment = os.environ.copy()
        environment.update({
            "APP_VERSION": json.loads(PACKAGE_JSON.read_text())["version"],
            "DATA_DIR": str(temporary_path / "data"),
            "KNOWLEDGEHUB_BACKEND_HOST": "127.0.0.1",
            "KNOWLEDGEHUB_BACKEND_PORT": str(port),
            "KNOWLEDGEHUB_ENV_FILE": str(temporary_path / "settings.env"),
            "KNOWLEDGEHUB_INSTANCE_TOKEN": token,
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
        })
        process = subprocess.Popen(
            [str(executable)],
            cwd=executable.parent,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        started = time.monotonic()
        response_payload: dict[str, object] | None = None
        try:
            deadline = started + 60
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    output = process.stdout.read() if process.stdout else ""
                    raise RuntimeError(
                        f"bundled backend exited with {process.returncode}: {output[-2000:]}"
                    )
                try:
                    request = urllib.request.Request(
                        f"http://127.0.0.1:{port}/api/health",
                        headers={"x-knowledgehub-token": token},
                    )
                    with urllib.request.urlopen(request, timeout=1) as response:
                        response_payload = json.loads(response.read())
                    break
                except (OSError, TimeoutError, json.JSONDecodeError):
                    time.sleep(0.25)
            if response_payload is None:
                raise RuntimeError("bundled backend did not become healthy within 60 seconds")
            expected = {
                "status": "ok",
                "service": "knowledgehub-backend",
                "instance_token": token,
            }
            if any(response_payload.get(key) != value for key, value in expected.items()):
                raise RuntimeError(f"unexpected backend health response: {response_payload}")
            return {
                "status": "ok",
                "startup_seconds": round(time.monotonic() - started, 2),
            }
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def smoke_test_mcp_entry(executable: Path) -> dict[str, object]:
    """Exercise the frozen stdio entry and its scoped backend capability end to end."""
    from smoke_macos_mcp import run_smoke

    return run_smoke(command=str(executable), prefix_args=[], cwd=executable.parent)


def validate_app(volume: Path, expected_version: str) -> dict[str, object]:
    app = volume / "KnowledgeHub.app"
    if not app.is_dir():
        raise RuntimeError("DMG does not contain KnowledgeHub.app at its root")

    contents = app / "Contents"
    info_path = contents / "Info.plist"
    with info_path.open("rb") as source:
        info = plistlib.load(source)
    if info.get("CFBundleIdentifier") != EXPECTED_BUNDLE_ID:
        raise RuntimeError(f"unexpected bundle identifier: {info.get('CFBundleIdentifier')}")
    if str(info.get("CFBundleShortVersionString")) != expected_version:
        raise RuntimeError(
            f"app version {info.get('CFBundleShortVersionString')} does not match {expected_version}"
        )

    app_executable = contents / "MacOS" / str(info.get("CFBundleExecutable") or "KnowledgeHub")
    backend = contents / "Resources" / "backend" / "knowledgehub-backend"
    backend_executable = backend / "knowledgehub-backend"
    required = [app_executable, contents / "Resources" / "app.asar", backend_executable]
    missing = [str(path.relative_to(app)) for path in required if not path.exists()]
    if missing:
        raise RuntimeError(f"release is missing required files: {', '.join(missing)}")

    for executable in (app_executable, backend_executable):
        architectures = executable_architectures(executable)
        if architectures != {"arm64"}:
            raise RuntimeError(
                f"{executable.name} must be arm64-only, found {sorted(architectures)}"
            )

    backend_bytes = directory_size(backend)
    if backend_bytes > MAX_BACKEND_BYTES:
        raise RuntimeError(
            f"bundled backend grew to {backend_bytes / 1024 / 1024:.1f} MiB; "
            f"limit is {MAX_BACKEND_BYTES / 1024 / 1024:.0f} MiB"
        )

    forbidden_runtime_paths = [
        contents / "Resources" / "data",
        contents / "Resources" / ".env",
        contents / "Resources" / "app.db",
    ]
    present_runtime_paths = [str(path.relative_to(app)) for path in forbidden_runtime_paths if path.exists()]
    if present_runtime_paths:
        raise RuntimeError(f"release contains local runtime data: {', '.join(present_runtime_paths)}")

    bundled_models = [
        path.relative_to(app).as_posix()
        for path in contents.rglob("*")
        if path.is_file()
        and (path.suffix.lower() in MODEL_SUFFIXES or MODEL_FILE_PATTERN.match(path.name))
    ]
    if bundled_models:
        raise RuntimeError(f"release contains model weights: {bundled_models[:5]}")

    return {
        "app": app.name,
        "bundle_id": info["CFBundleIdentifier"],
        "version": expected_version,
        "architecture": "arm64",
        "developer_id": validate_no_developer_id(app),
        "backend_mib": round(backend_bytes / 1024 / 1024, 1),
        "backend_smoke": smoke_test_backend(backend_executable),
        "mcp_entry_smoke": smoke_test_mcp_entry(backend_executable),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dmg", type=Path, required=True)
    parser.add_argument("--expected-version", default="")
    arguments = parser.parse_args()

    dmg = arguments.dmg.expanduser().resolve()
    if not dmg.is_file():
        raise SystemExit(f"DMG not found: {dmg}")
    package_version = str(json.loads(PACKAGE_JSON.read_text())["version"])
    expected_version = arguments.expected_version or package_version
    if package_version != expected_version:
        raise SystemExit(
            f"package version {package_version} does not match expected version {expected_version}"
        )
    expected_name = f"KnowledgeHub-{expected_version}-arm64.dmg"
    if dmg.name != expected_name:
        raise SystemExit(f"expected artifact {expected_name}, found {dmg.name}")
    if dmg.stat().st_size > MAX_DMG_BYTES:
        raise SystemExit(
            f"DMG grew to {dmg.stat().st_size / 1024 / 1024:.1f} MiB; "
            f"limit is {MAX_DMG_BYTES / 1024 / 1024:.0f} MiB"
        )

    run("hdiutil", "verify", str(dmg))
    volume = mounted_volume(dmg)
    try:
        report = validate_app(volume, expected_version)
    finally:
        run("hdiutil", "detach", str(volume), "-force")

    checksum = sha256(dmg)
    checksum_path = dmg.with_suffix(f"{dmg.suffix}.sha256")
    checksum_path.write_text(f"{checksum}  {dmg.name}\n", encoding="utf-8")
    report.update({
        "dmg": dmg.name,
        "dmg_mib": round(dmg.stat().st_size / 1024 / 1024, 1),
        "sha256": checksum,
        "checksum_file": checksum_path.name,
    })
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

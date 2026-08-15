"""On-demand runtime components that are intentionally excluded from the app bundle."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
from typing import Any

from config import settings
from services.network_policy import direct_network_environment, direct_requests_session

# Hugging Face Xet transfers can remain stuck behind local HTTP proxies after
# reporting nearly all bytes as received.  The model files are small enough for
# the regular HTTPS downloader, which resumes partial files reliably and gives
# the desktop an honest completion state.  This must be set before importing
# ``huggingface_hub`` so its constants read the intended value.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")


MODEL_ESTIMATED_BYTES = {
    "tiny": 80 * 1024**2,
    "base": 150 * 1024**2,
    "small": 500 * 1024**2,
    "medium": 1500 * 1024**2,
    "large-v3": 3000 * 1024**2,
}
# Model downloads are the one optional runtime download that benefits from a
# mainland-friendly mirror.  It is deliberately scoped here: media download,
# browser login and collectors keep their existing direct-network policy.
# Users who run a private Hub mirror can override the primary endpoint through
# ``HUGGING_FACE_HUB_ENDPOINT`` in the desktop settings environment file.
HUGGING_FACE_HUB_ENDPOINT = str(
    getattr(settings, "hugging_face_hub_endpoint", "https://hf-mirror.com")
).rstrip("/")
HUGGING_FACE_HUB_FALLBACK_ENDPOINT = "https://huggingface.co"
MODELSCOPE_ENDPOINT = "https://modelscope.cn"
MODELSCOPE_REVISION = "master"
FASTER_WHISPER_REPOS = {
    model_name: f"Systran/faster-whisper-{model_name}"
    for model_name in MODEL_ESTIMATED_BYTES
}
# MLX Community's current Whisper repositories use the ``-mlx`` suffix.  The
# former ``mlx-community/whisper-base`` style is not a public repository and
# causes Hugging Face to report a misleading 401/Repository Not Found error.
MLX_WHISPER_REPOS = {
    model_name: f"mlx-community/whisper-{model_name}-mlx"
    for model_name in MODEL_ESTIMATED_BYTES
}

_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}


def faster_whisper_cache_dir() -> Path:
    directory = settings.data_dir / "models" / "faster-whisper"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def mlx_whisper_model_dir(model_name: str) -> Path:
    return settings.data_dir / "models" / "mlx-whisper" / model_name


def _bundled_model_dir(model_name: str, backend: str) -> Path | None:
    """Locate an optional model bundled with a local desktop build.

    Public builds may intentionally omit the sizeable model.  PyInstaller
    exposes bundled resources through ``_MEIPASS``; source runs must never
    probe arbitrary project or user directories for a model cache.
    """

    resource_root = getattr(sys, "_MEIPASS", None)
    if not resource_root:
        return None
    candidate = Path(resource_root) / "preloaded_models" / backend / model_name
    return candidate if candidate.is_dir() else None


def _directory_contains_mlx_model(directory: Path | None) -> bool:
    return bool(directory and (directory / "config.json").is_file() and (
        any(directory.glob("*.safetensors"))
        or any(directory.glob("*.npz"))
    ))


def _bundled_model_available(model_name: str, backend: str) -> bool:
    if backend != "mlx":
        return False
    return _directory_contains_mlx_model(_bundled_model_dir(model_name, backend))


def _job_snapshot(key: str) -> dict[str, Any] | None:
    with _lock:
        job = _jobs.get(key)
        return dict(job) if job else None


def _set_job(key: str, **values: Any) -> None:
    with _lock:
        job = _jobs.setdefault(key, {})
        job.update(values)


def _is_macos() -> bool:
    return platform.system() == "Darwin"


def preferred_asr_backend() -> str:
    """Return the only ASR runtime offered for the current platform.

    MLX is both faster and more memory-efficient on Apple Silicon.  Every
    other supported host uses faster-whisper, which has the portable runtime.
    Keeping this choice in one place prevents a Mac from accumulating both
    model caches through an accidental fallback download.
    """

    return "mlx" if _is_macos() and platform.machine() == "arm64" else "faster_whisper"


def supported_asr_backends() -> list[str]:
    return ["auto", preferred_asr_backend()]


def _browser_candidates() -> list[Path]:
    candidates: list[Path] = []
    if _is_macos():
        candidates.extend([
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
            Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ])
    elif platform.system() == "Windows":
        for root in (os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"), os.environ.get("LOCALAPPDATA")):
            if root:
                candidates.append(Path(root) / "Google/Chrome/Application/chrome.exe")
    else:
        candidates.extend(Path(item) for item in ("/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"))
    return candidates


def _playwright_executable() -> Path | None:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            path = Path(playwright.chromium.executable_path)
            return path if path.is_file() else None
    except Exception:
        return None


def browser_executable() -> str | None:
    playwright_path = _playwright_executable()
    if playwright_path:
        return str(playwright_path)
    for candidate in _browser_candidates():
        if candidate.is_file():
            return str(candidate)
    return None


def browser_status() -> dict[str, Any]:
    executable = browser_executable()
    job = _job_snapshot("browser") or {}
    if executable:
        kind = "Playwright Chromium" if "playwright" in executable.lower() else Path(executable).stem
        return {
            "available": True,
            "state": "ready",
            "detail": f"使用 {kind}",
            "executable_path": executable,
            "job": job,
        }
    return {
        "available": False,
        "state": job.get("state", "missing"),
        "detail": job.get("detail") or "未找到可用于抖音浏览器兜底的 Chromium 或 Chrome",
        "executable_path": "",
        "job": job,
    }


def _playwright_install_command() -> tuple[list[str], dict[str, str]]:
    from playwright._impl._driver import compute_driver_executable, get_driver_env

    node, cli = compute_driver_executable()
    if not (Path(node).is_file() and Path(cli).is_file()):
        raise RuntimeError("Playwright 安装器不完整，无法下载浏览器组件")
    return [node, cli, "install", "chromium"], get_driver_env()


def install_browser() -> dict[str, Any]:
    current = browser_status()
    if current["available"]:
        return current
    existing = _job_snapshot("browser") or {}
    if existing.get("state") == "downloading":
        return browser_status()

    try:
        command, env = _playwright_install_command()
    except Exception as exc:
        _set_job("browser", state="failed", detail=str(exc), updated_at=time.time())
        return browser_status()

    _set_job("browser", state="downloading", detail="正在下载 Chromium 浏览器组件…", updated_at=time.time(), logs=[])

    def run() -> None:
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=direct_network_environment(env),
            )
            lines: list[str] = []
            assert process.stdout is not None
            for line in process.stdout:
                text = line.strip()
                if text:
                    lines.append(text)
                    _set_job("browser", logs=lines[-8:], detail=text, updated_at=time.time())
            if process.wait() != 0 or not browser_executable():
                _set_job("browser", state="failed", detail=lines[-1] if lines else "浏览器组件下载失败", logs=lines[-8:], updated_at=time.time())
                return
            _set_job("browser", state="ready", detail="Chromium 浏览器组件已准备完成", logs=lines[-8:], updated_at=time.time())
        except Exception as exc:
            _set_job("browser", state="failed", detail=f"浏览器组件下载失败：{exc}", updated_at=time.time())

    threading.Thread(target=run, name="knowledgehub-browser-install", daemon=True).start()
    return browser_status()


def _model_repo(model_name: str, backend: str) -> str:
    if backend not in {"mlx", "faster_whisper"}:
        raise ValueError(f"不支持的语音识别后端：{backend}")
    repositories = MLX_WHISPER_REPOS if backend == "mlx" else FASTER_WHISPER_REPOS
    if model_name not in repositories:
        raise ValueError(f"不支持的语音识别模型：{model_name}")
    return repositories[model_name]


def _faster_model_available(model_name: str) -> bool:
    direct_directory = model_storage_path(model_name, "faster_whisper")
    if (
        (direct_directory / "config.json").is_file()
        and (direct_directory / "model.bin").is_file()
    ):
        return True
    try:
        from huggingface_hub import snapshot_download
        snapshot_download(
            _model_repo(model_name, "faster_whisper"),
            cache_dir=str(faster_whisper_cache_dir()),
            local_files_only=True,
        )
        return True
    except Exception:
        return False


def _mlx_model_available(model_name: str) -> bool:
    directory = mlx_whisper_model_dir(model_name)
    # Official MLX Community Whisper models store ``weights.npz`` rather than
    # safetensors.  Accept both formats so a successful local download is not
    # immediately misreported as missing.
    return _directory_contains_mlx_model(directory)


def model_storage_path(model_name: str, backend: str) -> Path:
    """Return the deterministic cache directory for one downloaded model."""

    repository = _model_repo(model_name, backend)
    if backend == "mlx":
        return mlx_whisper_model_dir(model_name)
    return faster_whisper_cache_dir() / f"models--{repository.replace('/', '--')}"


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for entry in path.rglob("*"):
        try:
            if entry.is_file():
                total += entry.stat().st_size
        except OSError:
            # A model cache can be changing while status is being read.
            continue
    return total


def is_model_available(model_name: str, backend: str) -> bool:
    return _mlx_model_available(model_name) if backend == "mlx" else _faster_model_available(model_name)


def model_status(model_name: str, backend: str) -> dict[str, Any]:
    key = f"model:{backend}:{model_name}"
    job = _job_snapshot(key) or {}
    available = is_model_available(model_name, backend)
    bundled = not available and _bundled_model_available(model_name, backend)
    return {
        "model": model_name,
        "backend": backend,
        "available": available,
        "state": "ready" if available else job.get("state", "bundled" if bundled else "missing"),
        "detail": "模型已准备完成" if available else job.get("detail", "模型已随此应用附带，点击安装" if bundled else "尚未下载"),
        "estimated_bytes": MODEL_ESTIMATED_BYTES[model_name],
        "installed_bytes": _directory_size(model_storage_path(model_name, backend)),
        "bundled": bundled,
        "preferred": backend == preferred_asr_backend(),
        "download_source": job.get("source", ""),
        "job": job,
    }


def model_statuses() -> list[dict[str, Any]]:
    return [
        model_status(model_name, backend)
        for backend in ("mlx", "faster_whisper")
        for model_name in MODEL_ESTIMATED_BYTES
    ]


class _DownloadProgress:
    """Small silent tqdm replacement that exposes aggregate byte progress."""

    def __init__(self, *args: Any, job_key: str, **kwargs: Any) -> None:
        from tqdm.auto import tqdm

        kwargs["disable"] = True
        self._progress = tqdm(*args, **kwargs)
        self.total = int(self._progress.total or 0)
        self.current = int(self._progress.n or 0)
        self.job_key = job_key
        self._update()

    def update(self, amount: int = 1) -> None:
        self._progress.update(amount)
        # tqdm intentionally stops advancing ``n`` when output is disabled.
        # We disable terminal rendering in the desktop app, so keep the
        # byte count ourselves for the settings progress display.
        self.current = max(0, self.current + int(amount or 0))
        self._update()

    def __iter__(self):
        # ``huggingface_hub`` also uses tqdm_class around its worker iterator.
        # Mirror tqdm's iterable protocol while retaining a silent UI.
        for item in self._progress:
            self.current += 1
            self._update()
            yield item

    def close(self) -> None:
        self._progress.close()
        self._update()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._progress, name)

    def __enter__(self):
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()

    @classmethod
    def get_lock(cls):
        # huggingface_hub calls this on ``tqdm_class`` before it instantiates
        # progress bars, so the adapter must expose tqdm's class API too.
        from tqdm.auto import tqdm

        return getattr(cls, "_lock", tqdm.get_lock())

    @classmethod
    def set_lock(cls, lock: Any) -> None:
        # tqdm.contrib.concurrent temporarily assigns and later removes this
        # class attribute around its worker pool.
        cls._lock = lock

    def _update(self) -> None:
        _set_job(self.job_key, downloaded_bytes=self.current, total_bytes=self.total, updated_at=time.time())


def _download_progress_class(job_key: str) -> type[_DownloadProgress]:
    """Create the tqdm-compatible class required by huggingface_hub.

    ``snapshot_download`` invokes class methods such as ``get_lock`` before
    constructing a progress bar.  A lambda factory therefore cannot be used
    to bind the current model-download job.
    """

    class DownloadProgress(_DownloadProgress):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, job_key=job_key, **kwargs)

    return DownloadProgress


def _hub_endpoints() -> tuple[str, ...]:
    """Return the primary model mirror and one canonical fallback."""

    endpoints = (HUGGING_FACE_HUB_ENDPOINT, HUGGING_FACE_HUB_FALLBACK_ENDPOINT)
    return tuple(dict.fromkeys(endpoint.rstrip("/") for endpoint in endpoints if endpoint))


def _safe_modelscope_files(payload: object) -> list[dict[str, Any]]:
    """Validate the fixed ModelScope repository manifest before writing files."""

    data = payload.get("Data") if isinstance(payload, dict) else None
    files = data.get("Files") if isinstance(data, dict) else None
    if not isinstance(files, list):
        raise RuntimeError("ModelScope 未返回可识别的模型文件清单")
    result: list[dict[str, Any]] = []
    for item in files:
        if not isinstance(item, dict) or item.get("Type") != "blob":
            continue
        raw_path = str(item.get("Path") or "").strip().replace("\\", "/")
        relative = Path(raw_path)
        if not raw_path or relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError("ModelScope 返回了不安全的模型文件路径")
        try:
            size = max(0, int(item.get("Size") or 0))
        except (TypeError, ValueError):
            size = 0
        result.append({"path": raw_path, "size": size})
    if not result:
        raise RuntimeError("ModelScope 模型仓库为空")
    return result


def _download_model_from_modelscope(
    repository: str,
    model_name: str,
    backend: str,
    job_key: str,
) -> None:
    """Download one public model directly from ModelScope with safe resumption.

    This transport explicitly ignores shell and system proxy settings.  It is
    the mainland-China primary path and writes to the same deterministic local
    model directory used by inference.
    """

    target_root = model_storage_path(model_name, backend)
    target_root.mkdir(parents=True, exist_ok=True)
    encoded_repository = "/".join(quote(part, safe="") for part in repository.split("/"))
    manifest_url = f"{MODELSCOPE_ENDPOINT}/api/v1/models/{encoded_repository}/repo/files"
    session = direct_requests_session()
    try:
        _set_job(
            job_key,
            detail="正在连接 ModelScope 国内源…",
            source="modelscope",
            downloaded_bytes=_directory_size(target_root),
            total_bytes=0,
            updated_at=time.time(),
        )
        manifest_response = session.get(
            manifest_url,
            params={"Revision": MODELSCOPE_REVISION, "Recursive": "true"},
            timeout=(10, 30),
        )
        manifest_response.raise_for_status()
        files = _safe_modelscope_files(manifest_response.json())
        total_bytes = sum(int(item["size"]) for item in files)
        completed_bytes = sum(
            min(int(item["size"]), (target_root / item["path"]).stat().st_size)
            for item in files
            if (target_root / item["path"]).is_file()
        )
        _set_job(
            job_key,
            detail="正在从 ModelScope 国内源下载…",
            downloaded_bytes=completed_bytes,
            total_bytes=total_bytes,
            updated_at=time.time(),
        )
        for item in files:
            relative_path = str(item["path"])
            expected_size = int(item["size"])
            destination = target_root / relative_path
            if destination.is_file() and expected_size and destination.stat().st_size == expected_size:
                continue
            partial = destination.with_name(f"{destination.name}.part")
            partial.parent.mkdir(parents=True, exist_ok=True)
            existing = partial.stat().st_size if partial.is_file() else 0
            if expected_size and existing == expected_size:
                partial.replace(destination)
                completed_bytes += expected_size
                _set_job(
                    job_key,
                    downloaded_bytes=min(total_bytes, completed_bytes),
                    total_bytes=total_bytes,
                    updated_at=time.time(),
                )
                continue
            headers = {"Range": f"bytes={existing}-"} if existing else {}
            download_url = f"{MODELSCOPE_ENDPOINT}/api/v1/models/{encoded_repository}/repo"
            with session.get(
                download_url,
                params={"Revision": MODELSCOPE_REVISION, "FilePath": relative_path},
                headers=headers,
                stream=True,
                timeout=(10, 30),
            ) as response:
                response.raise_for_status()
                append = response.status_code == 206 and existing > 0
                mode = "ab" if append else "wb"
                written = existing if append else 0
                with partial.open(mode) as output:
                    for chunk in response.iter_content(chunk_size=1024 * 512):
                        if not chunk:
                            continue
                        output.write(chunk)
                        written += len(chunk)
                        _set_job(
                            job_key,
                            downloaded_bytes=min(total_bytes, completed_bytes + written),
                            total_bytes=total_bytes,
                            updated_at=time.time(),
                        )
            if expected_size and partial.stat().st_size != expected_size:
                raise RuntimeError(f"{relative_path} 下载不完整")
            partial.replace(destination)
            completed_bytes += destination.stat().st_size
            _set_job(
                job_key,
                downloaded_bytes=min(total_bytes, completed_bytes),
                total_bytes=total_bytes,
                updated_at=time.time(),
            )
    finally:
        session.close()


def _install_bundled_mlx_model(model_name: str, job_key: str) -> bool:
    """Copy a bundled model into the user-owned runtime cache, resumably."""

    source = _bundled_model_dir(model_name, "mlx")
    if not _directory_contains_mlx_model(source):
        return False
    assert source is not None
    target = mlx_whisper_model_dir(model_name)
    total_bytes = _directory_size(source)
    copied_bytes = 0
    _set_job(job_key, detail="正在安装随应用附带的语音模型…", downloaded_bytes=0, total_bytes=total_bytes, updated_at=time.time())
    for source_path in source.rglob("*"):
        if not source_path.is_file():
            continue
        relative_path = source_path.relative_to(source)
        target_path = target / relative_path
        size = source_path.stat().st_size
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if not target_path.is_file() or target_path.stat().st_size != size:
            shutil.copy2(source_path, target_path)
        copied_bytes += size
        _set_job(job_key, downloaded_bytes=copied_bytes, total_bytes=total_bytes, updated_at=time.time())
    return _mlx_model_available(model_name)


def _download_model_from_hub(
    repository: str,
    model_name: str,
    backend: str,
    progress_class: type[_DownloadProgress],
    job_key: str,
) -> None:
    """Fetch a model from China first, then retain compatible public fallbacks."""

    from huggingface_hub import snapshot_download

    failures: list[str] = []
    try:
        _download_model_from_modelscope(repository, model_name, backend, job_key)
        return
    except Exception as exc:
        failures.append(f"{MODELSCOPE_ENDPOINT}: {exc}")
    for endpoint in _hub_endpoints():
        try:
            _set_job(
                job_key,
                detail=f"ModelScope 不可用，正在尝试 {endpoint.replace('https://', '')}…",
                source="huggingface",
                downloaded_bytes=0,
                total_bytes=0,
                updated_at=time.time(),
            )
            if backend == "mlx":
                snapshot_download(
                    repository,
                    local_dir=str(mlx_whisper_model_dir(model_name)),
                    tqdm_class=progress_class,
                    endpoint=endpoint,
                    # Avoid a large parallel burst through local proxies. The
                    # MLX model has only a few files and resumes its partial
                    # weight file on a later attempt.
                    max_workers=2,
                )
            else:
                snapshot_download(
                    repository,
                    cache_dir=str(faster_whisper_cache_dir()),
                    tqdm_class=progress_class,
                    endpoint=endpoint,
                    max_workers=2,
                )
            return
        except Exception as exc:
            failures.append(f"{endpoint}: {exc}")
    raise RuntimeError("；".join(failures))


def download_model(model_name: str, backend: str) -> dict[str, Any]:
    _model_repo(model_name, backend)
    if backend != preferred_asr_backend():
        raise ValueError("当前系统仅支持下载对应平台的语音模型；旧兼容模型可在设置中移除")
    key = f"model:{backend}:{model_name}"
    current = model_status(model_name, backend)
    if current["available"] or (_job_snapshot(key) or {}).get("state") == "downloading":
        return current

    _set_job(key, state="downloading", detail="正在下载语音识别模型…", downloaded_bytes=0, total_bytes=0, updated_at=time.time())

    def run() -> None:
        try:
            progress_class = _download_progress_class(key)
            repository = _model_repo(model_name, backend)
            if backend == "mlx" and _install_bundled_mlx_model(model_name, key):
                _set_job(key, state="ready", detail="已安装应用附带的语音模型", updated_at=time.time())
                return
            _download_model_from_hub(repository, model_name, backend, progress_class, key)
            _set_job(key, state="ready", detail="模型已准备完成", updated_at=time.time())
        except Exception as exc:
            _set_job(key, state="failed", detail=f"模型下载失败：{exc}", updated_at=time.time())

    threading.Thread(target=run, name=f"knowledgehub-model-{backend}-{model_name}", daemon=True).start()
    return model_status(model_name, backend)


def remove_model(model_name: str, backend: str) -> dict[str, Any]:
    """Remove one explicit local model cache after the UI confirmation.

    The target is computed from the fixed model registry rather than supplied
    as a path, so this endpoint can never remove arbitrary user files.
    """

    _model_repo(model_name, backend)
    key = f"model:{backend}:{model_name}"
    if (_job_snapshot(key) or {}).get("state") == "downloading":
        raise ValueError("模型正在下载，完成或失败后才能移除")

    target = model_storage_path(model_name, backend)
    if target.exists():
        shutil.rmtree(target)
    if backend == "faster_whisper":
        lock_target = faster_whisper_cache_dir() / ".locks" / target.name
        if lock_target.exists():
            shutil.rmtree(lock_target)
    with _lock:
        _jobs.pop(key, None)
    return model_status(model_name, backend)


def runtime_components_status() -> dict[str, Any]:
    return {
        "preferred_asr_backend": preferred_asr_backend(),
        "supported_asr_backends": supported_asr_backends(),
        "browser": browser_status(),
        "models": model_statuses(),
    }

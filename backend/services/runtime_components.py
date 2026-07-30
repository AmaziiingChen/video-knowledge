"""On-demand runtime components that are intentionally excluded from the app bundle."""

from __future__ import annotations

from pathlib import Path
import os
import platform
import shutil
import subprocess
import threading
import time
from typing import Any

from config import settings
from services.network_policy import direct_network_environment

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
HUGGING_FACE_HUB_ENDPOINT = "https://huggingface.co"
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
    return (directory / "config.json").is_file() and (
        any(directory.glob("*.safetensors"))
        or any(directory.glob("*.npz"))
    )


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
    return {
        "model": model_name,
        "backend": backend,
        "available": available,
        "state": "ready" if available else job.get("state", "missing"),
        "detail": "模型已准备完成" if available else job.get("detail", "尚未下载"),
        "estimated_bytes": MODEL_ESTIMATED_BYTES[model_name],
        "installed_bytes": _directory_size(model_storage_path(model_name, backend)),
        "preferred": backend == preferred_asr_backend(),
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
            from huggingface_hub import snapshot_download

            progress_class = _download_progress_class(key)
            repository = _model_repo(model_name, backend)
            if backend == "mlx":
                snapshot_download(
                    repository,
                    local_dir=str(mlx_whisper_model_dir(model_name)),
                    tqdm_class=progress_class,
                    endpoint=HUGGING_FACE_HUB_ENDPOINT,
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
                    endpoint=HUGGING_FACE_HUB_ENDPOINT,
                    max_workers=2,
                )
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

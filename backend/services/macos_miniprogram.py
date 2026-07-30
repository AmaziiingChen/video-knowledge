from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
from threading import Lock
import time
from typing import Any

from config import settings


DEFAULT_WINDOW_PATTERN = "猹话会"


_native_dir = Path(__file__).resolve().parents[1] / "native"
_interaction_source = _native_dir / "macos_miniprogram_helper.m"
_ocr_source = _native_dir / "macos_vision_ocr.m"
_compile_lock = Lock()


class MiniProgramDriverError(RuntimeError):
    pass


class MacOSMiniProgramDriver:
    """Window-scoped capture and ordinary foreground interaction on macOS.

    This intentionally operates on pixels visible to the signed-in user.  It
    does not inspect WeChat traffic, unpack mini-program bundles, or replay
    private APIs.
    """

    def available(self) -> bool:
        return platform.system() == "Darwin"

    def status(self, window_pattern: str = DEFAULT_WINDOW_PATTERN, *, prompt: bool = False) -> dict[str, Any]:
        if not self.available():
            return {
                "available": False,
                "accessibility_granted": False,
                "screen_capture_granted": False,
                "windows": [],
                "selected_window": None,
                "error": "仅支持 macOS 桌面端",
            }
        helper = _ensure_native_helper(_interaction_source, "macos-miniprogram-helper", interaction=True)
        if helper is None:
            return {
                "available": False,
                "accessibility_granted": False,
                "screen_capture_granted": False,
                "windows": [],
                "selected_window": None,
                "error": "无法编译 macOS 采集组件",
            }
        args = [str(helper), "status"]
        if prompt:
            args.append("--prompt")
        payload = _run_json(args, timeout=30)
        windows = [item for item in payload.get("windows", []) if isinstance(item, dict)]
        selected = self.select_window(windows, window_pattern)
        return {
            **payload,
            "available": True,
            "windows": [selected] if selected else [],
            "selected_window": selected,
        }

    @staticmethod
    def select_window(windows: list[dict[str, Any]], pattern: str) -> dict[str, Any] | None:
        try:
            matcher = re.compile(pattern or DEFAULT_WINDOW_PATTERN, re.IGNORECASE)
        except re.error as exc:
            raise ValueError(f"窗口匹配规则无效：{exc}") from exc
        matches = []
        for window in windows:
            owner = str(window.get("owner") or "")
            normalized_owner = owner.strip().lower()
            if normalized_owner != "微信" and "wechat" not in normalized_owner:
                continue
            title = str(window.get("title") or "").strip()
            if matcher.search(title):
                matches.append(window)
        if not matches:
            return None
        # A standalone mini-program window is normally portrait-oriented.  A
        # large visible window is preferred over transient menus and popovers.
        return max(
            matches,
            key=lambda window: (
                float(window.get("height") or 0) >= float(window.get("width") or 0),
                float(window.get("width") or 0) * float(window.get("height") or 0),
            ),
        )

    def capture_window(self, window: dict[str, Any], output_path: Path) -> Path:
        window_id = int(window.get("window_id") or 0)
        if window_id <= 0:
            raise MiniProgramDriverError("微信小程序窗口 ID 无效")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        helper = _ensure_native_helper(_interaction_source, "macos-miniprogram-helper", interaction=True)
        if helper is None:
            raise MiniProgramDriverError("macOS 截图组件不可用")
        completed = subprocess.run(
            [str(helper), "capture", str(window_id), str(output_path)],
            check=False, capture_output=True, text=True, timeout=30,
        )
        if completed.returncode != 0 or not output_path.exists() or output_path.stat().st_size < 1024:
            output_path.unlink(missing_ok=True)
            detail = " ".join((completed.stderr or completed.stdout or "").split())[:160]
            raise MiniProgramDriverError(detail or "窗口截图失败，请检查屏幕录制权限")
        return output_path

    def recognize(self, image_path: Path) -> dict[str, Any]:
        helper = _ensure_native_helper(_ocr_source, "macos-vision-ocr", interaction=False)
        if helper is None:
            raise MiniProgramDriverError("无法编译本地 Vision OCR 组件")
        payload = _run_json([str(helper), str(image_path)], timeout=60)
        if not payload.get("available"):
            raise MiniProgramDriverError(str(payload.get("error") or "本地 OCR 失败"))
        payload["lines"] = [line for line in payload.get("lines", []) if isinstance(line, dict)]
        return payload

    def activate(self, window: dict[str, Any]) -> None:
        self._interaction(
            "activate",
            str(int(window.get("pid") or 0)),
            str(window.get("title") or ""),
        )
        time.sleep(0.18)

    def refresh_window(self, window: dict[str, Any]) -> dict[str, Any]:
        """Refresh mutable window geometry before coordinate-based input."""
        window_id = int(window.get("window_id") or 0)
        if window_id <= 0:
            raise MiniProgramDriverError("微信小程序窗口 ID 无效")
        helper = _ensure_native_helper(
            _interaction_source, "macos-miniprogram-helper", interaction=True
        )
        if helper is None:
            raise MiniProgramDriverError("macOS 交互组件不可用")
        payload = _run_json([str(helper), "status"], timeout=15)
        current = next(
            (
                item
                for item in payload.get("windows", [])
                if isinstance(item, dict)
                and int(item.get("window_id") or 0) == window_id
            ),
            None,
        )
        if current is None:
            raise MiniProgramDriverError("微信小程序窗口已关闭或无法定位")
        window.update(current)
        return window

    def click_pixel(self, window: dict[str, Any], image: dict[str, Any], x: float, y: float) -> None:
        current = self.refresh_window(window)
        self.activate(current)
        screen_x, screen_y = _image_to_screen(current, image, x, y)
        self._interaction("click", f"{screen_x:.2f}", f"{screen_y:.2f}")

    def click_normalized(self, window: dict[str, Any], x: float, y: float) -> None:
        current = self.refresh_window(window)
        self.activate(current)
        screen_x = float(current.get("x") or 0) + float(current.get("width") or 0) * x
        screen_y = float(current.get("y") or 0) + float(current.get("height") or 0) * y
        self._interaction("click", f"{screen_x:.2f}", f"{screen_y:.2f}")

    def scroll(self, window: dict[str, Any], wheel_ticks: int) -> None:
        current = self.refresh_window(window)
        self.activate(current)
        screen_x = float(current.get("x") or 0) + float(current.get("width") or 0) * 0.52
        screen_y = float(current.get("y") or 0) + float(current.get("height") or 0) * 0.68
        self._interaction("scroll", f"{screen_x:.2f}", f"{screen_y:.2f}", str(int(wheel_ticks)))

    def escape(self) -> None:
        self._interaction("escape")

    def _interaction(self, command: str, *args: str) -> None:
        helper = _ensure_native_helper(_interaction_source, "macos-miniprogram-helper", interaction=True)
        if helper is None:
            raise MiniProgramDriverError("macOS 交互组件不可用")
        completed = subprocess.run(
            [str(helper), command, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if completed.returncode != 0:
            detail = " ".join((completed.stderr or completed.stdout or "").split())[:160]
            raise MiniProgramDriverError(detail or f"窗口操作失败：{command}")


def image_perceptual_hash(
    path: Path,
    *,
    crop_top: float = 0.0,
    crop_bottom: float = 1.0,
) -> str:
    """Return a difference hash, optionally for a normalized vertical crop."""
    crop_top = max(0.0, min(float(crop_top), 0.95))
    crop_bottom = max(crop_top + 0.01, min(float(crop_bottom), 1.0))
    try:
        from PIL import Image

        with Image.open(path) as image:
            grayscale = image.convert("L")
            if crop_top > 0.0 or crop_bottom < 1.0:
                top = int(round(grayscale.height * crop_top))
                bottom = max(top + 1, int(round(grayscale.height * crop_bottom)))
                grayscale = grayscale.crop((0, top, grayscale.width, bottom))
            pixels = list(grayscale.resize((9, 8)).getdata())
        bits = [pixels[row * 9 + column] > pixels[row * 9 + column + 1] for row in range(8) for column in range(8)]
        value = 0
        for bit in bits:
            value = (value << 1) | int(bit)
        return f"{value:016x}"
    except (ImportError, OSError):
        try:
            return _dhash_with_sips(path)
        except (OSError, subprocess.SubprocessError, ValueError):
            return hashlib.sha256(path.read_bytes()).hexdigest()


def hash_distance(left: str, right: str) -> int:
    if len(left) == len(right) == 16:
        try:
            return (int(left, 16) ^ int(right, 16)).bit_count()
        except ValueError:
            pass
    return 0 if left == right else 256


def feed_top_button_position(path: Path) -> tuple[float, float] | None:
    """Return the normalized center of the green floating feed-top button.

    The button has no text, so OCR cannot identify it. The search is confined to
    the upper floating-control slot, excluding the lower green search button.
    """
    try:
        from PIL import Image

        with Image.open(path) as source:
            image = source.convert("RGB")
            width, height = image.size
            pixels = image.load()
            return _find_feed_top_button(width, height, lambda x, y: pixels[x, y])
    except ImportError:
        try:
            return _feed_top_button_with_sips(path)
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
    except OSError:
        return None


def _find_feed_top_button(width: int, height: int, pixel_at) -> tuple[float, float] | None:
    from collections import deque

    left = int(width * 0.84)
    right = width
    top = int(height * 0.68)
    bottom = int(height * 0.865)
    green = set()
    for y in range(top, bottom):
        for x in range(left, right):
            red, value, blue = pixel_at(x, y)
            if value >= 135 and value - red >= 24 and value - blue >= 8:
                green.add((x, y))

    components: list[tuple[int, int, int, int, int]] = []
    while green:
        start = green.pop()
        queue = deque([start])
        min_x = max_x = start[0]
        min_y = max_y = start[1]
        area = 0
        while queue:
            x, y = queue.popleft()
            area += 1
            min_x, max_x = min(min_x, x), max(max_x, x)
            min_y, max_y = min(min_y, y), max(max_y, y)
            for neighbor in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if neighbor in green:
                    green.remove(neighbor)
                    queue.append(neighbor)
        components.append((area, min_x, min_y, max_x, max_y))

    matches = []
    for area, min_x, min_y, max_x, max_y in components:
        blob_width = max_x - min_x + 1
        blob_height = max_y - min_y + 1
        center_x = (min_x + max_x) / 2
        center_y = (min_y + max_y) / 2
        aspect = blob_width / max(1, blob_height)
        if (
            area >= width * height * 0.0015
            and width * 0.055 <= blob_width <= width * 0.17
            and height * 0.032 <= blob_height <= height * 0.10
            and 0.70 <= aspect <= 1.45
            and center_x >= width * 0.88
            and height * 0.70 <= center_y <= height * 0.855
        ):
            matches.append((area, center_x / width, center_y / height))
    if not matches:
        return None
    _, center_x, center_y = max(matches)
    return center_x, center_y


def _feed_top_button_with_sips(path: Path) -> tuple[float, float] | None:
    sips = shutil.which("sips") or "/usr/bin/sips"
    if not Path(sips).exists() and shutil.which(sips) is None:
        raise OSError("sips unavailable")
    with tempfile.NamedTemporaryFile(suffix=".bmp", delete=False) as handle:
        resized = Path(handle.name)
    try:
        completed = subprocess.run(
            [sips, "-z", "384", "214", "-s", "format", "bmp", str(path), "--out", str(resized)],
            check=False,
            capture_output=True,
            timeout=20,
        )
        if completed.returncode != 0:
            raise OSError("sips resize failed")
        data = resized.read_bytes()
        if len(data) < 54 or data[:2] != b"BM":
            raise ValueError("invalid bmp")
        offset = struct.unpack_from("<I", data, 10)[0]
        width = abs(struct.unpack_from("<i", data, 18)[0])
        height_raw = struct.unpack_from("<i", data, 22)[0]
        height = abs(height_raw)
        bits = struct.unpack_from("<H", data, 28)[0]
        if bits not in {24, 32}:
            raise ValueError("unexpected bmp layout")
        pixel_bytes = bits // 8
        stride = ((width * pixel_bytes + 3) // 4) * 4

        def pixel_at(x: int, y: int) -> tuple[int, int, int]:
            source_row = height - 1 - y if height_raw > 0 else y
            base = offset + source_row * stride + x * pixel_bytes
            blue, green, red = data[base : base + 3]
            return red, green, blue

        return _find_feed_top_button(width, height, pixel_at)
    finally:
        resized.unlink(missing_ok=True)


def _dhash_with_sips(path: Path) -> str:
    sips = shutil.which("sips") or "/usr/bin/sips"
    if not Path(sips).exists() and shutil.which(sips) is None:
        raise OSError("sips unavailable")
    with tempfile.NamedTemporaryFile(suffix=".bmp", delete=False) as handle:
        resized = Path(handle.name)
    try:
        completed = subprocess.run(
            [sips, "-z", "8", "9", "-s", "format", "bmp", str(path), "--out", str(resized)],
            check=False, capture_output=True, timeout=20,
        )
        if completed.returncode != 0:
            raise OSError("sips resize failed")
        data = resized.read_bytes()
        if len(data) < 54 or data[:2] != b"BM":
            raise ValueError("invalid bmp")
        offset = struct.unpack_from("<I", data, 10)[0]
        width = abs(struct.unpack_from("<i", data, 18)[0])
        height_raw = struct.unpack_from("<i", data, 22)[0]
        height = abs(height_raw)
        bits = struct.unpack_from("<H", data, 28)[0]
        if width != 9 or height != 8 or bits not in {24, 32}:
            raise ValueError("unexpected bmp layout")
        pixel_bytes = bits // 8
        stride = ((width * pixel_bytes + 3) // 4) * 4
        rows = []
        for row_index in range(height):
            source_row = height - 1 - row_index if height_raw > 0 else row_index
            base = offset + source_row * stride
            row = []
            for column in range(width):
                blue, green, red = data[base + column * pixel_bytes : base + column * pixel_bytes + 3]
                row.append((red * 299 + green * 587 + blue * 114) // 1000)
            rows.append(row)
        value = 0
        for row in rows:
            for column in range(8):
                value = (value << 1) | int(row[column] > row[column + 1])
        return f"{value:016x}"
    finally:
        resized.unlink(missing_ok=True)


def _image_to_screen(
    window: dict[str, Any], image: dict[str, Any], x: float, y: float
) -> tuple[float, float]:
    image_width = max(1.0, float(image.get("width") or 1))
    image_height = max(1.0, float(image.get("height") or 1))
    screen_x = float(window.get("x") or 0) + (x / image_width) * float(window.get("width") or 0)
    screen_y = float(window.get("y") or 0) + (y / image_height) * float(window.get("height") or 0)
    return screen_x, screen_y


def _ensure_native_helper(source: Path, name: str, *, interaction: bool) -> Path | None:
    if platform.system() != "Darwin":
        return None
    bundled = Path(__file__).resolve().parents[1] / "native_tools" / name
    if bundled.exists():
        return bundled
    if not source.exists():
        return None
    tools_dir = settings.data_dir / "native_tools"
    helper = tools_dir / name
    if helper.exists() and helper.stat().st_mtime >= source.stat().st_mtime:
        return helper
    with _compile_lock:
        if helper.exists() and helper.stat().st_mtime >= source.stat().st_mtime:
            return helper
        compiler = shutil.which("clang") or "/usr/bin/clang"
        if not Path(compiler).exists() and shutil.which(compiler) is None:
            return None
        tools_dir.mkdir(parents=True, exist_ok=True)
        module_cache = tools_dir / "clang-module-cache"
        module_cache.mkdir(parents=True, exist_ok=True)
        temporary = tools_dir / f".{name}.tmp"
        command = [
            compiler,
            str(source),
            "-fobjc-arc",
            "-fblocks",
            "-framework",
            "AppKit",
            "-framework",
            "ApplicationServices" if interaction else "Vision",
            "-O2",
            f"-fmodules-cache-path={module_cache}",
            "-o",
            str(temporary),
        ]
        if interaction:
            command[command.index("-O2"):command.index("-O2")] = [
                "-framework", "ImageIO", "-framework", "ScreenCaptureKit",
            ]
        try:
            completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=90)
            if completed.returncode != 0 or not temporary.exists():
                temporary.unlink(missing_ok=True)
                return None
            temporary.replace(helper)
            helper.chmod(0o700)
            return helper
        except (OSError, subprocess.SubprocessError):
            temporary.unlink(missing_ok=True)
            return None


def _run_json(args: list[str], *, timeout: int) -> dict[str, Any]:
    try:
        completed = subprocess.run(args, check=False, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise MiniProgramDriverError(str(exc)) from exc
    if completed.returncode != 0 and not completed.stdout.strip():
        detail = " ".join((completed.stderr or "").split())[:160]
        raise MiniProgramDriverError(detail or "macOS 组件执行失败")
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise MiniProgramDriverError("macOS 组件返回了无效数据") from exc
    return payload if isinstance(payload, dict) else {}


__all__ = [
    "DEFAULT_WINDOW_PATTERN",
    "MacOSMiniProgramDriver",
    "MiniProgramDriverError",
    "feed_top_button_position",
    "hash_distance",
    "image_perceptual_hash",
]

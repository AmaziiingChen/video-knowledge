"""Record a reproducible empty-library resource baseline for a packaged app."""

from __future__ import annotations

import argparse
import ctypes
import json
import platform
import subprocess
import tempfile
import time
from pathlib import Path

from macos_desktop_runtime import (
    CdpClient,
    app_executable,
    close_desktop_app,
    free_loopback_port,
    launch_app,
    require_port_available,
    terminate,
    wait_for_port_available,
    wait_for_renderer,
)


class RusageInfoV2(ctypes.Structure):
    _fields_ = [
        ("uuid", ctypes.c_uint8 * 16),
        ("user_time", ctypes.c_uint64), ("system_time", ctypes.c_uint64),
        ("pkg_idle_wakeups", ctypes.c_uint64), ("interrupt_wakeups", ctypes.c_uint64),
        ("pageins", ctypes.c_uint64), ("wired_size", ctypes.c_uint64),
        ("resident_size", ctypes.c_uint64), ("phys_footprint", ctypes.c_uint64),
        ("proc_start_abstime", ctypes.c_uint64), ("proc_exit_abstime", ctypes.c_uint64),
        ("child_user_time", ctypes.c_uint64), ("child_system_time", ctypes.c_uint64),
        ("child_pkg_idle_wakeups", ctypes.c_uint64), ("child_interrupt_wakeups", ctypes.c_uint64),
        ("child_pageins", ctypes.c_uint64), ("child_elapsed_abstime", ctypes.c_uint64),
        ("diskio_bytesread", ctypes.c_uint64), ("diskio_byteswritten", ctypes.c_uint64),
    ]


class ProcTaskInfo(ctypes.Structure):
    _fields_ = [
        ("virtual_size", ctypes.c_uint64), ("resident_size", ctypes.c_uint64),
        ("total_user", ctypes.c_uint64), ("total_system", ctypes.c_uint64),
        ("threads_user", ctypes.c_uint64), ("threads_system", ctypes.c_uint64),
        ("policy", ctypes.c_int32), ("faults", ctypes.c_int32),
        ("pageins", ctypes.c_int32), ("cow_faults", ctypes.c_int32),
        ("messages_sent", ctypes.c_int32), ("messages_received", ctypes.c_int32),
        ("syscalls_mach", ctypes.c_int32), ("syscalls_unix", ctypes.c_int32),
        ("csw", ctypes.c_int32), ("threadnum", ctypes.c_int32),
        ("numrunning", ctypes.c_int32), ("priority", ctypes.c_int32),
    ]


def process_rows() -> list[dict[str, object]]:
    result = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,pcpu=,rss=,comm="],
        check=True,
        capture_output=True,
        text=True,
    )
    rows: list[dict[str, object]] = []
    for line in result.stdout.splitlines():
        fields = line.split(maxsplit=4)
        if len(fields) != 5:
            continue
        try:
            rows.append({
                "pid": int(fields[0]), "ppid": int(fields[1]), "cpu_percent": float(fields[2]),
                "rss_bytes": int(fields[3]) * 1024, "command": fields[4],
            })
        except ValueError:
            continue
    return rows


def descendant_rows(root_pid: int, rows: list[dict[str, object]]) -> list[dict[str, object]]:
    children: dict[int, list[int]] = {}
    by_pid = {int(row["pid"]): row for row in rows}
    for row in rows:
        children.setdefault(int(row["ppid"]), []).append(int(row["pid"]))
    pending = [root_pid]
    found: set[int] = set()
    while pending:
        pid = pending.pop()
        if pid in found:
            continue
        found.add(pid)
        pending.extend(children.get(pid, []))
    return [by_pid[pid] for pid in sorted(found) if pid in by_pid]


def process_io(pid: int) -> tuple[int, int]:
    if platform.system() != "Darwin":
        raise RuntimeError("待机资源采样只支持 macOS")
    library = ctypes.CDLL("/usr/lib/libproc.dylib")
    function = library.proc_pid_rusage
    function.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
    function.restype = ctypes.c_int
    usage = RusageInfoV2()
    if function(pid, 2, ctypes.byref(usage)) != 0:
        raise OSError(ctypes.get_errno(), f"无法读取进程 {pid} 的磁盘 I/O")
    return int(usage.diskio_bytesread), int(usage.diskio_byteswritten)


def process_thread_count(pid: int) -> int:
    if platform.system() != "Darwin":
        raise RuntimeError("待机资源采样只支持 macOS")
    library = ctypes.CDLL("/usr/lib/libproc.dylib")
    function = library.proc_pidinfo
    function.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
    function.restype = ctypes.c_int
    task = ProcTaskInfo()
    size = ctypes.sizeof(task)
    if function(pid, 4, 0, ctypes.byref(task), size) != size:
        raise OSError(ctypes.get_errno(), f"无法读取进程 {pid} 的线程数")
    return int(task.threadnum)


def sample(root_pid: int, previous_io: dict[int, tuple[int, int]]) -> tuple[dict[str, object], dict[int, tuple[int, int]]]:
    rows = descendant_rows(root_pid, process_rows())
    if not rows:
        raise RuntimeError("桌面进程树在待机采样期间消失")
    current_io: dict[int, tuple[int, int]] = {}
    disk_read_delta = 0
    disk_write_delta = 0
    process_entries: list[dict[str, object]] = []
    for row in rows:
        pid = int(row["pid"])
        try:
            threads = process_thread_count(pid)
            read, written = process_io(pid)
        except OSError:
            # Chromium helper processes can exit between the process snapshot
            # and libproc reads. Exclude that stale row from this sample.
            continue
        previous_read, previous_written = previous_io.get(pid, (read, written))
        disk_read_delta += max(0, read - previous_read)
        disk_write_delta += max(0, written - previous_written)
        current_io[pid] = (read, written)
        process_entries.append({
            **row,
            "threads": threads,
            "disk_read_bytes": read,
            "disk_write_bytes": written,
        })
    if not process_entries:
        raise RuntimeError("桌面进程树在待机采样期间消失")
    return ({
        "at": time.time(),
        "processes": process_entries,
        "cpu_percent": round(sum(float(row["cpu_percent"]) for row in process_entries), 3),
        "rss_bytes": sum(int(row["rss_bytes"]) for row in process_entries),
        "threads": sum(int(row["threads"]) for row in process_entries),
        "disk_read_delta_bytes": disk_read_delta,
        "disk_write_delta_bytes": disk_write_delta,
    }, current_io)


def aggregate(samples: list[dict[str, object]], interval_seconds: float) -> dict[str, object]:
    if not samples:
        raise RuntimeError("待机采样未取得任何数据")
    def values(key: str) -> list[float]:
        return [float(sample[key]) for sample in samples]
    return {
        "cpu_percent": {"average": round(sum(values("cpu_percent")) / len(samples), 3), "peak": max(values("cpu_percent"))},
        "rss_bytes": {"average": round(sum(values("rss_bytes")) / len(samples)), "peak": max(values("rss_bytes"))},
        "threads": {"average": round(sum(values("threads")) / len(samples), 2), "peak": max(values("threads"))},
        "disk_read_bytes_per_second": {
            "average": round(sum(values("disk_read_delta_bytes")) / max(interval_seconds * len(samples), 1), 3),
            "peak": round(max(values("disk_read_delta_bytes")) / max(interval_seconds, 1), 3),
        },
        "disk_write_bytes_per_second": {
            "average": round(sum(values("disk_write_delta_bytes")) / max(interval_seconds * len(samples), 1), 3),
            "peak": round(max(values("disk_write_delta_bytes")) / max(interval_seconds, 1), 3),
        },
    }


def run_measurement(app: Path, *, warmup_seconds: float, sample_seconds: float, interval_seconds: float) -> dict[str, object]:
    if warmup_seconds < 0 or sample_seconds <= 0 or interval_seconds <= 0:
        raise ValueError("预热、采样时长和采样间隔必须有效")
    executable = app_executable(app)
    require_port_available(8000)
    debugging_port = free_loopback_port()
    report: dict[str, object]
    with tempfile.TemporaryDirectory(prefix="knowledgehub-idle-baseline-") as temporary:
        profile = Path(temporary) / "profile"
        process = launch_app(executable, profile, debugging_port)
        known_pids: set[int] = set()
        try:
            page = wait_for_renderer(debugging_port, process)
            client = CdpClient(str(page["webSocketDebuggerUrl"]))
            ready = client.evaluate("document.readyState === 'complete'")
            if ready is not True:
                raise RuntimeError("待机采样前 renderer 未就绪")
            time.sleep(warmup_seconds)
            deadline = time.monotonic() + sample_seconds
            previous_io: dict[int, tuple[int, int]] = {}
            samples: list[dict[str, object]] = []
            while True:
                entry, previous_io = sample(process.pid, previous_io)
                samples.append(entry)
                known_pids.update(int(row["pid"]) for row in entry["processes"])
                if time.monotonic() >= deadline:
                    break
                time.sleep(min(interval_seconds, max(0.0, deadline - time.monotonic())))
            report = {
                "status": "ok",
                "profile": "isolated-temporary-empty-library",
                "machine": {"macos": platform.mac_ver()[0], "machine": platform.machine(), "processor": platform.processor()},
                "parameters": {"warmup_seconds": warmup_seconds, "sample_seconds": sample_seconds, "interval_seconds": interval_seconds},
                "summary": aggregate(samples, interval_seconds),
                "samples": samples,
                "known_process_ids": sorted(known_pids),
            }
        finally:
            try:
                close_desktop_app(client, process)
            except UnboundLocalError:
                terminate(process)
            else:
                client.close()
            wait_for_port_available(8000)
    report["temporary_profile_cleanup"] = "ok"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True, type=Path)
    parser.add_argument("--warmup-seconds", type=float, default=120)
    parser.add_argument("--sample-seconds", type=float, default=300)
    parser.add_argument("--interval-seconds", type=float, default=5)
    parser.add_argument("--report", required=True, type=Path)
    arguments = parser.parse_args()
    report = run_measurement(
        arguments.app,
        warmup_seconds=arguments.warmup_seconds,
        sample_seconds=arguments.sample_seconds,
        interval_seconds=arguments.interval_seconds,
    )
    destination = arguments.report.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "samples"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

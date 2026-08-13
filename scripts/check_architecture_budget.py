"""Prevent reviewed architecture hot spots from growing unnoticed."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# These are reviewed non-regression ceilings, not line-count targets. Add or
# lower one only after an evidenced responsibility move with behavior tests or
# a fully proven unreachable-code deletion; size alone is not a failure.
KNOWN_DEBT_BUDGETS = {
    "frontend/src/composables/useAppController.js": 1_245,
    "frontend/src/workbench/EditorHost.vue": 1_052,
    "frontend/src/App.vue": 2_759,
    "backend/services/database.py": 167,
    "backend/services/group_report_pipeline.py": 1_403,
    "frontend/src/styles/app.css": 2_410,
    "frontend/src/workbench/LibrarySidebar.vue": 1_134,
    "backend/services/wechat_publishing.py": 1_415,
    "backend/routers/content.py": 201,
    # Public builds add explicit collector preflight while retaining the
    # module's established router/test helper exports.
    "backend/services/creator_sync.py": 997,
    "backend/services/knowledge_v2.py": 661,
    "backend/services/campus_digest_generation.py": 984,
    "backend/services/campus_sources.py": 992,
    "backend/services/pipeline_runner.py": 999,
    "backend/services/wechat_reports.py": 1_229,
    "backend/services/prompt_templates.py": 1_424,
    "backend/services/knowledge_library.py": 1_386,
    "frontend/src/workbench/ProcessLogDock.vue": 1_279,
    "backend/services/wechat_discovery.py": 1_346,
    # The privacy pane owns the settings-side consent handshake; its UI remains
    # in this dialog rather than duplicating a second settings surface.
    "frontend/src/components/SettingsDialog.vue": 1_313,
    "frontend/src/styles/settings.css": 1_269,
    # Recovery and every queue-control mutation now enforce the optional
    # collector capability before touching durable task/content state.
    "backend/services/task_manager.py": 1_133,
    "frontend/src/workbench/WorkbenchShell.vue": 1_095,
    "backend/services/content_index.py": 1_083,
}

SOURCE_SUFFIXES = {".py", ".js", ".cjs", ".vue", ".css"}


def source_files() -> list[Path]:
    files: list[Path] = []
    for source_root in (ROOT / "backend", ROOT / "frontend" / "src"):
        for path in source_root.rglob("*"):
            if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
                continue
            relative = path.relative_to(ROOT)
            if "tests" in relative.parts or ".test." in path.name:
                continue
            files.append(path)
    return files


def line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def main() -> int:
    failures: list[str] = []
    measured: dict[str, int] = {}
    for path in source_files():
        relative = path.relative_to(ROOT).as_posix()
        count = line_count(path)
        measured[relative] = count
        budget = KNOWN_DEBT_BUDGETS.get(relative)
        if budget is not None and count > budget:
            failures.append(f"{relative}: {count} lines exceeds debt ceiling {budget}")

    missing = sorted(set(KNOWN_DEBT_BUDGETS) - set(measured))
    failures.extend(f"architecture budget references missing file: {path}" for path in missing)

    if failures:
        print("Architecture budget failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    largest = sorted(measured.items(), key=lambda item: item[1], reverse=True)[:5]
    print("Architecture budget passed. Largest production sources:")
    for path, count in largest:
        print(f"- {path}: {count} lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

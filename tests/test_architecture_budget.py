from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "check_architecture_budget.py"
SPEC = importlib.util.spec_from_file_location("check_architecture_budget", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def test_unlisted_large_source_is_a_review_signal_not_a_failure(tmp_path, monkeypatch):
    source = tmp_path / "frontend" / "src" / "LargeOwner.vue"
    source.parent.mkdir(parents=True)
    source.write_text("\n".join(["line"] * 1_200), encoding="utf-8")

    monkeypatch.setattr(checker, "ROOT", tmp_path)
    monkeypatch.setattr(checker, "KNOWN_DEBT_BUDGETS", {})

    assert checker.main() == 0


def test_reviewed_hot_spot_still_rejects_regrowth(tmp_path, monkeypatch):
    relative = "frontend/src/CompositionRoot.vue"
    source = tmp_path / relative
    source.parent.mkdir(parents=True)
    source.write_text("\n".join(["line"] * 101), encoding="utf-8")

    monkeypatch.setattr(checker, "ROOT", tmp_path)
    monkeypatch.setattr(checker, "KNOWN_DEBT_BUDGETS", {relative: 100})

    assert checker.main() == 1

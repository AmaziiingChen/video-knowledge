from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "check_public_release_tree.py"
SPEC = importlib.util.spec_from_file_location("check_public_release_tree", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def _disallowed_fixture_secret() -> str:
    return "sk-" + "abcdefghijklmnopqrstuvwxyz123456"


def test_secret_scanner_allows_only_the_explicit_existing_fixture_value():
    assert checker.disallowed_secret_values('api_key="sk-unsaved-test-key"') == []
    secret = _disallowed_fixture_secret()
    assert checker.disallowed_secret_values(f'api_key="{secret}"') == [secret]


def test_public_release_check_scans_test_directories_for_real_secrets(tmp_path, monkeypatch, capsys):
    for required in checker.REQUIRED:
        (tmp_path / required).write_text("public", encoding="utf-8")
    fixture = tmp_path / "tests" / "test_fixture.py"
    fixture.parent.mkdir()
    fixture.write_text(f'token = "{_disallowed_fixture_secret()}"\n', encoding="utf-8")

    monkeypatch.setattr(checker, "ROOT", tmp_path)
    monkeypatch.setattr(checker, "tracked_files", lambda: [*(tmp_path / required for required in checker.REQUIRED), fixture])
    monkeypatch.setattr(checker, "public_revisions", lambda: [])
    monkeypatch.setattr(checker, "history_secret_findings", lambda _revisions: [])

    assert checker.main() == 1
    assert "tests/test_fixture.py" in capsys.readouterr().err


def test_history_scanner_rejects_real_tokens_but_not_known_fixture_values(monkeypatch):
    monkeypatch.setattr(
        checker,
        "git_grep_history_lines",
        lambda _revisions: [
            'deadbeef:tests/fixture.py:1:token = "sk-unsaved-test-key"',
            f'deadbeef:old.py:9:token = "{_disallowed_fixture_secret()}"',
        ],
    )

    assert checker.history_secret_findings(["HEAD"]) == [
        "deadbeef:old.py:9（sk-abcde…）"
    ]


def test_public_revisions_scans_detached_ci_head(monkeypatch):
    monkeypatch.setattr(checker, "public_refs", lambda: [])

    assert checker.public_revisions() == ["HEAD"]

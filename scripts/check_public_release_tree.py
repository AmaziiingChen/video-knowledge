#!/usr/bin/env python3
"""Fail fast when the public release tree violates basic publication rules.

The checker deliberately limits Git history checks to branches and tags.  Local
Codex/recovery refs are not release refs and may retain old objects while a
developer is working; publishing with ``git push --mirror`` is therefore not a
supported release procedure.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ("LICENSE", "NOTICE", "PRIVACY.md", "SECURITY.md", "THIRD_PARTY_NOTICES.md")
FORBIDDEN_PREFIXES = (
    "data/",
    "materials/",
    "backend/vendor/Spider_XHS/",
    "frontend/assets/",
    "frontend/public-report/public/reports/",
)
FORBIDDEN_FILES = {"backend/.env"}
SECRET_PATTERNS = (
    re.compile(r"\b(?:sk|rk|ghp|github_pat|xox[abprs])[-_][A-Za-z0-9_-]{16,}\b", re.IGNORECASE),
    re.compile(r"[?&]xsec_token=[A-Za-z0-9_-]{20,}", re.IGNORECASE),
)
# These values exercise credential-redaction behavior in tests.  Keep this
# list exact: a newly introduced key-shaped fixture must still be reviewed,
# rather than inheriting a directory-wide exemption.
ALLOWED_FIXTURE_SECRET_VALUES = frozenset({"sk-unsaved-test-key"})
HISTORY_CANDIDATE_PATTERN = (
    r"(^|[^[:alnum:]_])(sk|rk|ghp|github_pat|xox[abprs])[-_][A-Za-z0-9_-]{16,}"
    r"|[?&]xsec_token=[A-Za-z0-9_-]{20,}"
)
LOCAL_PATH_PATTERN = re.compile(r"/(?:Users|home)/[^\s)`\]}>'\"]+", re.IGNORECASE)
MAX_SCANNED_FILE_BYTES = 5 * 1024 * 1024


def git_output(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True
    )
    return result.stdout.decode("utf-8", errors="replace")


def tracked_files() -> list[Path]:
    return [ROOT / item for item in git_output("ls-files", "-z").split("\0") if item]


def public_refs() -> list[str]:
    """Return only refs that a normal open-source release may publish."""
    return [
        ref
        for ref in git_output(
            "for-each-ref", "--format=%(refname)", "refs/heads", "refs/tags"
        ).splitlines()
        if ref
    ]


def public_revisions() -> list[str]:
    """Include detached CI HEAD as well as publishable local branches/tags."""
    revisions = public_refs()
    if "HEAD" not in revisions:
        revisions.append("HEAD")
    return revisions


def has_public_history_path(pathspec: str, revisions: list[str]) -> bool:
    if not revisions:
        return False
    return bool(git_output("log", "--format=", "--name-only", *revisions, "--", pathspec).strip())


def secret_values(content: str) -> list[str]:
    return [match.group(0) for pattern in SECRET_PATTERNS for match in pattern.finditer(content)]


def disallowed_secret_values(content: str) -> list[str]:
    return [value for value in secret_values(content) if value not in ALLOWED_FIXTURE_SECRET_VALUES]


def git_grep_history_lines(revisions: list[str]) -> list[str]:
    if not revisions:
        return []
    result = subprocess.run(
        ["git", "grep", "-n", "-I", "-E", HISTORY_CANDIDATE_PATTERN, *revisions],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if result.returncode not in {0, 1}:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"无法扫描公开历史中的疑似凭据：{detail}")
    return result.stdout.decode("utf-8", errors="replace").splitlines()


def history_secret_findings(revisions: list[str]) -> list[str]:
    findings: set[str] = set()
    for line in git_grep_history_lines(revisions):
        parts = line.split(":", 3)
        if len(parts) != 4:
            continue
        revision, path, line_number, content = parts
        for value in disallowed_secret_values(content):
            findings.add(f"{revision}:{path}:{line_number}（{value[:8]}…）")
    return sorted(findings)


def main() -> int:
    failures: list[str] = []
    tracked = tracked_files()
    tracked_relative = {path.relative_to(ROOT).as_posix() for path in tracked}
    for required in REQUIRED:
        if not (ROOT / required).is_file():
            failures.append(f"缺少公开发布文件：{required}")
        elif required not in tracked_relative:
            failures.append(f"公开发布文件尚未纳入版本控制：{required}")

    for path in tracked:
        relative = path.relative_to(ROOT).as_posix()
        if not path.is_file():
            continue
        if relative in FORBIDDEN_FILES or relative.startswith(FORBIDDEN_PREFIXES):
            failures.append(f"公开树不得跟踪本机或未授权资产：{relative}")
            continue
        if path.stat().st_size > MAX_SCANNED_FILE_BYTES:
            failures.append(f"文件过大，无法完成凭据检查：{relative}")
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if disallowed_secret_values(content):
            failures.append(f"疑似凭据或访问令牌：{relative}")
        if LOCAL_PATH_PATTERN.search(content):
            failures.append(f"包含本机绝对路径：{relative}")

    revisions = public_revisions()
    for forbidden in FORBIDDEN_PREFIXES:
        if has_public_history_path(forbidden, revisions):
            failures.append(f"公开分支或标签历史仍包含受阻路径：{forbidden}")
    for forbidden in FORBIDDEN_FILES:
        if has_public_history_path(forbidden, revisions):
            failures.append(f"公开分支或标签历史仍包含受阻文件：{forbidden}")
    for finding in history_secret_findings(revisions):
        failures.append(f"公开分支、标签或当前提交历史仍包含疑似凭据：{finding}")

    if failures:
        print("公开发布检查失败：", file=sys.stderr)
        print("\n".join(f"- {message}" for message in failures), file=sys.stderr)
        return 1
    print("公开发布检查通过：未发现受阻路径、常见凭据模式或本机绝对路径。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

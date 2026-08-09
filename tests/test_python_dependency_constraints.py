from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _requirements(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_verification_tools_are_exactly_pinned():
    requirements = _requirements(ROOT / "requirements-dev.txt")
    assert requirements == [
        "pytest==9.1.1",
        "ruff==0.16.2",
        "pip-audit==2.10.1",
    ]


def test_dependency_policy_documents_the_local_verification_manifest():
    policy = (ROOT / "docs" / "python-dependencies.md").read_text(encoding="utf-8")
    assert "requirements-dev.txt" in policy
    assert "cross-platform" in policy

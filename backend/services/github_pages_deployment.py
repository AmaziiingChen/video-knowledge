"""Publish the deliberately public report artifact to a dedicated GitHub Pages repo."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener

from config import PROJECT_ROOT


class GitHubPagesDeploymentError(RuntimeError):
    """GitHub Pages did not receive a verified public report build."""


_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_PROXY_ENVIRONMENT_KEYS = {
    "ALL_PROXY",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
}


def github_pages_url(repository: str) -> str:
    owner, name = _repository_parts(repository)
    return f"https://{owner}.github.io/{name}"


def deploy_github_pages(repository: str) -> dict[str, str]:
    """Build and replace only the dedicated Pages branch with public artifacts."""
    clean_repository = _normalize_repository(repository)
    for command, description in (("npm", "Node.js"), ("git", "Git"), ("gh", "GitHub CLI")):
        if not shutil.which(command):
            raise GitHubPagesDeploymentError(f"未找到{description}，无法自动部署 GitHub Pages")

    frontend_dir = PROJECT_ROOT / "frontend"
    dist_dir = frontend_dir / "dist-public-report"
    _run(["npm", "run", "build:public-report"], cwd=frontend_dir, message="构建公开报告网站失败")
    if not (dist_dir / "index.html").is_file():
        raise GitHubPagesDeploymentError("公开报告构建不完整，未找到首页文件")

    remote = f"https://github.com/{clean_repository}.git"
    with TemporaryDirectory(prefix="knowledgehub-github-pages-") as raw_directory:
        worktree = Path(raw_directory) / "site"
        _run(["git", "clone", "--depth", "1", remote, str(worktree)], message="下载 GitHub Pages 仓库失败")
        _run(["git", "checkout", "--orphan", "gh-pages"], cwd=worktree, message="准备 GitHub Pages 分支失败")
        _run(["git", "rm", "-rf", "."], cwd=worktree, message="清理旧的公开网站文件失败", allowed_returncodes={0, 128})
        _clear_worktree(worktree)
        _copy_public_build(dist_dir, worktree)
        (worktree / ".nojekyll").touch()
        _run(["git", "add", "--all"], cwd=worktree, message="整理公开网站文件失败")
        _run(["git", "config", "user.name", "KnowledgeHub Publisher"], cwd=worktree, message="配置 GitHub 提交身份失败")
        _run(["git", "config", "user.email", "knowledgehub-publisher@users.noreply.github.com"], cwd=worktree, message="配置 GitHub 提交身份失败")
        _run(["git", "commit", "-m", "Publish public report site"], cwd=worktree, message="提交公开网站文件失败")
        _run(["git", "push", "--force", "origin", "gh-pages"], cwd=worktree, message="上传公开网站文件到 GitHub 失败")

    _enable_pages(clean_repository)
    public_url = github_pages_url(clean_repository)
    _verify_public_site(public_url)
    return {"repository": clean_repository, "public_site_base_url": public_url}


def verify_github_pages_url(url: str) -> None:
    """Require the exact immutable report URL to answer before WeChat receives it."""
    _verify_public_site(url)


def _enable_pages(repository: str) -> None:
    endpoint = f"repos/{repository}/pages"
    payload = ["-f", "build_type=legacy", "-f", "source[branch]=gh-pages", "-f", "source[path]=/"]
    result = _run_raw(["gh", "api", "--method", "POST", endpoint, *payload])
    if result.returncode != 0:
        result = _run_raw(["gh", "api", "--method", "PUT", endpoint, *payload])
    if result.returncode != 0:
        raise GitHubPagesDeploymentError("已上传公开文件，但无法启用 GitHub Pages")

    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        latest = _run_raw(["gh", "api", f"repos/{repository}/pages/builds/latest"])
        if latest.returncode == 0:
            try:
                status = str(json.loads(latest.stdout).get("status") or "")
            except json.JSONDecodeError:
                status = ""
            if status == "built":
                return
            if status == "errored":
                raise GitHubPagesDeploymentError("GitHub Pages 构建失败，请在仓库的 Actions 页面查看详情")
        time.sleep(3)
    raise GitHubPagesDeploymentError("GitHub Pages 正在发布，请稍后重试创建草稿")


def _verify_public_site(url: str) -> None:
    deadline = time.monotonic() + 45
    direct_opener = build_opener(ProxyHandler({}))
    while time.monotonic() < deadline:
        try:
            request = Request(url, method="HEAD", headers={"User-Agent": "KnowledgeHub Publisher"})
            with direct_opener.open(request, timeout=10) as response:  # nosec B310: URL is generated from a validated GitHub repo.
                if 200 <= int(response.status) < 400:
                    return
        except (URLError, TimeoutError):
            pass
        time.sleep(3)
    raise GitHubPagesDeploymentError("GitHub Pages 尚未可公开访问，请稍后重试创建草稿")


def _copy_public_build(source: Path, destination: Path) -> None:
    for item in source.iterdir():
        target = destination / item.name
        if item.is_dir():
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def _clear_worktree(worktree: Path) -> None:
    for item in worktree.iterdir():
        if item.name == ".git":
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()


def _run(command: list[str], *, cwd: Path | None = None, message: str, allowed_returncodes: set[int] | None = None) -> None:
    result = _run_raw(command, cwd=cwd)
    if result.returncode not in (allowed_returncodes or {0}):
        detail = (result.stderr or result.stdout).strip().splitlines()
        suffix = f"：{detail[-1]}" if detail else ""
        raise GitHubPagesDeploymentError(f"{message}{suffix}")


def _run_raw(command: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            _direct_git_command(command),
            cwd=cwd,
            env=_direct_network_environment(),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitHubPagesDeploymentError("GitHub Pages 部署超时，请检查网络后重试") from exc


def _direct_network_environment() -> dict[str, str]:
    """Make publication independent from a user's local proxy application.

    This desktop workflow has no proxy setting of its own.  Inheriting an old
    Clash/VPN port from the launcher makes GitHub deployment silently depend on
    whether that other application happens to be running.
    """
    environment = os.environ.copy()
    for key in tuple(environment):
        if key.upper() in _PROXY_ENVIRONMENT_KEYS:
            environment.pop(key, None)
    return environment


def _direct_git_command(command: list[str]) -> list[str]:
    """Override Git's global proxy configuration for GitHub traffic only."""
    if not command or command[0] != "git":
        return command
    return [
        "git",
        "-c",
        "http.proxy=",
        "-c",
        "https.proxy=",
        "-c",
        "http.https://github.com.proxy=",
        *command[1:],
    ]


def _normalize_repository(value: str) -> str:
    repository = str(value or "").strip().strip("/")
    if not _REPOSITORY_PATTERN.fullmatch(repository):
        raise GitHubPagesDeploymentError("GitHub Pages 仓库应为 owner/repository 格式")
    return repository


def _repository_parts(repository: str) -> tuple[str, str]:
    normalized = _normalize_repository(repository)
    owner, name = normalized.split("/", 1)
    return owner.lower(), name

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import mcp_server


def _secure_token_file(
    tmp_path: Path,
    token: str,
    *,
    api_base: str = "http://127.0.0.1:8000/api",
) -> Path:
    run_dir = tmp_path / "mcp-run"
    run_dir.mkdir(mode=0o700)
    run_dir.chmod(0o700)
    token_file = run_dir / "token"
    token_file.write_text(token, encoding="utf-8")
    token_file.chmod(0o600)
    lease_file = run_dir / "mcp-bridge-lease.json"
    lease_file.write_text(
        json.dumps(
            {
                "session_id": "session-1",
                "updated_at": 100.0,
                "api_base": api_base,
            }
        ),
        encoding="utf-8",
    )
    lease_file.chmod(0o600)
    return token_file


class StubResponse:
    def __init__(self, payload=None, text: str = ""):
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


def test_mcp_request_attaches_only_the_scoped_capability(monkeypatch, tmp_path):
    token = "mcp-request-token-value-1234567890"
    token_file = _secure_token_file(tmp_path, token)
    monkeypatch.setenv("KNOWLEDGEHUB_MCP_BRIDGE_TOKEN_FILE", str(token_file))
    real_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("http://127.0.0.1:8000/api/tasks")
        assert request.headers["X-KnowledgeHub-MCP-Token"] == token
        assert "X-KnowledgeHub-Token" not in request.headers
        assert token not in str(request.url)
        return httpx.Response(200, json=[])

    def client_factory(**kwargs):
        assert kwargs["follow_redirects"] is False
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(mcp_server.httpx, "AsyncClient", client_factory)
    response = asyncio.run(mcp_server._request("GET", "/tasks"))

    assert response.json() == []


def test_mcp_request_rejects_remote_api_before_reading_or_sending_capability(monkeypatch, tmp_path):
    token_file = _secure_token_file(
        tmp_path,
        "mcp-request-token-value-1234567890",
        api_base="https://attacker.invalid/api",
    )
    monkeypatch.setenv("KNOWLEDGEHUB_MCP_BRIDGE_TOKEN_FILE", str(token_file))
    monkeypatch.setattr(
        mcp_server.httpx,
        "AsyncClient",
        lambda **_kwargs: pytest.fail("remote client must not be created"),
    )

    with pytest.raises(RuntimeError, match="回环"):
        asyncio.run(mcp_server._request("GET", "/tasks"))


def test_mcp_http_error_never_reflects_the_capability(monkeypatch, tmp_path):
    token = "mcp-request-token-value-1234567890"
    token_file = _secure_token_file(tmp_path, token)
    monkeypatch.setenv("KNOWLEDGEHUB_MCP_BRIDGE_TOKEN_FILE", str(token_file))
    real_client = httpx.AsyncClient

    def client_factory(**kwargs):
        return real_client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(401, json={"detail": f"reflected {token}"})
            ),
            **kwargs,
        )

    monkeypatch.setattr(mcp_server.httpx, "AsyncClient", client_factory)
    with pytest.raises(RuntimeError) as captured:
        asyncio.run(mcp_server._request("GET", "/tasks"))

    assert token not in str(captured.value)
    assert "[redacted]" in str(captured.value)


def test_search_wechat_mcp_tool_uses_local_subscription_api(monkeypatch):
    calls = []

    async def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return StubResponse([{"name": "测试公众号", "fakeid": "fakeid-1"}])

    monkeypatch.setattr(mcp_server, "_request", fake_request)
    result = asyncio.run(
        mcp_server.knowledgehub_search_wechat_accounts(
            mcp_server.SearchWeChatAccountsInput(account_id="account-1", query="测试")
        )
    )

    assert calls == [("GET", "/wechat-subscriptions/accounts/account-1/search", {"params": {"q": "测试", "limit": 10}})]
    assert "测试公众号" in result
    assert "fakeid-1" in result


def test_read_wechat_article_mcp_tool_returns_markdown(monkeypatch):
    async def fake_request(method, path, **kwargs):
        assert (method, path, kwargs) == ("GET", "/wechat-feed/article/article-1.md", {})
        return StubResponse(text="# 已缓存文章\n\n正文")

    monkeypatch.setattr(mcp_server, "_request", fake_request)
    result = asyncio.run(
        mcp_server.knowledgehub_read_wechat_article(
            mcp_server.ReadWeChatArticleInput(article_id="article-1")
        )
    )

    assert result == "# 已缓存文章\n\n正文"


def test_automation_status_mcp_tool_summarizes_the_full_link_path(monkeypatch):
    calls = []

    async def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return StubResponse({
            "automation_ready": True,
            "detail": "Gateway 与本地 RPC 已连接",
            "wechat": {"detail": "微信通道已连接"},
            "mcp": {"detail": "KnowledgeHub MCP 已配置"},
            "backend": {"detail": "KnowledgeHub 后端可接收链接"},
        })

    monkeypatch.setattr(mcp_server, "_request", fake_request)
    result = asyncio.run(
        mcp_server.knowledgehub_get_automation_status(
            mcp_server.AutomationStatusInput()
        )
    )

    assert calls == [("GET", "/openclaw-gateway", {"params": {"refresh": "true"}})]
    assert result.startswith("微信链接自动处理已就绪")


def test_conversation_task_mcp_tool_uses_the_scoped_mapping_api(monkeypatch):
    calls = []

    async def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return StubResponse([{
            "task_id": "task-1",
            "title": "测试链接",
            "status": "running",
            "progress": 40,
            "notified_at": None,
        }])

    monkeypatch.setattr(mcp_server, "_request", fake_request)
    result = asyncio.run(
        mcp_server.knowledgehub_list_conversation_tasks(
            mcp_server.ConversationTaskListInput(conversation_key="session-a")
        )
    )

    assert calls == [("GET", "/openclaw/conversation-tasks", {"params": {"conversation_key": "session-a", "limit": 8}})]
    assert "测试链接" in result
    assert "task-1" in result


def test_terminal_notification_mcp_tool_claims_once_before_reply(monkeypatch):
    async def fake_request(method, path, **kwargs):
        assert (method, path, kwargs) == (
            "POST",
            "/openclaw/conversation-tasks/claim-notification",
            {"json": {"conversation_key": "session-a", "task_id": "task-1"}},
        )
        return StubResponse({"task_id": "task-1", "should_notify": True})

    monkeypatch.setattr(mcp_server, "_request", fake_request)
    result = asyncio.run(
        mcp_server.knowledgehub_claim_conversation_notification(
            mcp_server.ClaimConversationNotificationInput(conversation_key="session-a", task_id="task-1")
        )
    )

    assert "可以向当前会话发送一次结果" in result


def test_recent_wechat_articles_mcp_filters_by_publication_date_and_keeps_dates(monkeypatch):
    async def fake_request(method, path, **kwargs):
        assert (method, path, kwargs) == (
            "GET",
            "/wechat-feed/articles.json",
            {"params": {"limit": 50, "order": "published_desc", "published_on": "2026-07-23"}},
        )
        return StubResponse({"articles": [{
            "id": "article-1",
            "publisher": "深圳技术大学",
            "title": "今日文章",
            "published_at": "2026-07-23 09:30",
        }]})

    monkeypatch.setattr(mcp_server, "_request", fake_request)
    result = asyncio.run(
        mcp_server.knowledgehub_get_recent_wechat_articles(
            mcp_server.GetRecentWeChatArticlesInput(published_on="2026-07-23")
        )
    )

    assert "发布于 2026-07-23 09:30" in result


def test_workspace_overview_mcp_uses_the_agent_read_model(monkeypatch):
    async def fake_request(method, path, **kwargs):
        assert (method, path, kwargs) == (
            "GET",
            "/agent/workspace-overview",
            {"params": {"content_limit": 12, "task_limit": 12, "for_date": "2026-07-23", "conversation_key": "session-a"}},
        )
        return StubResponse({
            "date": "2026-07-23",
            "timezone": "Asia/Shanghai",
            "library": {"total_visible_items": 8},
            "tasks": [],
            "conversation_tasks": [],
            "wechat": {"today_article_count": 1, "today_articles": [{"publisher": "测试号", "title": "今日文章", "published_at": "2026-07-23 09:00"}], "subscriptions": []},
        })

    monkeypatch.setattr(mcp_server, "_request", fake_request)
    result = asyncio.run(
        mcp_server.knowledgehub_get_workspace_overview(
            mcp_server.WorkspaceOverviewInput(for_date="2026-07-23", conversation_key="session-a")
        )
    )

    assert "内容库：8 项" in result
    assert "今日文章" in result


def test_group_report_mcp_creates_a_conversation_bound_persistent_task(monkeypatch):
    calls = []

    async def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return StubResponse({"task_id": "report-task-1", "status": "queued", "progress": 0})

    monkeypatch.setattr(mcp_server, "_request", fake_request)
    result = asyncio.run(
        mcp_server.knowledgehub_generate_group_report(
            mcp_server.GroupReportRequestInput(
                group_id="group-1",
                report_type="range",
                window_start="2026-07-20T00:00:00+08:00",
                window_end="2026-07-27T00:00:00+08:00",
                conversation_key="session-a",
            )
        )
    )

    assert calls == [("POST", "/openclaw/report-tasks", {"json": {
        "group_id": "group-1",
        "report_type": "range",
        "window_start": "2026-07-20T00:00:00+08:00",
        "window_end": "2026-07-27T00:00:00+08:00",
        "include_history_context": True,
        "file_name": None,
        "conversation_key": "session-a",
        "conversation_label": None,
    }})]
    assert "report-task-1" in result
    assert "直接发送" in result


def test_group_report_draft_mcp_requires_explicit_confirmation(monkeypatch):
    async def fake_request(method, path, **kwargs):
        assert (method, path, kwargs) == (
            "POST",
            "/openclaw/report-tasks/report-task-1/draft",
            {"json": {"user_confirmed": True, "title": "", "digest": "", "author": ""}},
        )
        return StubResponse({"draft_media_id": "draft-media-1"})

    monkeypatch.setattr(mcp_server, "_request", fake_request)
    result = asyncio.run(
        mcp_server.knowledgehub_create_group_report_draft(
            mcp_server.CreateGroupReportDraftInput(task_id="report-task-1", user_confirmed=True)
        )
    )

    assert "draft-media-1" in result
    assert "尚未发布" in result

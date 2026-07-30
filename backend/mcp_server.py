from __future__ import annotations

import json
import os
from datetime import date, datetime
from enum import Enum
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field


API_BASE = os.environ.get("KNOWLEDGEHUB_API_BASE", "http://127.0.0.1:8000/api").rstrip("/")

mcp = FastMCP("knowledgehub_mcp")


class ResponseFormat(str, Enum):
    JSON = "json"
    MARKDOWN = "markdown"


class IngestLinkInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    text: str = Field(..., min_length=1, description="A Douyin, Bilibili, WeChat Official Account, or Xiaohongshu link, or forwarded message text containing one.")
    mode: str = Field(default="process", pattern="^(process|capture)$", description="Use process to start a task immediately, or capture to only save it to the inbox.")
    use_cache: bool = Field(default=True, description="Reuse existing downloaded/transcribed content when available.")
    ai_model: str | None = Field(default=None, description="Optional model override, for example deepseek-chat.")
    conversation_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=512,
        description="Current OpenClaw session key. Pass it for every WeChat process request so KnowledgeHub can bind the task to this conversation. The backend stores only a hash.",
    )
    conversation_label: str | None = Field(default=None, max_length=120, description="Optional local-only label. Do not include a phone number or sensitive contact data.")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class GetTaskInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    task_id: str = Field(..., min_length=1, description="KnowledgeHub processing task id.")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class ExportMarkdownInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    content_item_id: str = Field(..., min_length=1, description="KnowledgeHub content item id.")


class ListTasksInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    limit: int = Field(default=8, ge=1, le=20, description="Maximum number of recent tasks to return.")
    status: str | None = Field(
        default=None,
        pattern="^(queued|running|paused|succeeded|failed|cancelled)$",
        description="Optional task status filter.",
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class SearchContentInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(..., min_length=1, description="Words to search in KnowledgeHub titles, summaries, and source text.")
    limit: int = Field(default=8, ge=1, le=20, description="Maximum number of search results to return.")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class RetryTaskInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    task_id: str = Field(..., min_length=1, description="A failed or cancelled KnowledgeHub task id to retry.")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class AutomationStatusInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class WorkspaceOverviewInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    for_date: date | None = Field(default=None, description="China calendar date for the workbench snapshot (YYYY-MM-DD). Defaults to today.")
    conversation_key: str | None = Field(default=None, min_length=1, max_length=512, description="Current OpenClaw session key, used only to include this conversation's tasks.")
    content_limit: int = Field(default=12, ge=1, le=50)
    task_limit: int = Field(default=12, ge=1, le=50)
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class ConversationTaskListInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    conversation_key: str = Field(..., min_length=1, max_length=512, description="Current OpenClaw session key; it is hashed locally for lookup.")
    limit: int = Field(default=8, ge=1, le=50)
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class BindConversationTaskInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    conversation_key: str = Field(..., min_length=1, max_length=512, description="Current OpenClaw session key; it is hashed locally before storage.")
    task_id: str = Field(..., min_length=1, description="Existing KnowledgeHub task id to bind to this conversation.")
    conversation_label: str | None = Field(default=None, max_length=120, description="Optional local-only label. Never use a phone number or sensitive contact data.")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class ClaimConversationNotificationInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    conversation_key: str = Field(..., min_length=1, max_length=512, description="Current OpenClaw session key; it is hashed locally for lookup.")
    task_id: str = Field(..., min_length=1, description="Bound KnowledgeHub task id.")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class RecordConversationTurnInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    conversation_key: str = Field(..., min_length=1, max_length=512, description="Current OpenClaw session key; it is hashed locally before storage.")
    role: str = Field(..., pattern="^(user|assistant)$", description="Whether this is the user's or assistant's visible message.")
    text: str = Field(..., min_length=1, max_length=12000, description="Visible message text. It is stored only when the user has enabled full local conversation mirroring.")
    turn_id: str | None = Field(default=None, max_length=160, description="Stable OpenClaw message/turn id when available, to avoid duplicate storage.")
    conversation_label: str | None = Field(default=None, max_length=120, description="Optional local-only label. Never use a phone number or sensitive contact data.")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class SearchWeChatAccountsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    account_id: str = Field(..., min_length=1, description="A connected WeChat public-platform account id.")
    query: str = Field(..., min_length=1, description="Official Account name or keyword to search.")
    limit: int = Field(default=10, ge=1, le=20)
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class SubscribeWeChatAccountInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    account_id: str = Field(..., min_length=1, description="A connected WeChat public-platform account id.")
    fakeid: str = Field(..., min_length=1, description="Official Account fakeid returned by knowledgehub_search_wechat_accounts.")
    publisher_name: str = Field(..., min_length=1, description="Official Account display name.")
    sync_interval_minutes: int = Field(default=1440, ge=360, le=1440)
    auto_process: bool = Field(default=False, description="Queue newly discovered articles for the AI pipeline.")
    initial_sync: bool = Field(default=True, description="Immediately inspect the latest articles after subscribing.")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class ListWeChatSubscriptionsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class GetRecentWeChatArticlesInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    subscription_id: str | None = Field(default=None, min_length=1)
    published_on: date | None = Field(default=None, description="Only articles published on this date (YYYY-MM-DD). Use the current China date for requests such as “今天有什么文章”.")
    limit: int = Field(default=50, ge=1, le=50)
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class ReadWeChatArticleInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    article_id: str = Field(..., min_length=1, description="A subscribed article id returned by knowledgehub_get_recent_wechat_articles.")


class GroupReportRequestInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    group_id: str = Field(..., min_length=1, description="Report group id returned by knowledgehub_list_report_groups.")
    report_type: str = Field(..., pattern="^(daily|weekly|range)$", description="daily, weekly, or a custom range.")
    window_start: datetime | None = Field(default=None, description="Inclusive China-time start, ISO 8601 with timezone, e.g. 2026-07-20T00:00:00+08:00. Required for range.")
    window_end: datetime | None = Field(default=None, description="Exclusive China-time end, ISO 8601 with timezone, e.g. 2026-07-27T00:00:00+08:00. Required for range.")
    include_history_context: bool = Field(default=True, description="Use the existing group report's historical context.")
    file_name: str | None = Field(default=None, max_length=120)
    conversation_key: str = Field(..., min_length=1, max_length=512, description="Current OpenClaw session key. The backend stores only its hash and delivers the finished report to this same WeChat conversation.")
    conversation_label: str | None = Field(default=None, max_length=120, description="Optional local-only label. Never use a phone number or sensitive contact data.")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class GetGroupReportTaskInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    task_id: str = Field(..., min_length=1, description="Task id returned by knowledgehub_generate_group_report.")
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class CreateGroupReportDraftInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    task_id: str = Field(..., min_length=1, description="A completed group report task id.")
    user_confirmed: bool = Field(..., description="Set true only after the user explicitly says to create a WeChat Official Account draft.")
    title: str = Field(default="", max_length=64)
    digest: str = Field(default="", max_length=120)
    author: str = Field(default="", max_length=64)
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


async def _request(method: str, path: str, **kwargs: Any) -> httpx.Response:
    url = f"{API_BASE}{path}"
    try:
        # This server is launched by OpenClaw's LaunchAgent, which does not
        # inherit NO_PROXY.  Do not let macOS proxy settings intercept calls
        # to the local KnowledgeHub API and turn them into opaque 502 errors.
        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            return response
    except httpx.ConnectError as exc:
        raise RuntimeError(
            "KnowledgeHub 后端未连接。请先启动 KnowledgeHub，再重试。"
        ) from exc
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500]
        try:
            parsed = exc.response.json()
            detail = parsed.get("detail", detail) if isinstance(parsed, dict) else detail
        except Exception:
            pass
        raise RuntimeError(f"KnowledgeHub API 返回错误 {exc.response.status_code}: {detail}") from exc


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _task_summary(task: dict[str, Any] | None) -> str:
    if not task:
        return "暂无任务。"
    lines = [
        f"任务：{task.get('task_id')}",
        f"状态：{task.get('status')}",
        f"进度：{task.get('overall_progress', 0)}%",
    ]
    if task.get("display_title"):
        lines.append(f"标题：{task['display_title']}")
    if task.get("platform"):
        lines.append(f"来源：{task['platform']}")
    if task.get("error"):
        lines.append(f"错误：{task['error']}")
    if task.get("summary"):
        summary = str(task["summary"]).strip()
        lines.append(f"\n摘要：\n{summary[:1200]}")
    if task.get("content_item_id"):
        lines.append(f"\ncontent_item_id：{task['content_item_id']}")
    return "\n".join(lines)


def _task_list_summary(tasks: list[dict[str, Any]]) -> str:
    if not tasks:
        return "没有符合条件的任务。"
    lines = ["最近任务："]
    for task in tasks:
        title = task.get("display_title") or task.get("source_title") or "未命名内容"
        lines.append(
            f"- {title}｜{task.get('status', 'unknown')}｜{task.get('overall_progress', 0)}%｜任务 {task.get('task_id')}"
        )
        if task.get("error"):
            lines.append(f"  错误：{task['error']}")
    return "\n".join(lines)


def _search_summary(results: list[dict[str, Any]]) -> str:
    if not results:
        return "没有找到匹配的 KnowledgeHub 内容。"
    lines = ["检索结果："]
    for result in results:
        lines.append(f"- {result.get('title') or '未命名内容'}｜内容 {result.get('content_key')}")
        snippet = result.get("summary_snippet") or result.get("transcript_snippet")
        if snippet:
            lines.append(f"  {snippet}")
    return "\n".join(lines)


def _automation_status_summary(status: dict[str, Any]) -> str:
    if status.get("automation_ready"):
        mapping = status.get("conversation_mapping") or {}
        mirror = "已开启" if mapping.get("transcript_mirror_enabled") else "关闭（不保存正文）"
        return (
            "微信链接自动处理已就绪：OpenClaw、微信、KnowledgeHub MCP 与本机后端均可用。\n"
            f"会话—任务映射：已启用；完整微信对话镜像：{mirror}。"
        )
    labels = {
        "gateway": "OpenClaw",
        "wechat": "微信通道",
        "mcp": "KnowledgeHub MCP",
        "backend": "本机后端",
    }
    details = [f"{labels['gateway']}：{status.get('detail') or '状态未知'}"]
    for key in ("wechat", "mcp", "backend"):
        item = status.get(key) or {}
        details.append(f"{labels[key]}：{item.get('detail') or '状态未知'}")
    return "自动处理尚未就绪：\n- " + "\n- ".join(details)


def _conversation_task_summary(tasks: list[dict[str, Any]]) -> str:
    if not tasks:
        return "当前会话没有已绑定的 KnowledgeHub 任务。"
    lines = ["当前会话的任务："]
    for task in tasks:
        notification = "已通知" if task.get("notified_at") else "待完成通知"
        lines.append(
            f"- {task.get('title') or '未命名内容'}｜{task.get('status')}｜{task.get('progress', 0):g}%｜{notification}｜任务 {task.get('task_id')}"
        )
    return "\n".join(lines)


def _notification_claim_summary(result: dict[str, Any]) -> str:
    if result.get("should_notify"):
        return f"任务 {result.get('task_id')} 已锁定本次完成通知；现在可以向当前会话发送一次结果。"
    return f"任务 {result.get('task_id')} 暂不应通知：{result.get('reason') or '没有可发送的新结果'}。"


def _workspace_overview_summary(overview: dict[str, Any]) -> str:
    library = overview.get("library") or {}
    wechat = overview.get("wechat") or {}
    lines = [
        f"KnowledgeHub 工作台总览｜{overview.get('date')}（{overview.get('timezone')}）",
        f"内容库：{library.get('total_visible_items', 0)} 项可见内容。",
        f"今日公众号文章：{wechat.get('today_article_count', 0)} 篇。",
    ]
    articles = wechat.get("today_articles") or []
    if articles:
        lines.append("今日文章：")
        for article in articles:
            lines.append(f"- {article.get('publisher')}｜{article.get('title')}｜{article.get('published_at')}")
    tasks = overview.get("tasks") or []
    if tasks:
        lines.append("最近任务：")
        for task in tasks[:6]:
            lines.append(f"- {task.get('title')}｜{task.get('status')}｜{task.get('progress', 0):g}%")
    subscriptions = wechat.get("subscriptions") or []
    attention = [item for item in subscriptions if item.get("last_error") or item.get("account_status") != "active"]
    if attention:
        lines.append("需要注意的订阅：")
        for item in attention[:6]:
            lines.append(f"- {item.get('publisher')}｜{item.get('last_error') or item.get('account_status')}")
    conversation_tasks = overview.get("conversation_tasks") or []
    if conversation_tasks:
        lines.append(f"当前会话任务：{len(conversation_tasks)} 个。")
    return "\n".join(lines)


def _wechat_subscription_summary(subscriptions: list[dict[str, Any]]) -> str:
    if not subscriptions:
        return "尚未订阅公众号。"
    lines = ["已订阅公众号："]
    for subscription in subscriptions:
        status = "启用" if subscription.get("enabled") else "已暂停"
        lines.append(f"- {subscription.get('mp_name')}｜{status}｜订阅 {subscription.get('id')}")
    return "\n".join(lines)


def _wechat_account_summary(accounts: list[dict[str, Any]]) -> str:
    if not accounts:
        return "没有找到匹配的公众号。"
    lines = ["搜索到的公众号："]
    for account in accounts:
        lines.append(f"- {account.get('name')}｜fakeid {account.get('fakeid')}")
    return "\n".join(lines)


def _wechat_articles_summary(articles: list[dict[str, Any]], *, published_on: date | None = None) -> str:
    if not articles:
        if published_on:
            return f"没有找到发布于 {published_on.isoformat()} 的本地订阅文章。"
        return "没有已发现的公众号文章。"
    lines = [f"公众号文章（发布于 {published_on.isoformat()}）：" if published_on else "公众号文章（按发布时间倒序）："]
    for article in articles:
        published_at = article.get("published_at") or "发布日期未知"
        lines.append(f"- {article.get('publisher')}｜{article.get('title')}｜发布于 {published_at}｜文章 {article.get('id')}")
    return "\n".join(lines)


def _report_task_summary(task: dict[str, Any]) -> str:
    lines = [
        f"分组报告任务：{task.get('task_id')}",
        f"状态：{task.get('status')}",
        f"进度：{float(task.get('progress') or 0):g}%",
    ]
    if task.get("report_title"):
        lines.append(f"报告：{task['report_title']}")
    if task.get("source_count") is not None:
        lines.append(f"分析文章：{task['source_count']} 篇")
    if task.get("error"):
        lines.append(f"错误：{task['error']}")
    if task.get("content_item_id"):
        lines.append(f"content_item_id：{task['content_item_id']}")
    return "\n".join(lines)


@mcp.tool(
    name="knowledgehub_ingest_link",
    annotations={
        "title": "Send a link to KnowledgeHub",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def knowledgehub_ingest_link(params: IngestLinkInput) -> str:
    """Capture a Douyin, Bilibili, WeChat Official Account, or Xiaohongshu link in KnowledgeHub.

    Use this when a user forwards a supported content link and wants KnowledgeHub
    to process it into transcript/article text, summary, and markdown.
    """
    response = await _request(
        "POST",
        "/ingest/link",
        json={
            "text": params.text,
            "mode": params.mode,
            "use_cache": params.use_cache,
            "ai_model": params.ai_model,
            "conversation_key": params.conversation_key,
            "conversation_channel": "weixin",
            "conversation_label": params.conversation_label,
        },
    )
    data = response.json()
    if params.response_format == ResponseFormat.JSON:
        return _json(data)
    task = data.get("task")
    item = data.get("item") or {}
    lines = [
        "已送入 KnowledgeHub。",
        f"来源：{data.get('platform')}",
        f"链接：{data.get('url')}",
        f"内容：{item.get('title') or item.get('id') or '未命名'}",
    ]
    if task:
        lines.append("")
        lines.append(_task_summary(task))
    else:
        lines.append("模式：仅收进箱，未开始处理。")
    return "\n".join(lines)


@mcp.tool(
    name="knowledgehub_get_task",
    annotations={
        "title": "Get KnowledgeHub task status",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def knowledgehub_get_task(params: GetTaskInput) -> str:
    """Get the actual processing status, progress, and summary for one KnowledgeHub task."""
    response = await _request("GET", f"/tasks/{params.task_id}")
    data = response.json()
    return _json(data) if params.response_format == ResponseFormat.JSON else _task_summary(data)


@mcp.tool(
    name="knowledgehub_list_tasks",
    annotations={
        "title": "List recent KnowledgeHub tasks",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def knowledgehub_list_tasks(params: ListTasksInput) -> str:
    """List recent KnowledgeHub tasks. Use this to answer status questions when no task id is known."""
    response = await _request("GET", "/tasks")
    tasks = response.json()
    if params.status:
        tasks = [task for task in tasks if task.get("status") == params.status]
    tasks = tasks[:params.limit]
    return _json(tasks) if params.response_format == ResponseFormat.JSON else _task_list_summary(tasks)


@mcp.tool(
    name="knowledgehub_search_content",
    annotations={
        "title": "Search KnowledgeHub content",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def knowledgehub_search_content(params: SearchContentInput) -> str:
    """Search finished KnowledgeHub content by title, summary, or transcript/article text."""
    response = await _request("GET", "/search", params={"q": params.query, "limit": params.limit})
    results = response.json()
    return _json(results) if params.response_format == ResponseFormat.JSON else _search_summary(results)


@mcp.tool(
    name="knowledgehub_retry_task",
    annotations={
        "title": "Retry a failed KnowledgeHub task",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def knowledgehub_retry_task(params: RetryTaskInput) -> str:
    """Retry a failed or cancelled KnowledgeHub task. Never use this for tasks that already succeeded."""
    response = await _request("POST", f"/tasks/{params.task_id}/retry")
    task = response.json()
    return _json(task) if params.response_format == ResponseFormat.JSON else _task_summary(task)


@mcp.tool(
    name="knowledgehub_get_automation_status",
    annotations={
        "title": "Check KnowledgeHub automation status",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def knowledgehub_get_automation_status(params: AutomationStatusInput) -> str:
    """Check whether the local OpenClaw, WeChat, MCP, and KnowledgeHub path is ready."""
    response = await _request("GET", "/openclaw-gateway", params={"refresh": "true"})
    status = response.json()
    return _json(status) if params.response_format == ResponseFormat.JSON else _automation_status_summary(status)


@mcp.tool(
    name="knowledgehub_get_workspace_overview",
    annotations={
        "title": "Get the KnowledgeHub workbench overview",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def knowledgehub_get_workspace_overview(params: WorkspaceOverviewInput) -> str:
    """Get the same safe, read-only facts visible in the KnowledgeHub workbench.

    Use this before answering broad questions such as “今天有什么”, “工作台
    现在怎么样”, or “最近有什么需要处理”. It includes library cards, task
    queue, dated WeChat articles, subscription health, and current-conversation
    tasks—but never credentials, cookies, full chat transcripts, or file paths.
    """
    query: dict[str, Any] = {"content_limit": params.content_limit, "task_limit": params.task_limit}
    if params.for_date:
        query["for_date"] = params.for_date.isoformat()
    if params.conversation_key:
        query["conversation_key"] = params.conversation_key
    response = await _request("GET", "/agent/workspace-overview", params=query)
    overview = response.json()
    return _json(overview) if params.response_format == ResponseFormat.JSON else _workspace_overview_summary(overview)


@mcp.tool(
    name="knowledgehub_list_report_groups",
    annotations={
        "title": "List KnowledgeHub report groups",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def knowledgehub_list_report_groups() -> str:
    """List the existing KnowledgeHub report groups before generating a group report."""
    response = await _request("GET", "/wechat-report-groups")
    groups = response.json()
    if not groups:
        return "尚未配置报告分组。请先在 KnowledgeHub 工作台的公众号报告中创建分组。"
    lines = ["可用报告分组："]
    for group in groups:
        lines.append(f"- {group.get('name') or '未命名分组'}｜分组 {group.get('id')}")
    return "\n".join(lines)


@mcp.tool(
    name="knowledgehub_generate_group_report",
    annotations={
        "title": "Generate a DeepSeek group report for this WeChat conversation",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def knowledgehub_generate_group_report(params: GroupReportRequestInput) -> str:
    """Start a persistent DeepSeek group report task and bind it to this WeChat conversation.

    Use this only after the user specifies a report group and period. For a
    custom date range, pass China-time ISO timestamps with an explicit +08:00
    timezone. The backend delivers the completed Markdown directly to this
    same WeChat conversation; do not create a cron job or retell the report.
    """
    response = await _request(
        "POST",
        "/openclaw/report-tasks",
        json={
            "group_id": params.group_id,
            "report_type": params.report_type,
            "window_start": params.window_start.isoformat() if params.window_start else None,
            "window_end": params.window_end.isoformat() if params.window_end else None,
            "include_history_context": params.include_history_context,
            "file_name": params.file_name,
            "conversation_key": params.conversation_key,
            "conversation_label": params.conversation_label,
        },
    )
    task = response.json()
    if params.response_format == ResponseFormat.JSON:
        return _json(task)
    return _report_task_summary(task) + "\n\n生成完成后，KnowledgeHub 会将 DeepSeek 生成的报告原文直接发送到当前微信会话。"


@mcp.tool(
    name="knowledgehub_get_group_report_task",
    annotations={
        "title": "Get a group report task status",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def knowledgehub_get_group_report_task(params: GetGroupReportTaskInput) -> str:
    """Check the actual persisted status of a DeepSeek group report task."""
    response = await _request("GET", f"/openclaw/report-tasks/{params.task_id}")
    task = response.json()
    return _json(task) if params.response_format == ResponseFormat.JSON else _report_task_summary(task)


@mcp.tool(
    name="knowledgehub_create_group_report_draft",
    annotations={
        "title": "Create a WeChat Official Account draft from a completed report",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def knowledgehub_create_group_report_draft(params: CreateGroupReportDraftInput) -> str:
    """Create an Official Account draft after an explicit user instruction.

    Never call this merely because a report has completed. It creates a remote
    WeChat draft but does not publish or group-send it. A reviewed report cover
    must already exist in KnowledgeHub; otherwise the backend returns a clear
    instruction instead of silently generating a billable image.
    """
    response = await _request(
        "POST",
        f"/openclaw/report-tasks/{params.task_id}/draft",
        json={
            "user_confirmed": params.user_confirmed,
            "title": params.title,
            "digest": params.digest,
            "author": params.author,
        },
    )
    draft = response.json()
    if params.response_format == ResponseFormat.JSON:
        return _json(draft)
    return (
        f"已创建微信公众号草稿：{draft.get('draft_media_id') or draft.get('id') or '已提交'}。\n"
        "草稿尚未发布或群发，请在微信公众号后台审核后自行发布。"
    )


@mcp.tool(
    name="knowledgehub_list_conversation_tasks",
    annotations={
        "title": "List tasks for this OpenClaw conversation",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def knowledgehub_list_conversation_tasks(params: ConversationTaskListInput) -> str:
    """List only the KnowledgeHub tasks bound to the current OpenClaw conversation.

    Use this for requests such as “刚才那个链接怎么样了”, never fall back to
    globally recent tasks when a current conversation key is available.
    """
    response = await _request(
        "GET",
        "/openclaw/conversation-tasks",
        params={"conversation_key": params.conversation_key, "limit": params.limit},
    )
    tasks = response.json()
    return _json(tasks) if params.response_format == ResponseFormat.JSON else _conversation_task_summary(tasks)


@mcp.tool(
    name="knowledgehub_bind_conversation_task",
    annotations={
        "title": "Bind an existing task to this OpenClaw conversation",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def knowledgehub_bind_conversation_task(params: BindConversationTaskInput) -> str:
    """Bind an existing task when it was created without a conversation key."""
    response = await _request(
        "POST",
        "/openclaw/conversation-tasks",
        json={
            "conversation_key": params.conversation_key,
            "task_id": params.task_id,
            "channel": "weixin",
            "display_name": params.conversation_label,
        },
    )
    data = response.json()
    if params.response_format == ResponseFormat.JSON:
        return _json(data)
    return f"任务 {data.get('task_id')} 已绑定到当前会话（{data.get('conversation_id')}）。"


@mcp.tool(
    name="knowledgehub_claim_conversation_notification",
    annotations={
        "title": "Claim one terminal notification for a conversation task",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def knowledgehub_claim_conversation_notification(params: ClaimConversationNotificationInput) -> str:
    """Atomically claim the one completion/failure reply for a task in this conversation.

    Call this after confirming a task is terminal and before replying from a
    follow-up cron job. If it says not to notify, return NO_REPLY.
    """
    response = await _request(
        "POST",
        "/openclaw/conversation-tasks/claim-notification",
        json={"conversation_key": params.conversation_key, "task_id": params.task_id},
    )
    data = response.json()
    return _json(data) if params.response_format == ResponseFormat.JSON else _notification_claim_summary(data)


@mcp.tool(
    name="knowledgehub_record_conversation_turn",
    annotations={
        "title": "Optionally mirror one visible conversation turn locally",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def knowledgehub_record_conversation_turn(params: RecordConversationTurnInput) -> str:
    """Store one visible WeChat turn only when the user has explicitly enabled local mirroring.

    This tool is safe to call while mirroring is disabled: the backend records
    no message content and reports that storage is off.
    """
    response = await _request(
        "POST",
        "/openclaw/conversation-turns",
        json={
            "conversation_key": params.conversation_key,
            "role": params.role,
            "text": params.text,
            "turn_id": params.turn_id,
            "channel": "weixin",
            "display_name": params.conversation_label,
        },
    )
    data = response.json()
    if params.response_format == ResponseFormat.JSON:
        return _json(data)
    return "已本地保存此消息。" if data.get("stored") else "未保存此消息：完整对话镜像未开启。"


@mcp.tool(
    name="knowledgehub_export_markdown",
    annotations={
        "title": "Export KnowledgeHub markdown",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def knowledgehub_export_markdown(params: ExportMarkdownInput) -> str:
    """Export the generated markdown draft for a processed KnowledgeHub item."""
    response = await _request("GET", f"/markdown/content/{params.content_item_id}/export")
    return response.text


@mcp.tool(name="knowledgehub_search_wechat_accounts", annotations={"title": "Search WeChat Official Accounts", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def knowledgehub_search_wechat_accounts(params: SearchWeChatAccountsInput) -> str:
    """Search WeChat Official Accounts using one of the user's connected public-platform accounts."""
    response = await _request("GET", f"/wechat-subscriptions/accounts/{params.account_id}/search", params={"q": params.query, "limit": params.limit})
    data = response.json()
    return _json(data) if params.response_format == ResponseFormat.JSON else _wechat_account_summary(data)


@mcp.tool(name="knowledgehub_subscribe_wechat_account", annotations={"title": "Subscribe to a WeChat Official Account", "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True})
async def knowledgehub_subscribe_wechat_account(params: SubscribeWeChatAccountInput) -> str:
    """Subscribe to an Official Account. This changes the local KnowledgeHub subscription list."""
    response = await _request("POST", "/wechat-subscriptions", json={"account_id": params.account_id, "fakeid": params.fakeid, "mp_name": params.publisher_name, "sync_interval_minutes": params.sync_interval_minutes, "auto_process": params.auto_process, "initial_sync": params.initial_sync})
    data = response.json()
    return _json(data) if params.response_format == ResponseFormat.JSON else _wechat_subscription_summary([data.get("subscription") or data])


@mcp.tool(name="knowledgehub_list_wechat_subscriptions", annotations={"title": "List WeChat subscriptions", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
async def knowledgehub_list_wechat_subscriptions(params: ListWeChatSubscriptionsInput) -> str:
    """List local WeChat Official Account subscriptions without exposing credentials."""
    response = await _request("GET", "/wechat-subscriptions")
    data = response.json()
    return _json(data) if params.response_format == ResponseFormat.JSON else _wechat_subscription_summary(data)


@mcp.tool(name="knowledgehub_get_recent_wechat_articles", annotations={"title": "Get recent WeChat articles", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False})
async def knowledgehub_get_recent_wechat_articles(params: GetRecentWeChatArticlesInput) -> str:
    """List subscribed articles by publication time, optionally for one exact date.

    For “今天有什么文章”, pass today's China date as published_on before
    answering. Every Markdown response includes the actual publication time.
    """
    query: dict[str, Any] = {"limit": params.limit, "order": "published_desc"}
    if params.subscription_id:
        query["subscription_id"] = params.subscription_id
    if params.published_on:
        query["published_on"] = params.published_on.isoformat()
    response = await _request("GET", "/wechat-feed/articles.json", params=query)
    data = response.json()
    articles = data.get("articles", [])
    return _json(data) if params.response_format == ResponseFormat.JSON else _wechat_articles_summary(articles, published_on=params.published_on)


@mcp.tool(name="knowledgehub_read_wechat_article", annotations={"title": "Read a subscribed WeChat article", "readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True})
async def knowledgehub_read_wechat_article(params: ReadWeChatArticleInput) -> str:
    """Read one subscribed article as Markdown. First read may fetch and cache its public body, but never invokes AI."""
    response = await _request("GET", f"/wechat-feed/article/{params.article_id}.md")
    return response.text


if __name__ == "__main__":
    mcp.run()

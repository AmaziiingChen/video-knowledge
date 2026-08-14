# KnowledgeHub OpenClaw Ingest

KnowledgeHub accepts Douyin short videos, Bilibili videos, WeChat Official
Account articles, and Xiaohongshu notes. OpenClaw or any other local bridge
should send captured links to the unified ingest endpoint instead of calling
task APIs directly.

## Endpoint

```http
POST /api/ingest/link
Content-Type: application/json
```

```json
{
  "text": "用户转发的整段消息或链接",
  "mode": "process",
  "use_cache": true,
  "ai_model": "deepseek-v4-flash"
}
```

`mode` supports:

- `process`: capture the link and immediately start processing.
- `capture`: only add it to the inbox.

Supported sources:

- `douyin`: `https://v.douyin.com/...`
- `bilibili`: `https://www.bilibili.com/video/...` and `https://b23.tv/...`
- `wechat`: `https://mp.weixin.qq.com/...`
- `xiaohongshu`: `https://www.xiaohongshu.com/explore/...`,
  `https://www.xiaohongshu.com/discovery/item/...`,
  `https://www.xiaohongshu.com/search_result/...`, and `https://xhslink.com/...`

The response includes the normalized platform, URL, content item, and task:

```json
{
  "platform": "wechat",
  "url": "https://mp.weixin.qq.com/...",
  "created": true,
  "duplicate": false,
  "item": {},
  "task": {}
}
```

OpenClaw should use `task.task_id` to poll:

```http
GET /api/tasks/{task_id}
```

When `task.status` is `succeeded`, the useful fields are:

- `task.display_title`
- `task.summary`
- `task.markdown_draft_path`
- `task.content_item_id`

Markdown export:

```http
GET /api/markdown/content/{content_item_id}/export
```

## Suggested WeChat Reply Flow

1. On message received, call `/api/ingest/link`.
2. Reply: `已收到，正在处理：{platform}`.
3. Poll `/api/tasks/{task_id}` every few seconds.
4. When done, reply with `display_title` and the first short paragraph of
   `summary`.
5. If failed, reply with `task.error`.

Keep OpenClaw as the WeChat transport layer. KnowledgeHub should stay focused on
content processing and local preview.

## OpenClaw conversation rules

For a supported link sent from a WeChat conversation, OpenClaw should immediately
acknowledge receipt, retain the returned `task_id` in that conversation, and use
the task id for later “刚才那个” status, retry, or Markdown requests. A `capture`
request must not start AI processing. Retry, subscription changes, cancellation,
or other state-changing requests require an explicit confirmation from the user.

OpenClaw should create one low-frequency, conversation-bound follow-up for a
processed task. It checks the task until it reaches a terminal state, replies
once with the title and concise summary or failure reason, then removes itself.
It must stay silent while the task is still queued or running and must never
automatically retry a failed task.

## Persistent WeChat conversation bindings

For every `process` request received through WeChat, OpenClaw must pass its
current runtime session key as `conversation_key` to
`knowledgehub_ingest_link`. KnowledgeHub hashes that key before writing it to
SQLite, then binds the returned task to that conversation. It never stores the
raw session key, WeChat account, or contact identifier.

Use these MCP tools for follow-ups instead of looking through globally recent
tasks:

- `knowledgehub_list_conversation_tasks`: resolve “刚才那个链接” only within
  the current session.
- `knowledgehub_bind_conversation_task`: repair a binding for a task created
  without `conversation_key`.
- `knowledgehub_claim_conversation_notification`: after a task reaches a
  terminal state, atomically claim its one completion/failure reply. If it
  reports that notification is already claimed, return `NO_REPLY`.

The desktop app also exposes an opt-in “完整微信对话镜像” control. It is off by
default. When enabled, OpenClaw may call `knowledgehub_record_conversation_turn`
for visible user and assistant messages. The backend saves these local copies
only for the selected retention period (7, 30, 90, or 365 days); it stores no
message text at all while the setting is off.

Before allowing more than one WeChat contact to use the agent, configure
OpenClaw private-message isolation as `session.dmScope: per-channel-peer`.
This prevents different contacts from sharing the same conversation key and
therefore the same KnowledgeHub task context.

## Local MCP bridge configuration

KnowledgeHub never modifies `~/.openclaw/openclaw.json` automatically at
startup. In the desktop app, open “设置 → 微信链接自动处理” and choose “修复 MCP”
when the KnowledgeHub row is missing or invalid. That explicit, local action
uses the OpenClaw CLI to replace **only** `mcp.servers.knowledgehub`, reloads
the managed OpenClaw Gateway so cached conversation runtimes are retired, and
proves the entry with a stdio tools-list handshake; it never edits other MCP
servers. The configuration contains a capability **file path**, never
the capability value; the file is created with mode `0600`, rotates on every
KnowledgeHub launch and is invalidated by a short parent-process lease.

For the installed DMG, use the packaged backend entry and replace `<HOME>` with
the current account's absolute home-directory path (OpenClaw does not expand the
placeholder):

```json
{
  "mcp": {
    "servers": {
      "knowledgehub": {
        "command": "/Applications/KnowledgeHub.app/Contents/Resources/backend/knowledgehub-backend/knowledgehub-backend",
        "args": ["--mcp-stdio"],
        "env": {
          "KNOWLEDGEHUB_MCP_BRIDGE_TOKEN_FILE": "<HOME>/Library/Application Support/knowledgehub-desktop/run/mcp-bridge-token"
        }
      }
    }
  }
}
```

For source development, point `command` to the absolute Python executable,
place the absolute repository `backend/desktop_server.py` before
`--mcp-stdio` in `args`, and use the repository's absolute
`data/run/mcp-bridge-token` path. Start with `./start.sh`; `./stop.sh` stops the
lease heartbeat and removes the bridge files before stopping the backend.

Do not paste the capability value into JSON, a URL, command argument or log.
The MCP capability is separate from the renderer's instance token and can call
only the method/path pairs used by the documented MCP tools. The API endpoint is
issued inside the same protected session lease, so an OpenClaw configuration
cannot redirect the capability to another local port. If KnowledgeHub is not
running, the lease expires or the configuration points to another command, the
status remains unavailable rather than reporting a config key as ready.
The `0700` directory and `0600` files prevent access by other local accounts;
they are not a security boundary against another malicious process already
running as the same macOS account. The short lease, per-launch rotation and
server-side route allowlist limit the effect of accidental exposure in that
local-account trust model.

## Local health checks

The app's “连接 → 微信链接自动处理” status checks the whole local chain instead
of only checking the Gateway: OpenClaw Gateway, the `openclaw-weixin` channel,
the `knowledgehub` MCP configuration, and the running KnowledgeHub backend.
The normal status view is cached briefly so opening the desktop app does not
continuously launch OpenClaw diagnostics; use “诊断” when a fresh check is needed.

If the backend is not running, the MCP bridge deliberately returns a clear
“请先启动 KnowledgeHub” error. Start the installed app or run `./start.sh`, then
resend the link or retry the OpenClaw task.

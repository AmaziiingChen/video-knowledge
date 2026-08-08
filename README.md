# Video Knowledge

一个仅面向 macOS（Apple Silicon）、数据留在本机的内容分析与知识沉淀工作台。它处理 Bilibili、抖音、微信公众号文章和校园官网内容，将内容转成可检索的文本、AI 总结和 Markdown 草稿，并可同步到 Obsidian。

> 当前公开版本仅支持 macOS；Windows 和 Linux 尚未进入支持范围。

在提交 issue、发布 fork 或打包前，请先阅读 [隐私与数据处理](PRIVACY.md)、[安全策略](SECURITY.md)、[第三方声明](THIRD_PARTY_NOTICES.md) 和 [贡献指南](CONTRIBUTING.md)。本项目采用 [MIT License](LICENSE)。

## 能做什么

- 处理抖音与 Bilibili 视频链接，并通过订阅自动发现微信公众号文章。
- 使用 B 站可获取字幕；没有字幕时下载媒体、提取音频并通过 Whisper 转写。
- 调用 DeepSeek 生成学习笔记、摘要、标签和质量评价，并记录 token、耗时和可选成本。
- 以后台队列处理任务，支持进度、日志、优先级、暂停、恢复、取消和失败重试；任务状态保存在 SQLite 中。
- 保存视频信息、字幕/转写、Markdown 草稿和本地全文索引；可在工作台内预览视频、字幕和笔记。
- 将 Markdown 同步到 Obsidian，并提示 Obsidian 中的外部修改冲突。
- 订阅微信公众号：授权后定时发现指定公众号的新文章，保存到内容库或送入 AI 分析队列。
- 按来源同步深圳技术大学公文通和学院官网，将通知、新闻按来源去重归档，并复用文章阅读与问答链路。
- 在 macOS 桌面端通过可见界面采集微信校园论坛帖子与评论，保留原始截图、断点和结构化结果；不抓包、不调用私有接口。

## 处理流程

```text
抖音 / Bilibili 链接 / 微信公众号订阅 / 校园官网
          ↓
内容库 → 解析元数据 → 字幕优先 / 下载与 ASR
          ↓
      AI 总结、标签、Markdown 草稿
          ↓
SQLite 全文检索 + 本地播放器 + Obsidian 同步
```

对于 B 站内容，应用会优先取得平台字幕；成功时跳过下载和 ASR。相同内容默认复用已保存的元信息、媒体、字幕和转写缓存，减少重复处理。

## 技术组成

| 层级 | 技术 |
| --- | --- |
| 前端 | Vue 3、Vite、Element Plus、Artplayer、Electron（Beta 外壳） |
| 后端 | FastAPI、SQLite、Pydantic Settings |
| 媒体与转写 | yt-dlp、ffmpeg、faster-whisper、MLX Whisper（可选） |
| AI | OpenAI SDK 兼容接口，默认 DeepSeek |
| 自动化接入 | 微信公众号订阅调度器 |

## 快速开始

### 1. 准备运行环境

需要 Python 3、Node.js/npm，以及以下系统命令：

- `ffmpeg`
- `yt-dlp`
- `node`
- `npm`

安装后端和前端依赖，并下载 Playwright Chromium：

```bash
python -m pip install -r requirements.txt
python -m playwright install chromium

cd frontend
npm ci
cd ..
```

### 2. 配置

复制 [backend/.env.example](backend/.env.example) 为 `backend/.env` 后，至少配置一个可用的 DeepSeek Key：

```dotenv
DEEPSEEK_API_KEY=你的_API_Key
```

默认会把笔记同步到应用数据目录内的 `data/obsidian`。请在设置中改成自己的 Obsidian vault，或在环境变量中指定：

```dotenv
OBSIDIAN_VAULT=/你的/Obsidian/Vault
```

常用可选配置：

```dotenv
# 默认模型与转写策略
DEEPSEEK_MODEL=deepseek-v4-flash
WHISPER_MODEL=small
ASR_BACKEND=auto
ASR_MODEL_STRATEGY=smart

# 仅在需要显示 AI 调用成本时配置（单位：每百万 token）
LLM_INPUT_COST_PER_MILLION_TOKENS=0
LLM_OUTPUT_COST_PER_MILLION_TOKENS=0

# B 站登录态（按需）
BILIBILI_COOKIE=

# Telegram 访问受限网络时可设置代理
TELEGRAM_PROXY_URL=

# 微信公众号订阅：本机调度器与默认检查间隔
WECHAT_SUBSCRIPTION_SCHEDULER_ENABLED=true
WECHAT_SUBSCRIPTION_SCHEDULER_INTERVAL_SECONDS=60
WECHAT_SUBSCRIPTION_DEFAULT_INTERVAL_MINUTES=1440

# 微信小程序视觉采集仍在 Beta，公开发行版保持关闭
MINIPROGRAM_FORUM_CAPTURE_ENABLED=false

```

完整配置项及默认值见 [backend/config.py](backend/config.py)。

抖音下载通常还需要 Cookie。可通过设置页配置，或将 Cookie 保存到 `data/douyin_cookies.txt`。Cookie 属于敏感信息，不应提交到版本控制。

### 3. 自检并启动

```bash
python scripts/preflight.py
./start.sh
```

启动成功后访问：

- 工作台：http://127.0.0.1:5173
- 后端 API：http://127.0.0.1:8000
- API 文档：http://127.0.0.1:8000/docs

macOS 也可直接双击：

- `Video Knowledge.command`：启动前后端并打开浏览器。
- `Video Knowledge Desktop.command`：以当前源码启动 Electron Beta 外壳；后端修改在下次启动时直接生效。正式发布包再执行对应的 `desktop:package:*` 命令。
- `Stop Video Knowledge.command`：停止由启动器管理的服务。

日志位于 `data/logs/backend.log` 与 `data/logs/frontend.log`；停止服务可运行：

```bash
./stop.sh
```

## 使用方式

### 从工作台处理 Bilibili 与抖音内容

在左侧栏底部的“粘贴链接...”输入框粘贴一条 Bilibili 或抖音分享链接，按 Enter 或点击发送按钮即可创建处理任务。处理完成后，内容会出现在左侧内容库；点击条目可查看视频、字幕/转写和 AI 结果。

### 补采平台互动与评论

B站和抖音内容会在常规处理时保存可用的作者、发布时间、互动指标、话题与评论样本。对已有内容，可在内容页右上角的“内容操作”中选择“补采互动与评论”，任务会进入现有的本机持久化队列。公开版暂不携带小红书采集组件，因为其原始第三方副本缺少可验证的授权文件；已保存的小红书资料仍可阅读。

补采默认最多读取 3 页、保存 60 条评论，单条内容的硬上限为 120 条；平台提前结束时会记录完整性，否则明确标记为样本。总结、追问和自定义分析最多选取 24 条有代表性的评论，避免评论体量挤占正文。评论属于未经验证的辅助材料，不能覆盖视频正文或被当作模型指令。

“提示词 → 侧栏操作 → 互动评论规则”可编辑评论共识、分歧、疑问和反馈的分析方式；底层仍保留一条只读的最小输入安全边界，避免评论内容劫持总结任务。修改后的当前启用版本会同时作用于视频总结、重新总结、追问和自定义按钮。

本机 API 还提供：

- `GET /api/content/{item_id}/source-context`：查看采集状态、互动指标、评论覆盖与最近错误。
- `POST /api/content/{item_id}/refresh-source-context`：为单条内容创建补采任务。
- `POST /api/content/source-context/backfill?limit=50`：按最近更新时间批量补采尚未就绪的内容，单次最多 200 条。

### 订阅微信公众号

从“设置 → 微信公众号订阅”打开管理面板，使用有公众号管理权限的微信公众平台账号扫码授权，搜索并选择要订阅的公众号。首次订阅默认检查最近 10 篇文章；之后默认每天检查一次，并在多个订阅之间错峰执行。

发现的新文章会去重写入内容库。订阅可选择“仅存入内容库”或“自动分析”；后者会直接复用现有的正文抓取、AI 总结、Markdown 和 Obsidian 同步流水线。登录态只存放在当前 macOS 用户的 Keychain，SQLite 与日志不会保存明文 Cookie 或 token。

微信公众平台的会话可能过期，也可能临时触发访问频控。登录失效时界面会提示重新授权；频控时账号会保持已授权状态并进入持久化冷却，暂停搜索、自动检查和手动回溯，预计恢复时间会显示在公众号管理页。请勿通过反复扫码或连续手动检查绕过冷却。

#### 详细操作

1. 确认你使用的微信具有至少一个公众号的公众平台管理权限；普通微信账号但未绑定任何公众号时，无法完成授权。
2. 打开“设置 → 微信公众号订阅”，在“授权账号”区域填写便于识别的名称（可选），点击“扫码连接”。
3. 使用微信扫描弹出的二维码，并在手机上确认登录；如果同一微信绑定多个公众号账号，按微信公众平台提示选择需要授权的账号。
4. 授权成功后，在“添加订阅”区域先选择刚连接的账号，再输入目标公众号名称并点击“搜索”。搜索结果来自该账号在微信公众平台可访问的检索能力。
5. 选择检查频率并点击“订阅”。默认每天检查一次；少量高优先级来源可选择每 6 或 12 小时。首次会检查最近 10 篇文章；重复发现的文章会自动去重，不会再次创建内容。
6. 选择文章处理方式：
   - “仅存入内容库”：保存文章记录和链接，方便在内容库中查找、整理或按需处理，不会自动调用 AI。
   - “自动分析”：新文章会进入现有的文章抓取、AI 总结、Markdown 与 Obsidian 同步流程。
7. 在“已订阅公众号”区域可暂停、恢复、切换“开启自动分析”、立即“同步”或取消订阅。自动分析开关影响之后新发现的文章；取消订阅只停止后续检查，不会删除已保存的文章和笔记。

#### 给阅读器与自动化工具使用

已发现的订阅文章可通过本机 API 增量读取：

- `GET /api/wechat-feed/articles.json?limit=50`：按发现顺序返回文章元数据和 `next_cursor`；下一次请求携带该 cursor 即可继续同步。
- `GET /api/wechat-feed/article/{article_id}.md`：按文章 id 导出带 YAML frontmatter 的 Markdown；首次导出会按需抓取并缓存正文，不会调用 AI。
- `GET /api/wechat-feed/subscriptions.json`：导出订阅配置（不含微信 Cookie、token 等凭据）。
- `GET /api/wechat-feed/rss.xml`：所有已发现文章的聚合 RSS；`GET /api/wechat-feed/rss/{subscription_id}.xml`：单公众号 RSS。

本项目的 MCP 服务也提供公众号搜索、订阅、列出订阅、读取最新文章和导出单篇文章 Markdown 工具；它们只使用本机 API，微信凭据仍保存在 macOS Keychain。

#### 正文清洗规则

可通过本机 API 配置文章入库前的清洗规则：`POST /api/wechat-content-filters` 创建规则，`GET /api/wechat-content-filters` 查看规则，`DELETE /api/wechat-content-filters/{rule_id}` 删除规则。规则可使用 CSS 选择器删除广告或推荐区块，也可用正则删除固定文字；不指定 `subscription_id` 时为全局规则，指定后只作用于该公众号订阅。

#### 扫码与授权问题

- “二维码已失效”：重新点击“扫码连接”，不要继续等待旧二维码。
- “登录态已失效”：在订阅面板重新扫码授权；已有文章和订阅配置会保留。
- “没有找到匹配的公众号”：换用更精确的名称，或确认授权的公众平台账号本身可以在网页端搜索到该公众号。
- 自动同步只在本项目后端运行时执行。关闭后端或电脑休眠期间不会补抓；恢复运行后可在订阅面板点击“同步”。
- “手动授权”仅用于扫码不可用的应急场景：只能填写你本人在官方公众平台网页会话中取得、且明确获授权使用的 token 与 Cookie。不要通过聊天、截图或任何公共渠道传递这些凭据；连接成功后它们仅保存在当前 macOS 用户的 Keychain。

公众号搜索、增量同步和正文抓取均在应用内部执行，不需要 Docker、额外管理页或本地端口。桌面版会随应用一同安装所需网络组件；微信登录态仍只保存在当前 macOS 用户的 Keychain。

### 任务与缓存

每个任务会经过解析、信息读取、下载、音频提取、转写、总结、保存等阶段。任务队列支持暂停、恢复、优先处理、取消和重试；重启后，排队与暂停任务可恢复，运行中的任务会标记为失败并可重试。

缓存默认存放在 `data/cache/`，包括元信息、媒体、字幕与转写。工作台的“已缓存内容”视图可检查或删除单个缓存；删除缓存不会删除已经同步到 Obsidian 的笔记。

### 校园官网同步

校园来源采用显式、低频同步，不会在启动时自动全量抓取：

- `GET /api/campus-sources`：列出公文通、学院官网及其板块。
- `POST /api/campus-sources/{source_slug}/sync`：同步指定来源，可传 `section` 与 `limit`（最多 100 条）。
- 桌面版可在“设置 → 校园内容”连接深圳技术大学 WebVPN。应用会先尝试校内直连，失败后使用独立的 WebVPN 浏览器会话同步公文通；账号、密码和验证码始终由用户在学校页面中输入。
- 首次校外连接时，需要在登录窗口中从服务大厅打开一次公文通列表，应用据此记录 WebVPN 改写后的入口。会话过期后重新连接即可。
- `POST /api/campus-sources/gwt/import-snapshot` 只接收桌面端在认证会话中取得的正文快照，不接收 Cookie 或统一认证凭据。

同步内容进入“校园官网 / 来源名称”文件夹。正文会在打开文章、运行分析或提问时按需抓取并缓存。跨文章问答的演进方案见 [校园内容接入与 RAG 方案](docs/campus-content-and-rag-plan.md)。

### 微信小程序校园论坛

> 此功能仍在开发中，当前不随公开发行版开放。只有测试构建显式设置
> `MINIPROGRAM_FORUM_CAPTURE_ENABLED=true` 时才会显示和运行；公开发行版不会展示入口，也不能通过本机 API 启动采集。

桌面端可从“设置 → 校园内容 → 校园论坛视觉采集”启动。首次使用需给采集组件开启 macOS“辅助功能”和“屏幕录制”权限，并在微信中打开目标小程序的“本校”帖子列表。采集器会自动打开帖子、切换最新评论、使用小步长离散滚轮事件保存具有重叠区域的可见评论并返回列表；不会拖动内容区，也不会点赞、收藏、评论或发送内容。

每次任务的原始窗口截图保存在 `data/miniprogram_forum/runs/<run-id>/`，由 macOS Vision 在本机生成带坐标的 OCR 文本，再从相邻重叠帧合并正文和评论。每次任务同时在左侧文件树的“微信小程序”下创建一篇带采集时间的文档，逐篇写入正文、互动数和已识别评论，并用 Markdown 分割线分隔帖子；运行目录中的 `capture.md` 只是这篇文件树文档的底层采集资产。截图不会在这条采集链路中上传到云端；它们作为校验和以后重新解析的原始证据保留。

- “首次回溯”按本次上限向下遍历；“增量采集”遇到连续已保存帖子后自动结束。
- 每个详情滚动帧和 OCR 坐标都保存在 `data/miniprogram_forum/runs/`，结构化失败不会丢掉原始证据。
- 当界面显示的评论数大于本轮实际取得的评论数时，帖子会标记为未完整，不会误报采集完成。
- 可开启“空闲时自动增量采集”。调度器仅在微信小程序窗口存在、权限齐全且电脑达到空闲时长后运行。
- 相对时间同时保存原始文字和估算区间，不伪造精确发布时间。

本功能只读取当前登录用户在正常界面中可见的内容。登录过期、验证码、已删除内容和界面未加载的数据不在自动化可保证范围内。

## 项目结构

```text
backend/                 FastAPI 路由、处理服务与 MCP 服务
  routers/               内容、任务、搜索、上传、同步等 API
  services/              下载、转写、总结、缓存、SQLite、索引等领域逻辑
frontend/                Vue 工作台与 Electron Beta 外壳
data/                    本地数据库、缓存、上传文件、草稿与日志（运行产物）
docs/                    产品规划、界面规范、OpenClaw 接入说明
scripts/preflight.py     环境自检
start.sh / stop.sh       本地服务启动与停止脚本
tests/                   后端基础测试
```

`data/app.db` 是本地内容与任务索引；媒体、草稿与缓存同样位于 `data/`。备份或迁移时请一并处理该目录，并注意其中可能含有视频、Cookie 和 Bot 配置等敏感数据。

## 开发与验证

后端测试：

```bash
python -m pytest
```

前端生产构建检查：

```bash
cd frontend
npm run build
```

公开发布前检查：

```bash
python scripts/check_public_release_tree.py
```

## 常见问题

| 现象 | 优先检查 |
| --- | --- |
| 启动前自检失败 | `ffmpeg`、`yt-dlp`、Node/npm、Python 依赖、Playwright Chromium 和 Obsidian 路径。 |
| 抖音下载失败 | `data/douyin_cookies.txt` 或设置页中的 Cookie 是否有效。 |
| B 站处理很慢 | 是否未取到字幕而回退到下载与 Whisper；查看任务日志和缓存命中情况。 |
| 总结阶段失败 | `DEEPSEEK_API_KEY`、网络与所选模型配置。 |
| 端口已占用 | 先运行 `./stop.sh`，或检查 8000 / 5173 端口的已有进程。 |
| Obsidian 未写入 | `OBSIDIAN_VAULT` 是否存在且当前用户有写入权限。 |

## 相关文档

- [开发协作约定](AGENTS.md)
- [隐私与数据处理](PRIVACY.md)
- [安全策略](SECURITY.md)
- [第三方声明](THIRD_PARTY_NOTICES.md)
- [产品开发计划](docs/product-development-plan.md)
- [界面参考与工作台规范](docs/ui-reference-and-workbench-spec.md)
- [校园内容接入与 RAG 方案](docs/campus-content-and-rag-plan.md)

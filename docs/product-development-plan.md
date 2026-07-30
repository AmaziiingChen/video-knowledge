# Video Knowledge 产品开发文档

版本：v0.1  
日期：2026-07-12  
定位：macOS-first 的本地学习内容摄取与知识沉淀工作台  
当前底座：继续基于现有 `Tools/video-knowledge` 演进

## 1. 背景与目标

当前工具已经跑通了“抖音/B站链接 -> 下载视频 -> 提取音频 -> Whisper 转写 -> DeepSeek 总结 -> 写入 Obsidian”的核心链路，并已具备批量链接、批量上传、macOS 剪贴板监听、进度展示、缓存和 Obsidian 写入能力。

下一阶段目标不是重写一个新项目，也不是直接 fork vsummary，而是在现有 `video-knowledge` 的基础上，引入 vsummary 的知识库工作台思路：系列管理、结构化数据、字幕时间轴、总结/问答、检索、RAG 演进路径，以及类 Obsidian 的三栏工作区。

产品最终形态：

- 本机优先、隐私优先；
- macOS 优先，后续再考虑 Windows；
- 第一阶段先把功能链路做稳定，暂不追求正式桌面 App 打包；
- UI 参考 Obsidian 三栏布局；
- 抖音和 B站是第一阶段核心输入源；
- 长期扩展为“学习内容摄取与知识沉淀工具”，不局限于视频。

## 2. 核心原则

1. 现有 `video-knowledge` 作为底座继续演进。
2. 第一阶段以个人稳定使用为验收，不面向公开发布。
3. Obsidian 是输出和同步目标，不是主数据库。
4. 工具内部保留结构化数据、Markdown 草稿、任务状态和索引。
5. B站优先尝试字幕，拿不到字幕再走 ASR。
6. 抖音以短视频单条捕获为第一优先级。
7. B站合集/系列是第一阶段重要能力，不后置。
8. 本地播放器是精确跳转主方案，平台内嵌只是补充。
9. 第一阶段做轻量检索式问答，向量 RAG 第二阶段。
10. 隐私数据全部本机保存，不做云同步。

## 3. 第一阶段范围

### 3.1 必做

- macOS 本机准桌面工具形态，继续使用现有前后端启动方式。
- 剪贴板链接进入待处理队列，不再默认立即处理。
- 待处理队列自动轻量解析标题、封面、时长、平台和合集信息。
- SQLite 作为主索引数据库。
- 完整本机后台队列系统：持久化、优先级、暂停、继续、取消、重试、阶段恢复。
- 轻量 Provider 接口，内置 `douyin` 和 `bilibili`。
- B站字幕优先，ASR 兜底。
- 手动导入字幕文件。
- 本地 ASR 优化：faster-whisper 参数模式、时间戳分段、缓存。
- B站合集导入为系列，先导入列表，再选择处理范围。
- 系列作为一等对象：列表、状态、进度、总览、轻量系列问答。
- 基础状态管理：收件箱、处理中、待阅读、已沉淀、归档、失败。
- 总结同时包含快速判断和学习笔记。
- AI 内容质量评价，但必须基于材料证据并标注不确定性。
- AI 自动标签和分类，用户可编辑。
- Prompt 模板管理、版本管理和手动 A/B 对比。
- LLM Provider 抽象，DeepSeek 作为默认。
- AI 调用、token、成本、耗时记录。
- Markdown 草稿编辑、预览、重新同步 Obsidian。
- Obsidian 外部修改冲突提示。
- 追问默认写入 Obsidian，可单次关闭。
- SQLite FTS / 本地全文搜索。
- Cookie 设置页和可用性检测。
- 字幕/章节/引用点击跳转。
- 中间产物放在高级信息里查看。
- 视频保留策略：默认保留 30 天，之后压缩成低码率归档；可手动永久保留。

### 3.2 暂不做

- 正式 macOS App 打包。
- Windows 发行版。
- 完整插件市场。
- 完整 OCR / 多模态图文视频理解。
- 云端 ASR 默认接入。
- LanceDB / LlamaIndex 等完整向量 RAG。
- 多设备云同步。
- 面向公开用户的安装器、升级器、权限引导。

## 4. 目标用户流程

### 4.1 抖音短视频日常捕获

1. 用户刷抖音时复制分享链接。
2. 后端剪贴板监听捕获链接。
3. 链接进入收件箱，不立即下载。
4. 系统轻量解析标题、封面、视频 ID、类型。
5. 用户在收件箱中选择处理。
6. 任务进入队列。
7. 系统下载媒体或读取缓存。
8. 提取音频并 ASR。
9. 如果疑似图文视频，标记并抽关键帧。
10. 生成快速判断、学习笔记、质量评价、标签。
11. 默认写入 Obsidian。
12. 用户在右侧问答区继续追问。
13. 追问默认追加到 Markdown，可单次关闭。

### 4.2 B站单视频

1. 用户复制 B站视频链接。
2. 链接进入收件箱并轻量解析。
3. 系统优先尝试官方字幕 / 自动字幕 / 可获取字幕。
4. 有字幕则跳过 ASR。
5. 无字幕则下载低画质视频或音频并 ASR。
6. 保存带时间戳的 transcript segments。
7. 生成总结、章节、引用和 Markdown。
8. 中间栏支持视频播放和字幕点击跳转。

### 4.3 B站合集 / 系列

1. 用户复制合集链接。
2. 系统解析为系列和视频列表。
3. 不自动全量处理。
4. 用户选择处理全部、处理选中或稍后处理。
5. 每个视频作为独立任务进入队列。
6. 系列页展示视频列表、处理状态、进度、已总结数量。
7. 系列可生成总览 Markdown。
8. 系列问答基于各视频摘要和分段文本做轻量检索。
9. 后续第二阶段升级到向量 RAG。

### 4.4 本地视频 / 手动字幕

1. 用户批量上传本地视频或选择本地文件。
2. 系统按文件 hash 去重。
3. 用户可为视频手动导入 `.srt`、`.vtt`、`.ass`、`.txt` 字幕。
4. 有时间戳字幕则生成 segments。
5. 纯文本字幕作为无时间戳文本。
6. 用户可重新生成总结和 Markdown。

## 5. 信息架构与 UI

第一阶段不追求精修 UI，但布局方向要提前稳定，避免后续重做。

### 5.1 三栏布局

左侧：文件和内容管理

- 收件箱；
- 待阅读；
- 已沉淀；
- 归档；
- 失败；
- 平台筛选；
- 系列列表；
- 标签筛选；
- 本地搜索入口。

中间：视频、时间轴和详细信息

- 本地视频播放器；
- 平台预览或来源链接；
- 封面；
- 关键帧；
- 字幕时间轴；
- 章节列表；
- 任务处理进度；
- 视频元信息；
- 高级信息面板。

右侧：总结、问答和 Markdown

- 快速判断；
- 学习笔记；
- 内容质量评价；
- 标签和分类；
- AI 问答；
- Markdown 预览；
- Markdown 编辑；
- Obsidian 同步状态和冲突提示。

### 5.2 中间栏显示规则

中间栏不能空。

优先级：

1. 本地视频播放器；
2. 平台内嵌预览；
3. 封面和来源跳转；
4. 关键帧列表；
5. 字幕/章节时间轴。

精确跳转以本地播放器为主。平台内嵌仅作补充。

## 6. 数据模型

第一阶段引入 SQLite 作为主索引数据库，文件系统保存媒体、结构化 JSON 和 Markdown 草稿。

数据模型预留非视频内容，但第一阶段完整支持视频。

### 6.1 核心实体

#### content_items

代表一个可沉淀的内容项。

字段建议：

- `id`
- `content_type`: `video` / `article` / `text` / `image_note` / `course`
- `source_provider`: `douyin` / `bilibili` / `local_file`
- `source_url`
- `canonical_source_id`
- `title`
- `cover_url`
- `duration_seconds`
- `status`: `inbox` / `processing` / `to_read` / `distilled` / `archived` / `failed`
- `series_id`
- `created_at`
- `updated_at`

#### series

代表课程、合集或用户自建主题。

字段建议：

- `id`
- `title`
- `source_provider`
- `source_url`
- `cover_url`
- `description`
- `status`
- `created_at`
- `updated_at`

#### series_items

维护系列内顺序。

- `series_id`
- `content_item_id`
- `position`
- `source_page`
- `title_override`

#### media_assets

保存媒体文件和资源。

- `id`
- `content_item_id`
- `asset_type`: `video` / `audio` / `cover` / `frame` / `subtitle_file`
- `path`
- `mime_type`
- `size_bytes`
- `retention_policy`
- `expires_at`
- `created_at`

#### text_assets

保存字幕、转写、正文等文本来源。

- `id`
- `content_item_id`
- `asset_type`: `subtitle` / `transcript` / `cleaned_transcript` / `article_body`
- `source`: `official` / `auto` / `manual` / `asr`
- `provider`
- `model`
- `mode`
- `path`
- `created_at`

#### transcript_segments

带时间戳的分段文本。

- `id`
- `content_item_id`
- `text_asset_id`
- `start_seconds`
- `end_seconds`
- `text`
- `confidence`
- `source`
- `position`

#### summaries

保存 AI 生成的结构化总结。

- `id`
- `content_item_id`
- `series_id`
- `summary_type`: `video_summary` / `series_overview` / `quality_eval`
- `prompt_template_id`
- `prompt_version`
- `llm_provider`
- `model`
- `json_path`
- `markdown_path`
- `created_at`

#### qa_threads / qa_messages

保存问答。

- `thread_id`
- `scope`: `video` / `series`
- `content_item_id`
- `series_id`
- `message_id`
- `role`
- `content`
- `write_to_obsidian`
- `created_at`

#### prompt_templates

保存 prompt 模板和版本。

- `id`
- `name`
- `task_type`: `summary` / `qa` / `quality_eval` / `series_overview`
- `version`
- `template`
- `variables_schema`
- `is_active`
- `created_at`
- `updated_at`

#### ai_calls

记录 AI 调用和成本。

- `id`
- `task_id`
- `content_item_id`
- `series_id`
- `call_type`
- `provider`
- `model`
- `prompt_template_id`
- `prompt_version`
- `input_chars`
- `output_chars`
- `prompt_tokens`
- `completion_tokens`
- `estimated_cost`
- `elapsed_seconds`
- `cache_hit`
- `error`
- `created_at`

#### tasks

后台任务。

- `id`
- `task_type`
- `parent_task_id`
- `content_item_id`
- `series_id`
- `status`: `queued` / `running` / `paused` / `completed` / `failed` / `cancelled`
- `priority`
- `current_stage`
- `progress`
- `error_type`
- `error_message`
- `created_at`
- `updated_at`
- `started_at`
- `finished_at`

#### task_events

任务日志和阶段事件。

- `id`
- `task_id`
- `stage`
- `level`
- `message`
- `progress`
- `created_at`

#### obsidian_sync

记录同步状态。

- `id`
- `content_item_id`
- `series_id`
- `markdown_draft_path`
- `obsidian_path`
- `last_synced_hash`
- `external_hash`
- `sync_status`: `synced` / `dirty` / `conflict` / `error`
- `last_synced_at`

#### tags

- `id`
- `name`
- `source`: `ai` / `user`
- `confidence`

#### content_tags

- `content_item_id`
- `tag_id`

## 7. 文件系统结构

建议结构：

```text
data/
  app.db
  workspace/
    content/
      <content_id>/
        metadata.json
        transcript.json
        summary.json
        draft.md
        qa.json
    series/
      <series_id>/
        overview.json
        overview.md
  media/
    videos/
    audio/
    covers/
    frames/
    subtitles/
  cache/
  logs/
  exports/
```

Obsidian 默认结构：

```text
Obsidian/Learning/
  Inbox/
  Videos/
    Douyin/
      2026/
    Bilibili/
      单视频/
      系列/
        系列名/
          00-系列总览.md
          01-视频标题.md
          02-视频标题.md
  Assets/
    video-knowledge/
      covers/
      frames/
```

根目录、命名规则和平台目录应允许配置。

## 8. Provider 设计

第一阶段做轻量 Provider 接口，不做完整插件市场。

接口建议：

```python
class SourceProvider:
    name: str

    def can_handle(self, url: str) -> bool: ...
    def normalize_url(self, url: str) -> str: ...
    def resolve(self, url: str) -> ResolvedContent: ...
    def resolve_series(self, url: str) -> ResolvedSeries | None: ...
    def fetch_subtitle(self, content: ResolvedContent) -> SubtitleResult | None: ...
    def download_media(self, content: ResolvedContent, target_dir: Path) -> MediaResult: ...
    def extract_frames(self, media_path: Path, target_dir: Path) -> list[FrameAsset]: ...
```

### 8.1 Bilibili Provider

第一阶段要求：

- 解析单视频；
- 解析合集/多 P/系列；
- 获取标题、UP主、封面、时长；
- 优先尝试字幕；
- 字幕失败再下载媒体；
- 支持 Cookie 检测；
- 支持手动字幕导入；
- 支持低画质视频 + 高质量音频策略。

### 8.2 Douyin Provider

第一阶段要求：

- 解析短链接和展开链接；
- 识别 video / note ID；
- 获取标题、封面；
- 下载视频或音频；
- 对疑似图文视频做标记；
- 抽取关键帧；
- 不依赖抖音内嵌播放器。

## 9. 处理流水线

### 9.1 阶段

1. `capture`：剪贴板或手动输入捕获。
2. `resolve`：轻量解析。
3. `dedupe`：URL/ID/hash 去重。
4. `enqueue`：进入任务队列。
5. `fetch_subtitle`：字幕优先。
6. `download_media`：必要时下载媒体。
7. `extract_audio`：必要时提取音频。
8. `extract_frames`：图文视频或需要预览时抽帧。
9. `transcribe`：ASR 兜底。
10. `normalize_transcript`：生成统一 transcript segments。
11. `summarize`：生成快速判断和学习笔记。
12. `quality_eval`：内容质量评价。
13. `tagging`：标签和分类建议。
14. `render_markdown`：生成 Markdown 草稿。
15. `sync_obsidian`：同步到 Obsidian。
16. `index_search`：更新 SQLite FTS。

### 9.2 B站字幕优先

B站处理顺序：

1. 尝试官方字幕；
2. 尝试自动字幕；
3. 尝试可解析字幕资源；
4. 支持用户手动导入字幕；
5. 仍失败时走 ASR。

字幕来源要写入 `text_assets.source`。

### 9.3 抖音图文视频

第一阶段不做完整 OCR / 多模态理解，但必须：

- 检测疑似图文视频；
- 标记“音频信息可能不足”；
- 抽取关键帧；
- Markdown 引用关键帧；
- 后续作为 OCR / 多模态输入。

## 10. 后台队列系统

用户选择：第一阶段做完整本机后台队列系统，但边界限定为单机单用户，不做分布式任务平台。

### 10.1 能力要求

- SQLite 持久化任务；
- 优先级；
- 暂停；
- 继续；
- 取消；
- 重试；
- 队列排序；
- 阶段级进度；
- 阶段级失败原因；
- 从失败阶段重试；
- 合集任务展开为子任务；
- 重启后恢复任务状态；
- 产物缓存复用。

### 10.2 默认并发

- 轻量解析：3-5 并发；
- 下载：2 并发；
- ASR：1 并发；
- 总结：1-2 并发；
- 用户可在设置中调整。

ASR 默认单并发，避免 Mac 被打满。

### 10.3 失败类型

必须区分：

- `resolve_failed`
- `cookie_required`
- `download_failed`
- `subtitle_unavailable`
- `asr_failed`
- `llm_failed`
- `obsidian_conflict`
- `disk_space_low`
- `cancelled`
- `rate_limited`
- `platform_blocked`

每类失败要有明确下一步：

- 配置 Cookie；
- 重试下载；
- 改用 ASR；
- 手动上传字幕；
- 跳过；
- 重新同步；
- 清理空间。

## 11. ASR 策略

第一阶段：

- 继续使用 faster-whisper；
- 优化参数；
- Apple Silicon 后端作为实验项；
- 云端 ASR 只预留接口，不默认接入。

### 11.1 转写模式

建议拆分“模型大小”和“转写模式”。

模型大小：

- `tiny`
- `base`
- `small`
- `medium`
- `large-v3`

转写模式：

- `fast`
- `balanced`
- `accurate`

默认建议：

- 模型：`base`
- 模式：`fast`
- `beam_size=1`
- `best_of=1`
- `condition_on_previous_text=False`

缓存键必须包含：

- 来源 ID；
- 字幕/ASR provider；
- 模型；
- 转写模式；
- prompt 版本不影响 transcript，但影响 summary。

### 11.2 实验项

待实测：

- `mlx-whisper`
- `whisper.cpp / Metal`
- 云端 ASR 供应商

不能在缺少速度、准确率、价格、额度数据时直接默认切换。

## 12. LLM 与 Prompt

### 12.1 LLM Provider

第一阶段抽象 LLM Provider，DeepSeek 作为默认。

接口建议：

- `generate_summary`
- `answer_question`
- `evaluate_quality`
- `generate_tags`
- `generate_series_overview`

每次调用记录：

- provider；
- model；
- prompt 模板；
- prompt 版本；
- 输入长度；
- 输出长度；
- token；
- 成本；
- 耗时；
- 错误；
- 是否命中缓存。

### 12.2 Prompt 模板管理

第一阶段支持完整 prompt 模板管理和手动 A/B 对比。

能力：

- 模板存数据库或模板目录；
- 支持启用/停用；
- 支持版本号；
- 支持变量；
- 支持总结、问答、质量评价、系列总览；
- 重新生成时可选模板版本；
- 同一视频可保留多份生成结果；
- UI 支持两个版本输出对比；
- 不做自动流量分配，不做复杂统计实验平台。

### 12.3 总结结构

总结必须同时服务“快速判断”和“学习笔记”。

默认输出结构：

- 一句话结论；
- 是否值得看；
- 适用人群；
- 不适合谁；
- 信息密度；
- 新颖性；
- 实操性；
- 可信度风险；
- 核心观点；
- 内容脉络；
- 可执行事项；
- 关键术语；
- 待确认；
- 原文证据和时间戳引用。

AI 可以评价内容质量，但必须只基于当前材料，不能补充外部事实。

## 13. 问答与检索

第一阶段做轻量检索式问答，不做完整向量 RAG。

### 13.1 视频级问答

材料来源：

- 当前视频总结；
- transcript segments；
- 章节；
- 用户笔记；
- 历史追问。

回答原则：

- 只基于当前材料；
- 材料不足时明确说明；
- 尽量引用时间戳片段；
- 默认写入 Markdown；
- 单次可关闭写入。

### 13.2 系列级问答

第一阶段基于：

- 各视频摘要；
- 各视频关键章节；
- SQLite FTS 检索到的相关 transcript segments；
- 用户笔记。

第二阶段再升级为向量 RAG。

### 13.3 本地搜索

第一阶段使用 SQLite FTS。

搜索范围：

- 标题；
- 摘要；
- 字幕/转写；
- 问答；
- 标签；
- 系列。

筛选条件：

- 平台；
- 状态；
- 系列；
- 标签；
- 是否同步 Obsidian；
- 是否有本地视频；
- 是否失败。

搜索结果应能跳到对应视频和时间片段。

## 14. Obsidian 同步

Obsidian 是输出和同步目标，不是主数据库。

### 14.1 同步策略

- 默认自动写入 Obsidian；
- 工具内部保存 Markdown 草稿；
- 工具内可预览和编辑 Markdown；
- 用户可重新同步到 Obsidian；
- 追问默认追加；
- 每次追问可关闭写入；
- AI 重新生成不能悄悄覆盖人工编辑内容。

### 14.2 冲突处理

如果检测到 Obsidian 文件外部修改：

- 标记为 `conflict`；
- 不自动覆盖；
- 提供三个动作：
  - 覆盖 Obsidian；
  - 从 Obsidian 导入覆盖草稿；
  - 另存为新笔记。

### 14.3 Markdown 模板

第一阶段：

- 内置默认模板；
- 设置中允许编辑全局模板；
- 系列级模板后置。

默认模板包含：

- YAML frontmatter；
- 来源链接；
- 平台；
- 系列；
- 视频状态；
- 快速判断；
- 学习笔记；
- 章节/时间轴；
- 关键结论；
- 可执行事项；
- 关键术语；
- 追问记录；
- 原始字幕/转写折叠区；
- 关键帧引用。

## 15. 存储与视频保留策略

核心价值是文本知识和可追问上下文，不是长期收藏原视频。

### 15.1 默认策略

- 文本、字幕、总结、问答、关键帧长期保留；
- 本地视频默认保留 30 天；
- 30 天后压缩成低码率归档；
- 用户可标记永久保留；
- 中间音频默认转写后删除；
- B站有字幕时尽量不下载视频，除非用户需要本地播放器。

### 15.2 播放器策略

- 本地视频用于精确跳转；
- 平台内嵌作为补充；
- 抖音不依赖内嵌；
- B站可尝试平台预览，但不作为主控制能力；
- YouTube 未来可用 iframe API。

## 16. 安全与隐私

第一阶段所有隐私数据本机保存，不做云同步。

要求：

- Cookie 不进 Git；
- API Key 不进 Git；
- Cookie/API Key 不写日志；
- `.env` 或后续 macOS Keychain 保存密钥；
- Obsidian 写入必须限制在 vault 内；
- 剪贴板监听必须可见、可暂停；
- 收件箱敏感链接可删除；
- 导出分享包默认不包含 Cookie、Key、缓存视频；
- Windows 版后续单独设计密钥存储。

## 17. 设置页

第一阶段设置页至少包含：

- Obsidian vault 路径；
- Markdown 模板；
- LLM Provider；
- DeepSeek API Key / Base URL / Model；
- ASR 模型和模式；
- 并发设置；
- 视频保留策略；
- 抖音 Cookie 状态和配置；
- B站 Cookie 状态和配置；
- Cookie 可用性检测；
- 自动处理规则；
- Prompt 模板管理。

## 18. 自动处理规则

剪贴板捕获后默认进入收件箱，不自动处理。

可配置规则：

- 自动处理抖音；
- 自动处理 B站单视频；
- 自动处理 B站合集；
- 每日自动处理上限；
- 只在空闲时处理；
- 低电量或磁盘空间不足时暂停；
- 指定系列自动归档。

第一阶段默认不开启激进自动处理。

## 19. 去重策略

第一阶段做基础去重：

- 同 URL；
- 短链接展开后同 canonical URL；
- B站同 BV 号；
- B站同视频不同参数；
- 抖音同 video/note ID；
- 本地文件 hash。

发现重复时：

- 不重复处理；
- 提示已有记录；
- 可选择重新生成总结；
- 可加入不同系列。

语义相似合并第二阶段再做。

## 20. 中间产物与高级信息

普通界面只展示必要结果，高级信息折叠展示：

- 原始字幕；
- 清洗后字幕；
- ASR 转写；
- 关键帧；
- 下载文件；
- 模型参数；
- prompt 版本；
- token 消耗；
- 错误日志；
- 缓存命中；
- 同步状态。

中间产物可导出。

## 21. 阶段计划

### P0：基础重构

- 引入 SQLite；
- 建立数据模型；
- 建立迁移机制；
- 建立 Provider 接口；
- 抽象 LLM Provider；
- Prompt 模板管理；
- 后台队列持久化。

### P1：收件箱与来源解析

- 剪贴板进入收件箱；
- 自动轻量解析；
- 基础去重；
- B站单视频解析；
- B站合集解析；
- 抖音解析；
- Cookie 状态检测。

### P2：处理流水线

- B站字幕优先；
- 手动字幕导入；
- faster-whisper 模式优化；
- 时间戳 transcript segments；
- 图文视频标记和关键帧；
- 阶段级缓存；
- 阶段级重试。

### P3：总结、问答与 Markdown

- 结构化总结；
- 内容质量评价；
- 标签分类；
- 视频级问答；
- 系列级轻量问答；
- Markdown 草稿；
- Obsidian 自动同步；
- 冲突检测。

### P4：三栏工作区

- 左侧内容管理；
- 中间播放器和时间轴；
- 右侧总结/问答/Markdown；
- 字幕/章节/引用跳转；
- 高级信息面板；
- 状态筛选和本地搜索。

### P5：稳定化

- 一周个人使用验证；
- 性能瓶颈记录；
- 错误分类补齐；
- 存储清理策略；
- 真实样本测试；
- README 更新。

## 22. 验收标准

第一阶段验收以个人稳定使用为准。

### 22.1 功能验收

- 抖音短视频可从剪贴板进入收件箱；
- 收件箱可轻量解析并去重；
- 用户可选择处理；
- B站有字幕时跳过 ASR；
- B站无字幕时走 ASR；
- B站合集可导入列表并选择处理范围；
- 本地视频可上传；
- 字幕文件可手动导入；
- 总结包含快速判断和学习笔记；
- AI 可评价内容质量并给出依据；
- 追问默认写入 Markdown；
- Obsidian 自动同步；
- 外部修改 Obsidian 时提示冲突；
- SQLite FTS 可搜索标题、摘要、字幕；
- 字幕/章节可点击跳转。

### 22.2 稳定性验收

- 后端重启后任务历史仍可见；
- 未完成任务可重试；
- 失败原因可读；
- 同一视频不会重复处理；
- ASR 不会并发把机器打满；
- Cookie/API Key 不出现在日志；
- 视频默认保留和清理策略生效。

### 22.3 使用体验验收

- 连续使用一周不丢数据；
- 抖音短视频捕获流程顺畅；
- B站单视频和合集流程可用；
- 用户能看懂失败原因并继续；
- 处理后内容能在工具内预览和编辑；
- Obsidian 笔记结构可接受。

## 23. 风险与注意事项

### 23.1 范围风险

长期目标包含视频、文章、纯文本和多平台，但第一阶段必须聚焦：

- 抖音视频；
- B站视频；
- B站合集；
- 本地视频。

不要在第一阶段扩展公众号、小红书、YouTube、文章处理。

### 23.2 性能风险

主要瓶颈：

- ASR；
- 下载；
- LLM 调用；
- 合集批处理；
- SQLite FTS 大文本索引。

应先通过字幕优先和缓存减少 ASR，再评测 Apple Silicon 后端和云端 ASR。

### 23.3 平台风险

- 抖音下载和解析容易受登录、风控、页面变化影响；
- B站字幕和 Cookie 也可能变化；
- Provider 层必须隔离平台细节；
- 失败提示必须可理解。

### 23.4 数据风险

- Obsidian 和工具内 Markdown 双编辑会冲突；
- 必须保存 hash 并提示用户；
- AI 重生成不能默认覆盖人工编辑。

### 23.5 成本风险

- 总结、问答、质量评价、标签都会消耗 token；
- 必须记录 token 和估算成本；
- 必须利用缓存和 prompt 版本控制。

## 24. 第二阶段候选能力

- 向量 RAG；
- LanceDB / LlamaIndex 评估；
- OCR；
- 多模态图文视频理解；
- 云端 ASR 接入；
- Apple Silicon ASR 后端正式切换；
- YouTube Provider；
- 小红书 Provider；
- 公众号/文章 Provider；
- 本地文件夹监听；
- 语义相似合并；
- 系列知识图谱；
- 正式 macOS App 打包；
- Windows 版。

## 25. 已确认决策摘要

1. 继续基于现有 `video-knowledge` 演进。
2. 第一阶段先做本机准桌面工具，后续再打包 App。
3. UI 参考 Obsidian 三栏布局。
4. Obsidian 是输出/同步目标，不是主数据库。
5. 默认自动写入 Obsidian，后续可编辑和重新同步。
6. B站字幕优先，失败再 ASR。
7. 抖音图文视频第一阶段标记并抽关键帧，OCR 后置。
8. 第一阶段本地 ASR 优化，云端 ASR 只预留接口。
9. 第一阶段轻量检索问答，向量 RAG 第二阶段。
10. 系列作为一等对象，尤其服务 B站合集。
11. B站合集先导入列表，再选择处理范围。
12. 本地播放器作为精确跳转主方案。
13. 工具内部 Markdown 草稿为主，Obsidian 外部修改触发冲突提示。
14. 剪贴板链接先进待处理队列。
15. 待处理队列自动轻量解析。
16. 第一阶段加入基础状态管理。
17. 总结同时包含快速判断和学习笔记。
18. AI 可以做内容质量评价。
19. 追问默认写入 Obsidian，可单次关闭。
20. 隐私数据全部本机保存，不做云同步。
21. 第一阶段做轻量来源 Provider 接口，内置抖音/B站。
22. 数据模型预留非视频，第一阶段完整支持视频。
23. 第一阶段引入 SQLite。
24. 第一阶段做完整本机后台队列系统。
25. 默认并发可配置，ASR 保守限流。
26. faster-whisper 先优化，Apple Silicon 后端作为实验项。
27. 主流程自己实现 B站字幕提取，vCaptions 只作为参考或手动导入来源。
28. 第一阶段内置默认 Markdown 模板，并允许编辑全局模板。
29. Obsidian 按来源和系列组织，并允许配置。
30. 第一阶段做 SQLite FTS。
31. 第一阶段抽象 LLM Provider，DeepSeek 默认。
32. 第一阶段记录 AI 调用、token、成本和耗时。
33. 支持 prompt 模板管理和手动 A/B 对比。
34. 允许 AI 自动打标签和分类，用户可编辑。
35. 第一阶段做基础去重。
36. 第一阶段做分类型失败提示和阶段级重试。
37. 第一阶段做 Cookie 设置页和可用性检测。
38. 第一阶段支持手动导入字幕文件。
39. 第一阶段支持字幕、章节、引用点击跳转。
40. 中间产物放在高级信息里。
41. 第一阶段以个人稳定使用为验收。


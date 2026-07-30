# UI Reference And Workbench Spec

## Decision

The product should use a workbench layout, not a dashboard layout.

Primary reference:
- VS Code workbench: Activity Bar, Primary Sidebar, Editor Area with tabs, Secondary Sidebar / Panel, persisted layout state.

Secondary references:
- Obsidian: quiet visual density, subtle separators, document-like tabs, low-noise chrome.
- Logseq: local-first knowledge workflow and lightweight right sidebar.
- AFFiNE / AppFlowy: modern knowledge workspace and page/database navigation patterns.

Implementation references:
- Splitpanes for Vue 3 resizable panes in phase 1.
- Dockview only if we later need IDE-grade docking, tab dragging across groups, floating panels, or full layout serialization.

Sources:
- VS Code User Interface: https://code.visualstudio.com/docs/editing/userinterface
- VS Code Sidebar UX Guidelines: https://code.visualstudio.com/api/ux-guidelines/sidebars
- Logseq source: https://github.com/logseq/logseq
- AFFiNE source: https://github.com/toeverything/AFFiNE
- AppFlowy source: https://github.com/AppFlowy-IO/AppFlowy
- Splitpanes: https://github.com/antoniandre/splitpanes
- Dockview: https://dockview.dev/
- Golden Layout: https://golden-layout.com/

## Layout Model

```text
Activity Bar | Primary Sidebar | Editor Area | Context Sidebar
```

Activity Bar:
- Only icon buttons.
- Switches the Primary Sidebar view container.
- Never changes the active content tab by itself.

Primary Sidebar:
- Contains navigation and light actions for the selected activity.
- Workbench input actions live here: paste link, clipboard, batch links, upload, search.
- Avoid repeated section titles when the control itself is self-explanatory.
- Avoid large cards. Use compact rows, inputs, segmented controls, and small action buttons.

### Primary Sidebar Contract

- The selected activity owns the Primary Sidebar's content; the Activity Bar is only the entry for switching that content.
- A sidebar follows the fixed `Header / Content / Footer` structure. Header hosts search and light actions, Footer hosts the current input/action dock, and only Content may scroll.
- The Content region contains one scroll owner. Tree rows, selection controls and the recycle bin belong to that region; fixed controls must not be placed over the scrollable list.
- Tree-row actions occupy reserved trailing space, so hover actions never change the label's position or row height.
- Collapsing a sidebar hides the pane and keeps the Activity Bar available; do not replace it with a second icon-only file tree.
- Persist both pane widths and primary/context visibility locally. Restoring the app must respect the user's last visibility choice; entering the Library from another view may reopen the context pane because it follows the newly active document.
- Pane boundaries remain resizable and keyboard reachable. The collapsed edge is an explicit control, not a hidden hover-only affordance.

Editor Area:
- Contains content tabs only.
- A video/content item opens as a tab.
- Tool pages should not become long-lived editor tabs.
- Empty editor state should be quiet: no marketing copy, no instructions beyond a minimal empty state.

Context Sidebar:
- Follows the active content tab.
- Shows summary, QA, citations, sync state, and current run state.
- No global mixed output. If no active tab, show quiet empty states.

## Interaction Rules

Content opening:
- Single click from the Primary Sidebar opens or activates a content tab.
- If the content tab already exists, activate it.
- Tabs persist across refresh using workspace state.
- Later: support drag to open/reorder tabs.

Pane resizing:
- Use Splitpanes in phase 1.
- Persist left/right pane sizes.
- Desktop minimums:
  - Primary Sidebar: 220px
  - Editor Area: 420px
  - Context Sidebar: 300px
- Mobile: hide Primary Sidebar by default; show Activity Bar horizontally or as a compact rail.

Progress:
- Single content progress belongs to the active editor or context sidebar.
- Batch progress belongs to queue rows.
- Each queue row should show:
  - Title/source
  - Status badge
  - One total progress bar
  - Current stage label
  - Actions: view, pause/resume, cancel, retry
- Stage details can be expanded; do not render six large progress blocks by default in queue rows.

Content editor:
- Top: media preview / cover / source state.
- Middle: transcript/subtitle/chapters/citations.
- Right: AI summary and QA.
- Markdown editing is out of scope for phase 1.

## Visual Rules

### Management pages

“网页管理”与“公众号管理”是来源管理页的视觉基准；RSS 订阅及后续同类页面必须复用这套层级和交互，不另起一套卡片或圆角语言。

- 页面结构固定为：44px 标题栏与操作区、可选的紧凑状态条、一个可滚动的来源表格面板。新增来源通过标题栏的主按钮打开对话框，不在主页面堆叠独立表单卡片。
- 所有管理页表面使用圆角矩形：按钮与行内操作使用 `--vk-radius-control`（8px），常规输入使用 `--vk-radius-input`（10px），列表/弹出面板使用 `--vk-radius-surface`（12px），仅需要突出分区时使用 `--vk-radius-feature`（14px）。胶囊仅用于搜索与筛选；不得自行填写新的圆角数值或使用直角边框。
- 列表采用管理表格：40px 浅色表头、64px 最小行高、细分隔线、悬停时的低强度强调色。来源信息在左侧，分组列必须能完整展示至少三个分组；活动列的表头与内容居中；检查与删除操作收束在右侧。
- 来源管理表格不得产生横向溢出或横向滚动。列根据容器宽度按优先级渐隐和回归：先收起处理方式、自动分析或频率等可从来源详情推断的字段，始终保留来源、分组、活动和操作。列的出现与收起使用短暂的 `opacity` / `transform` 过渡，并遵从 `prefers-reduced-motion`。
- 自动化配置直接展示为行内字段：启停开关、检查频率和适用的处理方式。检查采用增量同步，在远端历史记录与本地内容重叠时自动停止；不暴露“读取数量”配置。删除或取消订阅为透明危险文本操作，悬停时才以红色反馈。
- RSS 的文件树路径固定为 `RSS订阅 / 订阅源名称 / 文章`。每个订阅源独占一个直接子文件夹；标题相同的订阅源以 `名称 (2)` 区分，绝不能合并文章。
- 所有尺寸、颜色、间距、字体和动效必须使用现有 `--vk-*` token。所有弹窗、确认框、popover、菜单和管理面板必须为圆角矩形，禁止 `border-radius: 0`、`unset` 或任何直角外轮廓；表头与内容行必须复用完全相同的列栅格。

Chrome:
- Lines: `#dde2dc` or lighter.
- Borders should communicate pane boundaries, not decorate every block.
- Avoid nested cards.
- Avoid repeated page titles inside panes; active tool is already indicated by the Activity Bar.

Typography:
- Use system UI fonts.
- Pane labels: 11-12px, medium weight, muted.
- Content titles: only inside tabs or content metadata, not repeated as page headings.

Spacing:
- Pane padding: 12-16px.
- Row height: 30-36px for navigation and queues.
- Cards only for actual framed content: media preview, transcript block, modal dialogs.

Color:
- Keep the palette neutral and work-focused.
- Use one accent for active state.
- Status colors only for status: success, warning, error, running.

## Phase Plan

Phase 1:
- Replace hand-written pane resize with Splitpanes.
- Keep current Activity Bar, Primary Sidebar, Editor Area, Context Sidebar structure.
- Move remaining tool forms out of Editor Area.
- Convert batch queue progress into compact rows.
- Preserve current pipeline behavior.

Phase 2:
- Extract components from `App.vue`:
  - `WorkspaceShell`
  - `ActivityBar`
  - `PrimarySidebar`
  - `EditorTabs`
  - `ContentEditor`
  - `ContextSidebar`
  - `TaskQueue`
  - `ProgressRow`
- Add content detail API for transcript, summary, media assets, and task history.
- Make right sidebar QA history truly per content item.

Phase 3:
- Evaluate Dockview if multi-editor groups, drag/drop tab docking, or floating panels become necessary.
- Add keyboard shortcuts and command palette.
- Add configurable workspace presets.

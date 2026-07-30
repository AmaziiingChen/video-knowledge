# KnowledgeHub Interface System

Updated: 2026-07-17

## Direction

KnowledgeHub is a macOS-first, high-density knowledge workbench for a researcher who is continuously collecting, reading, transcribing, comparing, and distilling source material. It should feel like a quiet reference desk with visible annotation traces: calm enough for long sessions, dense enough to keep context, and explicit about processing state.

- Domain: shelves, source clippings, transcript rails, annotations, citations, queues, processing pipelines, and working notes.
- Color world: paper cream, warm ink, faded dividers, olive annotation marks, amber waiting states, and restrained cinnabar errors.
- Signature: the olive **knowledge trace**. A narrow, stable line marks explicitly designated activity navigation, tabs, transcript position, and process progress; resource rows use a selected surface instead.
- Reject generic dashboard cards: content and workbench structure lead; cards are reserved for discrete tasks or floating management surfaces.
- Reject rainbow status decoration: one olive accent carries selection, progress, success, and primary action; amber and cinnabar appear only for semantic warning/error states.
- Reject uniformly soft containers: the workbench remains square and structural, while inputs, task cards, menus, and overlays use restrained radii.

## Depth and Surfaces

Use a borders-first strategy for the permanent workbench and subtle shadows only for floating layers.

1. Quiet application surface: `--vk-bg-quiet`
2. Central reading/editing surface: `--vk-bg-center`
3. Panel and inset-control surface: `--vk-bg-panel`
4. Hover and soft-selected surface: `--vk-bg-hover`
5. Popover/dialog surface: panel color plus a low-opacity text-colored shadow

Permanent sidebars, editors, docks, and split panes use `1px solid var(--vk-border)` and no exterior shadow. Dialogs, menus, and managers may use the documented 10–38px soft shadow range. Do not mix elevated cards into permanent navigation.

## Shape Language

- Structural workbench: `0`
- Compact inline marks: `4px`
- Icon and menu controls: `8px`
- Inputs/search result media: `10px`
- Cards and dialogs: `12px`
- Feature management surfaces: `14px`
- Search, filters, chips, circular controls: `999px`

Use tokens `--vk-radius-*`; do not introduce a new radius without a product-specific reason. Nested rounded elements follow concentric radius: outer radius = inner radius + padding.

### Timed-media workbench

The in-place material preview is a permanent workbench plane, not a card. Its outer viewport is square (`border-radius: 0`) for every material type, including Markdown/document readers, images, audio, and video. Audio and video with a transcript/timeline add one continuous workbench region: the media preview, its inner player or waveform, draggable splitter, and transcript timeline join without gutters or rounded end-caps.

- Apply square outer edges to `.workbench-editor-host`, `.tab-content-workspace`, and `.content-media-frame`; leave cards, controls, menus, dialogs, popovers, and outer application chrome rounded.
- Keep the positioning, overflow, and background contract of `.content-media-frame` separate from the radius contract. Timed-media players are absolutely positioned and must be contained by their own frame, never by a higher-level page container.
- Generic `.content-media-frame` styling must preserve square preview edges; a later generic radius rule must never override this contract.

## Spacing and Density

- Base unit: `4px`.
- Tool controls: 28px compact, 34px default, 40px comfortable.
- Core interface padding: 8–12px.
- Panel/card padding: 14–18px.
- Page gutters: 22–24px; wide workspaces may reach 32–38px.
- Prefer the extracted scale: `2 / 4 / 6 / 8 / 10 / 12 / 14 / 16 / 18 / 22 / 24 / 32 / 38px`.
- Shared spacing roles are `--vk-space-micro / xs / sm / control / cluster / panel / section / page / wide`; use literal optical corrections only when the component geometry requires them.

The workbench is intentionally dense. Reading content may become more spacious, but tool chrome must not drift toward brochure spacing.

## Typography and Hierarchy

- Interface/body: `--vk-font-sans`
- Brand: `--vk-font-brand`
- Paths, logs, timecodes: `--vk-font-mono`
- Public scale: micro 10px, meta 11px, label 12px, body 13px, reading 14px, heading 15px, display 21px.
- Type ratio: approximately 1.2 for the dense tool UI.
- Use weight and text level before adding new font sizes: primary 600/text, supporting 500/muted, metadata 400/muted.
- Dynamic counts, durations, byte sizes, timecodes, and table numbers use tabular numerals.
- Headings should balance; reading copy should wrap prettily.

Each view has one focal point:

- Workbench: the open source or current task, not the navigation.
- Settings: the selected settings section and its status/action rows.
- Cache/WeChat management: the table or subscription workflow; filters and summary counts remain secondary.
- Assistant: the current answer/composer; model and shortcut controls recede.

## Color Contract

Use semantic variables from `frontend/src/styles/app.css`. Never use the light accent as small text.

- `--vk-text`: primary ink
- `--vk-muted`: supporting copy; all maintained themes must keep at least 4.5:1 against their primary surface
- `--vk-accent`: annotation/progress decoration
- `--vk-accent-strong`: success and emphasized annotation text
- `--vk-action-bg` / `--vk-action-fg`: readable primary actions and strong selection
- `--vk-warning`: recoverable waiting or unknown state
- `--vk-danger` / `--vk-error-text`: destructive action and error content

All maintained themes must preserve the same semantic roles. A new theme is incomplete until muted text, action content, focus, border, success, warning, and error contrast have been checked.

## Reusable Component Patterns

### Primary action

- Height: 34px by default, 28px compact, 40px comfortable.
- Background/foreground: `--vk-action-bg` / `--vk-action-fg`.
- Radius: structural for shared Element Plus buttons unless the surrounding task surface explicitly uses rounded controls.
- Press: scale to 0.985 for 120ms.
- Disabled: opacity 0.48, `not-allowed`, no hover lift.

### Secondary action

- Panel background, subtle border, primary text.
- Hover uses `--vk-bg-hover`; focus uses the shared double focus ring.
- Keep labels specific to the action.

### Icon control

- Visible size may be 28–30px, but the hit target should reach 40px where layout permits and never overlap neighboring targets.
- Requires an accessible name and tooltip when the icon is not self-explanatory.
- Active state uses either the knowledge trace or a stable selected surface, never hover alone.

### Input/select

- Height: 34px default, 40px in settings forms.
- Radius: `--vk-radius-input` in task surfaces; structural in the permanent workbench.
- Background: panel/inset surface, explicit text and placeholder colors.
- Focus: `--vk-focus-ring`.
- Every field needs a visible label or an accessible name, meaningful `name`, and appropriate `autocomplete`/input type.

### Management surfaces

- WeChat management, campus collection, and cache management share the same title → toolbar → table hierarchy. Do not insert dashboard cards ahead of the table unless they are independently actionable.
- Default management buttons are 34px with `--vk-radius-control`; selects use the same 34px height with `--vk-radius-input`. Use a 26px inline choice only inside a table operation cell.
- Use a select for one-of-many choices such as sorting or source filtering. Segmented controls are reserved for small, immediately visible mutually exclusive content categories; they are not a substitute for a select.
- Per-row action order is stable: inline choices, enabled state, direct action, then the 30px more-actions control. Header more-actions remain 34px.

### Selected navigation/resource

- Selection uses surface, text color, and weight by default. Do not add a left, right, top, or bottom emphasis line unless the component requirement explicitly calls for one.
- Primary activity navigation, tabs, transcript position, and process progress are the documented knowledge-trace exceptions; do not propagate their line treatment to file trees, lists, menus, or prompt rows.
- File and resource rows use `--vk-selected-bg` / `--vk-selected-fg` without an inset emphasis line.
- Hover must remain visually distinct from selected state.
- Library and prompt trees share `SidebarTreeRow`: 24px rows, 16px depth steps, disclosure arrow only for folders, and a source-specific icon only for files. Do not add a decorative folder icon beside the disclosure arrow.
- Library and prompt tree scroll rails terminate at the same right edge as the primary pane and meet the splitter track directly; keep content inset inside the scroll container instead of moving the scrollbar inward.
- Tree metadata counts occupy a fixed right-edge column with an 8px row inset. They stay aligned across root groups; rows with hover actions replace the count in that same column instead of shifting it sideways.
- Tree-row actions appear immediately on hover or keyboard focus and disappear otherwise. Do not add opacity, translation, or staggered entrance motion to rename/delete actions.

### Floating dialog/menu

- Radius: 12px unless a compact menu needs 8px.
- Panel surface plus restrained text-colored shadow.
- Focus is trapped and returned by the underlying primitive.
- Content area contains its own scroll; use `overscroll-behavior: contain`.

### History backfill dialog

- `HistorySyncDialog` is the shared entry for WeChat subscriptions and campus sources; do not recreate a product-specific history modal.
- Put the source name beneath a compact context label, then present the range as three equal scope cards: article count, publication date range, and all accessible history.
- The date-range primary action remains disabled until both endpoints are valid. State the per-source ceiling in the all-history copy: 1000 for WeChat and 300 for campus sources (the WebVPN-safe collection limit).
- Keep its contract plain: only unimported content is added, and it follows that source's current processing or analysis configuration.

### Prompt workbench

- Group prompt tasks by user intent: content processing, assistant actions, and sources/reports. Internal task identifiers never appear as labels.
- The prompt sidebar is a file tree, not a nested navigation rail. Its top level is exactly `内容处理`, `侧栏操作`, and `来源报告`; do not wrap them in an outer “提示词” folder.
- Use the shared library-tree row component, inline rename, drag/drop affordances, and recycle-bin behavior. Prompt files use `append.page.svg`; prompt folders use only the shared disclosure arrow.
- A task owns its folders and files: users may create nested folders, rename items, or move them only within that task. Every task must retain at least one prompt, so the last prompt's delete action stays disabled.
- Show `已启用` at the right edge of enabled rows. On hover, hide this marker and reveal rename/delete actions in the same position; do not show both at once. Report prompts are treated as enabled and remain protected while only one daily/weekly prompt exists.
- Prompt rows use selected surfaces without an emphasis line, following the selected-navigation/resource rule above.
- The editor reuses `WorkspaceTabs` without prompt-specific tab markup or styling, followed by a compact function bar and the prompt text editor. Tabs preserve independent drafts, expose unsaved state with a fixed 5×5px semantic marker, and confirm before closing dirty content; label overflow styles must never target the marker.
- Prompt tabs become dirty only when the user-visible draft differs from the tab's loaded baseline. Task switching, asynchronous template hydration, activation refreshes, and other programmatic editor writes must not create a dirty marker or close confirmation.
- The function bar always states entry, input, and output; only show variables that can actually be inserted. Report prompts document `{articles}` and its fallback behavior in the same editor layout as ordinary prompts.
- Keep activation secondary to saving. The primary save button uses the compact 8px radius and is enabled only when valid content has changed; support `Command/Ctrl + S`. Resetting a prompt is a visible secondary button beside save, with the same compact control geometry and radius—not a concealed more-actions menu.
- Prompt deletion is soft by default, requires confirmation, and offers restore/permanent delete from the tree's recycle bin.

### Process log dock

- Log entries are chronological and grow upward from the bottom. A newly opened task starts at its latest entry.
- Follow the live tail only while the reader remains at the bottom. Manual scrolling away pauses tail-follow without moving the viewport; expose a compact “回到最新” action until the reader returns.
- Keep the selected task stable while new tasks or entries arrive. Only select the newest task when no valid selection exists.
- The task list shows status, current stage, and tabular progress. A successful terminal task resolves to 100% even when an older backend record omitted its final percentage.
- Output uses a shared four-column grid: time, stage, message, metrics. Repeat the task title only in the dock header, not on every line.
- Keep timestamps and metrics single-line; let messages wrap. Reserve a stable right-aligned metrics column before giving extra width to messages. Inline metrics prioritize cumulative tokens, output characters, and duration; the provider name remains available as contextual detail. Long values truncate without creating horizontal overflow.
- When the log output itself is narrow (for example, with the assistant pane open), hide the stage column before reducing either the message or metrics column below a readable width.
- Token usage is recorded for every AI generation path. The global status bar shows today's aggregate; per-file and per-task usage remains available as contextual detail.

## State and Motion Contract

Every interactive component provides default, hover, active, focus-visible, disabled, and loading where applicable. Data views provide loading, empty, and actionable error states.

- Fast feedback: 120ms; standard control transition: 180ms; overlays may use 200–280ms.
- Only animate `transform` and `opacity` for movement; name transitioned properties explicitly.
- Respect `prefers-reduced-motion`; remove movement and looping shimmer/pulse while retaining necessary state changes.
- Repeated expert actions should feel immediate and avoid decorative animation.

## Accessibility and Content Invariants

- Use native buttons and links before custom click targets.
- Icon-only buttons require `aria-label`; decorative icons use `aria-hidden="true"`.
- Keyboard focus must be visible through `:focus-visible`.
- Form labels share a hit target with their controls where possible.
- Images have alt text, intrinsic dimensions when known, and lazy loading below the fold.
- Long titles and user-generated text must truncate, clamp, or wrap without forcing horizontal overflow.
- Destructive actions require confirmation or an undo path.
- Keep browser zoom enabled.

## Sources of Truth

- Detailed extracted baseline: `DESIGN.md`
- Runtime theme and state implementation: `frontend/src/styles/app.css`
- Portable design tokens: `design-system/tokens.css` and `design-system/tokens.json`
- This file: durable interface decisions for future design and implementation sessions

When implementation and documentation disagree, verify the running interface, update the runtime contract first, then update both `DESIGN.md` and this file.

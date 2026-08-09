# Architecture hardening execution backlog

This is the executable post-`v0.1.0` hardening backlog.  It is deliberately
ordered by risk and dependency: a checkable security or lifecycle defect is
fixed before moving large amounts of code between files.  Completion means a
behavior test and the applicable full gate pass; it never means merely moving
lines.

## P0 — release safety and confirmed broken behavior

- [x] Scan all tracked text, including tests, for credential-shaped values;
  retain only exact, documented fake fixtures.
- [x] Scan every public branch/tag and detached CI `HEAD` for forbidden paths
  and credential-shaped history; fetch complete history in public-release CI.
- [x] Start and stop the default-enabled favorite-source scheduler with the
  application lifecycle.
- [x] Remove unconditional post-first-paint loading of every lazy workspace.
  A workspace now loads when its UI is actually requested.
- [x] Enforce capability tokens for every private API read and write, retain
  anonymous fixed-liveness health checks, inject media headers only from the
  trusted desktop renderer, and reject non-loopback desktop binds.
- [x] Validate every untrusted HTTP URL and redirect hop after DNS resolution;
  reject mixed/private/non-global answers before the request is issued.
- [x] Pin every untrusted remote-fetch hop to the public addresses that were
  just validated, while retaining the URL host for HTTP Host, TLS SNI and
  certificate validation; this closes the validation-to-connect DNS-rebinding
  window without weakening redirect checks.

## P1 — maintainability, test truthfulness, and resource control

- [x] Extract the prompt-workspace controller from `App.vue`; retain all four
  tab types, draft/trash behavior and add mock-API race regression tests.
- [x] Extract the WeChat subscription controller from `App.vue`; retain
  single/bulk task behavior with mock-API regression tests and ratchet the
  remaining composition-root budget down. Account authorization, QR polling,
  transfer and account-search state live in
  `features/wechat/useWechatAccountController.js`; body-cleaning filter CRUD
  now lives in `features/wechat/useWechatFilterController.js`. Report-group
  creation, deletion and schedule changes now live in
  `features/wechat/useWechatReportGroupController.js`, retaining prompt
  selection and refresh ordering.
- [ ] Split `knowledge_v2.py` by structural chunking, source scope, retrieval,
  embedding and grounded-answer responsibilities. Pure source Markdown cleanup,
  token estimation and parent/child structural chunking now live in
  `services/knowledge_chunking.py`; `knowledge_v2.py` re-exports the former
  public chunking symbols so existing router, script and test imports remain
  compatible.
- [ ] Split `campus_digest_generation.py` by source identity, event clustering,
  fact extraction and editorial-generation responsibilities. Pure source URL
  canonicalization, identity normalization, hashing and text-shingle similarity
  now live in `services/campus_digest_identity.py`. Embedding API selection,
  local-model loading and deterministic fallback vectors now live in
  `services/campus_digest_embeddings.py`; the shared progress-event contract
  now lives in `services/campus_digest_progress.py`. The remaining generation
  and persistence flow will be separated in behavior-preserving slices.
- [ ] Split `useAppController.js` by library, task-runtime, import and
  assistant-session ownership while preserving its external facade.
  The first library boundary, debounced global search and result hydration, now
  lives in `features/library/useLibrarySearchController.js`; tree presentation,
  task runtime, imports and assistant sessions remain in the facade pending
  their own behavior-preserving slices.
  The independent trash transaction boundary now lives in
  `features/library/useLibraryTrashController.js`; history snapshots, undo/redo
  and shortcut handling now live in `features/library/useLibraryHistoryController.js`.
  Article preparation, platform credential status, completion-notification
  synchronization, content-detail/text-readiness hydration, and folder
  loading/creation/renaming/pinning have their own controllers as well. AI
  call history, daily usage aggregation and its polling lifecycle now live in
  `features/usage/useAiUsageController.js`; content-analysis prompt loading and
  delegation now live in `features/assistant/useContentAnalysisController.js`.
  Content recovery actions (source text, reprocessing, retranscription,
  subtitles and redownloads) now live in
  `features/library/useContentRecoveryController.js` while reusing the durable
  task queue. Source-group loading, guarded removal and editor lifecycle now
  live in `features/library/useLibrarySourceGroupController.js`. Folder-tree
  mutation transactions (rename, move and recycle-bin deletion) now live in
  `features/library/useLibraryMutationController.js`, preserving optimistic
  updates, rollback, tab cleanup and durable history records. Folder-tree
  ownership, task runtime, link import and assistant sessions remain in the
  facade because they still share durable queue state. The active-reader
  EventSource lifecycle now lives in
  `features/tasks/useActiveTaskEventStreamController.js`, retaining task-ID
  validation, terminal cleanup and polling fallback behavior.
  Task status, status-bar, progress, log-level and display-label presentation
  now live in `features/tasks/taskDisplayPresentation.js` with pure boundary
  tests; queue transport and durable task mutation remain in their existing
  controllers.
- [ ] Split `SecondarySidebar.vue` into conversation, composer and task-status
  surfaces. Its model normalization, shortcut filtering, empty state, external
  citation, OCR hint and text-preview rules now live in
  `features/assistant/assistantPresentation.js` with pure boundary tests;
  menus, composer focus/resize and conversation scrolling remain local UI
  behavior.
- [ ] Split `EditorHost.vue` into report, article, media/transcript and remote
  readers; each reader receives a mounted behavior test. Remote original-page
  lifecycle now lives in `workbench/useRemoteArticlePreviewController.js`: it
  owns desktop-only eligibility, WebView listener/timer cleanup, local-snapshot
  fallback, in-page find, bounded outline/progress messages and selection
  forwarding. Shared content-type, local-import preview and remote-source
  classification now lives in `workbench/editorContentKind.js` with pure
  boundary tests. Menu-action dispatch and detail-row presentation now live in
  `workbench/editorContentActions.js` and `workbench/editorContentDetails.js`.
  Report title, date-window and generated-time presentation now live in
  `workbench/editorReportPresentation.js` with pure formatting tests. Article
  outline filtering and visual hierarchy now live in
  `workbench/articleOutlineModel.js` with pure boundary tests. Report, article
  and media readers still need their own mounted behavior boundaries.
- [x] Extract report-generation SSE decoding from `App.vue`; preserve local
  capability headers, fragmented event handling and explicit server errors in
  `features/reports/reportEventStream.js` with protocol-level tests.
- [x] Extract WeChat RSS copying and credential-free subscription export from
  `App.vue` into `features/wechat/useWechatFeedExportController.js`.
- [ ] Separate library and prompt sidebars from `PrimarySidebar.vue` and test
  tree, drag, search and trash behavior at their owners.
  Local tree-preference persistence plus pure tree-node construction, unread
  ancestry and folder paths now live in
  `features/library/libraryTreePreferences.js` and
  `features/library/libraryTreeModel.js`; marquee selection and virtual-row
  lifecycle now live in `workbench/useTreeBoxSelectionController.js` and
  `workbench/useVirtualLibraryTreeController.js`. Drag/drop policy now lives
  in `features/library/libraryTreeDragPolicy.js`, while dispatch, file-import
  routing and move transactions now live in
  `workbench/useLibraryTreeDragController.js` with behavior-level tests.
- [x] Replace the idle one-second Markdown scan with deterministic adaptive
  backoff: changes stay on a two-second cadence, while an unchanged library
  backs off through 4/8/16/32 to 60 seconds.  The scheduler has no network
  path and its cadence is covered by a deterministic wait-budget test.
- [ ] Split `routers/content.py` into transport schemas, listing, analytics,
  import and mutation domains.  Move new SQL out of routers and keep router
  registration/API paths stable.
  AI/OCR call history and daily usage now live in `routers/content_usage.py`;
  response mapping, deletion cleanup, folders, trash, source groups and
  Markdown imports now have dedicated service/router owners. Article
  preparation/OCR queue endpoints now live in `routers/content_preparation.py`;
  text-readiness and explicit source refresh now live in
  `routers/content_source_text.py`; content status, rename/move and soft-delete
  mutations now live in `routers/content_mutations.py`; local-file import and
  reprocessing now live beside Markdown imports in `routers/local_imports.py`.
  The user-triggered article reading endpoint now lives in
  `routers/content_preview.py`; background capture remains a separate
  follow-up cut.
- [ ] Split `campus_sources.py` by source catalog, list discovery, procurement
  adapters and article extraction. OCR-document Markdown rendering, math-token
  marking and table-header promotion now live in
  `services/campus_document_rendering.py`; `campus_sources.py` retains its
  public renderer import and private caller alias for compatibility. Article
  HTML URL normalization, attachment de-duplication/scope selection and list
  node de-duplication now live in `services/campus_html_content.py`.
- [ ] Split `pipeline_runner.py` into stable transport contracts, media/source
  execution and persistence boundaries. Request/response/log models, durable
  error taxonomy and cancellation marker now live in
  `services/pipeline_contracts.py`; `pipeline_runner.py` keeps its original
  import surface while retaining all runtime orchestration.
  ASR configuration normalization and automatic short/long-model selection now
  live in `services/pipeline_asr_policy.py`.
  Timing, percentage bounding and log-level classification now live in
  `services/pipeline_progress_rules.py`.
- [x] Add direct tests for public-tree, DMG validation and backend packaging
  scripts. Public-tree credential/history checks, unsigned-DMG layout/model
  exclusion checks and backend packaging exclusions/native-helper commands now
  have direct tests.
- [ ] Persist release measurements. Verify jobs now have bounded timeouts and
  repeated pull-request/main checks cancel stale in-progress runs.
- [ ] Establish auditable Python dependency constraints/lock data and add an
  incremental, explicit coverage baseline for high-risk boundaries. The base
  manifest has removed its three verified-unused dependencies; exact
  verification-tool pins now live in `requirements-dev.txt`, while complete
  cross-platform runtime lock data remains outstanding.

## P2 — repository hygiene and release provenance

- [x] Remove verified-unreachable renderer batch-link, batch-upload and queue
  action code after facade/template/call-site audit; retain the live queue,
  clipboard and single-link processing paths.
- [x] Remove the two remaining verified-unused Vite starter assets after the
  full renderer build confirmed they are absent from source and output.  The
  previously listed third starter asset was no longer tracked.
- [ ] Remove committed macOS helper binaries after an arm64 build proves the
  tracked Objective-C sources reproduce them.
- [ ] Add generated SBOM/license review evidence to release artifacts; evaluate
  immutable action pins.  Dependabot now covers GitHub Actions alongside npm
  and pip dependencies.
- [x] Remove the unused external download-site instructions; the release guide
  now documents only the normal GitHub Release DMG and SHA-256 path.
- [ ] Continue ratcheting every production source below 1,000 lines, or add a
  narrowly documented generated/declarative exception. The group-report source
  summary cache now has its own database owner; source membership queries,
  deterministic ordering and managed-text/Markdown material loading now live
  in `group_report_sources.py`; the planner's JSON shape compatibility and
  parsing now live in `group_report_plan_shape.py`. The
  legacy first-sync task adapter now lives in
  `wechat_initial_sync_queue.py`, while the paced all-subscription check
  adapter and its remote/authorization stop policy now live in
  `wechat_bulk_sync_queue.py`. The bounded authenticated public-account client,
  including cookie-header scope, response deadlines and article identity, now
  lives in `wechat_subscription_client.py`. The ephemeral QR state machine,
  including in-memory pending sessions and only post-confirmation credential
  handoff, now lives in `wechat_subscription_qr_auth.py`; account persistence,
  Keychain session handling, validation cache and local request-budget policy
  now live in `wechat_subscription_accounts.py`, while
  `wechat_subscription.py` retains subscription persistence and collection
  orchestration. Report normalization and writing remain the next intentional
  boundaries in the main pipeline.

## Non-negotiable compatibility checks

Every item preserves existing HTTP routes, SQLite files, local-storage keys,
preload APIs, persistent queue states, runtime-model downloads, local-data
boundaries and the unsigned-DMG release contract.  New dependencies and bulk
formatting are out of scope unless a specific item proves they are necessary.

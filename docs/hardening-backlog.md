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
  compatible. Bounded prior-turn pairing, truncation and role-preserving
  message construction now live in `services/knowledge_conversation_context.py`;
  `knowledge_v2.py` retains its existing private entry point for compatibility.
  Model stream collection and final usage/reasoning metadata reconstruction now
  live in `services/knowledge_response_transport.py`, with the original helper
  retained as a compatibility import. Streaming JSON extraction now lives in
  `services/knowledge_streaming_json.py`, so only the structured ``answer``
  field can reach the visible response stream; the existing private entry point
  remains a compatibility import. Evidence context construction, server-side
  excerpt selection and model quotation validation now live in
  `services/knowledge_answer_evidence.py`, while existing internal call sites
  retain their aliases.
  Query rewriting and structured-object response parsing now live in
  `services/knowledge_query_rewrite.py`; the public query entry point and the
  existing structured-parser alias remain available from `knowledge_v2.py`.
  Scope predicates, FTS ranks and lexical fallback ranks now live in
  `services/knowledge_retrieval_store.py`; the answer orchestrator retains
  vector ranking and result selection.
  The process-local vector cache and scope-first dense ranking now live in
  `services/knowledge_vector_index.py`; embedding writes only invalidate that
  dedicated cache after a completed batch. Source hashing, parameterized chunk
  inserts and searchable-text projection now live in
  `services/knowledge_index_storage.py`; `knowledge_v2.py` retains only the
  index rebuild orchestration and public chunker-version entry point. Embedding
  API transport, vector normalization and source-hash-guarded persistence now
  live in `services/knowledge_embedding_runtime.py`, while the embedding batch
  budget and API-facing entry point remain in the index orchestrator. Source
  set listing, paged ready-document projection, strict selection validation and
  query-readiness statistics now live in `services/knowledge_source_catalog.py`.
  Source-scoped, durable Markdown loading now lives in
  `services/knowledge_source_loader.py` and reuses the canonical bound scope
  predicate before reading any local file.
- [ ] Split `campus_digest_generation.py` by source identity, event clustering,
  fact extraction and editorial-generation responsibilities. Pure source URL
  canonicalization, identity normalization, hashing and text-shingle similarity
  now live in `services/campus_digest_identity.py`. Embedding API selection,
  local-model loading and deterministic fallback vectors now live in
  `services/campus_digest_embeddings.py`; the shared progress-event contract
  now lives in `services/campus_digest_progress.py`. Untrusted model JSON
  parsing, fact-card normalization, event-brief normalization and chunk-safe
  source splitting now live in `services/campus_digest_payloads.py`. The
  SQLite fact-card cache now lives in `services/campus_digest_fact_cache.py`,
  validating source hashes and card schema before returning cached projections.
  Fact-card extraction now lives in
  `services/campus_digest_fact_extraction.py`, retaining source-order output,
  retry behavior, chunk-safe model calls and cache invalidation.
  Deterministic source projections, cluster-primary selection,
  publishing-brief fallback and source-appendix rendering now live in
  `services/campus_digest_source_views.py`.
  Candidate material construction, deterministic pair rules and cluster-member
  similarity now live in `services/campus_digest_cluster_rules.py`; model
  relation review and SQLite cluster persistence remain in the generator.
  The remaining generation and persistence flow will be separated in
  behavior-preserving slices.
- [ ] Split `useAppController.js` by library, task-runtime, import and
  assistant-session ownership while preserving its external facade.
  The first library boundary, debounced global search and result hydration, now
  lives in `features/library/useLibrarySearchController.js`; tree presentation,
  task runtime, imports and assistant sessions remain in the facade pending
  their own behavior-preserving slices.
  Folder-tree startup hydration, bounded restored-item resolution, per-folder
  history pagination, retry lifecycle and local content projection now live in
  `features/library/useLibraryContentController.js`. The unreachable legacy
  global recent-window pagination/fallback chain has been retired; the backend
  pagination contract remains unchanged for API compatibility.
  Debounced link recognition, authenticated ingest submission, durable queue
  registration, failure projection and input cleanup now live in
  `features/imports/useLinkIngestController.js`; the former private current-task
  cancellation path was unreachable and has been removed while queue-owned
  cancellation remains unchanged.
  The independent trash transaction boundary now lives in
  `features/library/useLibraryTrashController.js`; history snapshots, undo/redo
  and shortcut handling now live in `features/library/useLibraryHistoryController.js`.
  Prompt-template loading, ordering, selection, editor drafts, create/update,
  activation and soft deletion now live in
  `features/prompts/usePromptTemplateController.js`; its facade preserves the
  existing App and workbench contracts and rejects stale task-type responses.
  Article preparation, platform credential status, completion-notification
  synchronization, content-detail/text-readiness hydration, and folder
  loading/creation/renaming/pinning have their own controllers as well. AI
  call history, daily usage aggregation and its polling lifecycle now live in
  `features/usage/useAiUsageController.js`; content-analysis prompt loading and
  delegation now live in `features/assistant/useContentAnalysisController.js`.
  QA response SSE decoding, display throttling, usage updates and completed
  answer state reconciliation now live in
  `features/assistant/createQaResponseStreamController.js`. Initial QA-history
  loading, bounded retry, cursor pagination and stale-request invalidation now
  belong to `features/assistant/useQaSessionController.js`, together with the
  guarded new-conversation archive and reset transaction. Protected QA request
  creation, selected-text context, completion notification and answer
  regeneration now live in `features/assistant/useQaRequestController.js`;
  manual summary streaming, delayed progress feedback and failure logging now
  live in `features/assistant/useAiSummaryGenerationController.js`.
  Deterministic shortcut insertion,
  explicit expansion and local intent composition now live in the pure
  `features/assistant/qaPromptComposer.js` boundary. Conversation Markdown
  assembly, desktop export and local-API fallback now live in
  `features/assistant/useConversationMarkdownExportController.js`.
  Content recovery actions (source text, reprocessing, retranscription,
  subtitles and redownloads) now live in
  `features/library/useContentRecoveryController.js` while reusing the durable
  task queue. Source-group loading, guarded removal and editor lifecycle now
  live in `features/library/useLibrarySourceGroupController.js`. Folder-tree
  mutation transactions (rename, move and recycle-bin deletion) now live in
  `features/library/useLibraryMutationController.js`, preserving optimistic
  updates, rollback, tab cleanup and durable history records. Task runtime,
  assistant sessions remain in the facade because
  they still share durable queue state. The active-reader
  EventSource lifecycle now lives in
  `features/tasks/useActiveTaskEventStreamController.js`, retaining task-ID
  validation, terminal cleanup and polling fallback behavior.
  Task status, status-bar, progress, log-level and display-label presentation
  now live in `features/tasks/taskDisplayPresentation.js` with pure boundary
  tests. The active task result projection, reset transaction, task-identity QA
  isolation, persistence-error reporting and visible step state now live in
  `features/tasks/useActiveTaskStateController.js`. Single-task polling,
  progressive hydration, terminal feedback, bounded retry backoff and timer
  cleanup now live in `features/tasks/useActiveTaskPollingController.js`;
  process-log collection, report-log persistence, incremental backend-log
  ingestion and the clear-log transaction now live in
  `features/logs/useProcessLogController.js`, while the UI projection remains
  next to its task presentation dependencies. Markdown draft loading, stale
  selection protection, editor state, saving and explicit output-directory
  synchronization now live in
  `features/library/useMarkdownDocumentController.js`. Clipboard fallback,
  trusted external-link dispatch, Finder reveal, best-effort telemetry and the
  optional update prompt now live in
  `features/desktop/useDesktopActionController.js`. Progressive task-detail
  hydration, active-reader milestone refresh and bounded article/media/text
  preview deduplication now live in
  `features/tasks/useProgressiveTaskHydrationController.js`. Unreturned legacy
  task-detail row projections and the unconsumed selected-model projection have
  been removed instead of being carried into another abstraction. Markdown
  reader projection, durable source-text recovery, report classification,
  source statistics and UTF-8 size fallback now live in
  `features/library/useMarkdownReaderController.js`. Active-content AI calls,
  summary priority, pipeline summary state, QA readiness, insight title and
  output-path projection now live in
  `features/assistant/useAssistantWorkspaceProjectionController.js`. Local and
  queue log merging, clear boundaries, latest-event token totals, persistence
  failures and deterministic deduplication now live in
  `features/logs/useProcessLogProjectionController.js`;
  creator-sync content reveal, queue registration and first-task activation now
  live in `features/creator/useCreatorSyncTaskMonitorController.js`; three
  unreturned form/link helpers with no repository caller were removed instead
  of being moved. Total elapsed time, active queue count, status-bar transfer,
  ASR model options and stage labels now live in the pure
  `features/tasks/useTaskRuntimeProjectionController.js` boundary;
  queue transport and durable task mutation remain in their existing
  controllers. Workspace
  tab opening, selection hydration, close selection,
  reveal and recycle-bin dispatch now live in
  `features/workspace/useWorkspaceTabController.js`; task runtime remains the
  owner of progressive content refresh decisions. AI, assistant and appearance
  preference persistence now lives in
  `features/settings/useAppSettingsController.js`; the unconsumed legacy ASR
  form facade has been retired while the fixed desktop ASR request policy
  remains unchanged. Optional backend capabilities, server-provided model
  choices and video-download defaults now hydrate through the independently
  tested `features/settings/useDesktopBootstrapSettingsController.js` boundary.
  Content selection now has its own
  `features/library/useContentSelectionController.js` transaction for stale
  detail rejection, QA-session activation, read-state scheduling, article
  preview restoration and Markdown hydration.
- [ ] Split `SecondarySidebar.vue` into conversation, composer and task-status
  surfaces. Its model normalization, shortcut filtering, empty state, external
  citation, OCR hint and text-preview rules now live in
  `features/assistant/assistantPresentation.js` with pure boundary tests;
  conversation follow mode, history prepend position restoration and timestamp
  jumps now live in `features/assistant/useConversationScrollController.js`
  with injected-scheduler behavior tests; menus and composer focus/resize
  remain local UI behavior.
- [ ] Split `EditorHost.vue` into report, article, media/transcript and remote
  readers; each reader receives a mounted behavior test. Remote original-page
  lifecycle now lives in `workbench/useRemoteArticlePreviewController.js`: it
  owns desktop-only eligibility, WebView listener/timer cleanup, local-snapshot
  fallback, in-page find, bounded outline/progress messages and selection
  forwarding. Shared content-type, local-import preview and remote-source
  classification now lives in `workbench/editorContentKind.js` with pure
  boundary tests, including local PDF, image and durable Markdown readers.
  Readable-body extraction, character counts and current-document size
  selection now live in `workbench/editorReaderMetadata.js` with behavior
  tests. Menu-action dispatch and detail-row presentation now live in
  `workbench/editorContentActions.js` and `workbench/editorContentDetails.js`.
  Report title, date-window and generated-time presentation now live in
  `workbench/editorReportPresentation.js` with pure formatting tests. Article
  outline filtering and visual hierarchy now live in
  `workbench/articleOutlineModel.js` with pure boundary tests. Report, article
  and media readers still need their own mounted behavior boundaries. The
  former 1,907-line scoped style block now preserves its exact cascade through
  four co-located domains: `editor-host-workspace.css`,
  `editor-host-documents.css`, `editor-host-articles.css` and
  `editor-host-transcript.css`.
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
  Folder/content editing, picker/drop imports and delete-request projection
  now live in `workbench/useLibraryNodeEditingController.js`; direct tests lock
  parent-folder expansion, focus timing and the existing event payloads.
  Open-folder persistence, lazy branch hydration, ancestor reveal and unread
  expansion now live in `workbench/useLibraryOpenFolderController.js`; one
  flush cannot enqueue the same branch twice. Unread-list bulk deletion now
  normalizes its projection to the existing `content` mutation contract, and
  obsolete file-row/trash-transition selectors have been removed from the
  parent scoped stylesheet. User separator initialization, legacy-anchor
  migration, rendered placement, drag ordering and v2 preference persistence
  now share `workbench/useLibraryGroupLayoutController.js` instead of being
  distributed across the sidebar component.
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
  adapters and article extraction. Source models, the campus source registry,
  canonical section URLs and campus-host ownership checks now live in
  `services/campus_source_catalog.py`; `campus_sources.py` retains the same
  public imports for compatibility. Source-specific DOM selection, title/date
  normalization, list-row validation and de-duplication now live in
  `services/campus_list_parsing.py`, with the public parser still re-exported
  by the original service. OCR-document Markdown rendering, math-token
  marking and table-header promotion now live in
  `services/campus_document_rendering.py`; `campus_sources.py` retains its
  public renderer import and private caller alias for compatibility. Article
  HTML URL normalization, attachment de-duplication/scope selection and list
  node de-duplication now live in `services/campus_html_content.py`. Procurement
  feed mapping, provider document-path validation, CMS-fragment preservation,
  OCR status metadata and escaped fallback bodies now live in
  `services/campus_procurement_payloads.py`; network requests, provider-host
  enforcement and OCR execution remain in the orchestration service.
- [ ] Split `pipeline_runner.py` into stable transport contracts, media/source
  execution and persistence boundaries. Request/response/log models, durable
  error taxonomy and cancellation marker now live in
  `services/pipeline_contracts.py`; `pipeline_runner.py` keeps its original
  import surface while retaining all runtime orchestration.
  ASR configuration normalization and automatic short/long-model selection now
  live in `services/pipeline_asr_policy.py`.
  Timing, percentage bounding and log-level classification now live in
  `services/pipeline_progress_rules.py`. The duplicate legacy article-OCR
  refresh policy has been removed; the runner now delegates to the canonical
  `content_source_text.py` policy while retaining its non-mapping guard.
  Best-effort content status/title updates and preview-thumbnail preparation
  now live in `services/pipeline_content_updates.py`, separating those durable
  side effects from the main execution flow. Managed local-media authorization
  now lives in `services/pipeline_local_media_policy.py`; data and attachment
  roots are compared after path resolution so parent traversal and escaping
  symlinks fail closed, while exact database-owned originals remain compatible.
  Failure transitions now write status and error metadata through the actual
  active cache directory instead of an unreachable nested-function local.
  Monotonic stage progress, truthful transfer telemetry, immutable update
  snapshots, log projection, AI usage projection and throttled summary deltas
  now share the explicit `services/pipeline_run_reporter.py` state owner.
  Subtitle and ASR cache restoration now share
  `services/pipeline_cached_text.py`, returning transcript state explicitly
  instead of mutating two near-duplicate nested closures.
  Shared single-download admission, waiting cancellation, transfer forwarding
  and live provider-log de-duplication now live in
  `services/pipeline_media_download.py`; the runner retains its injectable
  downloader seam for existing integrations and tests.
  Best-effort Bilibili/Douyin interaction refresh, cache reuse and durable
  content attachment now share `services/pipeline_source_context.py`; provider
  failures remain non-fatal and the runner keeps both fetchers injectable.
  Authorized local subtitle/audio/video path validation, subtitle parsing,
  compact cache preparation and retained-media metadata now live in
  `services/pipeline_local_inputs.py`; stage reporting remains in the runner.
  Persisted campus/RSS/Xiaohongshu article lookup, legacy type repair, XHS
  capture and source-text validation now live in
  `services/pipeline_stored_article.py`, keeping those documents out of media
  parsing, download and ASR orchestration. The same boundary now owns
  transcript-only completion, article summarization, summary persistence and
  best-effort search indexing for those stored documents.
  Audio extraction, retained-audio protection, cancellation checkpoints, ASR
  execution, backend attribution and compact transcript caching now live in
  `services/pipeline_transcription.py`. ASR configuration validation remains
  in `services/pipeline_asr_policy.py`, while the runner preserves its public
  strategy/model exports.
- [ ] Split `downloader.py` by platform transport and pure media policy.
  Douyin URL classification, strict media-host ownership, credential-free
  browser header forwarding, signed-URL refresh decisions, payload lookup and
  quality/bitrate selection now live in `services/douyin_media_rules.py`;
  download result/progress contracts, callback isolation, bounded percentages,
  yt-dlp rate parsing and inactivity diagnostics now live in
  `services/download_contracts.py`, while `downloader.py` retains its former
  import surface. Codec probing, playable-H.264 conversion, media validation
  and optional storage compression now live in
  `services/download_media_processing.py`, with partial-output cleanup and the
  former private imports preserved. Bilibili yt-dlp execution, bounded
  inactivity detection, native progressive fallback and cancellation now live
  in `services/bilibili_download.py`; the public downloader dispatcher and its
  former private imports remain stable;
  browser execution, cookies, downloads, cancellation and retries remain in
  the downloader orchestrator.
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

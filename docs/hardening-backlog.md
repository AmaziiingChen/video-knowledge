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
  state remains deliberately in `App.vue` for a separate behavior-preserving
  slice.
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
  `features/usage/useAiUsageController.js`.
  Content recovery actions (source text, reprocessing, retranscription,
  subtitles and redownloads) now live in
  `features/library/useContentRecoveryController.js` while reusing the durable
  task queue. Folder-tree ownership, task runtime, link import and assistant
  sessions remain in the facade because they still share optimistic updates,
  tab cleanup and durable queue state.
- [ ] Split `EditorHost.vue` into report, article, media/transcript and remote
  readers; each reader receives a mounted behavior test.
- [ ] Separate library and prompt sidebars from `PrimarySidebar.vue` and test
  tree, drag, search and trash behavior at their owners.
  Local tree-preference persistence and pure tree-node construction now live in
  `features/library/libraryTreePreferences.js` and
  `features/library/libraryTreeModel.js`; drag/drop, selection and virtual-row
  rendering stay in the sidebar until they have their own behavior boundaries.
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
  Article capture remains a separate follow-up cut.
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
- [ ] Separate the unused external download-site instructions from the normal
  GitHub Release path.
- [ ] Continue ratcheting every production source below 1,000 lines, or add a
  narrowly documented generated/declarative exception. The group-report source
  summary cache now has its own database owner; report planning and writing
  remain the next intentional boundaries in the main pipeline.

## Non-negotiable compatibility checks

Every item preserves existing HTTP routes, SQLite files, local-storage keys,
preload APIs, persistent queue states, runtime-model downloads, local-data
boundaries and the unsigned-DMG release contract.  New dependencies and bulk
formatting are out of scope unless a specific item proves they are necessary.

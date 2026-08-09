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
- [ ] Add connection-level DNS pinning (or an equivalent transport guarantee)
  for untrusted remote fetches, so a hostname cannot rebind after validation
  but before the HTTP client opens its socket.

## P1 — maintainability, test truthfulness, and resource control

- [x] Extract the prompt-workspace controller from `App.vue`; retain all four
  tab types, draft/trash behavior and add mock-API race regression tests.
- [ ] Extract the WeChat subscription controller from `App.vue`; add mock-API
  behavior tests and ratchet its remaining composition-root budget down.
  Account authorization, QR polling, transfer and account-search state now live
  in `features/wechat/useWechatAccountController.js`; the remaining sync,
  filters and report-group state machine remains deliberately in `App.vue` for
  the next behavior-preserving slice.
- [ ] Split `useAppController.js` by library, task-runtime, import and
  assistant-session ownership while preserving its external facade.
  The first library boundary, debounced global search and result hydration, now
  lives in `features/library/useLibrarySearchController.js`; tree presentation,
  task runtime, imports and assistant sessions remain in the facade pending
  their own behavior-preserving slices.
  The independent trash transaction boundary now lives in
  `features/library/useLibraryTrashController.js`; folder history and content
  tree ownership remain in the facade because they share optimistic updates,
  tab cleanup and keyboard undo/redo.
- [ ] Split `EditorHost.vue` into report, article, media/transcript and remote
  readers; each reader receives a mounted behavior test.
- [ ] Separate library and prompt sidebars from `PrimarySidebar.vue` and test
  tree, drag, search and trash behavior at their owners.
- [x] Replace the idle one-second Markdown scan with deterministic adaptive
  backoff: changes stay on a two-second cadence, while an unchanged library
  backs off through 4/8/16/32 to 60 seconds.  The scheduler has no network
  path and its cadence is covered by a deterministic wait-budget test.
- [ ] Split `routers/content.py` into transport schemas, listing, analytics,
  import and mutation domains.  Move new SQL out of routers and keep router
  registration/API paths stable.
- [ ] Add direct tests for public-tree, DMG validation and backend packaging
  scripts; add bounded job timeouts and persist release measurements.
- [ ] Establish auditable Python dependency constraints/lock data and add an
  incremental, explicit coverage baseline for high-risk boundaries.

## P2 — repository hygiene and release provenance

- [x] Remove verified-unreachable renderer batch-link, batch-upload and queue
  action code after facade/template/call-site audit; retain the live queue,
  clipboard and single-link processing paths.
- [ ] Remove the three verified-unused Vite starter assets after the full
  renderer build confirms they are absent from output.
- [ ] Remove committed macOS helper binaries after an arm64 build proves the
  tracked Objective-C sources reproduce them.
- [ ] Add generated SBOM/license review evidence to release artifacts; extend
  Dependabot to GitHub Actions and evaluate immutable action pins.
- [ ] Separate the unused external download-site instructions from the normal
  GitHub Release path.
- [ ] Continue ratcheting every production source below 1,000 lines, or add a
  narrowly documented generated/declarative exception.

## Non-negotiable compatibility checks

Every item preserves existing HTTP routes, SQLite files, local-storage keys,
preload APIs, persistent queue states, runtime-model downloads, local-data
boundaries and the unsigned-DMG release contract.  New dependencies and bulk
formatting are out of scope unless a specific item proves they are necessary.

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
- [ ] Verify that capability tokens can protect all private read endpoints
  without breaking the packaged renderer, then enforce them for sensitive
  reads and reject non-loopback desktop binds.
- [ ] Validate every network fetch and redirect after DNS resolution to close
  private-address and DNS-rebinding SSRF paths.

## P1 — maintainability, test truthfulness, and resource control

- [ ] Extract WeChat subscription and prompt-workspace controllers from
  `App.vue`; add mock-API behavior tests and ratchet its budget down.
- [ ] Split `useAppController.js` by library, task-runtime, import and
  assistant-session ownership while preserving its external facade.
- [ ] Split `EditorHost.vue` into report, article, media/transcript and remote
  readers; each reader receives a mounted behavior test.
- [ ] Separate library and prompt sidebars from `PrimarySidebar.vue` and test
  tree, drag, search and trash behavior at their owners.
- [ ] Replace the idle one-second full Markdown scan with a deterministic
  directory fingerprint/backoff strategy; measure idle CPU, I/O and network
  requests before setting a budget.
- [ ] Split `routers/content.py` into transport schemas, listing, analytics,
  import and mutation domains.  Move new SQL out of routers and keep router
  registration/API paths stable.
- [ ] Add direct tests for public-tree, DMG validation and backend packaging
  scripts; add bounded job timeouts and persist release measurements.
- [ ] Establish auditable Python dependency constraints/lock data and add an
  incremental, explicit coverage baseline for high-risk boundaries.

## P2 — repository hygiene and release provenance

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

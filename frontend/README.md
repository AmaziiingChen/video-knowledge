# KnowledgeHub renderer and desktop shell

This directory contains the Vue renderer, Electron main/preload processes and
macOS packaging definition for KnowledgeHub. It is not a standalone Vite demo:
the normal desktop application is a local-first Vue + Electron client for the
FastAPI backend in `../backend/`.

Start with the repository-level [README](../README.md) for product setup, and
with [ARCHITECTURE.md](../ARCHITECTURE.md) before changing a feature boundary.

## Run locally

From this directory:

```bash
npm ci
npm run dev
```

For the packaged desktop shell, return to the repository root and use the
documented `start.sh` / `stop.sh` workflow. `npm run desktop` builds the
renderer and launches Electron against the local backend; it is for development,
not for making a distributable release.

## Important entry points

```text
src/App.vue                         application composition root
src/features/                       feature-owned state, API workflows and UI
src/workbench/                      shell, panes, tabs, editor and reading surfaces
src/components/                     reusable dialogs and focused UI primitives
src/utils/localApiAuth.js           canonical local API URL and auth helpers
electron/main.cjs                   Electron process, backend lifecycle and IPC policy
electron/preload.cjs                narrow renderer-facing desktop bridge
package.json                        renderer scripts and electron-builder definition
```

`App.vue` composes features and routes UI events. New feature state, requests,
polling and cleanup belong to a focused controller under `src/features/`, not
to another branch in the composition root. The ownership map in
[ARCHITECTURE.md](../ARCHITECTURE.md) records existing controllers and their
boundaries.

## Local API and desktop security

The packaged renderer talks only to the local backend. Do not hard-code a
loopback URL or put a token in a URL:

- use `localApiRequestUrl()` and `localApiAuthHeaders()` from
  `src/utils/localApiAuth.js` for `fetch`;
- use the configured Axios client for ordinary feature requests;
- Electron injects the per-session backend capability for browser media
  elements that cannot attach headers themselves;
- privileged operations belong behind the preload bridge, never in renderer
  code with Node access.

These rules preserve the desktop capability and origin boundary described in
[SECURITY.md](../SECURITY.md). A browser-development fallback must remain
explicit and must not weaken the packaged application.

## Validate a change

Run the closest behavior tests first. Before handing off a frontend feature,
run:

```bash
npm run lint
npm run typecheck
npm test
npm run check:reachability
npm run build
```

`npm test` includes Node behavior tests and mounted Vue component tests.
`npm run build` also enforces the renderer bundle budget. For a release
candidate, follow the complete repository-level gates in
[docs/release-candidate-verification.md](../docs/release-candidate-verification.md);
do not treat a renderer build as a DMG verification.

## Packaging

`npm run desktop:package:mac` produces an unsigned Apple Silicon DMG in
`release/`. The release process validates the bundled backend, application
metadata, icon, absence of local runtime data/models and the packaged MCP
bridge. Do not add models, user data, cookies, tokens or source `node_modules`
to electron-builder's product files.

The application icon source and reproducible macOS generation step are in
`build/`; use `../scripts/build_macos_icon.sh` after deliberately changing the
approved SVG source.

## Contribution rules

Read [CONTRIBUTING.md](../CONTRIBUTING.md), [AGENTS.md](../AGENTS.md) and
[DESIGN.md](../DESIGN.md) before changing behavior or visible UI. KnowledgeHub
is feature-frozen until the release baseline is stable: favor bug fixes,
privacy/security repairs, measured performance improvements, documentation and
evidence-backed dead-code removal over speculative abstraction.

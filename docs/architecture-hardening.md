# Architecture hardening after v0.1.0

`v0.1.0` is the first public KnowledgeHub baseline. Earlier development did
not use distributable version milestones, so the project will not invent
historical releases or retroactive version numbers.

The product is now feature-frozen. Until the hardening exit criteria below are
met, accepted changes are limited to bug fixes, security and privacy repairs,
compatibility work, tests, documentation, performance improvements and
behavior-preserving architecture refactors.

## Version policy

- Published tags are immutable.
- `0.1.x` releases contain compatible fixes, architecture work and release
  hardening. They preserve HTTP paths, persisted data, local-storage keys,
  preload APIs and existing user-visible workflows.
- A later minor version is created only for an intentional product capability
  or an explicitly migrated contract. Refactoring alone does not justify
  pretending that the product has acquired a new feature release history.
- Every published version receives a changelog entry, an unsigned Apple
  Silicon DMG and the checksum of that exact artifact.

## Hardening order

1. Keep composition roots small: `App.vue`, `useAppController.js` and
   `EditorHost.vue` must lose feature-owned UI and workflows.
2. Move feature state and behavior into its owning `features/` package. Pass
   explicit domain models across component boundaries instead of ever-growing
   prop and event lists.
3. Separate SQLite connection management, migrations and feature repositories.
4. Add executable lint, type, component-behavior and coverage gates.
5. Build and smoke-test the unsigned DMG in CI before a GitHub Release can be
   considered complete.

## Architecture debt budget

Run:

```bash
python scripts/check_architecture_budget.py
```

The check records ceilings for existing oversized production files and rejects
new production files over 1,000 lines. A ceiling is ratcheted downward whenever
a refactor shrinks its file. Raising a ceiling merely to pass CI is forbidden.

This budget does not declare the current sizes healthy. It prevents regression
while the files are split into feature-owned modules.

The second contraction ratchet moves publishing settings, cover tasks,
selected-text context, preview-find state, report data contracts and Markdown
normalization behind explicit owners. The remote original-page lifecycle is
also isolated in `useRemoteArticlePreviewController.js`; it keeps Electron-only
WebView access, cached-body fallback and bounded reader metadata together
without giving guest pages access to local content. The corresponding legacy
ceilings now match the smaller files; CI will reject putting those
responsibilities back into the composition roots.

Cover-style selection, negative prompts, runtime prompt inputs and cover-task
presentation now live in `services/wechat_publishing_cover_policy.py`; the
publishing service retains its existing public imports while concentrating on
credentials, persistence and remote API orchestration.

## Exit criteria

- No Vue or JavaScript production file exceeds 1,000 lines without a documented
  exception based on generated or declarative content.
- No backend router owns domain workflows or imports another router's private
  helpers.
- Database migrations and feature repositories no longer share one monolithic
  module.
- Core desktop workflows have mounted component tests and a packaged-app smoke
  test, not only source-text assertions.
- CI performs source checks, dependency audits, tests, renderer builds, backend
  packaging, DMG creation and artifact checksum verification.

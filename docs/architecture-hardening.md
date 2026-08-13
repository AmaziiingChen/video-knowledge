# Stabilization baseline after v0.1.0

`v0.1.0` is the first public KnowledgeHub baseline. Earlier development did
not use distributable version milestones, so the project will not invent
historical releases or retroactive version numbers.

The product is now feature-frozen. The previous broad contraction phase is
complete. Until the stabilization exit criteria below are met, accepted changes
are limited to verified dead-code removal, bug fixes, security and privacy
repairs, compatibility work, tests, documentation, measured performance work
and architecture changes required by a demonstrated ownership or testability
problem.

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

## Stabilization order

1. Remove production code, state, assets and dependencies only after its static
   call chain, runtime entry points, templates, IPC/API/script contracts and
   tests jointly prove that it is unreachable.
2. Fix verified correctness, security, data-integrity, resource and release
   blockers without changing existing product contracts.
3. Document core owners, data flows, failure paths and risk-tiered validation so
   a new contributor can locate and verify a change without a full-repository
   audit.
4. Freeze one explicit local release-candidate commit, then run the complete
   frontend and backend gates, dependency and public-tree checks, unsigned-DMG
   validation, packaged-app smoke tests and reproducible idle-resource sampling.
5. After the candidate is frozen, accept only release-blocking repairs. Do not
   add features or continue opportunistic architecture work.

## Architecture debt budget

Run:

```bash
python scripts/check_architecture_budget.py
```

The check records explicit non-regression ceilings for reviewed architecture hot
spots. It does not reject a source file merely for exceeding 1,000 lines, and
its ceilings are not a whole-repository target or architecture completion
criterion. The listed ceilings remain a CI and release gate against unnoticed
size regression. File size is otherwise a review signal only. Split a file only
when evidence shows multiple independent owners, frequent conflicts, poor test
isolation, unrelated state required for a change, or duplicated branches.

Add or lower a ceiling only after either a responsibility move with real callers
and behavior tests, or a deletion whose static chain, entries, templates,
IPC/API/script contracts and tests jointly prove it unreachable. A line ceiling
cannot prove that a responsibility stayed outside a composition root; behavior
and contract tests provide that protection. Do not move unchanged complexity
into wrappers, and do not raise a ceiling merely to make a check pass.

Completed contraction work moved publishing settings, cover tasks,
selected-text context, preview-find state, report data contracts and Markdown
normalization behind explicit owners. The remote original-page lifecycle is
also isolated in `useRemoteArticlePreviewController.js`; it keeps Electron-only
WebView access, cached-body fallback and bounded reader metadata together
without giving guest pages access to local content. The corresponding legacy
reviewed ceilings match the smaller files and flag gross size regression;
behavior and contract tests reject putting those responsibilities back into the
composition roots.

Cover-style selection, negative prompts, runtime prompt inputs and cover-task
presentation now live in `services/wechat_publishing_cover_policy.py`; the
publishing service retains its existing public imports while concentrating on
credentials, persistence and remote API orchestration.

## Stabilization exit criteria

- The worktree is clean and the exact local release-candidate commit is recorded.
- No known high-risk security issue or data-corruption path remains open.
- Production code and dependencies proven unreachable have been removed or have
  a documented contract-based retention reason.
- Core modules document their entry points, owners, data flow, failure paths and
  closest behavior tests.
- A new contributor can start, locate, modify, test and package the project from
  the maintained documentation.
- Complete frontend and backend regressions, dependency audits, architecture and
  public-tree checks pass on the candidate commit.
- The unsigned DMG, checksum and core packaged-app smoke tests pass without
  changing the unsigned-release contract.
- Idle CPU, memory, thread and disk activity have a reproducible measurement
  record; nonblocking release-governance debt is explicitly deferred instead of
  extending architecture work indefinitely.

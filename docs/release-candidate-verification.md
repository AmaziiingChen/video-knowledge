# Release candidate verification

This document is the evidence template for a local KnowledgeHub release
candidate. Fill it from one clean commit. Do not combine evidence from different
commits or rebuild the artifact after recording its checksum.

## Candidate identity

Record the source identity and builder environment before running the release
gates:

- version and exact Git commit;
- proof that the worktree is clean;
- macOS version, Apple Silicon model, available disk and build date;
- Python, Node and npm versions;
- resolved Python and npm dependency evidence used by the builder.

After the DMG is built and validated, add its exact filename and SHA-256 to the
same candidate record.

Prepare a clean builder and create the evidence directory before running any
gate:

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
npm --prefix frontend ci
mkdir -p release-evidence
python -m pip freeze --all | tee release-evidence/python-resolved.txt
npm --prefix frontend ls --all --json | tee release-evidence/npm-resolved.json
```

The resolved manifests describe this builder only; they are not substitutes for
cross-platform lock files.

## Risk-tiered gates

### 1. Publication and supply chain

```bash
python scripts/check_public_release_tree.py
python scripts/check_architecture_budget.py
python -m pip install pip-audit
pip-audit -r requirements.txt

cd frontend
npm audit --package-lock-only --audit-level=high
cd ..
```

Record every unresolved high-risk advisory and its reviewed disposition. A
network failure is not a passing audit.

### 2. Source regression

```bash
ruff check --select E9,F63,F7,F82 backend tests scripts
python -m pytest

cd frontend
npm run lint
npm run typecheck
npm test
npm run test:coverage
npm run check:reachability
npm run build
npm run build:public-report
cd ..
```

### 3. Unsigned artifact

```bash
cd frontend
npm run desktop:package:mac
cd ..

python scripts/validate_macos_release.py \
  --dmg frontend/release/KnowledgeHub-0.1.0-arm64.dmg \
  --expected-version 0.1.0
```

The validator must confirm Apple Silicon architecture, the unsigned contract,
version and Bundle ID, backend health, checksum generation, and the absence of
runtime data and bundled models. Replace the example filename/version with the
candidate's exact values.

### 4. Packaged behavior

Before freezing the first candidate, the repository must provide
`scripts/smoke_macos_desktop.py`. Run it against the extracted candidate app
with an isolated profile and retain its JSON report:

```bash
python scripts/smoke_macos_desktop.py \
  --app "/path/to/KnowledgeHub.app" \
  --profile release-smoke \
  --report release-evidence/desktop-smoke.json
```

The smoke must prove window/renderer readiness, bundled backend readiness, local
fixture import and open, restart persistence, clean shutdown and temporary data
cleanup. Repeat install, first open and reopen once from a clean macOS account.
Do not disable Gatekeeper; follow `docs/desktop-release.md` for this single
unsigned application.

MCP/OpenClaw is not required for the base desktop smoke. Because KnowledgeHub
advertises a local MCP service, the candidate must additionally contain a
documented packaged MCP entry. Before freezing the first candidate, the
repository must provide `scripts/smoke_macos_mcp.py` and retain its JSON report:

```bash
python scripts/smoke_macos_mcp.py \
  --app "/path/to/KnowledgeHub.app" \
  --report release-evidence/mcp-smoke.json
```

The smoke must execute one local read-only tool with fake fixture data, prove
that a valid capability succeeds, and prove that missing and incorrect
capabilities fail. The capability must never appear in a URL, ordinary log,
command-line argument, JSON report or OpenClaw configuration. Do not use a real
account, external gateway or production capability.

### 5. Idle resources

Before freezing the first candidate, the repository must provide
`scripts/measure_macos_idle.py`. With no queued work, model download or optional
automation, retain the raw JSON report from a fixed warm-up and sample window:

```bash
python scripts/measure_macos_idle.py \
  --app "/path/to/KnowledgeHub.app" \
  --warmup-seconds 120 \
  --sample-seconds 300 \
  --interval-seconds 5 \
  --report release-evidence/idle-resources.json
```

The report must identify the app/backend process tree and record average and
peak CPU, RSS, thread count, disk reads and disk writes, plus the exact profile
and machine configuration. For the first release candidate, a complete,
successful empty-library sample establishes the baseline; there is no invented
threshold. Later candidates compare only against the same profile on a
comparable machine and stop when a pre-recorded threshold is exceeded. A
documented large-library fixture is an additional requirement before changing
scheduler policy, not a blocker for the first baseline.

## Pass/fail record

A candidate passes only when every required command exits zero, required JSON
evidence is retained, `HEAD` still resolves to the recorded commit, the worktree
is clean, and no known high-risk security or data-corruption issue remains.
Missing evidence,
artifact/data leakage, checksum mismatch, packaged smoke failure, an incomplete
first idle baseline, a later pre-recorded resource-threshold breach or an
unreviewed high-risk advisory stops release.

Record complete cross-platform Python locks, SBOM/license evidence and immutable
Action pins as explicit governance deferrals. They must not be represented as
completed checks, but they do not by themselves extend line-count-driven
architecture work or block this Apple Silicon baseline.

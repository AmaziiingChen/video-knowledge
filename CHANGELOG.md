# Changelog

KnowledgeHub starts its public version history at `v0.1.0`. Development before
that tag was continuous and was not distributed as versioned releases.

## Unreleased

- Architecture hardening under a product feature freeze.

## v0.1.11

- Discover the diagnostics-only proxy from Electron's macOS networking session
  when Finder launches the app without shell proxy environment variables.

## v0.1.10

- Route only the fixed Cloudflare diagnostics uploader through a sanitized,
  dedicated copy of the user's HTTP(S) proxy while every other backend network
  client remains isolated from proxy environment variables.

## v0.1.9

- Restore OpenClaw MCP bridge sessions when a healthy backend belongs to an
  earlier desktop launch, and repair stale OpenClaw capability caches.
- Let release checks follow the user's macOS network settings while retaining
  the official Cloudflare manifest and GitHub Release allowlists, and fix the
  Worker runtime handler so it actually calls GitHub instead of its context.
- Add a diagnostics switch, pending-event and upload status, and a manual retry
  action; the fixed Cloudflare collector can use the macOS system proxy when a
  direct `workers.dev` connection is unavailable.

## v0.1.4

- Restore visible AI reasoning for manual summaries and preserve the existing
  reasoning stream for automatic article and video summaries.
- Add bounded follow-up suggestion generation for summaries and conversations
  when a model does not emit the strict stream trailer.
- Restore clean-room, user-initiated Xiaohongshu single-note reading while
  keeping favourites, creator sync and comment refresh unavailable.
- Disable unavailable WeChat public-account authorization and subscription
  entry points without affecting existing collections, groups or RSS.
- Bundle the native MLX runtime support files required by MLX Whisper in the
  macOS backend, and update diagnostic collection to the Cloudflare v3 notice.

## v0.1.3

- Add a strict Cloudflare release manifest that checks the official GitHub
  Release page at startup and prompts for manual macOS updates.
- Keep the unsigned-DMG installation contract: updates never download,
  replace, or restart the app automatically.
- Use stable SF Symbol fallbacks when an older macOS runner does not provide
  a newer symbol.
- Install the pinned PyInstaller release-build dependency in the macOS GitHub
  Actions job before packaging the bundled backend.

## v0.1.0

- First public macOS Apple Silicon release baseline.
- Local-first content ingestion, persistent processing tasks, searchable
  knowledge storage, AI-assisted reading and reporting, and Obsidian export.
- Unsigned DMG distribution with documented Gatekeeper guidance and checksum
  verification.

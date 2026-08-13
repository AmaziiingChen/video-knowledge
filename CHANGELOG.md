# Changelog

KnowledgeHub starts its public version history at `v0.1.0`. Development before
that tag was continuous and was not distributed as versioned releases.

## Unreleased

- Architecture hardening under a product feature freeze.

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

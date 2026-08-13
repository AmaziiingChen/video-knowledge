# Third-party notices

KnowledgeHub's own source code is licensed under the MIT License in the
repository root. Dependencies keep their own licenses and notices.

- JavaScript dependencies and their resolved versions are recorded in
  `frontend/package-lock.json`.
- macOS builds render their interface symbols from the installed operating
  system through AppKit. No Apple CoreSVG or SF Symbols SVG export is tracked
  or redistributed in this source tree; use of the rendered symbols remains
  subject to Apple's SF Symbols terms and platform restrictions.
- Close buttons use the default `IconX` from `@tabler/icons-vue`, distributed
  under Tabler's MIT License.
- `frontend/public/brand-icons/openclaw.svg` identifies the optional OpenClaw
  integration. OpenClaw is distributed under the MIT License; its name and
  visual identity remain the property of its respective owner.
- Python dependencies are listed in `requirements.txt`; their exact license
  terms must be reviewed before any binary distribution.
- Electron, Chromium, Playwright, ffmpeg, yt-dlp, Whisper runtimes and any
  user-installed executables are independent projects with their own licenses
  and distribution conditions.

## Excluded collector and independent clean-room reader

`backend/vendor/Spider_XHS` is intentionally excluded from this public source
tree and from macOS packaging. Its copied source lacked a verifiable upstream
license file, so it is not redistributed or represented as MIT code here. The
KnowledgeHub's own clean-room browser reader does not copy, import or call that
vendor source. It loads a user-supplied Xiaohongshu note page and observes only
narrowly allowlisted JSON responses initiated by the page itself. The current
boundary supports session probing and active single-note import only; favorites,
creator subscriptions and comments remain disabled. Do not restore or
redistribute `Spider_XHS` unless its upstream license, provenance, notices and
redistribution terms have been verified and recorded here.

This file is a release record, not legal advice.

## Release-history rule

The exclusion above also applies to public Git history. Before the first
public push and before every release, run
`python scripts/check_public_release_tree.py`. Publish only the intended
branches and tags; do not use `git push --mirror`, because local recovery or
tooling refs are not part of the public release surface.

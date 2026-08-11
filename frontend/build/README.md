# Application icon

`icon.svg` is the canonical KnowledgeHub application mark. It deliberately uses
a theme-neutral graphite and paper palette so the desktop identity does not
belong to any one selectable reader theme.

Run the repository-level generator on macOS after changing the source:

```bash
scripts/build_macos_icon.sh
```

The generator uses the project's pinned Electron runtime to rasterize the SVG,
then the macOS `sips` and `iconutil` tools to write `icon.png` (1024×1024) and
`icon.icns`. Electron Builder consumes the ICNS file directly. The release
validator compares the packaged icon with this approved source artifact so a
future build cannot silently fall back to Electron's default icon.

The same generator also rasterizes
`../electron/assets/trayTemplate.svg` into 18px and 36px PNGs. The menu-bar mark
is intentionally a separate, monochrome transparent K: Electron registers it as
a macOS template image so the operating system owns light, dark and pressed
states instead of reusing the full-color application tile.

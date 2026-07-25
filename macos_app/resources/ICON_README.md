# XeFM Application Icon

## Source of truth

`XeFM.icns` in this directory is **generated** — do not hand-edit or overwrite it.
The icon is authored as SVG, and every platform asset is rendered from it:

| Master | Used at |
|--------|---------|
| `tools/icon/xefm-icon.svg` | 128px and up — full detail: dual panes, `XeFM` wordmark badge with corner brackets, faint starfield |
| `tools/icon/xefm-icon-small.svg` | 64px and below — simplified: thicker rows, larger `Xe` badge, no starfield |

Two masters exist because the detailed art collapses into noise at 16–32px. The
generator picks the right one per output size, so the icon stays legible from the
Finder list view up to the 1024px Quick Look preview.

## Regenerating

```bash
make icons          # rewrite every asset from the SVG masters
make icons-check    # verify the committed assets are still in sync (exit 1 if not)
```

Both run `tools/make_icons.py`, which rasterizes through AppKit's native SVG support
(macOS 13+) into an sRGB, premultiplied-alpha bitmap context. **This is macOS-only** —
which is why all outputs are committed: the Windows build consumes them without
needing a rasterizer of its own.

Outputs:

| File | Contents |
|------|----------|
| `macos_app/resources/XeFM.icns` | all 10 iconset slots, 16px → 1024px |
| `windows_app/resources/XeFM.ico` | 16, 24, 32, 48, 64, 128, 256 — each rendered natively, not downscaled |
| `windows_app/resources/XeFM-1024.png` | detailed raster master for MSIX Store tiles >64px |
| `windows_app/resources/XeFM-small-256.png` | simplified raster master for MSIX Store tiles ≤64px |

Rendering is deterministic, so `--check` compares bytes and is safe to run in CI.

After regenerating, rebuild the bundle and clear the icon cache if Finder or the Dock
still shows the old art:

```bash
make macos-app
make macos-refresh-icon
```

## Design notes

The artwork draws its own rounded tile (a 200×200 viewBox with `rx="40"`, i.e. a 20%
corner radius) and is rendered **full-bleed**: the tile fills the whole canvas, with
transparency only outside the corners.

That matters downstream. `windows_app/make_icon.py` applies a rounded-corner mask when
its source is a full-bleed *opaque* square (the shape the old placeholder `.icns` had),
and skips it when the source already carries corner transparency — otherwise the mask's
wider 22.5% radius would shave a sliver off the artwork. `render_tile()` there makes
that call by probing a corner pixel's alpha, and `make_store_assets.py` shares it so the
launcher icon and the Store tiles match exactly.

If you want the icon to sit at the size Apple's Human Interface Guidelines specify for
macOS (an 824×824 tile centered in a 1024×1024 canvas, so it lines up with system icons
in the Dock rather than reading slightly oversized), that inset would go in
`tools/make_icons.py` — and only on the macOS path, since Windows icons are expected to
be full-bleed.

## Verifying

```bash
# Inspect the generated .icns
sips -g pixelWidth -g pixelHeight -g hasAlpha -g space macos_app/resources/XeFM.icns

# Confirm the bundle picked it up
ls -lh macos_app/build/XeFM.app/Contents/Resources/XeFM.icns
grep -A 1 "CFBundleIconFile" macos_app/build/XeFM.app/Contents/Info.plist

# Look at it
open macos_app/build/
```

## Troubleshooting

**Icon doesn't change after a rebuild** — macOS caches aggressively. Run
`make macos-refresh-icon` (touches the bundle, clears
`/Library/Caches/com.apple.iconservices.store`, restarts Dock and Finder). Quit and
relaunch the app if it was running.

**`make icons` fails with "AppKit could not load ..."** — the SVG rasterizer needs
macOS 13 or newer. Check `sw_vers`.

**Colors look off** — the generator tags output sRGB explicitly. If you re-render by
some other route, make sure you are not baking in the display's wide-gamut profile.

#!/usr/bin/env python3
"""
Generate the MSIX / Microsoft Store tile assets (PNG) for the XeFM package.

The Store manifest references PNG tiles (not the launcher's ``.ico``). This emits
the minimum useful set from the committed raster master
``windows_app/resources/XeFM-1024.png`` (or a ``--source`` PNG/ICNS), reusing
``make_icon.py``'s tile rendering so XeFM's Windows presence (exe icon + Store tiles)
stays visually consistent.

Emitted into ``--out-dir`` (default ``windows_app/resources/Assets``):
    StoreLogo.png                 50x50    <Properties><Logo>
    Square44x44Logo.png           44x44    app-list icon (+ .scale-200 = 88)
    Square150x150Logo.png         150x150  medium tile   (+ .scale-200 = 300)
    Wide310x150Logo.png           310x150  wide tile (square logo centered)
    Square44x44Logo.targetsize-N[_altform-unplated].png
                                  16/24/32/48/256  shell icons (taskbar, Alt-Tab, ...)

Note that MRT only finds the ``targetsize-*`` variants through the package's
``resources.pri``; build_msix.ps1 generates one with makepri after writing the
manifest. Dropping these PNGs in without that index leaves them inert.

Pillow is required (already a build dependency via make_icon.py). If it is missing
this exits non-zero rather than emitting junk — the Store listing needs real tiles.

Usage:
    python make_store_assets.py [--source <icon.png|.icns>] [--out-dir <dir>]
"""

import argparse
import sys
from pathlib import Path

# Reuse the launcher .ico's tile rendering so tiles match it.
from make_icon import default_source, render_tile  # noqa: E402

# name -> (width, height); square tiles pass width for both.
_SQUARE_TILES = {
    "StoreLogo.png": 50,
    "Square44x44Logo.png": 44,
    "Square150x150Logo.png": 150,
}
# Which square tiles also get a scale-200 (2x) variant that MSIX auto-selects.
_SCALE_200 = {"Square44x44Logo.png", "Square150x150Logo.png"}

# Sizes emitted as ``targetsize-N`` variants of Square44x44Logo -- the shell's icon
# sizes (taskbar, Alt-Tab, Task View, jump lists, Start's app list). Each is rendered
# natively rather than left for the shell to downscale the 44px tile to.
_TARGETSIZE_SIZES = [16, 24, 32, 48, 256]

_WIDE_TILE = ("Wide310x150Logo.png", 310, 150)

# At or below this tile size the simplified master is used: the detailed art's wordmark
# and pane rows are unreadable at 44-50px. Matches tools/make_icons.py's threshold.
_SIMPLE_MAX_PX = 64


def _scale_name(name: str, scale: int) -> str:
    """'Square44x44Logo.png' + 200 -> 'Square44x44Logo.scale-200.png'."""
    stem, _, ext = name.rpartition(".")
    return f"{stem}.scale-{scale}.{ext}"


def _targetsize_name(size: int, unplated: bool) -> str:
    """24 -> 'Square44x44Logo.targetsize-24[_altform-unplated].png'."""
    suffix = "_altform-unplated" if unplated else ""
    return f"Square44x44Logo.targetsize-{size}{suffix}.png"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate XeFM Store tile assets")
    parser.add_argument("--source", default=None,
                        help="source image (.png/.icns); defaults to windows_app/resources/XeFM-1024.png")
    parser.add_argument("--out-dir", default=None,
                        help="output dir; defaults to windows_app/resources/Assets")
    args = parser.parse_args()

    try:
        from PIL import Image  # noqa: F401
    except Exception:
        print("[ERROR] Pillow is required to generate Store tiles "
              "(pip install pillow). Aborting.")
        return 1

    from PIL import Image

    out_dir = (Path(args.out_dir).resolve() if args.out_dir
               else Path(__file__).resolve().parent / "resources" / "Assets")

    # An explicit --source overrides both masters; otherwise each tile picks the one
    # matching its size.
    override = Path(args.source).resolve() if args.source else None
    sources = {
        False: override or default_source(),
        True: override or default_source(small=True),
    }
    for source in set(sources.values()):
        if not source.exists():
            print(f"[ERROR] Source icon not found: {source}")
            return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    images = {small: Image.open(path).convert("RGBA") for small, path in sources.items()}

    def tile(size):
        """Render at ``size``, from whichever master suits that size."""
        return render_tile(images[size <= _SIMPLE_MAX_PX], size)

    count = 0
    # Square tiles (+ optional scale-200).
    for name, size in _SQUARE_TILES.items():
        tile(size).save(out_dir / name, format="PNG")
        print(f"[INFO] Wrote {out_dir / name} ({size}x{size})")
        count += 1
        if name in _SCALE_200:
            big = size * 2
            scaled_name = _scale_name(name, 200)
            tile(big).save(out_dir / scaled_name, format="PNG")
            print(f"[INFO] Wrote {out_dir / scaled_name} ({big}x{big})")
            count += 1

    # Shell icons. Windows *plates* a packaged app's icon -- composites it onto a
    # solid square filled with the manifest's BackgroundColor, or with the theme
    # accent color when that is "transparent" -- on every surface except those where
    # an ``_altform-unplated`` candidate exists. With no targetsize assets at all the
    # taskbar plated XeFM's rounded tile into a solid accent-blue square (issue #322).
    # So both forms ship from the same art: the plain one for the surfaces that plate
    # by design, the unplated one for the taskbar, Alt-Tab, Task View and jump lists.
    #
    # No ``_altform-lightunplated`` companion: that exists for icons which vanish
    # against a light taskbar, and XeFM's is a dark tile with light content, which
    # reads on either theme. Windows falls back to the unplated asset when the light
    # variant is absent.
    for size in _TARGETSIZE_SIZES:
        art = tile(size)
        for unplated in (False, True):
            name = _targetsize_name(size, unplated)
            art.save(out_dir / name, format="PNG")
            print(f"[INFO] Wrote {out_dir / name} ({size}x{size})")
            count += 1

    # Wide tile: the square logo (height-fit) centered on a transparent canvas.
    wide_name, ww, wh = _WIDE_TILE
    canvas = Image.new("RGBA", (ww, wh), (0, 0, 0, 0))
    logo = tile(wh)
    canvas.alpha_composite(logo, ((ww - wh) // 2, 0))
    canvas.save(out_dir / wide_name, format="PNG")
    print(f"[INFO] Wrote {out_dir / wide_name} ({ww}x{wh})")
    count += 1

    print(f"[INFO] Generated {count} Store tile asset(s) into {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

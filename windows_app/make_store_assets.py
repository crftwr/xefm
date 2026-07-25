#!/usr/bin/env python3
"""
Generate the MSIX / Microsoft Store tile assets (PNG) for the XeFM package.

The Store manifest references PNG tiles (not the launcher's ``.ico``). This emits
the minimum useful set from the shared macOS icon ``macos_app/resources/XeFM.icns``
(or a ``--source`` PNG/ICNS), reusing the same rounded-corner masking as
``make_icon.py`` so XeFM's Windows presence (exe icon + Store tiles) stays visually
consistent.

Emitted into ``--out-dir`` (default ``windows_app/resources/Assets``):
    StoreLogo.png                 50x50    <Properties><Logo>
    Square44x44Logo.png           44x44    app-list icon (+ .scale-200 = 88)
    Square150x150Logo.png         150x150  medium tile   (+ .scale-200 = 300)
    Wide310x150Logo.png           310x150  wide tile (square logo centered)

Pillow is required (already a build dependency via make_icon.py). If it is missing
this exits non-zero rather than emitting junk — the Store listing needs real tiles.

Usage:
    python make_store_assets.py [--source <icon.png|.icns>] [--out-dir <dir>]
"""

import argparse
import sys
from pathlib import Path

# Reuse the rounded-corner mask used for the launcher .ico so tiles match it.
from make_icon import _apply_rounded_mask  # noqa: E402

# name -> (width, height); square tiles pass width for both.
_SQUARE_TILES = {
    "StoreLogo.png": 50,
    "Square44x44Logo.png": 44,
    "Square150x150Logo.png": 150,
}
# Which square tiles also get a scale-200 (2x) variant that MSIX auto-selects.
_SCALE_200 = {"Square44x44Logo.png", "Square150x150Logo.png"}

_WIDE_TILE = ("Wide310x150Logo.png", 310, 150)


def _rounded(img, size):
    """size x size RGBA with rounded-corner alpha (shared with make_icon)."""
    return _apply_rounded_mask(img, size)


def _scale_name(name: str, scale: int) -> str:
    """'Square44x44Logo.png' + 200 -> 'Square44x44Logo.scale-200.png'."""
    stem, _, ext = name.rpartition(".")
    return f"{stem}.scale-{scale}.{ext}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate XeFM Store tile assets")
    parser.add_argument("--source", default=None,
                        help="source image (.png/.icns); defaults to macos_app/resources/XeFM.icns")
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

    repo_root = Path(__file__).resolve().parent.parent
    source = (Path(args.source).resolve() if args.source
              else repo_root / "macos_app" / "resources" / "XeFM.icns")
    out_dir = (Path(args.out_dir).resolve() if args.out_dir
               else Path(__file__).resolve().parent / "resources" / "Assets")

    if not source.exists():
        print(f"[ERROR] Source icon not found: {source}")
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    img = Image.open(source).convert("RGBA")

    count = 0
    # Square tiles (+ optional scale-200).
    for name, size in _SQUARE_TILES.items():
        _rounded(img, size).save(out_dir / name, format="PNG")
        print(f"[INFO] Wrote {out_dir / name} ({size}x{size})")
        count += 1
        if name in _SCALE_200:
            big = size * 2
            scaled_name = _scale_name(name, 200)
            _rounded(img, big).save(out_dir / scaled_name, format="PNG")
            print(f"[INFO] Wrote {out_dir / scaled_name} ({big}x{big})")
            count += 1

    # Wide tile: the square logo (height-fit) centered on a transparent canvas.
    wide_name, ww, wh = _WIDE_TILE
    canvas = Image.new("RGBA", (ww, wh), (0, 0, 0, 0))
    logo = _rounded(img, wh)
    canvas.alpha_composite(logo, ((ww - wh) // 2, 0))
    canvas.save(out_dir / wide_name, format="PNG")
    print(f"[INFO] Wrote {out_dir / wide_name} ({ww}x{wh})")
    count += 1

    print(f"[INFO] Generated {count} Store tile asset(s) into {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

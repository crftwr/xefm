#!/usr/bin/env python3
"""
Regenerate XeFM's desktop-app icon assets from the SVG masters in ``tools/icon/``.

Two masters are kept, and the right one is picked per output size:

  ``xefm-icon.svg``        full detail — dual panes, "XeFM" wordmark badge, starfield.
                           Used at 128px and up.
  ``xefm-icon-small.svg``  simplified — thicker rows, "Xe" badge, no starfield.
                           Used at 64px and below, where the detailed art turns to mush.

Outputs (all committed, so neither platform's build needs a rasterizer):

  ``macos_app/resources/XeFM.icns``           macOS bundle icon (all 10 iconset slots)
  ``windows_app/resources/XeFM.ico``          Windows launcher icon (7 sizes, per-size art)
  ``windows_app/resources/XeFM-1024.png``     detailed master for the large MSIX tiles
  ``windows_app/resources/XeFM-small-256.png`` simplified master for the small MSIX tiles

Rasterization uses AppKit's native SVG support (macOS 13+), so this script only runs
on macOS -- which is fine, since the assets it produces are checked in.

Usage:
    python3 tools/make_icons.py            # regenerate everything
    python3 tools/make_icons.py --check    # verify assets are up to date (exit 1 if not)
"""

import argparse
import io
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ICON_DIR = REPO_ROOT / "tools" / "icon"
SVG_DETAILED = ICON_DIR / "xefm-icon.svg"
SVG_SIMPLE = ICON_DIR / "xefm-icon-small.svg"

ICNS_OUT = REPO_ROOT / "macos_app" / "resources" / "XeFM.icns"
ICO_OUT = REPO_ROOT / "windows_app" / "resources" / "XeFM.ico"
# Both masters are committed: the MSIX tile generator runs on Windows, where there is
# no SVG rasterizer, but it still needs to pick detailed-vs-simplified art per tile.
PNG_OUT = REPO_ROOT / "windows_app" / "resources" / "XeFM-1024.png"
PNG_SMALL_OUT = REPO_ROOT / "windows_app" / "resources" / "XeFM-small-256.png"

# At or below this pixel size the simplified master is used instead of the detailed one.
SIMPLE_MAX_PX = 64

# macOS .iconset slot name -> pixel size. iconutil requires every one of these.
ICONSET_SLOTS = {
    "icon_16x16.png": 16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512,
    "icon_512x512@2x.png": 1024,
}

# Sizes embedded in the Windows .ico. 256 is stored as PNG by Pillow, the rest as BMP.
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]

MASTER_PNG_PX = 1024
MASTER_SMALL_PNG_PX = 256


def _master_for(size: int) -> Path:
    """Pick the SVG master appropriate for a given pixel size."""
    return SVG_SIMPLE if size <= SIMPLE_MAX_PX else SVG_DETAILED


def _render_png(svg: Path, size: int) -> bytes:
    """
    Rasterize ``svg`` to a ``size`` x ``size`` PNG and return the encoded bytes.

    Drawn through a CoreGraphics bitmap context tagged sRGB with a premultiplied
    alpha channel, so the artwork's rounded corners stay transparent and the colors
    do not drift into the display's wide-gamut space.
    """
    import AppKit
    import Quartz

    image = AppKit.NSImage.alloc().initWithContentsOfFile_(str(svg))
    if image is None:
        raise RuntimeError(f"AppKit could not load {svg} (needs macOS 13+ for SVG)")
    image.setSize_((size, size))

    color_space = Quartz.CGColorSpaceCreateWithName(Quartz.kCGColorSpaceSRGB)
    ctx = Quartz.CGBitmapContextCreate(
        None, size, size, 8, 0, color_space,
        Quartz.kCGImageAlphaPremultipliedLast | Quartz.kCGBitmapByteOrder32Big,
    )
    if ctx is None:
        raise RuntimeError(f"Could not create a {size}x{size} bitmap context")

    ns_ctx = AppKit.NSGraphicsContext.graphicsContextWithCGContext_flipped_(ctx, False)
    AppKit.NSGraphicsContext.saveGraphicsState()
    try:
        AppKit.NSGraphicsContext.setCurrentContext_(ns_ctx)
        ns_ctx.setImageInterpolation_(AppKit.NSImageInterpolationHigh)
        image.drawInRect_fromRect_operation_fraction_(
            ((0, 0), (size, size)),
            AppKit.NSZeroRect,
            AppKit.NSCompositingOperationSourceOver,
            1.0,
        )
    finally:
        AppKit.NSGraphicsContext.restoreGraphicsState()

    cg_image = Quartz.CGBitmapContextCreateImage(ctx)
    rep = AppKit.NSBitmapImageRep.alloc().initWithCGImage_(cg_image)
    png = rep.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, {})
    if png is None:
        raise RuntimeError(f"PNG encoding failed for {svg} at {size}px")
    return bytes(png)


def _render(size: int) -> bytes:
    """Render the size-appropriate master at ``size`` pixels."""
    return _render_png(_master_for(size), size)


def _build_icns() -> bytes:
    """Render every iconset slot and run ``iconutil`` to produce the .icns bytes."""
    if not shutil.which("iconutil"):
        raise RuntimeError("iconutil not found (Xcode command line tools required)")

    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "XeFM.iconset"
        iconset.mkdir()
        # Slots share pixel sizes (e.g. 32 is both 16x16@2x and 32x32), so render once
        # per distinct size and reuse the bytes.
        rendered: dict[int, bytes] = {}
        for name, size in ICONSET_SLOTS.items():
            if size not in rendered:
                rendered[size] = _render(size)
            (iconset / name).write_bytes(rendered[size])

        out = Path(tmp) / "XeFM.icns"
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(out)],
            check=True, capture_output=True,
        )
        return out.read_bytes()


def _build_ico() -> bytes:
    """Assemble the multi-size .ico, giving each size its own freshly rendered art."""
    from PIL import Image

    frames = [Image.open(io.BytesIO(_render(s))).convert("RGBA") for s in ICO_SIZES]
    # Pillow matches each requested size against append_images by exact dimensions and
    # only falls back to downscaling when none matches -- so every size here is native.
    buf = io.BytesIO()
    frames[-1].save(
        buf, format="ICO",
        sizes=[(s, s) for s in ICO_SIZES],
        append_images=frames[:-1],
    )
    return buf.getvalue()


def _write(path: Path, data: bytes, check: bool) -> bool:
    """
    Write ``data`` to ``path``, or in check mode just compare. Returns True if the
    file on disk already matched.
    """
    current = path.read_bytes() if path.exists() else None
    if current == data:
        print(f"[INFO] Up to date: {path.relative_to(REPO_ROOT)}")
        return True
    if check:
        reason = "missing" if current is None else "out of date"
        print(f"[ERROR] {path.relative_to(REPO_ROOT)} is {reason}")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    print(f"[INFO] Wrote {path.relative_to(REPO_ROOT)} ({len(data):,} bytes)")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Regenerate XeFM desktop icon assets from tools/icon/*.svg")
    parser.add_argument("--check", action="store_true",
                        help="verify the committed assets match the SVG masters")
    args = parser.parse_args()

    if sys.platform != "darwin":
        print("[ERROR] This script needs macOS (AppKit renders the SVG masters). "
              "The generated assets are committed, so only run it when the SVGs change.")
        return 1

    for svg in (SVG_DETAILED, SVG_SIMPLE):
        if not svg.exists():
            print(f"[ERROR] Missing SVG master: {svg}")
            return 1

    ok = True
    ok &= _write(ICNS_OUT, _build_icns(), args.check)
    ok &= _write(ICO_OUT, _build_ico(), args.check)
    ok &= _write(PNG_OUT, _render_png(SVG_DETAILED, MASTER_PNG_PX), args.check)
    ok &= _write(PNG_SMALL_OUT, _render_png(SVG_SIMPLE, MASTER_SMALL_PNG_PX), args.check)

    if not ok:
        print("[ERROR] Icon assets are stale; run: make icons")
        return 1
    print("[INFO] Icon assets " + ("verified" if args.check else "regenerated"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

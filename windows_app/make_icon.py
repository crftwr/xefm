#!/usr/bin/env python3
"""
Generate ``XeFM.ico`` for the Windows launcher's embedded icon resource.

Preference order:
  1. If Pillow is available, convert the macOS icon ``macos_app/resources/XeFM.icns``
     (or a ``--source`` PNG/ICNS) into a proper multi-size ``.ico``.
  2. Otherwise, emit a simple solid-color placeholder ``.ico`` with the pure-Python
     writer below, so ``rc.exe`` always has an icon to embed. Drop a hand-authored
     ``XeFM.ico`` into ``windows_app/resources/`` to override.

Usage:
    python make_icon.py --out <path>\\XeFM.ico [--source <path>\\icon.png|.icns]
"""

import argparse
import struct
import sys
from pathlib import Path

# Sizes to emit when Pillow can render them.
_ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]

# Placeholder colors (R, G, B) - a XeFM-ish teal with a lighter border.
_FILL = (38, 132, 128)
_BORDER = (90, 200, 190)

# Corner-rounding radius as a fraction of the icon size, applied when the source
# has no transparency of its own (macOS .icns files are full-bleed squares that
# the OS masks into a squircle). ~0.225 approximates the macOS Big Sur radius.
_CORNER_RADIUS_FRAC = 0.225


def _apply_rounded_mask(img, size):
    """
    Return a (size x size) RGBA image with rounded-corner transparency.

    Rendered at 4x and downsampled so the rounded edge is smoothly antialiased,
    and the existing alpha is multiplied by the mask (so a source that *does*
    have transparency keeps it).
    """
    from PIL import Image, ImageChops, ImageDraw

    ss = 4
    big = size * ss
    scaled = img.resize((big, big), Image.LANCZOS).convert("RGBA")
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, big - 1, big - 1], radius=round(big * _CORNER_RADIUS_FRAC), fill=255
    )
    scaled = scaled.resize((size, size), Image.LANCZOS)
    mask = mask.resize((size, size), Image.LANCZOS)
    r, g, b, a = scaled.split()
    scaled.putalpha(ImageChops.multiply(a, mask))
    return scaled


def _try_pillow(source: Path, out: Path) -> bool:
    try:
        from PIL import Image  # type: ignore
    except Exception:
        return False

    try:
        img = Image.open(source).convert("RGBA")
        # Master at the largest ICO size, with rounded-corner transparency; the
        # ICO encoder derives every smaller size by resizing this master, so the
        # corners (and the alpha channel) stay proportional across sizes.
        master = _apply_rounded_mask(img, 256)
        sizes = [(s, s) for s in _ICO_SIZES]
        master.save(out, format="ICO", sizes=sizes)
        print(f"[INFO] Wrote {out} from {source} via Pillow "
              f"({len(sizes)} sizes, rounded-corner alpha)")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[WARNING] Pillow conversion of {source} failed: {exc}")
        return False


def _write_placeholder_ico(out: Path, size: int = 32) -> None:
    """Write a minimal valid single-image 32-bit .ico (no external deps)."""
    w = h = size
    # Build BGRA pixel rows, bottom-up (as BMP/ICO stores them).
    rows = []
    for y in range(h):
        row = bytearray()
        for x in range(w):
            edge = x < 2 or x >= w - 2 or y < 2 or y >= h - 2
            r, g, b = _BORDER if edge else _FILL
            row += bytes((b, g, r, 255))  # BGRA, fully opaque
        rows.append(bytes(row))
    xor = b"".join(reversed(rows))  # bottom-up

    # 1-bpp AND mask, all zero (fully opaque), rows padded to 32-bit boundary.
    and_row_bytes = ((w + 31) // 32) * 4
    and_mask = b"\x00" * (and_row_bytes * h)

    # BITMAPINFOHEADER: height is doubled to cover XOR + AND masks.
    bih = struct.pack(
        "<IiiHHIIiiII",
        40,          # biSize
        w,           # biWidth
        h * 2,       # biHeight (XOR + AND)
        1,           # biPlanes
        32,          # biBitCount
        0,           # biCompression (BI_RGB)
        len(xor) + len(and_mask),  # biSizeImage
        0, 0, 0, 0,  # ppm x/y, clrUsed, clrImportant
    )
    image = bih + xor + and_mask

    # ICONDIR + one ICONDIRENTRY.
    width_b = 0 if w == 256 else w
    height_b = 0 if h == 256 else h
    icondir = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack(
        "<BBBBHHII",
        width_b, height_b, 0, 0,
        1, 32,
        len(image),
        6 + 16,  # offset to image (dir + one entry)
    )
    out.write_bytes(icondir + entry + image)
    print(f"[INFO] Wrote placeholder {out} ({w}x{h}). "
          f"Provide a real windows_app/resources/XeFM.ico to override.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate XeFM.ico")
    parser.add_argument("--out", required=True, help="output .ico path")
    parser.add_argument("--source", default=None,
                        help="source image (.png/.icns); defaults to macos_app/resources/XeFM.icns")
    args = parser.parse_args()

    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    # Resolve a default source relative to the repo (this file lives in windows_app/).
    repo_root = Path(__file__).resolve().parent.parent
    source = Path(args.source).resolve() if args.source else (repo_root / "macos_app" / "resources" / "XeFM.icns")

    if source.exists() and _try_pillow(source, out):
        return 0

    if not source.exists():
        print(f"[INFO] No source icon at {source}; emitting placeholder.")
    else:
        print("[INFO] Pillow unavailable or conversion failed; emitting placeholder.")
    _write_placeholder_ico(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

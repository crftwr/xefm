#!/usr/bin/env python3
"""
Build the Earth background scene's textures from NASA's public-domain sources.

The scene (``EARTH_MSL`` in ``xefm/background_shaders.py``) samples three
equirectangular maps, all with u = 0 at 180°W and v = 0 at the north pole:

  ``day.jpg``     4096x2048  sRGB  Blue Marble Next Generation, August 2004 —
                                   the cloud-free surface, ocean included.
  ``clouds.jpg``  4096x2048  linear  Visible Earth "Blue Marble: Clouds" — grey
                                   coverage, read from the red channel.
  ``relief.jpg``  2048x1024  linear  R/G: the surface slope toward east/north
                                   (0.5 = flat), from GEBCO 2008 elevation;
                                   B: the ocean mask (1 = water), from GEBCO 2008
                                   bathymetry. Saved without chroma subsampling,
                                   since the channels are unrelated data.

Every source is NASA Earth Observatory imagery, which NASA releases without
copyright; see ``xefm/assets/earth/SOURCES.md`` for the exact files and credit.
The outputs are committed, so a build never downloads anything — rerun this only
to change a resolution or the processing.

Usage:
    PYTHONPATH=. python3 tools/make_earth_textures.py [--src DIR]

The sources (about 40 MB) are downloaded into ``--src`` (default
``temp/earth_src``) when they are not already there.
"""

import argparse
import math
import sys
import urllib.request
from pathlib import Path

from PIL import Image, ImageFilter

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "xefm" / "assets" / "earth"

_BMNG = "https://assets.science.nasa.gov/content/dam/science/esd/eo/images/bmng"
SOURCES = {
    "day": f"{_BMNG}/bmng-base/august/world.200408.3x5400x2700.jpg",
    "elevation": f"{_BMNG}/topography/gebco_08_rev_elev_5400x2700.jpg",
    "bathymetry": f"{_BMNG}/bathymetry/gebco_08_rev_bath_5400x2700.jpg",
    "clouds": "https://eoimages.gsfc.nasa.gov/images/imagerecords/57000/57747/cloud_combined_8192.tif",
}

DAY_SIZE = (4096, 2048)
CLOUD_SIZE = (4096, 2048)
RELIEF_SIZE = (2048, 1024)

#: Elevation steps (0..255 grey) per texel that map to a full-scale slope. The
#: GEBCO grey spans roughly sea level to the top of the Himalaya, so a texel-to-
#: texel rise of this much is already a steep range; the shader scales the result
#: again (``RELIEF``), so this only has to keep real mountains out of the clamp.
SLOPE_FULL_SCALE = 24.0

#: Bathymetry grey at and above which a texel is land. Land is pure white in the
#: GEBCO bathymetry image; the margin absorbs JPEG ringing along the coasts.
LAND_LEVEL = 248


def fetch(src_dir: Path, key: str) -> Path:
    url = SOURCES[key]
    path = src_dir / url.rsplit("/", 1)[1]
    if not path.exists():
        print(f"downloading {url}")
        src_dir.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url) as response, open(path, "wb") as out:
            out.write(response.read())
    return path


def build_day(src: Path) -> None:
    img = Image.open(src).convert("RGB").resize(DAY_SIZE, Image.LANCZOS)
    img.save(OUT_DIR / "day.jpg", quality=88, optimize=True, progressive=False)


def build_clouds(src: Path) -> None:
    Image.MAX_IMAGE_PIXELS = None          # the 8192x4096 TIFF trips the bomb check
    grey = Image.open(src).convert("L").resize(CLOUD_SIZE, Image.LANCZOS)
    # Stored as RGB rather than greyscale: the OS decoders PuiKit loads textures
    # with hand back 32-bit pixels only, and a one-channel JPEG is refused.
    Image.merge("RGB", (grey, grey, grey)).save(
        OUT_DIR / "clouds.jpg", quality=85, optimize=True)


def build_relief(elevation: Path, bathymetry: Path) -> None:
    w, h = RELIEF_SIZE
    elev = (Image.open(elevation).convert("L").resize(RELIEF_SIZE, Image.LANCZOS)
            .filter(ImageFilter.GaussianBlur(0.8)))
    e = elev.tobytes()
    east = bytearray(w * h)
    north = bytearray(w * h)
    for y in range(h):
        # A texel spans cos(latitude) as much ground east-west as north-south, so
        # the same rise is that much steeper across than along a meridian.
        lat = math.pi * (0.5 - (y + 0.5) / h)
        sx = 1.0 / max(math.cos(lat), 0.05)
        row = y * w
        up = max(y - 1, 0) * w
        down = min(y + 1, h - 1) * w
        for x in range(w):
            left, right = row + (x - 1) % w, row + (x + 1) % w   # u wraps
            dx = (e[right] - e[left]) * 0.5 * sx
            dy = (e[up + x] - e[down + x]) * 0.5               # +y is north
            # The surface normal leans away from the uphill direction.
            east[row + x] = _byte(-dx / SLOPE_FULL_SCALE)
            north[row + x] = _byte(-dy / SLOPE_FULL_SCALE)
    bath = Image.open(bathymetry).convert("L").resize(RELIEF_SIZE, Image.BILINEAR)
    ocean = bath.point(lambda v: 0 if v >= LAND_LEVEL else 255).filter(
        ImageFilter.GaussianBlur(0.6))
    relief = Image.merge("RGB", (Image.frombytes("L", RELIEF_SIZE, bytes(east)),
                                 Image.frombytes("L", RELIEF_SIZE, bytes(north)),
                                 ocean))
    relief.save(OUT_DIR / "relief.jpg", quality=90, subsampling=0, optimize=True)


def _byte(v: float) -> int:
    v = max(-1.0, min(1.0, v))
    return int(round(127.5 + 127.5 * v))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--src", type=Path, default=REPO_ROOT / "temp" / "earth_src")
    args = parser.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    build_day(fetch(args.src, "day"))
    build_clouds(fetch(args.src, "clouds"))
    build_relief(fetch(args.src, "elevation"), fetch(args.src, "bathymetry"))
    for name in ("day.jpg", "clouds.jpg", "relief.jpg"):
        path = OUT_DIR / name
        print(f"{path.relative_to(REPO_ROOT)}  {path.stat().st_size / 1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())

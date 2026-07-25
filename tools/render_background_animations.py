"""Rasterize XeFM's background scenes to PNGs, to check how one actually looks
without launching the app.

The test suite checks invariants, not aesthetics, and XeFM's TUI cannot be launched
non-interactively. Every scene is a fragment shader, and ``MetalBackground`` renders
to an offscreen texture as readily as to a layer — so this compiles the real shader
with the real Metal compiler and writes exactly what the fragment function puts on
screen, with no window involved.

    PYTHONPATH=. python tools/render_background_animations.py
    PYTHONPATH=. python tools/render_background_animations.py --time 12 --out /tmp
    PYTHONPATH=. python tools/render_background_animations.py --kind starfield --size 1600x1000

Only the Metal (macOS) dialect can be rendered here. A scene's HLSL twin is compiled
by the Windows backend and has to be checked there; see the dialect-parity test in
``test/test_background_shaders.py`` for what is caught cross-platform.

Requires PyObjC (already a dependency of puikit's macOS backend); macOS only.
"""

import argparse
import os
import sys

try:
    import Quartz
    from Quartz import CGColorSpaceCreateDeviceRGB
except ImportError:  # pragma: no cover - developer tool, macOS only
    sys.exit("This tool needs PyObjC (macOS only): pip install pyobjc-framework-Quartz")

from puikit.background import Shader
from puikit.backends._metal import MetalBackground

from xefm.background_shaders import SHADER_KINDS

#: Theme colors to render against, so a scene is judged on the palette it ships
#: with rather than an arbitrary one. (foreground, background) per XeFM theme.
THEMES = {
    "sci-fi": ((200, 224, 245), (16, 30, 50)),
    "phosphor": ((51, 245, 121), (4, 15, 7)),
    "dark": ((212, 212, 212), (30, 30, 30)),
}

#: Which theme suits each scene, used when --theme is not given.
SCENE_THEME = {"starfield": "sci-fi", "rain": "phosphor",
               "constellation": "sci-fi", "grid": "sci-fi",
               "wave": "sci-fi"}


def render(kind, width, height, t, *, speed, opacity, theme, path):
    """Draw one frame of ``kind`` to a PNG at ``path``; returns the lit-pixel share.

    The share is a rough density read — how much of the frame the scene actually
    covers. These sit behind a working file manager, so a scene that lights most of
    the window is a scene that will fight the filenames on top of it.
    """
    fg, bg = THEMES[theme]
    renderer = MetalBackground()
    if not renderer.available:
        raise SystemExit("Metal unavailable: cannot render scenes here")
    shader = Shader(speed=speed, opacity=opacity, ink=fg, backdrop=bg,
                    **SHADER_KINDS[kind])
    if not renderer.set_shader(shader):
        raise SystemExit(f"shader {kind!r} failed to compile:\n{renderer.error}")
    bgra = MetalBackground.texture_pixels(renderer.render_to_texture(width, height, t))

    lit = sum(1 for i in range(0, len(bgra), 4)
              if max(abs(bgra[i + 2] - bg[0]), abs(bgra[i + 1] - bg[1]),
                     abs(bgra[i] - bg[2])) > 3)

    provider = Quartz.CGDataProviderCreateWithData(None, bytes(bgra), len(bgra), None)
    image = Quartz.CGImageCreate(
        width, height, 8, 32, width * 4, CGColorSpaceCreateDeviceRGB(),
        Quartz.kCGBitmapByteOrder32Little | Quartz.kCGImageAlphaPremultipliedFirst,
        provider, None, False, Quartz.kCGRenderingIntentDefault)
    url = Quartz.CFURLCreateWithFileSystemPath(None, path, Quartz.kCFURLPOSIXPathStyle, False)
    dest = Quartz.CGImageDestinationCreateWithURL(url, "public.png", 1, None)
    Quartz.CGImageDestinationAddImage(dest, image, None)
    if not Quartz.CGImageDestinationFinalize(dest):
        raise RuntimeError(f"could not write {path}")
    return 100.0 * lit / (width * height)


def _size(text):
    try:
        w, h = text.lower().split("x")
        return int(w), int(h)
    except ValueError:
        raise argparse.ArgumentTypeError("size must look like 1200x800")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--kind", action="append", choices=sorted(SHADER_KINDS),
                        help="scene to render (repeatable; default: all of XeFM's)")
    parser.add_argument("--size", type=_size, default=(900, 600), help="WxH, default 900x600")
    parser.add_argument("--time", type=float, default=6.0, help="scene time in seconds")
    parser.add_argument("--speed", type=float, default=0.6, help="speed multiplier (XeFM default 0.6)")
    parser.add_argument("--opacity", type=float, default=0.6, help="scene opacity (XeFM default 0.6)")
    parser.add_argument("--theme", choices=sorted(THEMES), help="palette (default: per scene)")
    parser.add_argument("--out", default="temp", help="output directory (default: temp/)")
    args = parser.parse_args()

    kinds = args.kind or sorted(SHADER_KINDS)
    width, height = args.size
    os.makedirs(args.out, exist_ok=True)
    for kind in kinds:
        path = os.path.join(args.out, f"bg_{kind}.png")
        theme = args.theme or SCENE_THEME.get(kind, "dark")
        lit = render(kind, width, height, args.time, speed=args.speed,
                     opacity=args.opacity, theme=theme, path=path)
        print(f"{kind:14s} {lit:5.1f}% lit  {theme:9s} -> {path}")


if __name__ == "__main__":
    sys.exit(main())

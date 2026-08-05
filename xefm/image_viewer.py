"""ImageViewer — a modal image viewer with zoom, pan, and sibling navigation.

The fourth full-window modal viewer (after text / file diff / directory diff),
built on the same skeleton: a ``cover`` layer pushed over the file manager, a
header band naming the file, a footer status bar of live key hints, and a help
overlay. Push it with :func:`show_image_viewer`.

Three interactions, all resolved as *geometry* rather than re-encoded pixels:

- **Zoom** — ``1.0`` fits the whole image in the window (letterboxed); each step
  multiplies by :data:`ZOOM_STEP` up to :data:`MAX_ZOOM`. Once zoomed, the image
  is grown past the client area and clipped to it (:meth:`_fill_geometry`), so it
  *fills* the body instead of floating in a letterbox — the standard image-viewer
  behaviour. Dest and source stay proportional, so nothing is distorted.
- **Pan** — the arrow keys (and a mouse drag) move the view center by a fraction
  of the *visible* extent, so a step feels the same however far in you are. The
  center is clamped to what the client area can reach, so panning to an edge
  slides the image flush (never shrinks it) and reversing moves immediately.
- **Prev / next** — the viewer is handed the sibling images from the pane it was
  opened from, so navigation walks the file list the user was already looking
  at, in the order they see it.

Non-local files (S3, SSH, inside an archive) have no filesystem path for the
backend or Pillow to open, so their bytes are materialized to a temp file for
the life of the viewer and cleaned up on close (see :meth:`_resolve`).

Where the picture cannot be drawn at all — a terminal with no inline-image
protocol, or a missing Pillow — the viewer shows a metadata card (format,
dimensions, file size) instead of the Panel's lone alt glyph, so opening an
image still tells you something about it. Zoom and pan are hidden in that mode;
prev/next still work.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any, Sequence

from puikit.backend import Style, TextAttribute
from puikit.event import Event, EventType
from puikit.image import image_size
from puikit.panel import Rect
from puikit.text import elide
from puikit.widgets.base import Widget

from xefm.config import (format_key_for_display, get_keys_for_action,
                        is_action_for_event, keys_label_for_action)
from xefm.dialog_geometry import OPEN_MS_VIEWER, animate_open
from xefm.log_manager import getLogger
from xefm.text_dialog import keys_markdown, show_markdown
from xefm.text_viewer import (_content_bg, _header_bg, draw_status_bar,
                             viewer_layer_hints, viewer_pad)

logger = getLogger("ImageViewer")

#: Extensions the built-in viewer claims. Kept to formats Pillow decodes out of
#: the box (no plugin install) so a file that opens here always renders.
IMAGE_SUFFIXES = frozenset({
    ".png", ".jpg", ".jpeg", ".jpe", ".gif", ".bmp", ".webp", ".tif", ".tiff",
    ".ico", ".ppm", ".pgm", ".pbm", ".pnm", ".tga", ".jfif",
})

#: Each zoom step multiplies (or divides) by this — a geometric ramp, so the
#: perceived change is constant whether you are at 1x or 20x.
ZOOM_STEP = 1.25
#: Zoom bounds. 1.0 is fit-to-window; below it there is nothing more to show.
MIN_ZOOM = 1.0
MAX_ZOOM = 40.0
#: One arrow-key pan step, as a fraction of the *visible* extent (not the whole
#: image), so a keypress covers the same share of the screen at every zoom.
PAN_STEP = 0.2

#: Pan action base names in display order, with the arrow glyph each renders as.
_ARROW_GLYPHS = {"UP": "↑", "DOWN": "↓", "LEFT": "←", "RIGHT": "→"}


def _keys_display(action: str, fallback: str) -> str:
    """Display label for ``action``'s configured key(s), formatted for the UI
    (``DOWN`` -> ↓, ``Shift-UP`` -> Shift-↑), or ``fallback`` when the action
    is absent from KEY_BINDINGS (a config from an older template)."""
    keys, _ = get_keys_for_action(action)
    if not keys:
        return fallback
    return " / ".join(format_key_for_display(k) for k in keys)


def _pan_keys_label() -> str:
    """One compact label for the four pan actions.

    The expected shapes collapse to a single arrow cluster: the default
    (``Shift-↑↓←→``), any rebind keeping one shared modifier on the four
    arrows, and — when the actions are absent from KEY_BINDINGS (an older
    config template) — the hardcoded plain-arrow pan (``↑↓←→``). Any other
    rebind lists each action's own label."""
    bindings = [get_keys_for_action(f"image_scroll_{base.lower()}")[0]
                for base in _ARROW_GLYPHS]
    if not any(bindings):
        return "↑↓←→"
    prefixes = set()
    for keys, base in zip(bindings, _ARROW_GLYPHS):
        if len(keys) == 1 and keys[0].upper().endswith(base):
            prefixes.add(keys[0][:-len(base)])
        else:
            prefixes.add(None)
    if len(prefixes) == 1 and (prefix := next(iter(prefixes))) is not None:
        # "Shift-↑" -> "Shift-" + the full cluster (empty prefix -> "↑↓←→").
        return format_key_for_display(prefix + "UP")[:-1] + "↑↓←→"
    return " ".join(format_key_for_display(k) for keys in bindings for k in keys)


def is_image_file(path: Any) -> bool:
    """Whether ``path``'s extension is one the built-in image viewer handles.
    ``path`` is any object exposing ``suffix`` (``xefm.path.Path`` / ``pathlib``);
    anything else is not an image."""
    try:
        return path.suffix.lower() in IMAGE_SUFFIXES
    except AttributeError:
        return False


def _have_pillow() -> bool:
    """Whether Pillow is importable. It decodes every format the backend cannot
    (and is what the terminal protocols encode through), so without it the
    viewer shows its metadata card rather than a broken picture."""
    try:
        import PIL.Image  # noqa: F401
    except ImportError:
        return False
    return True


def _format_size(count: int) -> str:
    """A file size as a short human string (``1.4 MB``)."""
    size = float(count)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


class ImageViewer(Widget):
    """Full-window modal image viewer. Construct via :func:`show_image_viewer`."""

    focusable = True

    def __init__(self, path, siblings: Sequence | None = None, index: int = 0,
                 on_close=None, on_navigate=None):
        # The sibling list is a snapshot taken at open time, never a live
        # reference to the pane's list: the file monitor mutates that in place on
        # refresh, which would shift the index out from under the viewer.
        self.paths = list(siblings) if siblings else [path]
        try:
            self.index = self.paths.index(path)
        except ValueError:
            self.paths = [path]
            self.index = 0
        if siblings and 0 <= index < len(self.paths) and self.paths[index] == path:
            self.index = index  # trust the caller's index when it agrees
        self.zoom = MIN_ZOOM
        self.cx = self.cy = 0.5  # pan center, normalized image coordinates
        # Called once when the viewer closes. The app uses it to restore the
        # theme's post-effect, which it suspends while a picture is up so the
        # real pixels show instead of a CRT/scanline-filtered version of them.
        self._on_close = on_close
        # Called with the new path each time prev/next (or Home/End) moves to
        # another image. The app uses it to keep the pane's cursor on the file
        # being shown, so closing the viewer leaves the user where they looked.
        self._on_navigate = on_navigate
        self._panel: Any = None
        self._child_z = 90
        # Local filesystem path for the current image (a temp copy for a remote
        # or in-archive file), its pixel size, and its byte size — all resolved
        # lazily by _resolve and dropped when the index moves.
        self._local: str | None = None
        self._temp: str | None = None
        self._size: tuple[int, int] | None = None
        self._bytes: int | None = None
        self._error: str | None = None
        # Body rect (layer-local) captured each draw, so a mouse drag can turn a
        # pixel delta into a pan.
        self._body_rect: tuple[float, float, float, float] | None = None
        self._drag: tuple[float, float] | None = None
        # Client-area geometry captured each draw — (body_w, body_h, base_w,
        # base_h), the first two in base units and the last two the pixel size of
        # a base unit — so pan clamping knows the real client area between frames.
        self._view: tuple[float, float, float, float] | None = None
        self._resolve()

    # --- current image --------------------------------------------------------

    @property
    def path(self):
        """The image currently being shown."""
        return self.paths[self.index]

    def _resolve(self) -> None:
        """Materialize the current image to a local path and read its size.

        The backend's ``draw_image`` and Pillow both take a filesystem path, so a
        non-local file (S3 / SSH / inside an archive) is copied to a temp file
        that lives until the viewer moves on or closes. Any failure is recorded
        in ``_error`` and surfaced on the card rather than raised — a directory
        of images should not become unbrowsable because one of them is corrupt."""
        self._release_temp()
        self._local = self._size = self._bytes = self._error = None
        path = self.path
        try:
            if getattr(path, "is_remote", lambda: False)() or not os.path.exists(str(path)):
                data = path.read_bytes()
                suffix = path.suffix or ".img"
                handle, temp = tempfile.mkstemp(prefix="xefm_img_", suffix=suffix)
                with os.fdopen(handle, "wb") as out:
                    out.write(data)
                self._temp = self._local = temp
                self._bytes = len(data)
            else:
                self._local = str(path)
                self._bytes = os.path.getsize(self._local)
        except Exception as e:
            self._error = f"Cannot read: {e}"
            logger.error(f"Cannot read image {path}: {e}")
            return
        # The header parse covers PNG/GIF/BMP/JPEG without decoding; Pillow fills
        # in the rest (WebP, TIFF, ICO...) when it is installed.
        self._size = image_size(self._local)
        if self._size is None and _have_pillow():
            try:
                from PIL import Image

                with Image.open(self._local) as image:
                    self._size = image.size
            except Exception as e:
                self._error = f"Cannot decode: {e}"
                logger.error(f"Cannot decode image {path}: {e}")

    def _release_temp(self) -> None:
        """Delete the temp copy of a remote / in-archive image, if there is one."""
        if self._temp is None:
            return
        try:
            os.unlink(self._temp)
        except OSError as e:
            logger.error(f"Could not remove temp image {self._temp}: {e}")
        self._temp = None

    # --- navigation / zoom / pan ---------------------------------------------

    def _step_image(self, delta: int) -> None:
        """Move ``delta`` images through the sibling list, wrapping at both ends.
        Zoom and pan reset, since a fresh image has its own extent and carrying a
        20x crop across would open the next file on an arbitrary corner."""
        if len(self.paths) < 2:
            return
        self.index = (self.index + delta) % len(self.paths)
        self.zoom = MIN_ZOOM
        self.cx = self.cy = 0.5
        self._resolve()
        if self._on_navigate is not None:
            self._on_navigate(self.path)

    def _zoom_by(self, factor: float) -> None:
        """Multiply the zoom by ``factor``, clamped to the allowed range, then
        re-clamp the pan center — zooming out shrinks the reachable range, so a
        center parked near an edge has to come back in. At the fit level
        ``_clamp_center`` pins it to the middle (there is nowhere to pan)."""
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, self.zoom * factor))
        self._clamp_center()

    def _pan_by(self, dx: float, dy: float) -> None:
        """Move the pan center by ``(dx, dy)`` in fractions of the *visible*
        extent. Dividing by the zoom is what makes one keypress cover the same
        share of the screen at 2x and at 20x."""
        self.cx += dx / self.zoom
        self.cy += dy / self.zoom
        self._clamp_center()

    def _pixel_dims(self, body_w: float, body_h: float,
                    base_w: float, base_h: float):
        """The client area and the displayed image, both in *device pixels*, as
        ``(bw, bh, dw, dh)`` — or ``None`` when the image size is unknown.

        Working in device pixels (base units × the pixel size of a base unit)
        keeps the aspect ratio correct where a base unit is not square — GUI
        cells are taller than wide. ``bw``/``bh`` is the client area; ``dw``/``dh``
        is the image scaled by *fit-scale × zoom*, where fit-scale is the largest
        that shows the whole image. So at zoom 1 the image just fits the body and
        at zoom 2 it is twice that — big enough to overflow and fill the body."""
        if self._size is None:
            return None
        iw, ih = self._size
        bw, bh = body_w * base_w, body_h * base_h
        if bw <= 0 or bh <= 0 or iw <= 0 or ih <= 0:
            return None
        scale = min(bw / iw, bh / ih) * self.zoom
        return bw, bh, iw * scale, ih * scale

    def _clamp_center(self) -> None:
        """Clamp the pan center to the range it can actually *reach*.

        A dimension the displayed image does not overflow (``dw <= bw``) cannot
        pan — it is centered, so the center pins to ``0.5``. A dimension it does
        overflow pans within ``[k, 1 - k]``, where ``k`` is half the visible
        fraction of the image on that axis. Clamping to the *reachable* range
        (not the full ``0..1``) is what stops the center accumulating off the
        edge: otherwise panning past a border keeps incrementing an unreachable
        value, and reversing direction moves nothing until it winds back in.

        Uses the client-area geometry cached at the last draw; before any draw it
        falls back to a plain ``0..1`` clamp."""
        if self.zoom <= MIN_ZOOM:
            self.cx = self.cy = 0.5  # fit: the whole image shows, nothing to pan
            return
        dims = self._pixel_dims(*self._view) if self._view is not None else None
        if dims is None:
            self.cx = min(1.0, max(0.0, self.cx))
            self.cy = min(1.0, max(0.0, self.cy))
            return
        bw, bh, dw, dh = dims
        self.cx = 0.5 if dw <= bw else min(1 - bw / (2 * dw), max(bw / (2 * dw), self.cx))
        self.cy = 0.5 if dh <= bh else min(1 - bh / (2 * dh), max(bh / (2 * dh), self.cy))

    def _fill_geometry(self, body_w: float, body_h: float,
                       base_w: float, base_h: float):
        """The destination rect and source crop for the *scaled-image-clipped-to-
        the-client-area* view, or ``None`` when the size is unknown.

        Returns ``((dx, dy, dw, dh), src)``: the dest offset+size in base units
        (relative to the body origin) and the normalized ``src`` crop. As the
        zoom grows the image overflows the body and the visible rect expands to
        cover it, so a zoomed image fills the whole client area instead of
        floating in a letterbox. Dest and source stay proportional (the image is
        uniformly scaled), so ``fit="fill"`` draws them without distortion."""
        dims = self._pixel_dims(body_w, body_h, base_w, base_h)
        if dims is None:
            return None
        bw, bh, dw, dh = dims
        # Top-left of the displayed image within the body (device px): centered
        # while it fits an axis, else panned and clamped so it always covers it.
        ox = (bw - dw) / 2 if dw <= bw else min(0.0, max(bw - dw, bw / 2 - self.cx * dw))
        oy = (bh - dh) / 2 if dh <= bh else min(0.0, max(bh - dh, bh / 2 - self.cy * dh))
        # Visible intersection of the displayed image with the body.
        vx0, vy0 = max(0.0, ox), max(0.0, oy)
        vx1, vy1 = min(bw, ox + dw), min(bh, oy + dh)
        dest = (vx0 / base_w, vy0 / base_h,
                (vx1 - vx0) / base_w, (vy1 - vy0) / base_h)
        src = ((vx0 - ox) / dw, (vy0 - oy) / dh,
               (vx1 - vx0) / dw, (vy1 - vy0) / dh)
        return dest, src

    def _can_render(self, ctx) -> bool:
        """Whether a real picture can be drawn: the backend must support images
        and the size must be known. Otherwise the metadata card stands in."""
        return ctx.images and self._size is not None and self._error is None

    # --- drawing --------------------------------------------------------------

    def draw(self, ctx) -> None:
        self._panel = ctx.panel
        theme = ctx.theme
        wu, hu = ctx.size_units
        pad_x, pad_y = viewer_pad(ctx)
        bg = _content_bg(theme)
        # Like the other viewers: over an animated background the page fill is
        # dropped so the scene reads at full strength.
        if not ctx.wallpaper:
            ctx.fill_rect(0, 0, wu, hu, Style(bg=bg))

        text_fg = theme.text if theme is not None else (212, 212, 212)
        muted = theme.muted_text if theme is not None else (150, 150, 150)
        accent = theme.accent if theme is not None else (0, 122, 204)

        # Header — file name left, position / dimensions / zoom right.
        head_h = 1.0 + pad_y
        header_bg = _header_bg(theme)
        ctx.fill_rect(0, 0, wu, head_h, Style(bg=header_bg))
        iw = max(1.0, wu - 2 * pad_x)
        header = f" {self.path.name}"
        if len(self.paths) > 1:
            header += f"  ({self.index + 1}/{len(self.paths)})"
        ctx.draw_text(pad_x, pad_y,
                      elide(header, iw, where="end", measure=ctx.measure_text),
                      Style(fg=accent, bg=header_bg, attr=TextAttribute.BOLD))
        info = f"{self._dimensions_label()} "
        if self._can_render(ctx) and self.zoom > MIN_ZOOM:
            info = f"{self.zoom:.1f}x  " + info
        ctx.draw_text(max(pad_x, wu - pad_x - len(info)), pad_y, info,
                      Style(fg=muted, bg=header_bg))

        # Body — the picture, or the metadata card where it cannot be drawn.
        fy = hu - 1.0 - pad_y
        body_h = max(1.0, fy - head_h)
        self._body_rect = (pad_x, head_h, iw, body_h)
        # The *physical* pixel size of a base unit, not base_size: on a character
        # grid base_size is (1, 1) but a cell is taller than wide, and the image
        # fit is aspect-sensitive — a square-cell assumption crops to the wrong
        # aspect and the terminal letterboxes the picture. On GUI the two agree.
        base_w, base_h = ctx.base_pixel_size
        self._view = (iw, body_h, base_w, base_h)  # for pan clamping between frames
        if self._can_render(ctx):
            self._draw_image(ctx, pad_x, head_h, iw, body_h, base_w, base_h)
        else:
            self._draw_card(ctx, pad_x, head_h, iw, body_h, text_fg, muted, bg)

        draw_status_bar(ctx, fy, self._hint(ctx), pad_x=pad_x, bottom_pad=pad_y)

    def _draw_image(self, ctx, x: float, y: float, body_w: float, body_h: float,
                    base_w: float, base_h: float) -> None:
        """Draw the picture into the body at ``(x, y)``.

        The *scaled-image-clipped-to-the-client-area* geometry (``_fill_geometry``)
        drives every zoom level, including the fit level. At fit it returns a
        **centered** destination box holding the whole image (``src=(0,0,1,1)``),
        so the letterbox splits evenly — a plain ``fit="contain"`` would let a
        terminal place the letterboxed picture at the top-left of its cell box,
        leaving all the empty space at the bottom. Zoomed in, the box grows to
        cover the client area so the image fills it. Dest and source stay
        proportional, so ``fit="fill"`` draws them undistorted."""
        geom = self._fill_geometry(body_w, body_h, base_w, base_h)
        if geom is None:  # size unknown — let the backend contain the whole image
            ctx.draw_image(x, y, self._local,
                           hints={"w": body_w, "h": body_h, "fit": "contain",
                                  "src": None, "alt": "🖼"})
            return
        (dx, dy, dw, dh), src = geom
        ctx.draw_image(x + dx, y + dy, self._local,
                       hints={"w": dw, "h": dh, "fit": "fill", "src": src,
                              "alt": "🖼"})

    def _dimensions_label(self) -> str:
        """The right-hand header tag: pixel dimensions and file size, as far as
        each is known."""
        parts = []
        if self._size is not None:
            parts.append(f"{self._size[0]}x{self._size[1]}")
        if self._bytes is not None:
            parts.append(_format_size(self._bytes))
        return "  ".join(parts)

    def _draw_card(self, ctx, x: float, y: float, w: float, h: float,
                   text_fg, muted, bg) -> None:
        """The fallback shown when the picture cannot be drawn: the file's format,
        dimensions and size, centered, with the reason underneath. Better than the
        Panel's lone alt glyph — opening an image still tells you what it is."""
        suffix = (self.path.suffix or "").lstrip(".").upper()
        rows = [(f"[ {suffix} ]" if suffix else "[ IMAGE ]", text_fg)]
        label = self._dimensions_label()
        if label:
            rows.append((label, text_fg))
        if self._error is not None:
            rows.append((self._error, muted))
        elif not _have_pillow():
            rows.append(("Install pillow to view images", muted))
        else:
            rows.append(("This terminal cannot display images", muted))
            rows.append(("Try kitty, iTerm2, WezTerm or a sixel terminal", muted))
        top = y + max(0.0, (h - len(rows)) / 2.0)
        for offset, (line, color) in enumerate(rows):
            text = elide(line, w, where="end", measure=ctx.measure_text)
            width = ctx.measure_text(text)
            ctx.draw_text(x + max(0.0, (w - width) / 2.0), top + offset, text,
                          Style(fg=color, bg=bg))

    def _hint(self, ctx) -> str:
        """The footer key hints — only for what is actually available: zoom and
        pan are omitted where no picture can be drawn, prev/next where the file
        has no siblings."""
        quit_k = keys_label_for_action("quit", "q")
        help_k = keys_label_for_action("help", "?")
        parts = []
        if self._can_render(ctx):
            parts.append("+/- zoom")
            if self.zoom > MIN_ZOOM:
                parts.append(f"{_pan_keys_label()} pan")
                parts.append(f"{_keys_display('image_zoom_reset', '0')} fit")
        if len(self.paths) > 1:
            parts.append(f"{_keys_display('image_prev', 'p')}"
                         f"/{_keys_display('image_next', 'n')} prev·next")
        parts.append(f"{help_k} help")
        parts.append(f"{quit_k}/Esc close")
        return " " + " · ".join(parts) + " "

    # --- events ---------------------------------------------------------------

    def handle_event(self, event: Event) -> bool:
        if event.type is EventType.MOUSE_SCROLL:
            # Scroll zooms about the center, the convention every image viewer
            # uses; panning is the drag gesture below.
            uy = event.hints.get("scroll_units")
            delta = float(uy) if uy is not None else float(event.scroll)
            if delta:
                self._zoom_by(ZOOM_STEP ** delta)
            return True
        if event.type in (EventType.MOUSE_DOWN, EventType.MOUSE_DRAG, EventType.MOUSE_UP):
            self._drag_mouse(event)
            return True
        if event.type is not EventType.KEY:
            return True  # modal: swallow other non-key events
        key = event.key
        if key == "escape" or is_action_for_event(event, "quit"):
            self._close()
            return True
        if is_action_for_event(event, "help"):
            self._show_help()
            return True
        if self._pressed(event, "image_zoom_in", ("+", "=")):
            self._zoom_by(ZOOM_STEP)
        elif self._pressed(event, "image_zoom_out", ("-", "_")):
            self._zoom_by(1.0 / ZOOM_STEP)
        elif self._pressed(event, "image_zoom_reset", ("0",)):
            self.zoom = MIN_ZOOM
            self.cx = self.cy = 0.5
        elif self._pressed(event, "image_next", ("n",)):
            self._step_image(1)
        elif self._pressed(event, "image_prev", ("p",)):
            self._step_image(-1)
        elif self._pressed_key(event, "image_scroll_left", "left"):
            self._pan_by(-PAN_STEP, 0.0)
        elif self._pressed_key(event, "image_scroll_right", "right"):
            self._pan_by(PAN_STEP, 0.0)
        elif self._pressed_key(event, "image_scroll_up", "up"):
            self._pan_by(0.0, -PAN_STEP)
        elif self._pressed_key(event, "image_scroll_down", "down"):
            self._pan_by(0.0, PAN_STEP)
        elif key == "home":
            self._step_image(-self.index)
        elif key == "end":
            self._step_image(len(self.paths) - 1 - self.index)
        return True

    def _pressed(self, event: Event, action: str, fallback: tuple[str, ...]) -> bool:
        """Whether ``event`` triggers ``action``, matched by name so a binding
        shared with the file manager still resolves correctly here. Falls back to
        the literal characters when the action is absent from KEY_BINDINGS —
        which is what a config merged from a template older than this viewer
        looks like, and mirrors TextViewer._wrap_pressed."""
        if is_action_for_event(event, action):
            return True
        # get_keys_for_action returns (keys, selection_requirement) -- index the
        # key list, or the non-empty tuple would always read as "bound".
        return not get_keys_for_action(action)[0] and event.char in fallback

    def _pressed_key(self, event: Event, action: str, fallback_key: str) -> bool:
        """``_pressed`` for named (non-printable) keys: falls back to the bare
        unmodified ``fallback_key`` when the action is absent from KEY_BINDINGS.
        The fallbacks are the plain arrows that used to pan here hardcoded, so a
        config from a template older than the pan actions keeps its keys."""
        if is_action_for_event(event, action):
            return True
        return (not get_keys_for_action(action)[0]
                and event.key == fallback_key and not event.modifiers)

    def _drag_mouse(self, event: Event) -> None:
        """Drag to pan: a press anchors, each drag step converts the pointer
        delta into a pan proportional to the body rect, so the image tracks the
        pointer. Only meaningful while zoomed in — at fit there is nowhere to go."""
        if event.type is EventType.MOUSE_UP:
            self._drag = None
            return
        position = (float(event.x), float(event.y))
        if event.type is EventType.MOUSE_DOWN:
            self._drag = position
            return
        if self._drag is None or self._body_rect is None or self.zoom <= MIN_ZOOM:
            return
        _, _, body_w, body_h = self._body_rect
        dx, dy = position[0] - self._drag[0], position[1] - self._drag[1]
        self._drag = position
        # Dragging right moves the image right, i.e. the window left — hence the
        # negated delta.
        if body_w > 0 and body_h > 0:
            self._pan_by(-dx / body_w, -dy / body_h)

    # --- chrome ---------------------------------------------------------------

    def _close(self) -> None:
        panel = self._panel
        self._release_temp()
        if panel is not None and panel.has_layers and panel._layers[-1].widget is self:
            panel.pop_layer()
            # Only after we actually popped: the callback restores the theme's
            # post-effect the app suspended while the picture was up. Guarded so a
            # stray close on a viewer that is not the top layer cannot fire it.
            if self._on_close is not None:
                self._on_close()

    def _show_help(self) -> None:
        if self._panel is None:
            return
        rows = [
            (_keys_display("image_zoom_in", "+"), "zoom in"),
            (_keys_display("image_zoom_out", "-"), "zoom out"),
            (_keys_display("image_zoom_reset", "0"), "fit to window"),
            (_pan_keys_label(), "pan (while zoomed in)"),
            ("drag", "pan with the mouse"),
            ("scroll", "zoom in / out"),
        ]
        if len(self.paths) > 1:
            rows += [
                (_keys_display("image_next", "n"), "next image"),
                (_keys_display("image_prev", "p"), "previous image"),
                ("Home / End", "first / last image"),
            ]
        rows += [
            (keys_label_for_action("help", "?"), "this help"),
            (keys_label_for_action("quit", "q") + " / Esc", "close"),
        ]
        show_markdown(self._panel, keys_markdown(rows),
                      title="Image Viewer — Keys", z=self._child_z)


def show_image_viewer(panel: Any, path, siblings: Sequence | None = None,
                      index: int = 0, z: int = 80, on_close=None,
                      on_navigate=None) -> ImageViewer:
    """Push a full-window modal :class:`ImageViewer` over ``panel``.

    ``siblings`` is the image files from the pane the viewer was opened from, in
    the order the user sees them, so prev/next walks that list; ``index`` is
    ``path``'s position in it. Omit both to view a single image with navigation
    disabled. ``on_close`` runs once when the viewer closes (the app restores the
    post-effect it suspended for a faithful picture); ``on_navigate(path)`` runs
    each time prev/next or Home/End moves to another image (the app keeps the
    pane's cursor on the shown file). Like the other viewers, ``reflow``
    re-derives the layer rect from the live window size each render, so it
    follows resizes."""
    viewer = ImageViewer(path, siblings=siblings, index=index, on_close=on_close,
                         on_navigate=on_navigate)
    sw, sh = panel.backend.size_units
    viewer._panel = panel
    viewer._child_z = z + 10  # help overlay stacks above the viewer's own layer
    panel.push_layer(viewer, z=z, hints=viewer_layer_hints(sw, sh),
                     reflow=lambda sw, sh: Rect(0, 0, sw, sh))
    animate_open(panel, viewer, OPEN_MS_VIEWER)
    return viewer

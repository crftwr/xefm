"""Quick view — the inactive pane as a live preview of the cursor item (#569).

Toggled from the file list, a :class:`QuickView` takes the inactive pane's
place and follows the active pane's cursor: the start of a text file,
highlighted; a picture; a hex dump of a binary; a directory's item count and
total size. It is built from the pieces the viewers already have —
:func:`xefm.text_encoding.decode_text`, the text viewer's highlighter and
palette, the image decoders, :class:`xefm.disk_usage.UsageScan` — rather than
by embedding a whole modal viewer, which owns the keyboard and the window.

Latency is the design constraint. Moving the cursor down a listing must not
read every file it passes, and on an ``s3://`` bucket must not download them:

- a load starts :data:`DEBOUNCE_S` after the cursor *stops*;
- it runs on a worker, and a result for an item the cursor has since left is
  dropped (``_gen``);
- a remote file is read only when it is small (:data:`REMOTE_CAP`), and a
  remote directory is not walked.

The keyboard stays on the file list; the preview scrolls with the wheel.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Optional

from puikit.backend import Style, TextAttribute
from puikit.event import EventType
from puikit.text import display_width, elide
from puikit.widgets.base import Widget

from xefm import image_decoders
from xefm.disk_usage import UsageScan
from xefm.log_manager import getLogger
from xefm.str_format import format_size, format_timestamp
from xefm.text_encoding import decode_text, looks_binary_bytes
from xefm.text_viewer import MONO, _expand_tabs, _highlight, _syntax_palette

logger = getLogger("QuickView")

#: How long the cursor must rest on an item before it is loaded.
DEBOUNCE_S = 0.15
#: How much of a local text file is read.
TEXT_CAP = 256 * 1024
#: The largest remote file read at all; larger ones show their details only.
REMOTE_CAP = 256 * 1024
#: How much of a binary file the hex dump shows.
HEX_BYTES = 512
#: The largest picture decoded here (a format the backend cannot read itself).
IMAGE_DECODE_CAP = 64 * 1024 * 1024
#: How often a running directory walk repaints its totals.
_SCAN_REPAINT_S = 0.2


def is_remote(path) -> bool:
    """A location reading which costs round trips: anything with a scheme —
    ``ssh://``, ``s3://``, an archive member."""
    return "://" in str(path)


def hex_lines(data: bytes) -> list[str]:
    """``data`` as ``offset  hex bytes  ascii`` rows, 16 bytes a row."""
    rows = []
    for off in range(0, len(data), 16):
        chunk = data[off:off + 16]
        hexes = " ".join(f"{b:02x}" for b in chunk)
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        rows.append(f"{off:08x}  {hexes:<47}  {text}")
    return rows


class QuickView(Widget):
    """The preview. :meth:`follow` is told the cursor item on every event;
    everything else happens on its own tick and worker."""

    focusable = False

    def __init__(self, panel: Any):
        self.panel = panel
        self.entry = None
        self.info: dict = {}
        #: What is shown: "empty", "pending", "text", "hex", "image", "dir",
        #: "details" (not read), or "error".
        self.kind = "empty"
        self.lines: list = []          # highlighted rows: [(text, fg), ...]
        self.note = ""                 # one line under the header
        self.image = None              # a path or a RasterImage
        self.scroll = 0
        self._scan: Optional[UsageScan] = None
        self._gen = 0
        self._due = 0.0
        self._ticking = False
        # Finished loads, (gen, kind, lines, note, image) by generation. Each
        # worker stores its own key - one dict operation, safe with no GIL - so
        # a slow load for an older entry never overwrites the current result.
        self._results: dict = {}
        self._last_scan_render = 0.0
        #: The generation whose load has started, so a tick starts it once.
        self._load_started = -1
        self._scan_reported = False
        self._view_h = 1

    # --- following the cursor (UI thread) -------------------------------------

    def follow(self, entry, info: Optional[dict]) -> None:
        """The cursor is on ``entry`` now (``info`` its pane's display record).
        Nothing is read yet: the load waits for the cursor to rest."""
        if entry is not None and self.entry is not None \
                and str(entry) == str(self.entry):
            return
        self._stop_scan()
        self._gen += 1
        self.entry = entry
        self.info = dict(info or {})
        self.lines, self.note, self.image, self.scroll = [], "", None, 0
        self.kind = "empty" if entry is None else "pending"
        self._due = time.monotonic() + DEBOUNCE_S
        self._ensure_ticking()

    def close(self) -> None:
        """Stop anything still running; called when quick view is turned off."""
        self._gen += 1
        self._stop_scan()

    def _stop_scan(self) -> None:
        if self._scan is not None:
            self._scan.cancel()
            self._scan = None

    def _ensure_ticking(self) -> None:
        if not self._ticking and self.panel.request_animation_ticks(self._tick):
            self._ticking = True

    def _tick(self) -> bool:
        if self.kind == "pending" and self._gen not in self._results \
                and time.monotonic() >= self._due and self._load_started != self._gen:
            self._start_load()
        for stale in [g for g in list(self._results) if g != self._gen]:
            self._results.pop(stale, None)
        result = self._results.pop(self._gen, None)
        if result is not None:
            _gen, self.kind, self.lines, self.note, self.image = result
            self.panel.render()
        # The finished scan stays on self._scan: its totals are what the pane
        # goes on showing. Only a running one keeps the tick alive.
        scanning = self._scan is not None and not self._scan_reported
        if scanning:
            now = time.monotonic()
            if self._scan.done or now - self._last_scan_render >= _SCAN_REPAINT_S:
                self._last_scan_render = now
                self.panel.render()
            if self._scan.done:
                self._scan_reported = True
                scanning = False
        busy = self.kind == "pending" or scanning
        self._ticking = busy
        return busy

    def _start_load(self) -> None:
        entry, info, gen = self.entry, self.info, self._gen
        self._load_started = gen
        if info.get("is_dir"):
            if is_remote(entry):
                self.kind = "details"
                self.note = "Remote folder — not walked"
                self.panel.render()
                return
            self._scan = UsageScan([entry])
            self._scan_reported = False
            self._scan.start()
            self.kind = "dir"
            self.panel.render()
            return
        palette = _syntax_palette(self.panel)
        draws_images = self._draws_images()

        def worker() -> None:
            try:
                out = self._load_file(entry, info, palette, draws_images)
            except Exception as e:  # noqa: BLE001 — a preview never takes the app down
                logger.error(f"Quick view could not read {entry}: {e}")
                out = ("error", [], f"Cannot read: {e}", None)
            self._results[gen] = (gen,) + out

        threading.Thread(target=worker, name="xefm-quickview", daemon=True).start()

    def _draws_images(self) -> bool:
        return bool(getattr(self.panel, "images", False))

    @staticmethod
    def _size_of(entry, info) -> Optional[int]:
        try:
            return entry.stat().st_size
        except Exception:  # noqa: BLE001
            return None

    def _load_file(self, entry, info, palette, draws_images):
        """Worker: what to show for a file. Returns ``(kind, lines, note,
        image)``."""
        remote = is_remote(entry)
        size = self._size_of(entry, info)
        suffix = image_decoders.normalize(getattr(entry, "suffix", ""))
        if suffix in image_decoders.claimed_suffixes():
            if not draws_images:
                return ("details", [], "Picture — this window cannot draw it", None)
            if not remote and image_decoders.is_native(suffix):
                return ("image", [], "", str(entry))
            if image_decoders.decoder_for(suffix) is not None and \
                    (size or 0) <= (REMOTE_CAP if remote else IMAGE_DECODE_CAP):
                raster = image_decoders.decode(suffix, entry.read_bytes())
                if raster is not None:
                    return ("image", [], "", raster)
            return ("details", [], "Picture — open it with the viewer", None)
        if remote and (size is None or size > REMOTE_CAP):
            return ("details", [], "Remote file — not read (larger than "
                    f"{format_size(REMOTE_CAP, compact=True)})", None)
        with entry.open("rb") as f:
            data = f.read(TEXT_CAP + 1)
        truncated = len(data) > TEXT_CAP
        data = data[:TEXT_CAP]
        if looks_binary_bytes(data):
            rows = hex_lines(data[:HEX_BYTES])
            note = f"Binary — first {min(len(data), HEX_BYTES)} bytes"
            return ("hex", [[(r, None)] for r in rows], note, None)
        text, encoding = decode_text(data)
        lines = [_expand_tabs(line) for line in text.splitlines()]
        if truncated and lines:
            lines = lines[:-1]  # the last line was cut mid-way
        note = f"First {format_size(TEXT_CAP, compact=True)}" if truncated else ""
        return ("text", _highlight(lines, entry, palette), note, None)

    # --- drawing --------------------------------------------------------------

    def draw(self, ctx) -> None:
        theme = ctx.theme
        w, h = ctx.size_units
        pad = 1.0 if not ctx.vector_shapes else 0.6
        avail = max(0.0, w - 2 * pad)
        self._view_h = max(1, int(h) - 2)
        if self.entry is None:
            ctx.draw_text(pad, 0, "Quick View", Style(fg=theme.muted_text))
            return
        name = self.entry.name or str(self.entry)
        ctx.draw_text(pad, 0, elide(name, avail, where="middle",
                                    measure=ctx.measure_text),
                      Style(fg=theme.accent, attr=TextAttribute.BOLD))
        ctx.draw_text(pad, 1, elide(self._details(), avail, where="end",
                                    measure=ctx.measure_text),
                      Style(fg=theme.muted_text))
        body_y = 2.0
        if self.kind == "pending":
            return
        if self.kind == "dir":
            self._draw_dir(ctx, pad, body_y)
            return
        if self.kind == "image" and self.image is not None:
            ctx.draw_image(pad, body_y, self.image,
                           hints={"w": avail, "h": max(1.0, h - body_y),
                                  "fit": "contain", "alt": "🖼"})
            return
        y = body_y
        if self.note:
            ctx.draw_text(pad, y, self.note, Style(fg=theme.muted_text))
            y += 1.0
        rows = self.lines[self.scroll:]
        cells = int(avail)
        for row in rows:
            if y >= h:
                break
            x = 0
            for text, fg in row:
                if x >= cells:
                    break
                shown = text
                if x + display_width(shown) > cells:
                    shown = shown[:max(0, cells - x)]
                ctx.draw_text(pad + x, y, shown,
                              Style(fg=fg if fg is not None else theme.text,
                                    font=MONO),
                              ink=fg is None)
                x += display_width(shown)
            y += 1.0

    def _details(self) -> str:
        parts = []
        if self.info.get("is_dir"):
            parts.append("Folder")
        elif self.info.get("size_str"):
            parts.append(self.info["size_str"].strip())
        if self.info.get("date_str"):
            parts.append(self.info["date_str"].strip())
        return "  ·  ".join(p for p in parts if p)

    def _draw_dir(self, ctx, x: float, y: float) -> None:
        theme = ctx.theme
        scan = self._scan
        if scan is None and self.note:
            ctx.draw_text(x, y, self.note, Style(fg=theme.muted_text))
            return
        if scan is None:
            return
        size, files, folders, _errors = scan.grand_totals()
        state = "Done" if scan.done else "Counting…"
        for i, line in enumerate((f"{files:,} files, {folders:,} folders",
                                  f"{format_size(size)}", state)):
            ctx.draw_text(x, y + i, line,
                          Style(fg=theme.text if i < 2 else theme.muted_text))

    # --- events ---------------------------------------------------------------

    def handle_event(self, event) -> bool:
        if event.type is EventType.MOUSE_SCROLL:
            amount = event.hints.get("scroll_units")
            if amount is None:
                amount = float(event.scroll)
            limit = max(0, len(self.lines) - 1)
            self.scroll = max(0, min(limit, self.scroll - int(round(amount))))
            return True
        return False

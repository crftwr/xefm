"""Built-in image viewer: zoom, pan, and prev/next navigation.

The modal image viewer resolves zoom and pan as *geometry* — a destination rect
plus a source crop (the ``src`` hint) computed per frame — rather than by
re-encoding pixels, so these tests assert on the hints that reach the backend. At
fit it sends ``contain`` + no crop; zoomed, it grows the image past the client
area and clips to it (``fit="fill"``) so the picture fills the body. Where no
picture can be drawn (a terminal with no inline-image protocol) the viewer falls
back to a metadata card, checked against the TUI profile. See
doc/dev/IMAGE_VIEWER_IMPLEMENTATION.md.

Run with: python -m pytest test/test_image_viewer.py -v
"""

import os
import struct
import sys
import zlib

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from puikit import Event, EventType, Panel, PROFILE_GUI_DESKTOP, PROFILE_TUI
from puikit.backends.memory_backend import MemoryBackend
from puikit.widgets.base import Widget

from xefm._config import Config as DefaultConfig
from xefm.config import config_manager
from xefm.image_viewer import (IMAGE_SUFFIXES, MAX_ZOOM, MIN_ZOOM, PAN_STEP,
                              ZOOM_STEP, ImageViewer, is_image_file,
                              show_image_viewer)
from xefm.path import Path

# Imported at module scope, not inside a test: both the repo root and test/ are
# packages, so once pytest prepends the repo's *parent* to sys.path a later
# ``import xefm`` would resolve to the repo directory (its __init__.py) instead of
# the xefm/app.py app entry. Binding it here, right after the inserts above, gets the
# entry point -- the same thing test_xefm_app_open_viewer.py relies on.
from xefm import app as xefm_app  # noqa: E402


def _png(path, w, h):
    """Write a minimal valid RGB PNG of the given pixel size."""
    raw = bytearray()
    for _ in range(h):
        raw.append(0)  # filter type 0
        raw += bytes((120, 120, 120) * w)

    def chunk(tag, data):
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw))) + chunk(b"IEND", b"")
    )
    return path


def _key(key=None, char=None, mods=()):
    """A KEY event shaped the way a real backend delivers it.

    PuiKit's keyboard contract (puikit/docs/keyboard_contract.md §3) says a
    letter press carries ``key`` = the lowercase letter *as well as* the typed
    glyph in ``char``; punctuation and digits carry ``key`` = ``char`` = the
    produced glyph. XeFM's keymap follows that split — letters are matched on
    ``key``, punctuation on ``char`` — so a char-only "n" is an event no backend
    ever sends and no letter binding can match. Each test passes the half it
    means; the other half is filled in here.
    """
    if key is None and char is not None:
        key = char.lower()
    return Event(type=EventType.KEY, key=key, char=char,
                 modifiers=frozenset(mods))


@pytest.fixture(autouse=True)
def shipped_config(monkeypatch):
    """Resolve key bindings from xefm/_config.py, not from ~/.xefm/config.py.

    The viewer matches its keys through the *active* configuration, which is the
    developer's own file when one exists — so without this, whether ``n`` steps
    to the next image would depend on whose machine the suite runs on. Pinning
    the shipped template keeps these tests a check on XeFM's defaults.
    """
    monkeypatch.setattr(config_manager, "config", DefaultConfig())
    monkeypatch.setattr(config_manager, "_key_bindings", None)


@pytest.fixture
def images(tmp_path):
    """Three images (plus a non-image) in one directory, as xefm.path.Paths."""
    _png(tmp_path / "a.png", 200, 100)
    _png(tmp_path / "b.png", 40, 40)
    _png(tmp_path / "c.png", 640, 480)
    (tmp_path / "notes.txt").write_text("not an image")
    return [Path(str(tmp_path / n)) for n in ("a.png", "b.png", "c.png")]


@pytest.fixture(params=[PROFILE_TUI, PROFILE_GUI_DESKTOP], ids=["tui", "gui"])
def backend(request):
    return MemoryBackend(width=60, height=20, capabilities=request.param)


def _render(backend, viewer):
    """Push the viewer onto a panel and draw one frame."""
    panel = Panel(backend)
    viewer._panel = panel
    panel.push_layer(viewer, z=80, hints={"x": 0, "y": 0, "w": 60, "h": 20})
    panel.render()
    return panel


def _image_hints(backend):
    assert backend.image_calls, "expected the picture to be drawn"
    return backend.image_calls[-1][3]


# --- file-type claim ---------------------------------------------------------


def test_is_image_file_matches_extension_case_insensitively(tmp_path):
    assert is_image_file(Path(str(tmp_path / "x.PNG")))
    assert is_image_file(Path(str(tmp_path / "x.jpeg")))
    assert not is_image_file(Path(str(tmp_path / "x.txt")))
    assert not is_image_file(Path(str(tmp_path / "noextension")))


def test_is_image_file_tolerates_objects_without_a_suffix():
    assert not is_image_file(object())


def test_claimed_suffixes_are_normalized():
    # Every entry must be lower-case and dotted, or the lookup silently misses.
    for suffix in IMAGE_SUFFIXES:
        assert suffix.startswith(".") and suffix == suffix.lower()


# --- opening / metadata ------------------------------------------------------


def test_viewer_reads_dimensions_and_size(images):
    viewer = ImageViewer(images[0])
    assert viewer._size == (200, 100)
    assert viewer._bytes == os.path.getsize(str(images[0]))
    assert viewer._error is None


def test_viewer_starts_fitted_and_centered(images):
    viewer = ImageViewer(images[0])
    assert viewer.zoom == MIN_ZOOM
    assert (viewer.cx, viewer.cy) == (0.5, 0.5)


def test_unreadable_image_records_an_error_instead_of_raising(tmp_path):
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not really a png")
    viewer = ImageViewer(Path(str(broken)))
    # It must open — a corrupt file should not make a directory unbrowsable.
    assert viewer._size is None or viewer._error is not None


# --- zoom --------------------------------------------------------------------


def test_zoom_in_and_out_step_geometrically(images):
    viewer = ImageViewer(images[0])
    viewer.handle_event(_key(char="+"))
    assert viewer.zoom == pytest.approx(ZOOM_STEP)
    viewer.handle_event(_key(char="+"))
    assert viewer.zoom == pytest.approx(ZOOM_STEP ** 2)
    viewer.handle_event(_key(char="-"))
    assert viewer.zoom == pytest.approx(ZOOM_STEP)


def test_zoom_is_clamped_to_the_allowed_range(images):
    viewer = ImageViewer(images[0])
    for _ in range(200):
        viewer.handle_event(_key(char="+"))
    assert viewer.zoom == pytest.approx(MAX_ZOOM)
    for _ in range(200):
        viewer.handle_event(_key(char="-"))
    # MIN_ZOOM is fit-to-window; there is nothing smaller to show.
    assert viewer.zoom == pytest.approx(MIN_ZOOM)


def test_zoom_reset_returns_to_fit_and_recenters(images):
    viewer = ImageViewer(images[0])
    for _ in range(4):
        viewer.handle_event(_key(char="+"))
    viewer.handle_event(_key(key="right", mods={"shift"}))
    viewer.handle_event(_key(char="0"))
    assert viewer.zoom == pytest.approx(MIN_ZOOM)
    assert (viewer.cx, viewer.cy) == (0.5, 0.5)


def test_zooming_back_out_to_fit_recenters(images):
    # A stale pan center at fit would make the next zoom-in jump to a corner.
    viewer = ImageViewer(images[0])
    viewer.handle_event(_key(char="+"))
    viewer.handle_event(_key(key="right", mods={"shift"}))
    viewer.handle_event(_key(char="-"))
    assert viewer.zoom == pytest.approx(MIN_ZOOM)
    assert (viewer.cx, viewer.cy) == (0.5, 0.5)


def test_scroll_zooms(images):
    viewer = ImageViewer(images[0])
    viewer.handle_event(Event(type=EventType.MOUSE_SCROLL, scroll=1, hints={}))
    assert viewer.zoom > MIN_ZOOM


# --- pan ---------------------------------------------------------------------


def test_pan_moves_the_center_by_a_share_of_the_visible_extent(images):
    viewer = ImageViewer(images[0])
    viewer.zoom = 2.0
    viewer.handle_event(_key(key="right", mods={"shift"}))
    # The step is divided by the zoom, so it covers the same share of screen.
    assert viewer.cx == pytest.approx(0.5 + PAN_STEP / 2.0)
    viewer.handle_event(_key(key="down", mods={"shift"}))
    assert viewer.cy == pytest.approx(0.5 + PAN_STEP / 2.0)


def test_pan_center_clamps_to_the_reachable_range(images):
    # The center only travels within the range the client area can actually
    # reach. It must NOT accumulate to 0/1: parking off the edge is the bug that
    # made reversing direction move nothing for several presses. A body matching
    # the 200x100 image's 2:1 aspect makes the reachable range symmetric.
    viewer = ImageViewer(images[0])
    viewer._view = (200, 100, 1, 1)  # cached client area (matches image aspect)
    viewer.zoom = 2.0                # reachable range = [1/(2*zoom), 1-1/(2*zoom)]
    for _ in range(50):
        viewer.handle_event(_key(key="right", mods={"shift"}))
        viewer.handle_event(_key(key="down", mods={"shift"}))
    assert viewer.cx == pytest.approx(0.75)
    assert viewer.cy == pytest.approx(0.75)
    for _ in range(100):
        viewer.handle_event(_key(key="left", mods={"shift"}))
        viewer.handle_event(_key(key="up", mods={"shift"}))
    assert viewer.cx == pytest.approx(0.25)
    assert viewer.cy == pytest.approx(0.25)


def test_reversing_pan_moves_immediately_at_the_edge(images):
    # Regression: one reverse press must move the view straight back off the
    # edge, because the center was never allowed past what the client area reaches.
    viewer = ImageViewer(images[0])
    viewer._view = (200, 100, 1, 1)
    viewer.zoom = 2.0
    for _ in range(20):  # jam against the right edge
        viewer.handle_event(_key(key="right", mods={"shift"}))
    assert viewer.cx == pytest.approx(0.75)  # the reachable edge
    viewer.handle_event(_key(key="left", mods={"shift"}))    # a single reverse press
    assert viewer.cx < 0.75                   # moved immediately, no dead presses


def test_zooming_out_pulls_the_center_back_into_range(images):
    # Zoom in at a corner, then zoom out: the reachable range shrinks, so the
    # center must be pulled back in rather than left stranded off the edge.
    viewer = ImageViewer(images[0])
    viewer._view = (200, 100, 1, 1)
    viewer.zoom = 8.0
    for _ in range(30):
        viewer.handle_event(_key(key="right", mods={"shift"}))
    assert viewer.cx > 0.8
    viewer.zoom = 2.0
    viewer._clamp_center()
    assert viewer.cx == pytest.approx(0.75)  # pulled back to the 2x reachable edge


def test_fill_uses_the_real_cell_aspect_on_a_grid(images):
    # Regression (TUI white-space bug): on a character grid base_size is (1,1) but
    # a cell is ~1:2 tall. Feeding the *real* cell pixel aspect makes the source
    # crop match the cell box, so the terminal fills it; a square-cell assumption
    # produced a wrong-aspect crop that the terminal letterboxed, leaving a big
    # blank band. This is why the viewer reads ctx.base_pixel_size, not base_size.
    viewer = ImageViewer(images[2])  # 640x480
    viewer.zoom = 3.0
    iw, ih = viewer._size
    # 100x40 cells at a real 8x16 px cell -> an 800x640 px (1.25:1) client area.
    (dx, dy, dw, dh), src = viewer._fill_geometry(100, 40, 8, 16)
    crop_aspect = (src[2] * iw) / (src[3] * ih)
    box_aspect = (100 * 8) / (40 * 16)
    assert crop_aspect == pytest.approx(box_aspect)  # matches the box -> fills


def test_pan_at_an_edge_keeps_filling_the_client_area(images):
    # Panning to a border slides the visible window; it must not shrink, so the
    # image keeps filling the body and the zoom level survives hitting the edge.
    viewer = ImageViewer(images[0])
    viewer._view = (200, 100, 1, 1)
    viewer.zoom = 4.0
    for _ in range(50):
        viewer.handle_event(_key(key="left", mods={"shift"}))
    (dx, dy, dw, dh), src = viewer._fill_geometry(200, 100, 1, 1)
    assert (dw, dh) == pytest.approx((200, 100))  # dest still fills the whole body
    assert src[0] == pytest.approx(0.0)           # flush to the left image edge
    assert src[2] == pytest.approx(0.25)          # visible width = 1/zoom


def test_drag_pans_opposite_the_pointer(images):
    viewer = ImageViewer(images[0])
    viewer.zoom = 2.0
    viewer._body_rect = (0.0, 1.0, 60.0, 18.0)
    viewer.handle_event(Event(type=EventType.MOUSE_DOWN, x=30.0, y=10.0, hints={}))
    viewer.handle_event(Event(type=EventType.MOUSE_DRAG, x=36.0, y=10.0, hints={}))
    # Dragging right moves the image right, i.e. the source window left.
    assert viewer.cx < 0.5
    viewer.handle_event(Event(type=EventType.MOUSE_UP, x=36.0, y=10.0, hints={}))
    assert viewer._drag is None


def test_drag_does_nothing_while_fitted(images):
    viewer = ImageViewer(images[0])
    viewer._body_rect = (0.0, 1.0, 60.0, 18.0)
    viewer.handle_event(Event(type=EventType.MOUSE_DOWN, x=30.0, y=10.0, hints={}))
    viewer.handle_event(Event(type=EventType.MOUSE_DRAG, x=50.0, y=10.0, hints={}))
    assert (viewer.cx, viewer.cy) == (0.5, 0.5)


# --- prev / next navigation --------------------------------------------------


def test_next_and_prev_walk_the_sibling_list(images):
    viewer = ImageViewer(images[0], siblings=images, index=0)
    viewer.handle_event(_key(key="down"))
    assert viewer.path.name == "b.png"
    viewer.handle_event(_key(key="down"))
    assert viewer.path.name == "c.png"
    viewer.handle_event(_key(key="up"))
    assert viewer.path.name == "b.png"


def test_navigation_wraps_at_both_ends(images):
    viewer = ImageViewer(images[0], siblings=images, index=0)
    viewer.handle_event(_key(key="up"))
    assert viewer.path.name == "c.png"
    viewer.handle_event(_key(key="down"))
    assert viewer.path.name == "a.png"


def test_home_and_end_jump_to_first_and_last(images):
    viewer = ImageViewer(images[1], siblings=images, index=1)
    viewer.handle_event(_key(key="end"))
    assert viewer.path.name == "c.png"
    viewer.handle_event(_key(key="home"))
    assert viewer.path.name == "a.png"


def test_navigation_resets_zoom_and_pan(images):
    # Carrying a deep crop across would open the next image on a corner of it.
    viewer = ImageViewer(images[0], siblings=images, index=0)
    for _ in range(5):
        viewer.handle_event(_key(char="+"))
    viewer.handle_event(_key(key="right", mods={"shift"}))
    viewer.handle_event(_key(key="down"))
    assert viewer.zoom == MIN_ZOOM
    assert (viewer.cx, viewer.cy) == (0.5, 0.5)


def test_navigation_reloads_dimensions_for_the_new_image(images):
    viewer = ImageViewer(images[0], siblings=images, index=0)
    assert viewer._size == (200, 100)
    viewer.handle_event(_key(key="down"))
    assert viewer._size == (40, 40)


def test_single_image_has_navigation_disabled(images):
    viewer = ImageViewer(images[0])
    viewer.handle_event(_key(key="down"))
    assert viewer.path.name == "a.png"


def test_sibling_list_is_snapshotted_not_referenced(images):
    # The file monitor mutates the pane's list in place on refresh; holding a
    # live reference would shift the index out from under the viewer.
    live = list(images)
    viewer = ImageViewer(images[0], siblings=live, index=0)
    live.clear()
    viewer.handle_event(_key(key="down"))
    assert viewer.path.name == "b.png"


def test_index_is_recovered_when_it_disagrees_with_the_path(images):
    # A caller passing a stale index must not land the viewer on another file.
    viewer = ImageViewer(images[2], siblings=images, index=0)
    assert viewer.path.name == "c.png"


def test_plain_arrows_step_and_do_not_pan_with_shipped_bindings(images):
    # Down/Up step the sibling list now; panning is on the Shift-arrows.
    viewer = ImageViewer(images[0], siblings=images, index=0)
    viewer.zoom = 2.0
    viewer.handle_event(Event(type=EventType.KEY, key="down", char=None))
    assert viewer.path.name == "b.png"  # stepped (and reset), not panned


# --- older user configs (template without the rebindable viewer keys) --------


@pytest.fixture
def legacy_config(monkeypatch):
    """A user config merged from a template older than the image viewer's
    rebindable navigation / pan actions: those actions are simply absent from
    its KEY_BINDINGS.

    ``_copy_missing_fields`` can add a whole missing config *field* but never a
    missing key inside one, so such a config would otherwise be stuck with those
    keys dead forever. The action registry is what closes that: an action the
    config never names falls back to the default the action itself declares
    (:mod:`xefm.actions`), so a legacy config lands on exactly the same keys a
    freshly written one does."""
    cfg = DefaultConfig()
    bindings = dict(cfg.KEY_BINDINGS)
    for action in ("image_next", "image_prev", "image_scroll_up",
                   "image_scroll_down", "image_scroll_left",
                   "image_scroll_right"):
        bindings.pop(action, None)
    cfg.KEY_BINDINGS = bindings  # instance attr shadows the class dict
    monkeypatch.setattr(config_manager, "config", cfg)
    monkeypatch.setattr(config_manager, "_key_bindings", None)


def test_legacy_config_gets_the_registry_default_navigation(images, legacy_config):
    viewer = ImageViewer(images[0], siblings=images, index=0)
    viewer.handle_event(Event(type=EventType.KEY, key="down", char=None))
    assert viewer.path.name == "b.png"
    viewer.handle_event(Event(type=EventType.KEY, key="up", char=None))
    assert viewer.path.name == "a.png"


def test_legacy_config_gets_the_registry_default_pan(images, legacy_config):
    viewer = ImageViewer(images[0])
    viewer.zoom = 2.0
    viewer.handle_event(_key(key="right", mods={"shift"}))
    assert viewer.cx == pytest.approx(0.5 + PAN_STEP / 2.0)
    # The unmodified arrow steps images, exactly as with a current config.
    cx = viewer.cx
    viewer.handle_event(Event(type=EventType.KEY, key="down", char=None))
    assert viewer.cx == cx  # stepped (and zoom reset), not panned


# --- key labels in the hint bar / help ----------------------------------------


def test_pan_keys_label_collapses_the_default_chord():
    from xefm.image_viewer import _pan_keys_label
    assert _pan_keys_label() == "Shift-↑↓←→"


def test_pan_keys_label_uses_registry_defaults_for_a_legacy_config(legacy_config):
    from xefm.image_viewer import _pan_keys_label
    assert _pan_keys_label() == "Shift-↑↓←→"


# --- drawing: real picture vs metadata card ----------------------------------


def test_draw_fills_the_client_area_when_zoomed(images):
    # The fix for "the image floats in a letterbox when zoomed": a zoomed image
    # is grown past the client area and clipped to it, filling the whole body.
    backend = MemoryBackend(width=60, height=20, capabilities=PROFILE_GUI_DESKTOP)
    viewer = ImageViewer(images[0])
    viewer.zoom, viewer.cx, viewer.cy = 2.0, 0.5, 0.5
    _render(backend, viewer)
    x, y, path, hints = backend.image_calls[-1]
    assert hints["fit"] == "fill"      # dest and src proportional -> undistorted
    assert hints["src"] is not None    # a zoom/pan crop
    body_w, body_h, _, _ = viewer._view
    assert hints["w"] == pytest.approx(body_w)  # fills the client width
    assert hints["h"] == pytest.approx(body_h)  # ...and height


def test_draw_centers_the_whole_image_when_fitted(images):
    # At fit level the whole image shows (src covers all of it), in a *centered*
    # destination box so the letterbox splits evenly — a plain contain would let a
    # terminal top-left-align the picture, leaving the empty space all at the
    # bottom. images[0] is 200x100 (2:1) in a wider-than-tall body, so it
    # letterboxes left/right and centers horizontally (a positive x offset).
    backend = MemoryBackend(width=60, height=20, capabilities=PROFILE_GUI_DESKTOP)
    viewer = ImageViewer(images[0])
    _render(backend, viewer)
    x, y, path, hints = backend.image_calls[-1]
    assert hints["src"] == (0.0, 0.0, 1.0, 1.0)  # the whole image
    assert x > 0  # centered in the body, not drawn flush at the origin


def test_draw_targets_the_body_between_header_and_footer(images):
    backend = MemoryBackend(width=60, height=20, capabilities=PROFILE_GUI_DESKTOP)
    _render(backend, ImageViewer(images[0]))
    x, y, _, hints = backend.image_calls[-1]
    assert y >= 1  # below the header band
    assert hints["h"] <= 20 - 2  # clear of the header and the footer bar


def test_tui_without_an_image_protocol_draws_the_metadata_card(images):
    backend = MemoryBackend(width=60, height=20, capabilities=PROFILE_TUI)
    _render(backend, ImageViewer(images[0]))
    screen = "\n".join(backend.snapshot())
    assert backend.image_calls == []  # nothing tried to draw pixels
    assert "PNG" in screen
    assert "200x100" in screen


def test_header_shows_name_dimensions_and_position(images):
    backend = MemoryBackend(width=60, height=20, capabilities=PROFILE_TUI)
    _render(backend, ImageViewer(images[0], siblings=images, index=0))
    screen = "\n".join(backend.snapshot())
    assert "a.png" in screen
    assert "1/3" in screen


def test_header_shows_the_zoom_factor_only_while_zoomed(images):
    backend = MemoryBackend(width=60, height=20, capabilities=PROFILE_GUI_DESKTOP)
    viewer = ImageViewer(images[0])
    _render(backend, viewer)
    assert "2.0x" not in "\n".join(backend.snapshot())
    viewer.zoom = 2.0
    backend.clear()
    _render(backend, viewer)
    assert "2.0x" in "\n".join(backend.snapshot())


def test_footer_hides_pan_hint_until_zoomed(images):
    backend = MemoryBackend(width=60, height=20, capabilities=PROFILE_GUI_DESKTOP)
    viewer = ImageViewer(images[0])
    _render(backend, viewer)
    assert "pan" not in "\n".join(backend.snapshot())
    viewer.zoom = 2.0
    backend.clear()
    _render(backend, viewer)
    assert "pan" in "\n".join(backend.snapshot())


def test_draw_works_on_both_profiles(backend, images):
    # Whatever the fidelity, drawing must not raise.
    _render(backend, ImageViewer(images[0], siblings=images, index=0))
    assert "a.png" in "\n".join(backend.snapshot())


# --- modal behaviour ---------------------------------------------------------


def test_escape_closes_the_viewer(images):
    backend = MemoryBackend(width=60, height=20, capabilities=PROFILE_GUI_DESKTOP)
    panel = Panel(backend)
    viewer = show_image_viewer(panel, images[0], siblings=images, index=0)
    panel.render()
    assert panel.has_layers
    viewer.handle_event(_key(key="escape"))
    assert not panel.has_layers


def test_viewer_swallows_unhandled_events(images):
    # Modal: nothing leaks through to the file manager underneath.
    viewer = ImageViewer(images[0])
    assert viewer.handle_event(_key(char="Z")) is True
    assert viewer.handle_event(Event(type=EventType.RESIZE, hints={})) is True


def test_on_close_fires_once_when_closed(images):
    backend = MemoryBackend(width=60, height=20, capabilities=PROFILE_GUI_DESKTOP)
    panel = Panel(backend)
    calls = []
    viewer = show_image_viewer(panel, images[0], on_close=lambda: calls.append(1))
    panel.render()
    viewer.handle_event(_key(key="escape"))
    assert calls == [1]  # exactly once, and only after the layer was popped


def test_on_close_does_not_fire_if_not_top_layer(images):
    # The guard: a stray close on a viewer buried under another layer must not
    # fire the restore hook (which would put the effect back too early).
    backend = MemoryBackend(width=60, height=20, capabilities=PROFILE_GUI_DESKTOP)
    panel = Panel(backend)
    calls = []
    viewer = show_image_viewer(panel, images[0], on_close=lambda: calls.append(1))
    panel.push_layer(Widget(), z=200, hints={"x": 0, "y": 0, "w": 10, "h": 10})
    viewer._close()  # viewer is no longer the top layer
    assert calls == []


def test_show_image_viewer_stacks_help_above_itself(images):
    backend = MemoryBackend(width=60, height=20, capabilities=PROFILE_GUI_DESKTOP)
    panel = Panel(backend)
    viewer = show_image_viewer(panel, images[0], z=80)
    assert viewer._child_z > 80


# --- app dispatch ------------------------------------------------------------


def _app_open(images, focus, pane_files, backend=None, pane=None):
    """Drive XeFMApp._open_viewer directly with a synthetic pane, so the routing
    is tested without depending on the live config's FILE_ASSOCIATIONS (which
    decide only whether an *external* program pre-empts the built-in viewer).
    Pass ``pane`` to supply (and keep a reference to) the pane dict itself —
    the cursor-follow tests read ``focused_index`` back out of it."""
    app = xefm_app.XeFMApp.__new__(xefm_app.XeFMApp)  # no curses / no file monitor
    backend = backend or MemoryBackend(width=60, height=20,
                                       capabilities=PROFILE_GUI_DESKTOP)
    panel = Panel(backend)
    app.panel = panel
    app.backend = backend
    app.state_manager = None
    # _open_viewer reads the active theme to decide whether to suspend a
    # post-effect; the auto-derived theme carries none.
    app.themes = [("Test", panel.theme)]
    app._theme_index = 0
    app._open_viewer(focus, pane if pane is not None else {"files": pane_files})
    return panel._layers[-1].widget


def test_open_viewer_routes_images_to_the_image_viewer(images):
    widget = _app_open(images, images[0], list(images))
    assert isinstance(widget, ImageViewer)
    assert widget.path.name == "a.png"


def test_open_viewer_passes_only_the_image_siblings(tmp_path, images):
    text = Path(str(tmp_path / "notes.txt"))
    widget = _app_open(images, images[1], [images[0], text, images[1], images[2]])
    assert [p.name for p in widget.paths] == ["a.png", "b.png", "c.png"]
    assert widget.path.name == "b.png"  # index follows the file, not the slot


def test_open_viewer_routes_non_images_to_the_text_viewer(tmp_path):
    from xefm.text_viewer import TextViewer

    note = tmp_path / "notes.txt"
    note.write_text("hello")
    path = Path(str(note))
    widget = _app_open(None, path, [path])
    assert isinstance(widget, TextViewer)


def test_open_viewer_without_a_pane_falls_back_to_a_single_image(images):
    widget = _app_open(images, images[0], [])
    assert isinstance(widget, ImageViewer)
    assert [p.name for p in widget.paths] == ["a.png"]


# --- the pane cursor follows prev/next ----------------------------------------


def test_step_reports_the_new_path_to_on_navigate(images):
    seen = []
    viewer = ImageViewer(images[0], siblings=images, index=0,
                         on_navigate=seen.append)
    viewer.handle_event(_key(key="down"))
    viewer.handle_event(_key(key="down"))
    viewer.handle_event(_key(key="up"))
    assert [p.name for p in seen] == ["b.png", "c.png", "b.png"]
    viewer.handle_event(_key(key="end"))  # Home/End step too
    assert seen[-1].name == "c.png"


def test_on_navigate_not_called_when_navigation_is_disabled(images):
    seen = []
    viewer = ImageViewer(images[0], on_navigate=seen.append)
    viewer.handle_event(_key(key="down"))
    assert seen == []


def test_pane_cursor_follows_the_viewer(tmp_path, images):
    # The pane holds a non-image between the pictures: the cursor must land on
    # the file's index in the *full* list, not its index among the images.
    text = Path(str(tmp_path / "notes.txt"))
    pane = {"files": [images[0], text, images[1], images[2]],
            "focused_index": 0}
    viewer = _app_open(images, images[0], None, pane=pane)
    viewer.handle_event(_key(key="down"))     # -> b.png, at pane index 2
    assert pane["focused_index"] == 2
    viewer.handle_event(_key(key="down"))     # -> c.png, at pane index 3
    assert pane["focused_index"] == 3
    viewer.handle_event(_key(key="up"))       # back to b.png
    assert pane["focused_index"] == 2


def test_pane_cursor_stays_put_when_the_file_vanished(images):
    # A refresh under the viewer may drop the file from the pane; stepping to
    # it must leave the cursor alone rather than raise or guess.
    pane = {"files": list(images), "focused_index": 0}
    viewer = _app_open(images, images[0], None, pane=pane)
    pane["files"] = [images[0]]               # b.png / c.png vanished
    viewer.handle_event(_key(key="down"))     # viewer still shows its snapshot
    assert viewer.path.name == "b.png"
    assert pane["focused_index"] == 0         # cursor untouched


class _EffectBackend(MemoryBackend):
    """A GUI backend that records set_post_effect calls, so a test can see the
    effect suspended for the image and restored on close."""

    def __init__(self):
        super().__init__(width=60, height=20, capabilities=PROFILE_GUI_DESKTOP)
        self.effect_calls = []

    def set_post_effect(self, effect):
        self.effect_calls.append(effect)


def test_post_effect_is_suspended_for_the_image_and_restored_on_close(images):
    from puikit import PostEffect

    backend = _EffectBackend()
    app = xefm_app.XeFMApp.__new__(xefm_app.XeFMApp)
    panel = Panel(backend)
    app.panel = panel
    app.backend = backend
    app.state_manager = None
    # A theme carrying a CRT-style effect: the viewer must not filter the picture.
    theme = panel.theme
    theme.extras["post_effect"] = PostEffect(bloom=0.4)
    app.themes = [("CRT", theme)]
    app._theme_index = 0

    app._open_viewer(images[0], {"files": list(images)})
    assert backend.effect_calls == [None]  # suspended on open

    panel._layers[-1].widget.handle_event(_key(key="escape"))
    # Restored on close (the theme's effect pushed back).
    assert len(backend.effect_calls) == 2
    assert backend.effect_calls[1] is theme.extras["post_effect"]


def test_post_effect_untouched_when_theme_has_none(images):
    backend = _EffectBackend()
    app = xefm_app.XeFMApp.__new__(xefm_app.XeFMApp)
    panel = Panel(backend)
    app.panel = panel
    app.backend = backend
    app.state_manager = None
    theme = panel.theme
    theme.extras.pop("post_effect", None)  # a theme that recommends no effect
    app.themes = [("Plain", theme)]
    app._theme_index = 0

    app._open_viewer(images[0], {"files": list(images)})
    panel._layers[-1].widget.handle_event(_key(key="escape"))
    assert backend.effect_calls == []  # nothing to suspend, nothing to restore


# --- remote / in-archive files ----------------------------------------------


def test_non_local_image_is_materialized_to_a_temp_file(images, monkeypatch):
    # A remote path has no filesystem path for Pillow or the backend to open, so
    # the bytes are copied to a temp file for the life of the viewer.
    source = images[0]
    data = open(str(source), "rb").read()

    class RemotePath:
        name, suffix = "remote.png", ".png"

        def is_remote(self):
            return True

        def read_bytes(self):
            return data

        def __str__(self):
            return "s3://bucket/remote.png"

    viewer = ImageViewer(RemotePath())
    assert viewer._temp is not None
    assert os.path.exists(viewer._temp)
    assert viewer._size == (200, 100)
    temp = viewer._temp
    viewer._release_temp()
    assert not os.path.exists(temp)

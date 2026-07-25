#!/usr/bin/env python3
"""XeFM on PuiKit — dual-pane file manager.

XeFM running on PuiKit instead of ttk. It reuses the storage-agnostic business
logic unchanged — ``xefm.path.Path`` for listing, ``PaneManager`` /
``FileListManager`` for pane state, and ``xefm.config``'s keymap (ported to the
PuiKit keyboard contract) — and renders through a custom ``FilePane`` widget
hosted in a PuiKit ``Panel`` layout, on curses + macOS.

Navigation (cursor, pane switch, arrow-key focus, descend / go up), selection,
sort, hidden-file toggle, filename filter and incremental search, the built-in
text and diff viewers, and the create / rename / batch-rename / favorites /
jump-to-path dialogs are all wired — as are file operations (copy / move /
delete, threaded with progress and per-conflict resolution via ``xefm.task``),
archive browsing, and remote storage (S3 / SFTP). The original ttk implementation
was removed after the port (see git history).

    python -m xefm                       # TUI (curses)
    python -m xefm --backend gui         # macOS GUI
    python -m xefm --left ./src --right ./test
"""

import argparse
import os
import platform
import queue
import re
import shlex
import shutil
import subprocess
import threading
import time
import sys
from pathlib import Path as _StdPath

from puikit import EventType, Font, Item, Panel, PostEffect, Style, TextAttribute, Theme, VSplit, derive_theme, mix
from puikit.background import Shader, Wallpaper
from puikit.posteffect import PRESETS as _POST_EFFECT_PRESETS
from puikit.backends import create_backend
from puikit.menu import Menu, MenuItem, SEPARATOR
from puikit.text import elide
from puikit.layout import SizeRequest
from puikit.widgets import LayoutView, LogView, MenuBar, Splitter, show_message_box
from puikit.widgets.base import Widget

from xefm import __version__ as _VERSION
from xefm.backend_detector import is_desktop_mode
# Every background scene XeFM offers is a fragment shader; a theme's ``animation`` key
# names one of these and ``_resolve_background`` turns it into a puikit ``Shader``.
from xefm.background_shaders import SHADER_KINDS
from xefm.config import (KeyBindings, config_manager, get_builtin_handler_for_file,
                         get_config, get_favorite_directories, get_program_for_file,
                         has_explicit_association, keys_label_for_action)
from xefm.file_list_manager import FileListManager
from xefm.file_monitor_manager import FileMonitorManager
from xefm.file_pane import FilePane
from xefm.filter_list_dialog import show_filter_list
from xefm.completion import FilepathCompleter
from xefm.input_dialog import show_input
from xefm.progressive_search_dialog import show_progressive_search
from xefm.isearch_bar import ISearchBar
from xefm.pane_manager import PaneManager
from xefm.path import Path
from xefm.state_manager import get_state_manager
from xefm.str_format import abbreviate_path, format_size
from xefm.batch_rename_dialog import show_batch_rename
from xefm.compare_dialog import show_compare_select
from xefm.compare_selection import compute_compare_selection
from xefm.progress_manager import OperationType
from xefm.diff_viewer import show_diff_viewer
from xefm.directory_diff_viewer import show_directory_diff_viewer
from xefm.file_operations import (FileOperationService, format_op_errors,
                                  format_op_summary)
from xefm.task import Task, TaskManager
from xefm.text_dialog import show_markdown
from xefm.image_viewer import is_image_file, show_image_viewer
from xefm.text_viewer import looks_binary, show_text_viewer
from xefm.viewer_registry import rich_renderer_for

#: Initial share of the content area given to the file panes (vs the log pane).
PANES_FRACTION = 0.74

#: Persistent, most-recent-first history of filename-filter patterns (fed by
#: isearch's Enter and the ';' Filter prompt), and the cap kept in the store.
_FILTER_HISTORY_KEY = "filter.history"
_FILTER_HISTORY_MAX = 100

#: Cap on the recent-directory history behind the History picker, applied both
#: in memory (``_record_history_path``) and when persisted to the state DB.
_HISTORY_MAX = 100


# --- theme palettes ----------------------------------------------------------
#
# Theme switching is pure intent, exactly as in PuiKit's demo catalog: the shell
# tags its panes with semantic surface roles (header / content / status) instead
# of hardcoded colors, and every widget reads its accent / selection / text
# colors from ``panel.theme`` at draw time (see ``PaneHeader`` / ``PaneFooter`` /
# ``StatusBar`` below). So cycling the active ``Theme`` (the ``toggle_color_scheme``
# action, bound to ``T``) recolors the whole file manager — chrome and file lists
# alike — with one assignment and no per-widget repaint logic; the surface
# backgrounds re-resolve from the new theme on the next render.
#
# Each theme is the base colors ``derive_theme`` needs; it computes the rest
# (hovers, borders, inactive selections, dividers) by lighten/darken/blend rules.
#   background — content surface (its luminance also picks the lift direction)
#   foreground — primary text          muted     — secondary text / dividers
#   accent     — focus / default bars  surface   — raised panels (header/popup)
#   selection  — active selection fill accent2   — secondary hue for chrome recipes
#
# The two chrome bars — the global ``status`` bar and each pane's ``footer`` — are
# separate surface roles, and both default to the accent. A theme overrides either
# with its own *recipe*: ``status``/``footer`` may be a Color or a callable taking
# the palette namespace ``p`` (``p["bg"]``, ``p["accent2"]``, …), so a bar can be a
# neutral gray, an accent2 blend, or anything expressible over the palette. Recipes
# blend with ``mix`` / ``lift`` (from puikit); the theme's headroom pass then keeps
# whatever a recipe produces legible. See puikit ``docs/color_system.md`` §7.


def _resolve_post_effect(value) -> "PostEffect | None":
    """Turn a theme's ``post_effect`` recommendation into a ``PostEffect`` (or
    ``None``). Accepts a named preset (``'crt'`` — see ``puikit.posteffect.PRESETS``),
    a params dict (``{'bloom': 0.3, 'scanline': 0.15, ...}``), an already-built
    ``PostEffect``, or ``None``/``''`` for "no effect". An unknown name or malformed
    dict resolves to ``None`` so a typo in config.py degrades to "no effect" rather
    than blocking startup."""
    if value is None or value == "":
        return None
    if isinstance(value, PostEffect):
        return value
    if isinstance(value, str):
        return _POST_EFFECT_PRESETS.get(value.strip().lower())
    if isinstance(value, dict):
        try:
            return PostEffect(**value)
        except TypeError:
            return None
    return None


#: XeFM's tuning for an animation background: slow and subdued, since it sits behind
#: a working file manager. ``color`` (theme foreground) and ``backdrop`` (theme
#: background) are filled per theme by ``_resolve_background`` so a scene stays
#: on-palette and legible. How opaque the UI is (so the background reads *through*
#: the panes where < 1) is a separate theme value (``opacity``), pushed via
#: ``set_surface_opacity`` — see ``_apply_surface_opacity``.
_ANIM_DEFAULTS = dict(speed=0.6, opacity=0.6)

#: The animation used when a theme asks for one without naming a type
#: (``animation: True``). The scenes themselves live in ``xefm.background_shaders``;
#: puikit's own ``'cube'`` remains valid but is a toolkit reference scene rather than
#: a production look.
_ANIM_DEFAULT_KIND = "starfield"

#: Per-kind param keys carried from the theme spec onto the puikit descriptor.
_ANIM_PARAMS = ("speed", "opacity", "color")
_WALLPAPER_PARAMS = ("fit", "opacity")


def _resolve_background(animation, wallpaper, *, color, backdrop):
    """Turn a theme's background choice into a puikit descriptor — a ``Shader``
    (animation), a ``Wallpaper`` (image), or ``None`` (solid) — mirroring
    ``_resolve_post_effect``. A theme names at most one, both separate from the base
    ``background`` *color*:

    * ``animation`` — the scene *type* string (``'starfield'``, ``'rain'``,
      ``'constellation'``, ``'grid'``, ``'wave'``; see ``xefm.background_shaders``),
      ``True`` (the tuned default, ``_ANIM_DEFAULT_KIND``), or a params dict
      (``{'type': 'rain', 'speed': ..., ...}`` merged onto the tuned default). The
      line ``color`` (theme fg) and ``backdrop`` (theme bg) are filled from the theme;
      a shader receives the former as its ``ink`` uniform, the name the GPU contract
      uses for the same intent.
    * ``wallpaper`` — an image path string, or a params dict
      (``{'image': 'path', 'fit': ..., 'opacity': ...}``).

    A name that is not one of XeFM's scenes resolves to ``None`` — a plain solid
    background — so a config typo costs the scene, not startup. (There is nowhere
    else for it to go: a scene *is* a shader, and puikit no longer has a second
    background kind to fall through to.)

    Either may also be a pre-built ``Shader`` / ``Wallpaper``, used as-is. A
    malformed value resolves to ``None`` for the same reason."""
    try:
        if wallpaper:
            if isinstance(wallpaper, (Shader, Wallpaper)):
                return wallpaper
            spec = wallpaper if isinstance(wallpaper, dict) else {"image": wallpaper}
            params = {k: spec[k] for k in _WALLPAPER_PARAMS if k in spec}
            params.setdefault("backdrop", backdrop)
            return Wallpaper(image=spec.get("image") or spec["wallpaper"], **params)
        if animation:
            if isinstance(animation, (Shader, Wallpaper)):
                return animation
            params = dict(_ANIM_DEFAULTS)
            if isinstance(animation, dict):
                atype = animation.get("type", _ANIM_DEFAULT_KIND)
                params.update({k: animation[k] for k in _ANIM_PARAMS if k in animation})
            else:  # a type string, or True for the tuned default
                atype = animation if isinstance(animation, str) else _ANIM_DEFAULT_KIND
            if atype not in SHADER_KINDS:
                return None
            params.setdefault("color", color)
            params.setdefault("backdrop", backdrop)
            # ``color`` is the theme foreground, which a shader receives as its
            # ``ink`` uniform — same intent, the name the GPU contract uses.
            return Shader(speed=params["speed"], opacity=params["opacity"],
                          ink=params["color"], backdrop=params["backdrop"],
                          **SHADER_KINDS[atype])
    except (TypeError, KeyError):
        return None
    return None


def _theme(bg, fg, muted, accent, surface, selection, *, accent2=None,
           status=None, footer=None, directory=None, isearch_match=None,
           syntax=None, file_types=None, cursor=None, selection_fill=None,
           post_effect=None, animation=None, wallpaper=None, opacity=1.0,
           pane_frame=None, pane_dim=None, text_effect=None,
           dialog_effect=None) -> Theme:
    ac2 = accent if accent2 is None else accent2
    p = {"bg": bg, "fg": fg, "muted": muted, "accent": accent, "accent2": ac2,
         "surface": surface}
    surfaces = {}
    for role, spec in (("status", status), ("footer", footer)):
        if spec is not None:
            surfaces[role] = spec(p) if callable(spec) else spec
    # App-specific themed colors carried in ``Theme.extras`` (read off ``ctx.theme``
    # by the widgets): the file-pane ``file_types`` name palette (directory / file /
    # link) and ``cursor`` cue palette (active / inactive) — both the sub-dict shape
    # of ``syntax`` — the i-search ``isearch_match`` base hue, and a partial
    # ``syntax`` palette (token → Color) the text/diff viewers merge onto the VS Code
    # default. ``isearch_match`` may be a Color or a callable over the palette
    # namespace ``p`` (like the chrome recipes); ``directory`` is a legacy shorthand
    # for ``file_types['directory']`` and may likewise be a callable, with an
    # explicit ``file_types`` entry winning.
    extras: dict = {}
    ft = dict(file_types) if file_types else {}
    if directory is not None and "directory" not in ft:
        ft["directory"] = directory(p) if callable(directory) else directory
    if ft:
        extras["file_types"] = ft
    if cursor is not None:
        extras["cursor"] = dict(cursor)
    # Pane focus chrome (see xefm.file_pane): corner brackets framing the focused
    # pane, and how far the resting pane's ink recedes. Both are opt-in — a theme
    # that names neither renders exactly as it did before they existed.
    if pane_frame is not None:
        extras["pane_frame"] = dict(pane_frame) if isinstance(pane_frame, dict) else pane_frame
    if pane_dim is not None:
        extras["pane_dim"] = pane_dim
    # How text arrives (puikit.textfx): a kind name or a params dict. PuiKit
    # coerces and validates it, so a bad value here disables the effect rather
    # than raising — themes are data, often hand-written in a user's config.py.
    if text_effect is not None:
        extras["text_effect"] = text_effect
    # Whether modals play the app-wide entrance (see xefm.dialog_geometry). Every
    # theme wants it except one whose metaphor has no growing box, so this is an
    # opt-*out* flag: ``dialog_effect=False`` and dialogs simply appear.
    if dialog_effect is not None:
        extras["dialog_effect"] = bool(dialog_effect)
    if isearch_match is not None:
        extras["isearch_match"] = isearch_match(p) if callable(isearch_match) else isearch_match
    # A pinned file-pane selection fill: used verbatim as the selected-row bg
    # instead of the accent-tinted, legibility-corrected default. For a 2-colour
    # theme (black accent) that default corrects itself to invisibility; a dark
    # pinned fill gives a bold, inverted selection (the row text auto-inks light).
    if selection_fill is not None:
        extras["selection_fill"] = selection_fill(p) if callable(selection_fill) else selection_fill
    if syntax is not None:
        extras["syntax"] = dict(syntax)
    # A theme may *recommend* a post-processing effect (a CRT/phosphor look), a
    # ``background`` behind the UI (a cube animation or a wallpaper image), and/or a
    # UI ``opacity`` (how opaque the surfaces are, so the background shows through
    # where < 1): all ride in extras and XeFMApp pushes them to the backend on theme
    # switch, so a pixel backend (macOS GUI) auto-adjusts while a terminal ignores
    # them. ``opacity`` is kept separate from ``background`` on purpose — one
    # per-theme value, reusable across background kinds.
    effect = _resolve_post_effect(post_effect)
    if effect is not None:
        extras["post_effect"] = effect
    bg_obj = _resolve_background(animation, wallpaper, color=fg, backdrop=bg)
    if bg_obj is not None:
        extras["background"] = bg_obj
    if opacity != 1.0:
        extras["opacity"] = min(1.0, max(0.0, float(opacity)))
    kw: dict = {}
    if surfaces:
        kw["surfaces"] = surfaces
    if extras:
        kw["extras"] = extras
    return derive_theme(background=bg, foreground=fg, muted=muted, accent=accent,
                        surface=surface, selection=selection, accent2=ac2, **kw)


# Theme palettes as data: each spec is the keyword set ``_theme`` needs, kept
# separate from the built ``THEMES`` so the active theme can be rebuilt with a
# user's ``config.py`` ``THEME`` overrides merged in (see ``XeFMApp.__init__`` /
# ``_merge_theme_override``). Beyond the six base colors a spec may name the two
# chrome-bar recipes (``status`` / ``footer``) and the app-specific colors:
# ``file_types`` (a file-pane name palette — directory / file / link, with a flat
# ``directory`` accepted as shorthand), ``cursor`` (the file-pane cursor cue —
# active / inactive), ``isearch_match`` (the i-search wash base — defaults to
# ``accent2``), and ``syntax`` (a partial text-viewer palette).
_THEME_SPECS: list[tuple[str, dict]] = [
    ("Dark+", dict(bg=(30, 30, 30), fg=(212, 212, 212), muted=(157, 157, 157),
                   accent=(0, 122, 204), surface=(48, 48, 52), selection=(10, 105, 178),
                   accent2=(78, 201, 176))),
    ("Monokai", dict(bg=(39, 40, 34), fg=(248, 248, 242), muted=(140, 140, 130),
                     accent=(166, 226, 46), surface=(56, 57, 48), selection=(86, 122, 38),
                     accent2=(249, 38, 114))),
    ("Dracula", dict(bg=(40, 42, 54), fg=(248, 248, 242), muted=(98, 114, 164),
                     accent=(189, 147, 249), surface=(56, 59, 76), selection=(120, 86, 175),
                     accent2=(255, 121, 198))),
    # Nord: status stays the frost accent, footer is a neutral gray (a blend of
    # the background toward the text) — the "accent bar + gray footer" recipe.
    ("Nord", dict(bg=(46, 52, 64), fg=(216, 222, 233), muted=(76, 86, 106),
                  accent=(136, 192, 208), surface=(62, 70, 88), selection=(76, 128, 158),
                  accent2=(180, 142, 173),
                  footer=lambda p: mix(p["bg"], p["fg"], 0.16))),
    # Solarized: both bars are an 80/20 blend of the background and the secondary
    # accent (cyan) rather than the primary accent — the "accent2 blend" recipe.
    ("Solarized", dict(bg=(0, 43, 54), fg=(147, 161, 161), muted=(88, 110, 117),
                       accent=(38, 139, 210), surface=(10, 62, 78), selection=(26, 102, 150),
                       accent2=(42, 161, 152),
                       status=lambda p: mix(p["bg"], p["accent2"], 0.20),
                       footer=lambda p: mix(p["bg"], p["accent2"], 0.20))),
    # Sample theme — the *simple* per-theme color config: on top of the six base
    # colors it names a file_types palette (directory + link hues), a secondary
    # accent (the i-search match base), and a few syntax tokens; everything else
    # falls back to the defaults. _config.py carries the fully spelled-out config.
    ("Gruvbox Dark", dict(bg=(40, 40, 40), fg=(235, 219, 178), muted=(146, 131, 116),
                          accent=(131, 165, 152), surface=(60, 56, 54), selection=(80, 73, 69),
                          accent2=(254, 128, 25),            # orange — i-search match base
                          file_types={"directory": (250, 189, 47),  # gruvbox yellow
                                      "link": (131, 165, 152)},      # gruvbox aqua
                          syntax={"keyword": (251, 73, 52),   # red
                                  "string": (184, 187, 38),   # green
                                  "comment": (146, 131, 116)})),  # gray
    # --- light variants: same bases, opposite polarity (panels sink, text
    # defaults dark). Each names a darker directory yellow that reads on a light
    # surface (the default soft yellow is tuned for dark themes).
    ("Light+", dict(bg=(255, 255, 255), fg=(30, 30, 30), muted=(110, 110, 110),
                    accent=(0, 122, 204), surface=(235, 235, 238), selection=(120, 180, 240),
                    accent2=(0, 128, 128), directory=(160, 120, 0))),
    ("Solarized Light", dict(bg=(253, 246, 227), fg=(88, 110, 117), muted=(147, 161, 161),
                             accent=(38, 139, 210), surface=(234, 228, 206), selection=(150, 195, 230),
                             accent2=(211, 54, 130), directory=(181, 137, 0))),
    # --- retro hardware looks: each pairs a period-correct palette with a
    # recommended GUI-backend ``post_effect`` — an emissive screen texture (glow /
    # bloom / scanline / vignette) composited over the whole frame on a pixel
    # backend (macOS / Windows GUI), and silently ignored by a terminal. The theme
    # carries the color identity; the effect adds the screen's material feel. No
    # effect sets a ``tint`` — each palette is already the color it wants to be, so
    # the effect only textures it (unlike a mono theme that forces a hue via tint).
    #
    # Sci-Fi: a tactical-HUD look (à la a mission-select map screen) — soft
    # cyan-white text on a deep tactical navy, cool cyan chrome, and a warm amber
    # selection accent (the cursor) that pops against the cyan. A strong, wide bloom
    # halo + glow give the emissive holographic feel; NO scanlines and NO rolling
    # band (with no scanlines the bloom is free to spread into a broad glow).
    # status/footer are a cyan blend of the navy, not a solid bar.
    ("Sci-Fi", dict(bg=(16, 30, 50), fg=(200, 224, 245), muted=(98, 128, 164),
                    accent=(96, 186, 255), surface=(26, 46, 74), selection=(32, 68, 108),
                    accent2=(255, 158, 54),
                    status=lambda p: mix(p["bg"], p["accent"], 0.20),
                    footer=lambda p: mix(p["bg"], p["accent"], 0.20),
                    file_types={"directory": (130, 205, 255), "link": (176, 186, 255)},
                    cursor={"active": (255, 158, 54), "inactive": (122, 98, 58)},
                    syntax={"keyword": (96, 186, 255), "string": (255, 182, 98),
                            "comment": (98, 128, 164), "number": (255, 158, 54),
                            "operator": (176, 186, 255), "builtin": (140, 212, 255)},
                    post_effect={"bloom": 0.45, "vignette": 0.26, "glow": 0.22},
                    animation="starfield",  # stars streaming past (GUI backend)
                    opacity=0.6,            # chrome at 60% so the field reads through
                    # The focus pair that completes the tactical-HUD look, and the
                    # proof that a purely visual change needs no app code: cyan
                    # corner brackets mark the focused pane, and the resting pane's
                    # ink recedes toward the navy. Both are plain theme data —
                    # every other theme leaves them unset and renders exactly as
                    # before. The bracket color is the accent by default; named
                    # explicitly here because the HUD wants the brighter cyan.
                    pane_frame={"color": (130, 205, 255), "arm": 2},
                    pane_dim=True,
                    # Text *arrives* rather than appearing: a pane's listing, a
                    # dialog's labels and a viewer's first screen decode into
                    # place when they show up. Theme data, so it costs no app code
                    # and no other theme is affected — and PuiKit applies it inside
                    # draw_text, so no XeFM widget knows it exists.
                    #
                    # ``typewriter`` — a clean left-to-right reveal with nothing
                    # in the tail. ``decode`` (the tail churning as junk glyphs
                    # until the head passes over it) is the louder alternative and
                    # stays available; swap the kind here or in config.py to get
                    # it. Plain reading of a filename wins for the default: the
                    # pane's job is to be read, and a decoding tail competes with
                    # the text that has already resolved.
                    #
                    # Short and lightly staggered on purpose: this fires on every
                    # directory change, so anything longer would sit between the
                    # user and their file list. ``stagger_ms`` steps per ROW, so
                    # the cascade tracks the window height rather than how many
                    # strings a widget spends per row, and ``max_rows`` is only a
                    # backstop for a very tall window (120 x 8ms ≈ 1s).
                    text_effect={"kind": "typewriter", "duration_ms": 260,
                                 "stagger_ms": 8, "max_rows": 120})),
    # Cyber: a data-wall look — near-black navy under dense cyan telemetry, with a
    # warm amber for the things that need to be found (cursor, i-search, numbers) and
    # a magenta reserved for links, over the ``hologram`` scene (see
    # xefm.background_shaders).
    #
    # Purely emissive: no ``scanline``, and no ``roll`` glitch. Those two are what
    # read as a *CRT* — a physical tube being scanned — and this look is a projected
    # hologram, which has no scan to show. Dropping them also buys the glow it wants:
    # a scanline darkens every other row and so holds the bloom tight against the
    # geometry, and without it the halo is free to spread (the same reasoning Sci-Fi
    # spells out, taken further — the bloom and glow here are roughly double).
    ("Cyber", dict(bg=(9, 17, 28), fg=(198, 230, 244), muted=(94, 128, 154),
                   accent=(64, 214, 236), surface=(17, 31, 48), selection=(24, 82, 108),
                   accent2=(255, 196, 84),
                   status=lambda p: mix(p["bg"], p["accent"], 0.18),
                   footer=lambda p: mix(p["bg"], p["accent"], 0.18),
                   file_types={"directory": (120, 230, 248), "link": (236, 132, 200)},
                   cursor={"active": (255, 196, 84), "inactive": (118, 96, 52)},
                   syntax={"keyword": (64, 214, 236), "string": (255, 196, 84),
                           "comment": (94, 128, 154), "number": (255, 224, 138),
                           "operator": (236, 132, 200), "builtin": (140, 240, 250)},
                   post_effect={"bloom": 0.78, "glow": 0.60, "vignette": 0.30},
                   # The one theme that overrides the scene's ink. A shader defaults
                   # to the theme *foreground*, which here is a near-white blue —
                   # right for text, but it renders the panels as grey haze. The
                   # identity of this look is that the data is *cyan*, so the scene
                   # is anchored on the accent instead. (``color`` is the theme-side
                   # name for what the GPU contract calls ``ink``.) The scene derives
                   # its amber accent by swapping that colour's red and blue, so the
                   # choice of cyan here is what puts the warm marks on screen too.
                   # ``opacity`` is how strongly the scene reads against the backdrop
                   # — the brightness knob for a background that is composited rather
                   # than lit. Kept low: this scene is busy, and it sits behind a
                   # working file list that has to stay the thing you look at.
                   animation={"type": "hologram", "color": (64, 214, 236),
                              "opacity": 0.21},
                   opacity=0.62,           # chrome at 62% so the traffic reads through
                   pane_frame={"color": (64, 214, 236), "arm": 2},
                   pane_dim=True,
                   # Sci-Fi picks ``typewriter`` because a decoding tail competes with
                   # the filename that has already resolved. Cyber takes the opposite
                   # side of that trade on purpose — the churn *is* the theme's
                   # identity — and pays for it by being quicker, so the noisier
                   # effect spends less time between the user and their file list.
                   text_effect={"kind": "decode", "duration_ms": 220,
                                "stagger_ms": 7, "max_rows": 120})),
    # Segment LCD: a positive/reflective digital display — a sage-green base with
    # near-black "segments" (just two colors: the green + black). A light-polarity
    # mono theme; because the text is genuine black (maximally dark), the app's
    # legibility auto-ink never needs to lift it, so it stays black on every green.
    # Its only effect is a soft `drop_shadow` — every drawn element (the black
    # segments, the cursor outline, fills) casts a shadow, the embossed look of a
    # reflective LCD. No scanline / glow / low-res.
    # The green is a *light* sage on purpose, for two reasons. (1) The app's
    # legibility auto-ink keeps text black only where black out-contrasts white on
    # the surface — a mid/dark green flips it to white — so a light green keeps
    # genuine black segments on every surface. (2) The file pane's selection fill is
    # the pane bg nudged toward the accent (here black) but pulled back until black
    # row text is legible; on a green that only *just* clears that floor it gets
    # pulled all the way back to the bg and the selection vanishes. Extra lightness
    # gives it headroom, so the selection settles a visibly darker shade.
    ("Segment LCD", dict(bg=(209, 225, 173), fg=(22, 32, 22), muted=(72, 90, 58),
                         accent=(22, 32, 22), surface=(220, 233, 188), selection=(176, 196, 132),
                         accent2=(22, 32, 22),
                         # Chrome bars are a slightly darker sage (still green) with black
                         # text, not a black strip — the whole screen stays one green.
                         status=lambda p: mix(p["bg"], p["muted"], 0.16),
                         footer=lambda p: mix(p["bg"], p["muted"], 0.16),
                         file_types={"directory": (22, 32, 22), "link": (58, 82, 48)},
                         # Bold inverted selection (row text auto-inks light over it),
                         # so selected files read clearly in the two-colour palette —
                         # the accent-tinted default corrects itself invisible here.
                         selection_fill=(70, 100, 58),
                         # Active cursor is the black frame; the inactive pane's is a
                         # mid-green frame — clearly softer, so the focused pane reads.
                         cursor={"active": (22, 32, 22), "inactive": (120, 140, 95)},
                         syntax={"keyword": (22, 32, 22), "string": (58, 82, 48),
                                 "comment": (110, 128, 92), "number": (22, 32, 22),
                                 "operator": (72, 90, 58), "builtin": (22, 32, 22)},
                         post_effect={"drop_shadow": 0.6},
                         # The one theme with no modal entrance. Every other look
                         # has a surface that can plausibly move — a window, a
                         # projection, a tube. This one is a fixed sheet of glass
                         # with fixed segments behind it, and the only thing such a
                         # display can do is switch them on. A box that grows from
                         # 92% and fades in is the one gesture the metaphor cannot
                         # produce, so dialogs here appear whole, instantly.
                         dialog_effect=False)),
    # Shinagawa: a bay-at-night look — white text over a deep marine blue, with the
    # ``wave`` sheet rolling behind it (see xefm.background_shaders). Named for the
    # Tokyo waterfront. The base is one hue (blue → white), but the *content* colors
    # are deliberately not: a warm orange for directories with a full-spectrum syntax
    # palette, so the file list and the code viewer stay maximally sortable at a
    # glance. Blue backdrop + orange marks is the complementary pairing that buys the
    # most separation per unit of color, which is why the directories get the orange.
    ("Shinagawa", dict(bg=(14, 34, 74), fg=(244, 248, 253), muted=(128, 156, 196),
                       accent=(92, 168, 236), surface=(24, 52, 100), selection=(38, 84, 148),
                       # accent2 is the i-search wash base, and it takes the same warm
                       # orange as the directories — the "things to find" hue, held
                       # apart from the blue chrome (the Sci-Fi / Cyber recipe).
                       accent2=(255, 168, 76),
                       status=lambda p: mix(p["bg"], p["accent"], 0.20),
                       footer=lambda p: mix(p["bg"], p["accent"], 0.20),
                       file_types={"directory": (255, 168, 76),   # orange
                                   "link": (94, 234, 214)},        # turquoise
                       # The cursor stays near-white rather than joining the warm
                       # family: it frames whichever row you are on, and half those
                       # rows are now orange directory names — a warm frame around a
                       # warm name is the one place the cue could disappear.
                       cursor={"active": (232, 244, 255), "inactive": (110, 140, 180)},
                       # A full spread of hues, one per token class, each held above
                       # 4.5:1 on the navy. ``comment`` is the deliberate exception —
                       # it keeps the muted slate, because a comment's job is to
                       # recede while the code around it is loud.
                       syntax={"keyword": (198, 148, 255),   # violet
                               "string": (158, 232, 138),    # green
                               "comment": (118, 146, 186),   # slate — recedes
                               "number": (255, 186, 110),    # amber
                               "operator": (255, 138, 178),  # pink
                               "builtin": (108, 224, 240)},  # cyan
                       # The one effect, and it earns its place twice: Segment LCD uses
                       # a text shadow for an embossed look, and here the same shadow is
                       # what lifts white glyphs off a *moving* background — the classic
                       # reason to shadow text over imagery. No bloom or glow: this is a
                       # flat, lit UI floating over water, not an emissive screen.
                       post_effect={"drop_shadow": 0.5},
                       # Like Cyber, this overrides the scene's ink rather than letting
                       # it default to the theme foreground.
                       #
                       # Two separate knobs, and it is worth not confusing them. How
                       # *visible* the sheet is comes from ``opacity`` alone — that is
                       # the term the shader composites over the backdrop with — so it
                       # is the one raised here. ``color`` only sets where on the
                       # spectrum the sheet sits.
                       #
                       # And it cannot sit on white. The wave shader builds its gradient
                       # by pushing ``ink`` apart into a violet and a cyan through fixed
                       # channel scales (see WAVE_MSL); the violet end scales green by
                       # 0.42, so its green is capped at 42% no matter how bright the
                       # ink — even a pure-white ink resolves to magenta↔cyan, not
                       # white. What a near-white ink *does* buy is luminance, so this
                       # is a pale ice blue: bright enough to read as lit water
                       # (violet≈(180,97,255), cyan≈(61,253,255)) while keeping the red
                       # channel low enough that the violet end stays blue-violet rather
                       # than going orchid. The genuine white is the shader's own crest
                       # term, which lifts the leading edges up to 70% toward white
                       # independently of the ink — that is the foam, and raising the
                       # opacity is what makes it show.
                       animation={"type": "wave", "color": (180, 230, 255),
                                  "opacity": 0.5},
                       opacity=0.7)),   # chrome at 70% so the swell reads through
    # NB: no ``text_effect`` — text arrives instantly here. Water is the thing that
    # moves in this theme; having the filenames type themselves in as well would put
    # two independent animations on screen competing for the same attention.
]

THEMES: list[tuple[str, Theme]] = [(name, _theme(**spec)) for name, spec in _THEME_SPECS]

#: Friendly ``config.py`` theme key → ``_theme`` keyword. Covers the base
#: palette, the two chrome-bar recipes, and the app-specific colors (``file_types``
#: sub-dict, ``directory`` shorthand, ``cursor`` sub-dict, ``isearch_match``,
#: ``syntax``); an unknown key is ignored (forward-compatible).
_THEME_OVERRIDE_MAP = {
    "background": "bg", "foreground": "fg", "muted": "muted", "accent": "accent",
    "accent2": "accent2", "surface": "surface", "selection": "selection",
    "status": "status", "footer": "footer", "directory": "directory",
    "isearch_match": "isearch_match", "syntax": "syntax", "file_types": "file_types",
    "cursor": "cursor", "selection_fill": "selection_fill", "post_effect": "post_effect",
    # Pane focus chrome: corner brackets on the focused pane, ink wash on the
    # resting one. Both pure data — a theme (or a user's config) turns them on
    # without a line of app code.
    "pane_frame": "pane_frame", "pane_dim": "pane_dim",
    "text_effect": "text_effect", "dialog_effect": "dialog_effect",
    # NB: config ``background`` is the base *color* (→ bg, above). The content behind
    # the UI is a separate choice — ``animation`` (a type / params) or ``wallpaper``
    # (an image path / params) — so it never collides with the color key.
    "animation": "animation", "wallpaper": "wallpaper", "opacity": "opacity",
}

#: Sub-dict theme keys that deep-merge (the user recolors only the entries they
#: name, keeping the base's other choices) rather than replacing wholesale.
_THEME_SUBDICT_KEYS = frozenset({"syntax", "file_types", "cursor"})


def _merge_theme_override(spec: dict, override: dict) -> dict:
    """Merge one user theme's overrides (config.py, friendly keys) onto a base
    theme ``spec`` (``_theme`` keywords). Colors replace; the sub-dict palettes
    (``syntax``, ``file_types``) deep-merge so the user recolors only the entries
    they name (keeping the base's other choices). ``base`` is consumed by the
    caller; unknown keys are ignored."""
    merged = dict(spec)
    for key, kw in _THEME_OVERRIDE_MAP.items():
        if key not in override:
            continue
        val = override[key]
        if kw in _THEME_SUBDICT_KEYS and isinstance(val, dict) and isinstance(merged.get(kw), dict):
            merged[kw] = {**merged[kw], **val}
        else:
            merged[kw] = val
    return merged


def _build_theme_list(config) -> list[tuple[str, Theme]]:
    """The runtime theme list: the built-ins plus every theme the user registered
    in ``config.THEMES`` — all selectable at run time from the View ▸ Theme menu
    and the ``T`` cycle.

    ``config.THEMES`` is ``{name: overrides}``. Each theme inherits a base spec and
    overrides it: ``overrides['base']`` names the base (any built-in or an
    already-registered theme); with no ``base`` it builds on the theme of the same
    name when one exists (so ``{'Dark+': {...}}`` tweaks the built-in) and on
    ``Dark+`` otherwise. A registered name that matches an existing theme replaces
    it in place (keeping its slot); a new name is appended. A theme that fails to
    build (e.g. a from-scratch palette missing a base color) is skipped with a
    logged warning rather than blocking startup."""
    specs: list[list] = [[name, dict(spec)] for name, spec in _THEME_SPECS]
    index = {name: i for i, (name, _s) in enumerate(specs)}
    user = getattr(config, "THEMES", None) or {}
    for name, override in user.items():
        override = dict(override)
        base_name = override.pop("base", None) or (name if name in index else "Dark+")
        base_spec = dict(specs[index.get(base_name, index["Dark+"])][1])
        merged = _merge_theme_override(base_spec, override)
        if name in index:
            specs[index[name]][1] = merged
        else:
            index[name] = len(specs)
            specs.append([name, merged])
    themes: list[tuple[str, Theme]] = []
    for name, spec in specs:
        try:
            themes.append((name, _theme(**spec)))
        except Exception as exc:  # a bad user theme must not block startup
            print(f"Skipping theme {name!r}: {exc}", file=sys.stderr)
    return themes


def _archive_header_label(path_str: str) -> str:
    """Render an ``archive://…#internal`` URI for the pane header as
    ``[archive.zip]/internal/path`` (or ``[archive.zip]`` at the archive root),
    so a browsed archive reads as a location rather than a raw URI. Assumes
    ``path_str`` starts with ``archive://`` (the caller checks)."""
    path_part = path_str[len("archive://"):]
    archive_path, sep, internal = path_part.partition("#")
    archive_name = _StdPath(archive_path).name
    if not sep:  # malformed (no '#'); fall back to the raw string
        return path_str
    return f"[{archive_name}]/{internal}" if internal else f"[{archive_name}]"


#: Content inset for the chrome bars (pane header / footer, global status), in
#: device pixels on a vector backend. This replaces the old window-level margin
#: (``Panel.set_layout(margin_px=…)``): each bar's *surface* fills its whole slot
#: — edge to edge — while only its *text* is inset by this much, so the colored
#: bars reach the window frame with no gap and the content still breathes. See
#: ``_bar_pad`` for the grid fallback and the FilePane's own ``CONTENT_PAD_CELLS``.
BAR_PAD_PX = 4.0

#: How long (seconds) a pane's disk-usage reading is cached before the footer
#: re-queries the filesystem. The footer redraws every frame, so an uncached
#: ``statvfs`` per draw would be wasteful — and could stall on a slow network
#: mount. A short TTL keeps the readout fresh without hammering the syscall.
DISK_USAGE_TTL = 5.0


def _bar_pad(ctx) -> tuple[float, float]:
    """``(x, y)`` content inset for a chrome bar, in base units, from its
    DrawContext. On a vector backend both are ``BAR_PAD_PX`` device pixels. On a
    character grid the horizontal inset is one whole cell (matching the single
    leading space the bars carried before) and the vertical inset is zero — a
    grid cannot spend a fraction of a row, and a whole extra row would waste
    space on a terminal."""
    if not ctx.vector_shapes:
        return (1.0, 0.0)
    bw, bh = ctx.base_size
    return (BAR_PAD_PX / bw if bw else 0.0, BAR_PAD_PX / bh if bh else 0.0)


def _bar_height(ctx) -> SizeRequest:
    """Height request (base units) for a ``size="content"`` chrome bar that
    reserves ``BAR_PAD_PX`` of vertical padding on top of its single text row —
    the header pads its top, the status bar its bottom. Vector backends only;
    a grid keeps the bare one-row height (``ctx.snap``)."""
    pad = 0.0 if ctx.snap else (BAR_PAD_PX / ctx.base_h if ctx.base_h else 0.0)
    h = 1.0 + pad
    return SizeRequest(min=h, preferred=h, max=h)


class PaneHeader(Widget):
    """The location bar above a pane: its current path, brighter when active."""

    def __init__(self, app: "XeFMApp", pane_name: str):
        self.app = app
        self.pane_name = pane_name

    def draw(self, ctx) -> None:
        pane = self.app.pane(self.pane_name)
        active = self.app.pm.active_pane == self.pane_name
        # Inset the text from the top/left/right; the surface fills the whole slot.
        pad_x, pad_y = _bar_pad(ctx)
        avail = max(0.0, ctx.size_units[0] - 2 * pad_x)
        virtual = pane.get("virtual")
        if virtual:
            # Not a directory: a search-results feed. Say so (and which pane an
            # operation will hit) rather than showing the — misleading — root path.
            mode = "content" if virtual["mode"] == "content" else "filename"
            n = len(pane["files"])
            label = f'⌕ "{virtual["query"]}" — {n} result{"" if n == 1 else "s"} ({mode})'
            text = elide(label, avail, where="end", measure=ctx.measure_text)
        elif self.app._is_archive(pane["path"]):
            # A browsed archive: show [archive.zip]/sub rather than the raw URI.
            label = _archive_header_label(str(pane["path"]))
            text = abbreviate_path(label, avail, measure=ctx.measure_text)
        else:
            # Drop whole directory components rather than cutting mid-name, so
            # every name still on screen is one the user can actually read.
            text = abbreviate_path(str(pane["path"]), avail, measure=ctx.measure_text)
        fg = ctx.theme.accent if active else ctx.theme.text
        ctx.draw_text(pad_x, pad_y, text, Style(fg=fg, attr=TextAttribute.BOLD))

    def measure(self, ctx, axis, available) -> SizeRequest:
        # Reserve a strip of top padding above the path (vector backends); the
        # bar is placed with size="content" so this height wins. See _bar_height.
        return _bar_height(ctx) if axis == "y" else SizeRequest()


class PaneFooter(Widget):
    """The info bar below a pane: dir/file counts, selection, sort, filter."""

    def __init__(self, app: "XeFMApp", pane_name: str):
        self.app = app
        self.pane_name = pane_name
        #: This footer's absolute rect (base units), captured each draw, so the
        #: controller can position the isearch overlay exactly on top of it.
        self.rect: tuple[float, float, float, float] | None = None

    def draw(self, ctx) -> None:
        self.rect = ctx.screen_rect
        pane = self.app.pane(self.pane_name)
        active = self.app.pm.active_pane == self.pane_name
        pad_x, _ = _bar_pad(ctx)  # left/right inset; the surface fills the slot
        avail = max(0.0, ctx.size_units[0] - 2 * pad_x)
        dirs, files = self.app.counts(pane)
        nsel = len(pane["selected_files"])
        sel = f" ({nsel} selected)" if nsel else ""
        filt = f"  |  Filter: {pane['filter_pattern']}" if pane["filter_pattern"] else ""
        sort = self.app.flm.get_sort_description(pane)
        text = f"{dirs} dirs, {files} files{sel}  |  {sort}{filt}"
        fg = ctx.theme.text if active else ctx.theme.muted_text
        style = Style(fg=fg, attr=TextAttribute.BOLD if active else TextAttribute.NORMAL)

        # Free/total space of the pane's filesystem, right-aligned so it stays put
        # (and readable) while the left summary elides as the pane narrows. Absent
        # for remote panes (S3/SCP) or a filesystem that can't be queried.
        reserved = 0.0
        disk = self.app.disk_free_total(pane)
        if disk is not None:
            free, total = disk
            disk_text = f"{format_size(free)} free / {format_size(total)}"
            disk_w = ctx.measure_text(disk_text)
            gap = ctx.measure_text("   ")
            # Draw only when the summary still gets room after the readout + gap;
            # on a very narrow pane, give the whole bar back to the summary.
            if disk_w + gap < avail:
                ctx.draw_text(pad_x + avail - disk_w, 0, disk_text, style)
                reserved = disk_w + gap

        left = elide(text, max(0.0, avail - reserved), measure=ctx.measure_text)
        ctx.draw_text(pad_x, 0, left, style)


class StatusBar(Widget):
    """The bottom bar: global key hints (XeFM's dynamic status line, simplified).

    The key labels are derived from the live keymap (§2.3) so the bar tracks
    user rebindings rather than repeating hardcoded strings."""

    #: (action, label) pairs shown as ``<key> <label>``, in bar order. The key
    #: for each is looked up from the keymap and formatted for display.
    _HINTS = (
        ("quit", "quit"),
        ("switch_pane", "switch"),
        ("select_file", "select"),
        ("select_all_files", "all-files"),
        ("open_item", "open"),
        ("go_parent", "parent"),
        ("search", "find"),
        ("filter", "filter"),
        ("toggle_hidden", "hidden"),
    )

    #: Shown in place of the hints while the footer isearch is open, so the bottom
    #: bar explains the isearch keys rather than the (now-inaccessible) global
    #: ones. These are isearch-mode internal keys, not configurable bindings.
    ISEARCH_HINTS = ("I-Search   ↑/↓ prev/next match   "
                     "↵ stop (save to filter history)   esc cancel")

    def __init__(self, app: "XeFMApp"):
        self.app = app
        self._hints_cache: str | None = None

    def _hints(self) -> str:
        """Build (and cache) the hint line from the keymap. The keymap is fixed
        for the process lifetime, so this is computed once."""
        if self._hints_cache is None:
            parts = []
            for action, label in self._HINTS:
                keys, _ = self.app.keys.get_keys_for_action(action)
                if keys:
                    key = self.app.keys.format_key_for_display(keys[0])
                    parts.append(f"{key} {label}")
            self._hints_cache = "   ".join(parts)
        return self._hints_cache

    def draw(self, ctx) -> None:
        # Left/right inset; the bottom padding is the extra row height reserved
        # by measure(), so the text stays at the top (y=0) of the taller slot.
        pad_x, _ = _bar_pad(ctx)
        avail = max(0.0, ctx.size_units[0] - 2 * pad_x)
        hints = self.ISEARCH_HINTS if self.app._isearch_active else self._hints()
        text = elide(hints, avail, where="end", measure=ctx.measure_text)
        ctx.draw_text(pad_x, 0, text, Style(fg=ctx.theme.muted_text))

    def measure(self, ctx, axis, available) -> SizeRequest:
        # Reserve a strip of bottom padding below the hints (vector backends);
        # placed with size="content" so this height wins. See _bar_height.
        return _bar_height(ctx) if axis == "y" else SizeRequest()


class _StreamToLog:
    """A ``sys.stdout`` / ``sys.stderr`` stand-in that funnels writes into the
    log pane, mirroring the terminal build's stdout/stderr capture so real-world
    output — a stray ``print``, a library warning, an uncaught traceback, and the
    WARNING+ records Python's ``logging.lastResort`` emits for our handler-less
    loggers — stays visible even when there is no terminal behind the GUI.

    Writes are line-buffered (a ``print`` that emits its text and its newline as
    two writes becomes one log line) and complete lines are handed to a
    thread-safe queue rather than the ``LogView`` directly: output can originate
    on worker threads (async listings, file ops, archives) that must never touch
    the widget. The UI thread drains the queue on its monitoring pump."""

    def __init__(self, source: str, sink: "queue.Queue", on_write=None):
        self.source = source  # "STDOUT" or "STDERR"
        self._sink = sink
        self._on_write = on_write  # wakes the UI thread to drain (event-driven mode)
        self._buffer = ""
        self._lock = threading.Lock()

    def write(self, text: str) -> int:
        wrote_line = False
        with self._lock:
            self._buffer += text
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                self._sink.put((self.source, line))
                wrote_line = True
        # Wake outside the lock: a worker thread posted a line; the UI thread must
        # drain it. No-op when nothing is draining the queue on a timer already.
        if wrote_line and self._on_write is not None:
            self._on_write()
        return len(text)

    def drain_partial(self) -> None:
        """Emit any buffered text not yet terminated by a newline. Called on
        restore so a trailing partial line is not silently dropped."""
        with self._lock:
            if self._buffer:
                self._sink.put((self.source, self._buffer))
                self._buffer = ""

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return False


class XeFMApp:
    """Controller: owns pane state and maps key actions onto it."""

    #: Default until ``__init__`` resolves it from the backend's capabilities.
    #: False means "drain queues via the polling tick" — also the right behavior
    #: for a partially constructed app (unit tests that drive listings manually).
    _event_driven = False

    def __init__(self, backend, left_dir: str, right_dir: str, *,
                 left_provided: bool = True, right_provided: bool = True,
                 state_manager=None):
        self.backend = backend
        # The log pane's copy chord follows the platform convention: Cmd-C on the
        # macOS GUI, Ctrl-C on the curses TUI and other GUI platforms (curses
        # never sees Cmd; Windows/Linux copy with Ctrl). See _copy_log_selection.
        self._log_copy_mod = "cmd" if type(backend).__name__ == "MacOSBackend" else "ctrl"
        # Load via ConfigManager (the shared singleton): this creates
        # ~/.xefm/config.py from the template on first run and reads the user's
        # config, filling any missing fields from the template. Instantiating
        # _config.Config() directly (as the port did) skipped both — the file was
        # never created and the user's settings were ignored.
        self.config = get_config()
        self.keys = KeyBindings(self.config.KEY_BINDINGS)
        # Central registry of running background tasks (file ops today; the seam
        # for future queued / non-modal tasks + a task-management UI).
        self.tasks = TaskManager()
        # Shared copy/move/delete engine (confirm dialogs + threaded progress),
        # used by both this view and the directory diff viewer; submits through
        # the shared task manager.
        self._fileops = FileOperationService(self.config, self.tasks)
        # Persistent cross-session state (window layout, pane dirs, cursor
        # positions, recent dirs). Injectable so tests can supply a temp-db
        # manager instead of touching ~/.xefm/state.db.
        self.state_manager = state_manager if state_manager is not None else get_state_manager()
        self._left_provided = left_provided
        self._right_provided = right_provided
        self.flm = FileListManager(self.config)
        self.pm = PaneManager(self.config, self._resolve_dir(left_dir),
                              self._resolve_dir(right_dir),
                              state_manager=self.state_manager,
                              file_list_manager=self.flm)
        # Restore saved window layout and pane paths/sort/filter *before* the
        # splitters are built (they read ``pm.left_pane_ratio`` /
        # ``_panes_fraction``) and before the first refresh lists a directory.
        self._restore_layout_and_paths()
        self.flm.refresh_files(self.pm.left_pane)
        self.flm.refresh_files(self.pm.right_pane)
        #: Recent-directory history for the History picker — a bounded, in-order
        #: list of visited paths, recorded on every directory change (see
        #: ``_record_history_path``) and persisted across restarts (#220).
        self._seed_history()

        #: Pane footers by name, so ``enter_isearch`` can read the active footer's
        #: captured rect and position the isearch overlay exactly on it.
        self._footers: dict[str, PaneFooter] = {}
        #: TTL cache for the footer's disk-usage readout, keyed by directory
        #: string → ``(monotonic_timestamp, (free, total) | None)``. See
        #: ``disk_free_total`` and ``DISK_USAGE_TTL``.
        self._disk_usage_cache: dict[str, tuple[float, tuple[int, int] | None]] = {}
        #: Incremental-search state. The prompt is an overlay layer pinned to the
        #: pane footer (``ISearchBar``); the list above stays visible and its
        #: cursor keeps moving as you type. ``_isearch_origin`` is the pre-search
        #: cursor (restored on cancel); ``_isearch_matches`` caches the current
        #: hit indices for Up/Down navigation; ``_isearch_active`` only drives the
        #: bottom status-bar hint line.
        self._isearch_active = False
        self._isearch_origin = 0
        self._isearch_matches: list[int] = []
        self._isearch_bar: "ISearchBar | None" = None

        #: The pane a native file-drag started from — set by ``_start_drag`` and
        #: cleared once the session ends in ``_on_drag_complete``. Lets a drop
        #: routed back to the *same* pane be recognised as a released-in-place
        #: gesture and cancelled silently rather than treated as a copy (#230).
        self._drag_source_pane: "str | None" = None
        #: Set by ``_on_drop`` when that drag was released in place on its source
        #: pane, so ``_on_drag_complete`` (which the OS still ends as ``copy``)
        #: suppresses its "Dragged … out" log for the cancelled no-op (#230).
        self._drag_cancelled_in_place = False

        self.panel = Panel(backend)
        # Guarantee text legibility across every theme: each run is lifted to a
        # readability floor against its own background at draw time (floor-only,
        # so designed colors that already read are untouched). This is what keeps
        # directory names, the log, dialogs, and the diff views readable on the
        # light themes and the low-contrast accents without per-widget tuning.
        self.panel.auto_ink = True
        # The selectable theme list — built-ins plus any the user registered in
        # config.THEMES — held on the instance so the picker (View ▸ Theme) and the
        # T cycle switch among all of them at run time. Resolved before the menu
        # (which lists them) and the widgets (which read the active theme) are
        # built. Restore the theme the user last switched to (persisted by
        # ``_apply_theme``); default to the first theme (Dark+) on a fresh profile
        # or if that theme no longer exists.
        self.themes = _build_theme_list(self.config)
        # Motion preference, before any theme is applied: a reduced-motion launch
        # must never play the opening beat even once, and the background the theme
        # is about to set has to come up already stopped rather than animate and
        # then coast down.
        self.panel.set_reduced_motion(bool(getattr(self.config, "REDUCED_MOTION", False)))
        start = self.state_manager.get_state("theme")
        self._theme_index = next(
            (i for i, (name, _t) in enumerate(self.themes) if name == start), 0)
        self.panel.theme = self.themes[self._theme_index][1]
        # Apply the restored theme's recommended post effect at launch too (the
        # backend stores it and re-attaches it once its window opens).
        self._apply_post_effect(self.themes[self._theme_index][1])
        self._apply_background(self.themes[self._theme_index][1])
        self._apply_surface_opacity(self.themes[self._theme_index][1])
        self.left_view = FilePane(
            self.pm.left_pane,
            config=self.config,
            on_click=lambda i: self._on_click("left", i),
            on_context=lambda i, x, y: self._show_context_menu("left", i, x, y),
            on_drag=lambda i, ev: self._start_drag("left", i, ev),
            on_drop=lambda i, paths: self._on_drop("left", i, paths),
        )
        self.right_view = FilePane(
            self.pm.right_pane,
            config=self.config,
            on_click=lambda i: self._on_click("right", i),
            on_context=lambda i, x, y: self._show_context_menu("right", i, x, y),
            on_drag=lambda i, ev: self._start_drag("right", i, ev),
            on_drop=lambda i, paths: self._on_drop("right", i, paths),
        )
        # Same chrome inset as the bars: the log's surface fills its slot, its
        # text breathes in from the frame (BAR_PAD_PX on GUI, flush on the grid).
        self.log = LogView(max_lines=2000, auto_scroll=True, wrap=True, padding_px=BAR_PAD_PX)
        self.status = StatusBar(self)
        # One Menu model drives the OS-native menu bar on macOS (an NSMenu) and an
        # in-window strip on curses — the Panel resolves which, so we never branch.
        self.menu_bar = MenuBar(self._build_menu())
        self._sync_active()

        # Two draggable splitters: the file panes side-by-side (vertical handle),
        # and the panes-over-log split (horizontal handle). The status bar stays
        # a fixed bottom row outside the splitters.
        self.pane_splitter = Splitter(
            self._pane_column("left", self.left_view),
            self._pane_column("right", self.right_view),
            orientation="horizontal",
            fraction=self.pm.left_pane_ratio,
            min_first=10, min_second=10,
        )
        self.content_splitter = Splitter(
            self.pane_splitter, self.log,
            orientation="vertical",
            fraction=self._panes_fraction,
            min_first=5, min_second=2,
            # No handle row on the grid: the pane footer already sits directly
            # above the log and serves as the divider, so a separate handle cell
            # would waste a row. Still draggable via the grab margin; the vector
            # backend keeps its hairline.
            flat=True,
            # The footer IS the visible divider, so make its whole height (the
            # 1-base-unit ``Item(footer, size=1)`` slot in ``_pane_column``)
            # grabbable — not just the hairline at its bottom edge. Without this
            # the vector backend's grab margin is a few pixels and the footer
            # reads as draggable but mostly isn't. Only the first (upper) side is
            # widened; the log below keeps the default margin.
            grab_first=1.0,
        )
        self.panel.set_layout(
            VSplit(
                # The MenuBar self-sizes via "content": a 1-row strip on curses,
                # zero height on macOS (it installs the native bar instead), so
                # no row branch. Without "content" the item would flex and eat
                # half the window. It carries no divider after it — when it
                # collapses to 0 height (macOS), a divider here would float at the
                # very top — so the subtle divider lives on the nested split below,
                # only between the content and the status bar.
                Item(self.menu_bar, size="content", hints={"surface": "header"}),
                Item(
                    VSplit(
                        # ``reveal_mode: transparent`` drops the content surface fill
                        # entirely whenever a wallpaper (the cube) is present — so the
                        # file / log panes show it at full strength at any ``opacity``,
                        # even 1 — while the chrome bars (header / footer / status)
                        # keep their opacity-dissolved fill (``opacity`` tunes those).
                        Item(self.content_splitter, weight=1,
                             hints={"surface": "content", "reveal_mode": "transparent"}),
                        # "content" (not size=1): the status bar measures itself a
                        # touch taller to pad its hints up from the window's bottom.
                        Item(self.status, size="content", hints={"surface": "status"}),
                        divider="subtle",
                    ),
                    weight=1,
                ),
            ),
        )
        # (the theme + picker list were resolved above, before the menu / widgets)
        self.log_info(f"XeFM on PuiKit — {self.pm.left_pane['path']}")
        # Files are listed now, so the saved cursor filenames can be matched.
        self._restore_cursor_positions()

        # Filesystem monitoring: observer threads post pane names to
        # ``reload_queue``; the main thread drains it via an animation tick (and
        # opportunistically on every event). ``_sync_monitored_dirs`` re-points
        # the watchers whenever a pane navigates, so navigation code stays
        # unaware of monitoring. Auto-disables cleanly if watchdog is missing.
        self.reload_queue: queue.Queue = queue.Queue()
        # Completed async directory listings (remote panes list off the UI
        # thread; see ``_list_pane``): worker threads post
        # ``(pane_name, gen, result, on_ready)`` here and the main thread drains
        # it on the same tick as ``reload_queue``.
        self._result_queue: queue.Queue = queue.Queue()
        self.file_monitor = FileMonitorManager(self.config, self)
        self._monitored: dict[str, object] = {"left": None, "right": None}
        self._sync_monitored_dirs()

        # Idle-CPU strategy. When the backend can accept work from other threads
        # (native run loop → ``dispatches_to_main_thread``), go fully event-driven:
        # each producer (fs watcher, listing worker, stdout/stderr streams) wakes
        # the UI thread to drain, so there is NO idle polling timer at all. A burst
        # of producer signals coalesces into at most one pending main-thread hop
        # (``_wake_lock``/``_wake_pending``). On a poll-loop backend (curses) that
        # can't dispatch, fall back to the animation-tick pump that drains queues
        # each frame. See ``_wake_pump`` / ``_reload_tick``.
        self._event_driven = self.panel.dispatches_to_main_thread
        self._wake_lock = threading.Lock()
        self._wake_pending = False
        # Guard against a render that feeds itself: see ``_wake_pump``. The UI
        # thread is whichever thread builds the app — the same one that runs the
        # backend's event loop.
        self._rendering = False
        self._ui_thread_ident = threading.get_ident()
        if not self._event_driven:
            self.panel.request_animation_ticks(self._reload_tick)

        # Route stdout/stderr into the log pane (as the terminal build does), so
        # output that would otherwise vanish behind the GUI surfaces here: worker
        # threads post complete lines to ``_log_queue`` and the UI thread drains
        # it on the monitoring pump. Redirected last, once everything above has
        # initialized, and undone in ``run``'s finally.
        self._log_queue: queue.Queue = queue.Queue()
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr
        sys.stdout = _StreamToLog("STDOUT", self._log_queue, on_write=self._wake_pump)
        sys.stderr = _StreamToLog("STDERR", self._log_queue, on_write=self._wake_pump)

    def _pane_column(self, name: str, view: FilePane) -> LayoutView:
        # A LayoutView wraps the header/list/footer sub-layout as a single widget
        # so it can be a Splitter child (Splitter hosts widgets, not layouts).
        # A "subtle" divider draws a hairline between the path/info bars and the
        # file list on GUI (zero base-unit cost) — without it the footer's status
        # surface matches the content background and the boundary vanishes; on TUI
        # nothing is reserved and the surface-role contrast does the separating.
        footer = PaneFooter(self, name)
        # Kept so enter_isearch can read the footer's captured rect and drop the
        # isearch overlay exactly on it.
        self._footers[name] = footer
        return LayoutView(VSplit(
            # "content" (not size=1): the header measures itself a touch taller so
            # it can pad the path text down from the window's top edge (§_bar_pad).
            Item(PaneHeader(self, name), size="content", hints={"surface": "header"}),
            Item(view, weight=1, hints={"surface": "content"}),
            Item(footer, size=1, hints={"surface": "footer"}),
            divider="subtle",
        ))

    @staticmethod
    def _resolve_dir(path_str: str) -> Path:
        """Make a startup directory absolute (expanding ``~``) so the pane header
        and every path derived from it — parents on ``go_parent``, children from
        ``iterdir``, the ``selected_files`` keys, history entries, and file-op
        destinations — is a full path, not one relative to the launch directory.
        Falls back to ``absolute`` (a plain cwd join, no symlink resolution) if
        ``resolve`` fails for an odd input."""
        p = Path(path_str).expanduser()
        try:
            return p.resolve()
        except Exception:
            return p.absolute()

    # --- persistent state ----------------------------------------------------

    def _restore_layout_and_paths(self) -> None:
        """Restore window layout and each pane's directory / sort / filter from
        the saved session, *before* the splitters and file lists are built.

        A pane's saved directory is only re-applied when the user did not pass an
        explicit startup directory for it on the command line, and only if that
        directory still exists; sort mode and filter are always restored. Fully
        best-effort — the log view does not exist yet, so failures stay silent
        rather than blocking startup on a corrupt or absent state store."""
        self._panes_fraction = PANES_FRACTION
        try:
            self.state_manager.update_session_heartbeat()
            self.state_manager.cleanup_non_existing_directories()

            layout = self.state_manager.load_window_layout()
            if layout:
                ratio = layout.get('left_pane_ratio', self.pm.left_pane_ratio)
                self.pm.left_pane_ratio = max(0.1, min(0.9, ratio))
                log_h = layout.get('log_height_ratio', 1.0 - PANES_FRACTION)
                self._panes_fraction = max(0.1, min(0.95, 1.0 - log_h))

            self._restore_one_pane('left', self.pm.left_pane, self._left_provided)
            self._restore_one_pane('right', self.pm.right_pane, self._right_provided)
        except Exception:
            pass

    def _restore_one_pane(self, name: str, pane: dict, cmdline_provided: bool) -> None:
        state = self.state_manager.load_pane_state(name)
        if not state:
            return
        if not cmdline_provided:
            try:
                saved = Path(state['path'])
                if saved.exists():
                    pane['path'] = saved
            except Exception:
                pass
        pane['sort_mode'] = state.get('sort_mode', pane['sort_mode'])
        pane['sort_reverse'] = state.get('sort_reverse', pane['sort_reverse'])
        pane['filter_pattern'] = state.get('filter_pattern', pane['filter_pattern'])

    def _display_height(self) -> int:
        """Rows available for a file list, used to keep a restored cursor on
        screen. Best-effort: falls back to a sane default before first layout."""
        try:
            _w, h = self.backend.size
            return max(1, int(h) - 4)
        except Exception:
            return 20

    def _restore_cursor_positions(self) -> None:
        """Move each pane's cursor to the file remembered for its directory."""
        try:
            display_height = self._display_height()
            self.pm.restore_cursor_position(self.pm.left_pane, display_height)
            self.pm.restore_cursor_position(self.pm.right_pane, display_height)
        except Exception:
            pass

    def _remember_cursor(self, pane: dict) -> None:
        """Persist the cursor position of the directory ``pane`` currently shows so
        a later revisit (entering a child, jumping to a favorite/drive/history) can
        land the cursor back on the same file. Left and right panes are remembered
        independently. No-op for a virtual (search-results) pane, whose rows aren't
        a single directory's listing. Call this *before* changing ``pane['path']``."""
        if pane.get("virtual"):
            return
        try:
            self.pm.save_cursor_position(pane)
        except Exception:
            pass

    def _restore_remembered_cursor(self, pane: dict) -> None:
        """``on_ready`` hook for a directory change: land the cursor on the file
        remembered for this pane's new directory, or leave it at the top when
        nothing is remembered."""
        try:
            self.pm.restore_cursor_position(pane, self._display_height())
        except Exception:
            pass

    def _save_application_state(self) -> None:
        """Persist window layout, pane state, cursor positions, and recent dirs.
        Called on quit; best-effort so a state-store failure never blocks exit."""
        try:
            self.state_manager.save_window_layout(
                self.pane_splitter.fraction,
                1.0 - self.content_splitter.fraction,
            )
            self.state_manager.save_pane_state('left', self.pm.left_pane)
            self.state_manager.save_pane_state('right', self.pm.right_pane)
            self.pm.save_cursor_position(self.pm.left_pane)
            self.pm.save_cursor_position(self.pm.right_pane)

            # Persist the full visited-directory trail (most-recent-first,
            # de-duplicated) so the History picker survives restarts (#220),
            # rather than only the two panes' final paths.
            self.state_manager.save_recent_directories(
                self._recent_dirs_most_recent_first(), _HISTORY_MAX)

            self.state_manager.cleanup_session()
        except Exception as e:
            self.log_info(f"Could not save application state: {e}")

    def _quit(self) -> None:
        """Stop monitoring, save state, then end the event loop."""
        if getattr(self, "file_monitor", None) is not None:
            self.file_monitor.stop_monitoring()
        self._save_application_state()
        self.backend.quit()

    # --- filesystem monitoring -----------------------------------------------

    def _sync_monitored_dirs(self) -> None:
        """Point each pane's watcher at that pane's current directory, (re)starting
        monitoring on the ones that changed. Called on every tick, so navigating a
        pane transparently moves its watcher — no navigation site needs to know."""
        if not self.file_monitor.is_monitoring_enabled():
            return
        for name in ("left", "right"):
            path = self.pane(name)["path"]
            if path != self._monitored[name]:
                self._monitored[name] = path
                self.file_monitor.update_monitored_directory(name, path)

    def _pump_monitoring(self) -> bool:
        """Re-point watchers, apply queued reloads, and install any async remote
        listings that have completed. Returns True if a pane changed (so the
        caller re-renders)."""
        self._sync_monitored_dirs()
        reloaded = self._process_reload_queue()
        listed = self._process_result_queue()
        loading = self._pump_loading_indicator()
        captured = self._drain_captured_output()
        return reloaded or listed or loading or captured

    #: Log-pane styles for captured streams. stdout leaves its color unset so it
    #: resolves to ``theme.text`` at draw time (tracking the theme like
    #: ``log_info``) but dimmed, so captured output reads as recessive under XeFM's
    #: own messages. stderr keeps a fixed warning red so an error stands out on
    #: any theme.
    _STDERR_STYLE = Style(fg=(230, 130, 120))
    _STDOUT_STYLE = Style(attr=TextAttribute.DIM)

    def _drain_captured_output(self) -> bool:
        """Append any stdout/stderr lines captured since the last pump to the log
        pane. Runs on the UI thread (only place the ``LogView`` is touched); the
        queue is fed by the ``_StreamToLog`` streams, possibly from worker
        threads. Returns True if anything was appended (so the caller redraws)."""
        appended = False
        while True:
            try:
                source, line = self._log_queue.get_nowait()
            except queue.Empty:
                break
            style = self._STDERR_STYLE if source == "STDERR" else self._STDOUT_STYLE
            self.log.append(line, style)
            appended = True
        return appended

    def _pane_name_of(self, pane: dict) -> str:
        return "left" if pane is self.pm.left_pane else "right"

    #: How long a listing may run before the pane shows a "Loading…" indicator.
    #: Below this, a fast (local) listing lands and swaps in with no flash; only a
    #: genuinely slow directory (a network mount, a spun-down disk, a huge dir, or
    #: a remote path) ever shows the indicator. See ``_pump_loading_indicator``.
    _LOADING_INDICATOR_DELAY = 0.12

    def _list_pane(self, pane_name: str, *, on_ready=None) -> None:
        """(Re)list a pane's directory on a worker thread, so the UI never blocks
        on the ``iterdir`` + per-entry ``stat`` — no matter whether the path is
        local, a slow network mount, a spun-down disk, or a remote (S3/SSH) URL.
        The result is installed on the UI thread by ``_process_result_queue``.

        A fast (typically local) listing completes within a tick and swaps in with
        no visible change; only one still pending past ``_LOADING_INDICATOR_DELAY``
        shows a "Loading…" state (``_pump_loading_indicator``), so ordinary
        navigation never flashes an indicator.

        Single-flight per pane: each call bumps the pane's ``_load_gen``; a result
        whose generation no longer matches (a newer navigation superseded it) is
        dropped. ``on_ready(pane)`` runs once the files are in place (on the tick),
        for cursor placement etc."""
        pane = self.pane(pane_name)
        gen = pane["_load_gen"] = pane.get("_load_gen", 0) + 1
        pane["loading"] = True
        pane["_load_started"] = time.monotonic()
        pane["_loading_shown"] = False
        # Clear the old listing so a stale entry can't be acted on under the new
        # path; the pane shows blank (then "Loading…" only if slow) until the
        # result lands. Snapshot the inputs so the worker never reads the pane
        # dict — the UI thread owns it.
        pane["files"] = []
        pane["file_info"] = {}
        path = pane["path"]
        filter_pattern = pane["filter_pattern"]
        sort_mode = pane["sort_mode"]
        sort_reverse = pane["sort_reverse"]

        def worker() -> None:
            result = self.flm.compute_listing(
                path, filter_pattern=filter_pattern,
                sort_mode=sort_mode, sort_reverse=sort_reverse,
            )
            self._result_queue.put((pane_name, gen, result, on_ready))
            self._wake_pump()  # wake the UI thread to install the listing

        threading.Thread(target=worker, name=f"xefm-list-{pane_name}", daemon=True).start()

        # Event-driven mode has no permanent tick, so a slow listing would never
        # surface its "Loading…" indicator; a transient tick runs while any pane
        # is loading and retires itself the moment the listing lands.
        if self._event_driven:
            self.panel.request_animation_ticks(self._loading_tick)

    def _process_result_queue(self) -> bool:
        """Install completed async listings on the UI thread, dropping any that a
        newer navigation superseded (stale generation)."""
        applied = False
        while True:
            try:
                pane_name, gen, result, on_ready = self._result_queue.get_nowait()
            except queue.Empty:
                break
            pane = self.pane(pane_name)
            if gen != pane.get("_load_gen"):
                continue  # superseded by a newer navigation
            self.flm.apply_listing(pane, result)
            pane["loading"] = False
            pane["_loading_shown"] = False
            self._animate_pane_text(pane_name)
            if on_ready:
                on_ready(pane)
            applied = True
        return applied

    def _animate_pane_text(self, pane_name: str) -> None:
        """Replay the theme's arriving-text effect over a pane whose listing was
        just replaced.

        The pane widget stays on screen across a directory change, so PuiKit's
        automatic "animate on appear" trigger correctly does not fire — that
        trigger deliberately ignores content changing in place, or scrolling a
        listing would re-decode every row on every keypress. A wholesale swap is
        the case only the app can recognize, so it says so here. One call for the
        pane, not one per row, and a no-op unless a theme opted in.

        Silent no-op before the views exist: the first listings are requested in
        ``__init__`` and can land before the FilePanes are constructed. Nothing is
        lost — a pane that has never been drawn animates on its first draw
        anyway, through the appear trigger this method exists to supplement."""
        view = getattr(self, f"{pane_name}_view", None)
        if view is not None:
            self.panel.animate_text(view)

    def _listings_pending(self) -> bool:
        """True while any pane's async listing is still in flight (worker running
        or its result not yet drained)."""
        return any(self.pane(n).get("loading") for n in ("left", "right"))

    def _settle_listings(self, timeout: float = 2.0) -> None:
        """Block until every in-flight async listing has completed and been
        installed, draining results as workers post them.

        The interactive UI never calls this — it drains listings on the idle tick
        (``_reload_tick``) so it never blocks. It exists for callers that need a
        directory listed before they can proceed deterministically — chiefly unit
        tests, which navigate and then assert on ``pane["files"]``."""
        deadline = time.monotonic() + timeout
        self._process_result_queue()
        while self._listings_pending():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                item = self._result_queue.get(timeout=remaining)
            except queue.Empty:
                break
            self._result_queue.put(item)
            self._process_result_queue()

    def _pump_loading_indicator(self) -> bool:
        """Reveal the "Loading…" indicator on any pane whose listing has been
        pending past ``_LOADING_INDICATOR_DELAY``, forcing exactly one re-render as
        it crosses the threshold (so a slow directory shows the indicator without a
        fast one ever flashing it). Returns True if a pane just crossed."""
        crossed = False
        now = time.monotonic()
        for name in ("left", "right"):
            pane = self.pane(name)
            if (pane.get("loading") and not pane.get("_loading_shown")
                    and now - pane.get("_load_started", now) >= self._LOADING_INDICATOR_DELAY):
                pane["_loading_shown"] = True
                crossed = True
        return crossed

    def _reload_tick(self) -> bool:
        """Animation-tick pump: drains reload requests on idle. Stays registered
        for the app's lifetime (returns True). Used only on backends that can't
        dispatch to the main thread; the event-driven path uses ``_wake_pump``."""
        if self._pump_monitoring():
            self._pump_render()
        return True

    # --- event-driven pump (no idle timer) -----------------------------------

    def _wake_pump(self) -> None:
        """Ask the UI thread to drain the monitoring queues. Thread-safe and
        callable from any producer thread (fs watcher, listing worker, log
        streams). Coalesces a burst of signals into at most one pending
        main-thread hop. No-op on a poll-loop backend, where the animation-tick
        pump drains queues each frame instead."""
        if not self._event_driven:
            return
        # A write from the UI thread *during* a render must not schedule another
        # render. stdout/stderr are routed into the log pane, so a single stray
        # write from the draw path (a `logger.warning` on a handler-less logger
        # reaches stderr via logging.lastResort) would otherwise self-sustain:
        # render → write → wake → drain → render → …, pegging a core while the
        # UI still responds. The line is not lost — it stays queued and the next
        # pump drains it; it just no longer causes the frame that re-emits it.
        # Only the UI thread is skipped: a worker racing a render is exactly the
        # case this method exists to serve, and must still wake it.
        if self._rendering and threading.get_ident() == self._ui_thread_ident:
            return
        with self._wake_lock:
            if self._wake_pending:
                return
            self._wake_pending = True
        self.panel.call_on_main_thread(self._on_pump_wake)

    def _on_pump_wake(self) -> None:
        """Main thread: clear the pending flag BEFORE draining so a producer that
        enqueues mid-drain re-arms a fresh wake (never a lost update), then drain
        and render if anything changed."""
        with self._wake_lock:
            self._wake_pending = False
        if self._pump_monitoring():
            self._pump_render()

    def _pump_render(self) -> None:
        """Render a pump-driven frame with the self-feeding guard raised, so
        output written from the draw path cannot schedule the next frame. Only
        the pump's own renders need this: a handler-triggered render that writes
        schedules at most one wake, and that wake lands here, where the chain
        stops."""
        self._rendering = True
        try:
            self.panel.render()
        finally:
            self._rendering = False

    def _any_pane_loading(self) -> bool:
        return any(self.pane(n).get("loading") for n in ("left", "right"))

    def _loading_tick(self) -> bool:
        """Transient tick, registered only while a listing is in flight in
        event-driven mode: reveals the "Loading…" indicator at the delay
        threshold and installs a completed listing. Unregisters (returns False)
        once no pane is loading, so it never runs at idle."""
        if self._pump_monitoring():
            self._pump_render()
        return self._any_pane_loading()

    def _process_reload_queue(self) -> bool:
        reloaded = False
        while True:
            try:
                pane_name = self.reload_queue.get_nowait()
            except queue.Empty:
                break
            if self._handle_reload_request(pane_name):
                reloaded = True
        return reloaded

    def _handle_reload_request(self, pane_name: str) -> bool:
        """Reload one pane's file list while preserving user context: keep the
        cursor on the same filename if it survives, otherwise the nearest name
        alphabetically, and hold the scroll offset where it can still show it.

        Returns True if the pane was reloaded, False for an unknown pane name."""
        if pane_name == "left":
            pane = self.pm.left_pane
        elif pane_name == "right":
            pane = self.pm.right_pane
        else:
            return False

        # A virtual (search-results) pane isn't a directory listing — a
        # filesystem event on its old watched root must not re-list and blow the
        # result set away. Monitoring is effectively suspended while it is virtual;
        # a mutating op reconciles it explicitly via _refresh -> _refresh_virtual.
        if pane.get("virtual"):
            return False

        old_focused = pane["focused_index"]
        old_scroll = pane["scroll_offset"]
        selected_filename = None
        if pane["files"] and 0 <= old_focused < len(pane["files"]):
            selected_filename = pane["files"][old_focused].name

        def restore(pane: dict) -> None:
            files = pane["files"]
            if selected_filename and files:
                idx = next((i for i, f in enumerate(files)
                            if f.name == selected_filename), None)
                if idx is None:
                    # Selected file is gone: land on where it would have sorted, so
                    # the cursor stays near its old neighbours (list is name-sorted).
                    idx = 0
                    for i, f in enumerate(files):
                        if f.name < selected_filename:
                            idx = i + 1
                        else:
                            break
                    idx = min(idx, len(files) - 1)
                pane["focused_index"] = idx

                display_height = self._display_height()
                max_offset = max(0, len(files) - display_height)
                pane["scroll_offset"] = min(old_scroll, max_offset)
                if pane["focused_index"] < pane["scroll_offset"]:
                    pane["scroll_offset"] = pane["focused_index"]
                elif pane["focused_index"] >= pane["scroll_offset"] + display_height:
                    pane["scroll_offset"] = pane["focused_index"] - display_height + 1
            else:
                pane["focused_index"] = 0
                pane["scroll_offset"] = 0

        # Local: lists + restores synchronously (unchanged). Remote: lists on a
        # worker (a polled remote reload no longer blocks the tick), restoring the
        # cursor when the result lands.
        self._list_pane(pane_name, on_ready=restore)
        return True

    # --- state ---------------------------------------------------------------

    def active_pane(self) -> dict:
        return self.pm.get_current_pane()

    def pane(self, name: str) -> dict:
        return self.pm.left_pane if name == "left" else self.pm.right_pane

    def counts(self, pane: dict) -> tuple[int, int]:
        """(dirs, files) in a pane, read from the file-info cache."""
        info = pane.get("file_info", {})
        dirs = sum(1 for f in pane["files"] if info.get(str(f), {}).get("is_dir"))
        return dirs, len(pane["files"]) - dirs

    def disk_free_total(self, pane: dict) -> tuple[int, int] | None:
        """``(free_bytes, total_bytes)`` for the pane's filesystem, or ``None``
        when the path is remote (S3/SCP) or the filesystem can't be queried
        (e.g. the directory was just deleted, or it's a browsed archive).

        Cached per path with a short TTL (:data:`DISK_USAGE_TTL`): the footer
        calls this every frame, and an uncached ``statvfs`` per draw would be
        wasteful and could stall on a slow network mount."""
        path = pane["path"]
        if path.is_remote():
            return None
        key = str(path)
        now = time.monotonic()
        cached = self._disk_usage_cache.get(key)
        if cached is not None and now - cached[0] < DISK_USAGE_TTL:
            return cached[1]
        try:
            usage = shutil.disk_usage(key)
            result = (usage.free, usage.total)
        except OSError:
            # Expected/benign for a display-only readout (missing path, archive
            # URI, unsupported filesystem): fall back to showing nothing.
            result = None
        self._disk_usage_cache[key] = (now, result)
        return result

    def log_info(self, message: str) -> None:
        """Append a line to the log pane in the theme's primary text color. The
        color is left unset so the LogView resolves it to ``theme.text`` at draw
        time — the whole log then tracks the active theme (green on a monochrome
        theme, dark on a light one) and recolors on a theme switch, instead of a
        fixed near-white that clashes with monochrome themes like Phosphor."""
        self.log.append(message)

    def _log_result(self, result) -> None:
        """Log the (success, message) a FileListManager action returns."""
        if isinstance(result, tuple) and len(result) == 2 and result[1]:
            self.log_info(result[1])

    def _sync_active(self) -> None:
        self.left_view.active = self.pm.active_pane == "left"
        self.right_view.active = self.pm.active_pane == "right"

    def _on_click(self, pane_name: str, index: int) -> None:
        """A FilePane was left-clicked: make it active and move the cursor."""
        self.pm.active_pane = pane_name
        self._sync_active()
        self.active_pane()["focused_index"] = index

    def _refresh(self, pane: dict, *, on_ready=None) -> None:
        """Re-list ``pane`` after a directory change: reset the cursor, record
        history, and (re)list — synchronously for a local path, on a worker for a
        remote one (see ``_list_pane``). ``on_ready(pane)`` runs once the files
        are in place, for callers that then place the cursor by name.

        For a **virtual pane** (a search-results feed) there is no directory to
        re-list: rebuild the flat listing from the result set in place (re-stat
        survivors, re-sort, re-filter — see ``FileListManager.refresh_files``),
        preserving the cursor rather than resetting it, and fire ``on_ready``
        synchronously. This is the post-op reconciliation path — every existing
        ``self._refresh(pane)`` call site keeps working after a mutating op."""
        if pane.get("virtual"):
            self.flm.refresh_files(pane)
            if on_ready is not None:
                on_ready(pane)
            return
        pane["focused_index"] = 0
        pane["scroll_offset"] = 0
        self._record_history_path(str(pane["path"]))
        self._list_pane(self._pane_name_of(pane), on_ready=on_ready)

    def _seed_history(self) -> None:
        """Populate the recent-directory history from the persisted
        ``recent.directories`` (oldest first, so the History picker survives
        restarts, #220), then the two current pane directories, which thus become
        the most-recent entries."""
        self._history: list[str] = []
        for p in reversed(self.state_manager.load_recent_directories()):
            self._record_history_path(str(p))
        for p in (self.pm.left_pane["path"], self.pm.right_pane["path"]):
            self._record_history_path(str(p))

    def _record_history_path(self, path: str) -> None:
        """Append ``path`` to the recent-directory history, coalescing an
        immediate repeat (a same-directory refresh from create/rename doesn't add
        a duplicate) and capping the list length."""
        if not self._history or self._history[-1] != path:
            self._history.append(path)
            del self._history[:-_HISTORY_MAX]

    def _recent_dirs_most_recent_first(self) -> list[str]:
        """The visited-directory history as a most-recent-first, de-duplicated
        list — the order the History picker shows and the form persisted to the
        state DB (``recent.directories``)."""
        seen: set[str] = set()
        out: list[str] = []
        for p in reversed(self._history):
            if p not in seen:
                seen.add(p)
                out.append(p)
        return out

    # --- actions -------------------------------------------------------------

    def dispatch(self, action: str | None) -> bool:
        """Apply an action to the active pane. Returns True if a redraw is needed."""
        if action is None:
            return False
        pane = self.active_pane()
        files = pane["files"]
        last = max(0, len(files) - 1)
        idx = pane["focused_index"]

        if action == "quit":
            self.confirm_quit()
            return False
        if action == "cursor_up":
            pane["focused_index"] = max(0, idx - 1)
        elif action == "cursor_down":
            pane["focused_index"] = min(last, idx + 1)
        elif action == "page_up":
            pane["focused_index"] = max(0, idx - 10)
        elif action == "page_down":
            pane["focused_index"] = min(last, idx + 10)
        # --- selection (reuses FileListManager) ---
        elif action == "select_file":  # SPACE: toggle current, move down
            self._log_result(self.flm.toggle_selection(pane, move_cursor=True, direction=1))
        elif action == "select_file_up":  # Shift-SPACE: toggle, move up
            self._log_result(self.flm.toggle_selection(pane, move_cursor=True, direction=-1))
        elif action == "select_all_files":  # A: toggle all files
            self._log_result(self.flm.toggle_all_files_selection(pane))
        elif action == "select_all_items":  # Shift-A: toggle all items
            self._log_result(self.flm.toggle_all_items_selection(pane))
        elif action == "select_all":  # HOME: select every item
            pane["selected_files"] = {str(f) for f in files}
        elif action == "unselect_all":  # END: clear selection
            pane["selected_files"].clear()
        elif action == "switch_pane":
            self.pm.active_pane = "right" if self.pm.active_pane == "left" else "left"
            self._sync_active()
        elif action == "open_item":
            self._open(pane)
        elif action == "go_parent":
            self._go_parent(pane)
        elif action == "nav_left":
            # Context-aware LEFT (ttk XeFM): from the right pane, move focus to the
            # left pane; already in the left pane, go to its parent directory.
            if self.pm.active_pane == "right":
                self.pm.active_pane = "left"
                self._sync_active()
            else:
                self._go_parent(pane)
        elif action == "nav_right":
            # Context-aware RIGHT (ttk XeFM): from the left pane, move focus to the
            # right pane; already in the right pane, go to its parent directory.
            if self.pm.active_pane == "left":
                self.pm.active_pane = "right"
                self._sync_active()
            else:
                self._go_parent(pane)
        elif action == "toggle_hidden":
            self.flm.show_hidden = not self.flm.show_hidden
            self._list_pane(self._pane_name_of(pane))
            self.log_info(f"Hidden files: {'shown' if self.flm.show_hidden else 'hidden'}")
        elif action == "toggle_color_scheme":
            self._cycle_theme()  # falls through to a full re-render below
        elif action in ("quick_sort_name", "quick_sort_size",
                        "quick_sort_date", "quick_sort_ext"):
            self._quick_sort(action[len("quick_sort_"):])
        elif action == "sort_menu":
            self.show_sort_menu()
            return False  # the menu popup drives its own redraw
        elif action == "clear_filter":
            if pane["filter_pattern"]:
                self.flm.apply_filter(pane, "")
                self.log_info("Filter cleared")
            else:
                self.log_info("No filter to clear")
        elif action == "sync_current_to_other":
            # O = go to the other pane's location, landing the cursor there.
            other = self.pm.get_inactive_pane()
            other_hit = self._virtual_focused_entry(other)
            if other_hit is not None:
                # Other pane is a results view: its "location" is the highlighted
                # hit's directory, cursor on that file.
                self._go_to_dir(pane, other_hit.parent, other_hit.name)
                self.log_info(f"Go to: {other_hit}")
            elif pane.get("virtual"):
                # Standing on the results view: O behaves like a normal pane —
                # leave the results and open the other pane's directory (cursor
                # synced to the other pane's cursor).
                self._go_to_dir(pane, other["path"], self._focused_name(other))
                self.log_info(f"Go to {other['path']}")
            elif pane["path"] == other["path"]:
                # Both panes already show the same directory: a second O moves
                # this pane's cursor onto the file the other pane is highlighting.
                self.pm.sync_cursor_to_other_pane(self.log_info)
            elif self.pm.sync_current_to_other(self.log_info):
                self._list_pane(self._pane_name_of(self.active_pane()))
        elif action == "sync_other_to_current":
            # From the results pane, Shift-O reveals the highlighted result in the
            # *other* pane, keeping the results here. If instead the *other* pane
            # is the results view, there is nowhere to send a directory — block it.
            if self._reveal_result_other():
                pass
            elif self.pm.get_inactive_pane().get("virtual"):
                self.log_info("The other pane is a search-results view")
            elif pane["path"] == self.pm.get_inactive_pane()["path"]:
                # Both panes already show the same directory: a second Shift-O
                # moves the other pane's cursor onto this pane's focused file.
                self.pm.sync_cursor_from_current_pane(self.log_info)
            elif self.pm.sync_other_to_current(self.log_info):
                self._list_pane(self._pane_name_of(self.pm.get_inactive_pane()))
        elif action == "redraw":
            pass  # falls through to a full re-render below
        elif action == "adjust_pane_left":     # make the left pane smaller
            self._nudge(self.pane_splitter, -self._PANE_STEP)
        elif action == "adjust_pane_right":    # make the left pane larger
            self._nudge(self.pane_splitter, +self._PANE_STEP)
        elif action == "reset_pane_boundary":  # even 50 | 50 split
            self.pane_splitter.fraction = 0.5
        elif action == "adjust_log_up":        # grow the log (panes shrink)
            self._nudge(self.content_splitter, -self._LOG_STEP)
        elif action == "adjust_log_down":      # shrink the log (panes grow)
            self._nudge(self.content_splitter, +self._LOG_STEP)
        elif action == "reset_log_height":     # back to the default share
            self.content_splitter.fraction = PANES_FRACTION
        elif action == "scroll_log_up":
            self.log.scroll_by(-1.0)
        elif action == "scroll_log_down":
            self.log.scroll_by(+1.0)
        elif action == "scroll_log_page_up":
            self.log.scroll_by(-self._LOG_PAGE)
        elif action == "scroll_log_page_down":
            self.log.scroll_by(+self._LOG_PAGE)
        elif action == "file_details":
            self.file_details()
            return False  # the dialog drives its own redraw
        elif action == "drives_dialog":
            self.show_drives()
            return False
        elif action == "search_dialog":
            self.show_search()
            return False
        elif action == "search_content":
            self.show_content_search()
            return False
        elif action == "history":
            self.show_history()
            return False
        elif action == "programs":
            self.show_programs()
            return False
        elif action == "open_with_os":
            self.open_with_os()
            return False  # hands off to the OS; no in-app redraw
        elif action == "reveal_in_os":
            self.reveal_in_os()
            return False
        elif action == "edit_file":
            self.edit_file()
            return False
        elif action == "subshell":
            self.subshell()
            return False
        elif action == "edit_config":
            self.edit_config()
            return False  # hands over to the editor; self-renders on return
        elif action == "reload_config":
            self.reload_config()
            return False  # reload_config renders once applied
        elif action == "filter":
            self.enter_filter()
            return False  # the dialog drives its own redraw
        elif action == "search":
            self.enter_isearch()
            return False  # the isearch overlay drives its own redraw
        elif action == "favorites":
            self.show_favorites()
            return False  # the dialog drives its own redraw
        elif action == "create_directory":
            self.create_directory()
            return False  # the dialog drives its own redraw
        elif action == "create_file":
            self.create_file()
            return False
        elif action == "rename_file":
            self.rename()
            return False
        elif action == "copy_names":
            self.copy_names_to_clipboard()
        elif action == "copy_paths":
            self.copy_paths_to_clipboard()
        elif action == "copy_files":
            # A guard bail returns True (redraw so the reason shows at once); once
            # the confirm dialog takes over it returns False and drives its own redraw.
            return self.copy_files()
        elif action == "move_files":
            return self.move_files()
        elif action == "duplicate_files":
            return self.duplicate_files()
        elif action == "delete_files":
            return self.delete_files()
        elif action == "create_archive":
            return self.create_archive()
        elif action == "extract_archive":
            return self.extract_archive()
        elif action == "jump_to_path":
            self.jump_to_path()
            return False
        elif action == "compare_selection":
            self.compare_selection()
            return False
        elif action == "view_file":
            self.view_file()
            return False
        elif action == "diff_files":
            self.diff_files()
            return False
        elif action == "diff_directories":
            self.diff_directories()
            return False
        elif action == "help":
            self.show_help()
            return False
        else:
            return False
        return True

    def _exit_virtual(self, pane: dict) -> None:
        """Drop a pane out of virtual (search-results) mode so a subsequent
        ``_refresh`` lists a real directory. Called by every navigation that sets
        a real ``pane['path']``; a no-op on a normal pane."""
        pane["virtual"] = None

    def _open(self, pane: dict) -> None:
        files = pane["files"]
        if not files:
            return
        entry = files[pane["focused_index"]]
        try:
            if entry.is_dir():
                self._remember_cursor(pane)  # remember where we were in this dir
                self._exit_virtual(pane)  # entering a dir leaves the result set
                pane["path"] = entry
                self._refresh(pane, on_ready=self._restore_remembered_cursor)
                self.log_info(f"Entered {entry.name}/")
            elif self._archive_format(entry.name) and not self._is_archive(entry):
                # A recognised archive file: browse it as a virtual directory via
                # its archive:// URI. The listing/navigation machinery then treats
                # it like any other (remote) directory — ArchivePathImpl backs
                # iterdir/is_dir/read_bytes and returns the real containing dir as
                # its parent, so "up" exits the archive on its own. Nested archives
                # (already inside one) are skipped: the backend can't open an
                # archive from within an archive.
                self._remember_cursor(pane)  # remember the archive file's cursor
                self._exit_virtual(pane)
                pane["path"] = Path(f"archive://{entry.absolute()}#")
                self._refresh(pane, on_ready=self._restore_remembered_cursor)
                self.log_info(f"Entered archive {entry.name}")
            else:
                # A plain file. Enter is the *casual* open: it stays inside XeFM
                # (Cmd/Ctrl-Enter is the one that hands off to another app), so
                # a FILE_ASSOCIATIONS 'enter' rule selects a built-in handler
                # rather than a program to launch.
                self._enter_file(pane, entry)
        except Exception as exc:
            self.log_info(f"Cannot open {entry.name}: {exc}")

    def _enter_file(self, pane: dict, entry) -> None:
        """Handle Enter on a plain file, inside XeFM.

        An ``enter`` rule in FILE_ASSOCIATIONS picks the handler: ``'viewer'``
        for the built-in viewer, ``'navigate'`` to browse the file as an
        archive (useful for zip-shaped formats XeFM does not recognise by
        extension, like ``.jar`` or ``.whl``), or ``None`` to do nothing.

        With no rule, the default stands: the built-in viewer — the same one V
        uses, which routes *.md to the Markdown renderer and shows a
        placeholder for binaries (issue #212). A file inside a
        password-protected zip prompts for the password first (#180).
        """
        configured, handler = get_builtin_handler_for_file(entry.name)
        if configured and handler is None:
            self.log_info(f"Nothing configured to open {entry.name}")
            return
        if handler == "navigate" and not self._is_archive(entry):
            self._remember_cursor(pane)
            self._exit_virtual(pane)
            pane["path"] = Path(f"archive://{entry.absolute()}#")
            self._refresh(pane, on_ready=self._restore_remembered_cursor)
            self.log_info(f"Entered archive {entry.name}")
            return
        # Nothing built in can render this: warn in the log rather than spending
        # a full-screen viewer on a placeholder. Images are binary but the image
        # viewer renders them, and a rich renderer likewise claims its type even
        # when binary — so both bypass this guard.
        if handler != "viewer" and rich_renderer_for(entry) is None \
                and not is_image_file(entry) and looks_binary(entry):
            self.log_info(self._no_builtin_viewer_message(entry))
            return
        self._ensure_archive_password(entry, lambda: self._open_viewer(entry, pane))

    @staticmethod
    def _no_builtin_viewer_message(entry) -> str:
        """Warning for a file XeFM has no built-in way to display.

        Names the key actually bound to ``open_with_os`` rather than assuming
        Cmd-Enter — that binding is configurable, and differs on Windows out of
        the box. Says nothing about a key at all when the action is unbound.
        """
        keys = keys_label_for_action("open_with_os")
        if keys:
            return (f"No built-in viewer for {entry.name} — "
                    f"press {keys} to open it in an external program")
        return (f"No built-in viewer for {entry.name} — bind 'open_with_os' "
                f"to open it in an external program")

    def _go_parent(self, pane: dict) -> None:
        # From a virtual pane, "up" leaves the result set and lists the search
        # root (pane['path'] still holds it); land the cursor generically.
        if pane.get("virtual"):
            self._exit_virtual(pane)
            self._refresh(pane)
            self.log_info(f"Up to {pane['path']}")
            return
        parent = pane["path"].parent
        if str(parent) != str(pane["path"]):
            child_name = pane["path"].name
            self._remember_cursor(pane)  # remember the child's cursor for later
            pane["path"] = parent

            # Land the cursor on the directory we came from — once the listing is
            # in place (deferred for a remote pane that lists on a worker).
            def land_on_child(p: dict) -> None:
                for i, f in enumerate(p["files"]):
                    if f.name == child_name:
                        p["focused_index"] = i
                        break

            self._refresh(pane, on_ready=land_on_child)
            self.log_info(f"Up to {parent}")

    # --- menus & dialogs -----------------------------------------------------

    def _build_menu(self) -> Menu:
        """The app menu model — one tree, realized as the macOS menu bar or an
        in-window strip. Items reuse the same callbacks the keymap and context
        menu drive, and ``checked``/``enabled`` predicates re-evaluate on open so
        the menu always mirrors live pane state."""
        def has_files() -> bool:
            return bool(self.active_pane()["files"])

        # Shortcut hints are derived from the live keymap (§2.3) so menu labels
        # track user rebindings instead of drifting from hardcoded strings.
        sc = self._menu_shortcut
        sort_menu = self._sort_menu()

        file_menu = Menu(
            MenuItem("Open", on_select=lambda: self._menu("open_item"),
                     enabled=has_files, shortcut=sc("open_item")),
            MenuItem("View File", on_select=self.view_file,
                     enabled=has_files, shortcut=sc("view_file")),
            MenuItem("Edit File", on_select=self.edit_file,
                     enabled=has_files, shortcut=sc("edit_file")),
            MenuItem("Details…", on_select=self.file_details, enabled=has_files,
                     shortcut=sc("file_details")),
            MenuItem("Open with Default App", on_select=self.open_with_os,
                     enabled=has_files, shortcut=sc("open_with_os")),
            MenuItem("Reveal in File Manager", on_select=self.reveal_in_os,
                     enabled=has_files, shortcut=sc("reveal_in_os")),
            SEPARATOR,
            MenuItem("New Folder…", on_select=self.create_directory, shortcut=sc("create_directory")),
            MenuItem("New File…", on_select=self.create_file, shortcut=sc("create_file")),
            MenuItem("Rename…", on_select=self.rename, enabled=has_files, shortcut=sc("rename_file")),
            MenuItem("Duplicate", on_select=self.duplicate_files,
                     enabled=has_files, shortcut=sc("duplicate_files")),
            MenuItem("Copy to Other Pane", on_select=self.copy_files,
                     enabled=has_files, shortcut=sc("copy_files")),
            MenuItem("Move to Other Pane", on_select=self.move_files,
                     enabled=has_files, shortcut=sc("move_files")),
            MenuItem("Delete…", on_select=self.delete_files,
                     enabled=has_files, shortcut=sc("delete_files")),
            SEPARATOR,
            MenuItem("Copy Name(s)", on_select=self.copy_names_to_clipboard,
                     enabled=has_files, shortcut=sc("copy_names")),
            MenuItem("Copy Full Path(s)", on_select=self.copy_paths_to_clipboard,
                     enabled=has_files, shortcut=sc("copy_paths")),
            SEPARATOR,
            MenuItem("Create Archive…", on_select=self.create_archive,
                     enabled=has_files, shortcut=sc("create_archive")),
            MenuItem("Extract Archive…", on_select=self.extract_archive,
                     enabled=has_files, shortcut=sc("extract_archive")),
            SEPARATOR,
            MenuItem("Quit", on_select=self.confirm_quit, shortcut=sc("quit")),
            title="File",
        )
        go_menu = Menu(
            MenuItem("Parent Directory", on_select=lambda: self._menu("go_parent"),
                     shortcut=sc("go_parent")),
            MenuItem("Go to Favorite…", on_select=self.show_favorites, shortcut=sc("favorites")),
            MenuItem("Jump to Path…", on_select=self.jump_to_path, shortcut=sc("jump_to_path")),
            MenuItem("Drives…", on_select=self.show_drives, shortcut=sc("drives_dialog")),
            MenuItem("History…", on_select=self.show_history, shortcut=sc("history")),
            title="Go",
        )
        tools_menu = Menu(
            MenuItem("External Programs…", on_select=self.show_programs, shortcut=sc("programs")),
            MenuItem("Subshell Here", on_select=self.subshell, shortcut=sc("subshell")),
            SEPARATOR,
            MenuItem("Edit Configuration…", on_select=self.edit_config,
                     shortcut=sc("edit_config")),
            MenuItem("Reload Configuration", on_select=self.reload_config,
                     shortcut=sc("reload_config")),
            title="Tools",
        )
        select_menu = Menu(
            MenuItem("Toggle Selection", on_select=lambda: self._menu("select_file"),
                     enabled=has_files, shortcut=sc("select_file")),
            MenuItem("Select All Items", on_select=lambda: self._menu("select_all"),
                     shortcut=sc("select_all")),
            MenuItem("Clear Selection", on_select=lambda: self._menu("unselect_all"),
                     enabled=lambda: bool(self.active_pane()["selected_files"]),
                     shortcut=sc("unselect_all")),
            MenuItem("Compare and Select…", on_select=self.compare_selection,
                     enabled=has_files, shortcut=sc("compare_selection")),
            SEPARATOR,
            MenuItem("Compare Selected Files…", on_select=self.diff_files, shortcut=sc("diff_files")),
            MenuItem("Compare Directories…", on_select=self.diff_directories,
                     shortcut=sc("diff_directories")),
            title="Select",
        )
        view_menu = Menu(
            MenuItem("Find…", on_select=self.enter_isearch, enabled=has_files, shortcut=sc("search")),
            MenuItem("Filter…", on_select=self.enter_filter, shortcut=sc("filter")),
            MenuItem("Search Files…", on_select=self.show_search, shortcut=sc("search_dialog")),
            MenuItem("Search Content…", on_select=self.show_content_search, shortcut=sc("search_content")),
            SEPARATOR,
            MenuItem("Show Hidden Files", on_select=lambda: self._menu("toggle_hidden"),
                     checked=lambda: self.flm.show_hidden, shortcut=sc("toggle_hidden")),
            MenuItem("Reverse Sort", on_select=self._toggle_reverse,
                     checked=lambda: self.active_pane()["sort_reverse"]),
            MenuItem("Sort By", submenu=sort_menu),
            SEPARATOR,
            MenuItem("Theme", submenu=self._theme_menu()),
            MenuItem("Next Theme", on_select=lambda: self._menu("toggle_color_scheme"),
                     shortcut=sc("toggle_color_scheme")),
            SEPARATOR,
            MenuItem("Switch Pane", on_select=lambda: self._menu("switch_pane"), shortcut=sc("switch_pane")),
            title="View",
        )
        help_menu = Menu(
            MenuItem("Keyboard Shortcuts…", on_select=self.show_help, shortcut=sc("help")),
            SEPARATOR,
            MenuItem("About XeFM", on_select=self.show_about),
            title="Help",
        )
        return Menu(
            MenuItem("File", submenu=file_menu),
            MenuItem("Go", submenu=go_menu),
            MenuItem("Select", submenu=select_menu),
            MenuItem("View", submenu=view_menu),
            MenuItem("Tools", submenu=tools_menu),
            MenuItem("Help", submenu=help_menu),
        )

    def _menu(self, action: str) -> None:
        """Run a keymap action from a menu/context-menu selection and redraw."""
        if self.dispatch(action):
            self.panel.render()

    def _menu_shortcut(self, action: str) -> str | None:
        """The display-formatted first key bound to ``action`` for a MenuItem
        shortcut hint, or ``None`` when unbound — so menu labels track the live
        keymap (and user rebindings) instead of hardcoded strings."""
        keys, _ = self.keys.get_keys_for_action(action)
        return self.keys.format_key_for_display(keys[0]) if keys else None

    def _focused_entry(self):
        """The entry under the cursor in the active pane, or None if empty."""
        pane = self.active_pane()
        files = pane["files"]
        if not files:
            return None
        return files[pane["focused_index"]]

    _REMOTE_SCHEMES = ("ssh://", "s3://", "scp://", "ftp://", "archive://")

    @classmethod
    def _is_local(cls, path) -> bool:
        """Whether ``path`` is a plain local-filesystem path — the only kind a
        terminal editor or subshell can operate on directly."""
        return not str(path).startswith(cls._REMOTE_SCHEMES)

    @staticmethod
    def _is_archive(path) -> bool:
        """Whether ``path`` is inside a browsed archive (an ``archive://`` URI).
        Such paths are read-only, so write-side operations refuse them."""
        return str(path).startswith("archive://")

    def _run_in_terminal(self, argv: list, cwd: str | None = None) -> None:
        """Run a full-screen child process (editor / shell) with the display
        handed over via ``backend.suspended()``, then refresh both panes and
        repaint — the child may have changed files while we were away."""
        try:
            with self.backend.suspended():
                subprocess.run(argv, cwd=cwd)
        except FileNotFoundError:
            self.log_info(f"Command not found: {argv[0]}")
        except Exception as exc:
            self.log_info(f"Command failed: {exc}")
        self.flm.refresh_files(self.pm.left_pane)
        self.flm.refresh_files(self.pm.right_pane)
        self.panel.render()

    def _launch_associated(self, entry, command: list) -> bool:
        """Run the FILE_ASSOCIATIONS program ``command`` on ``entry``.

        Whether to hand over the display is a property of *our backend*, not of
        the program, so associations do not describe it:

        * Terminal mode — the child shares our tty, so we suspend curses, wait
          for it, and restore. Correct for ``less``/``vim``; a launcher like
          ``open -a`` merely returns straight away and we repaint.
        * Desktop mode — there is no tty to hand over and blocking would freeze
          the window, so the child is detached and we keep running.

        Returns False — having logged why — when the program could not be run,
        so callers can fall back to their built-in behavior rather than leaving
        the key press doing nothing. An external program needs a real path on
        disk, so remote and in-archive entries always take that fallback.
        """
        if not self._is_local(entry):
            self.log_info(f"{entry.name}: external programs need a local file")
            return False
        argv = list(command) + [str(entry)]
        if not is_desktop_mode():
            self._run_in_terminal(argv)
            return True
        try:
            subprocess.Popen(argv)
        except FileNotFoundError:
            self.log_info(f"Command not found: {argv[0]}")
            return False
        except Exception as exc:
            self.log_info(f"Failed to open {entry.name}: {exc}")
            return False
        return True

    def edit_file(self) -> None:
        """Open the focused file for editing.

        A matching ``edit`` entry in FILE_ASSOCIATIONS wins; otherwise the
        configured ``TEXT_EDITOR`` gets the terminal via suspend/resume. An
        association set explicitly to ``None`` means "no editor for this kind
        of file" and is honored rather than falling back. Local files only;
        directories and remote paths are skipped."""
        entry = self._focused_entry()
        if entry is None:
            return
        if not self._is_local(entry):
            self.log_info("Edit is only available for local files")
            return
        try:
            if entry.is_dir():
                self.log_info(f"{entry.name} is a directory")
                return
        except Exception:
            pass
        command = get_program_for_file(entry.name, "edit")
        if command:
            if self._launch_associated(entry, command):
                self.log_info(f"Edited {entry.name} with {command[0]}")
                return
        elif has_explicit_association(entry.name, "edit"):
            # Explicitly None: the config says this type has no editor (a PDF,
            # say). Falling back to $EDITOR would ignore that on purpose.
            self.log_info(f"No editor configured for {entry.name}")
            return
        editor = getattr(self.config, "TEXT_EDITOR", "vim")
        self._run_in_terminal(shlex.split(editor) + [str(entry)])
        self.log_info(f"Edited {entry.name}")

    def subshell(self) -> None:
        """Drop to an interactive shell (``$SHELL``) in the active pane's
        directory, handing over the terminal via suspend/resume; refresh on
        return. Local directories only."""
        path = self.active_pane()["path"]
        if not self._is_local(path):
            self.log_info("Subshell is only available for local directories")
            return
        shell = os.environ.get("SHELL", "/bin/sh")
        self.log_info(f"Subshell in {path} — exit the shell to return")
        self._run_in_terminal([shell], cwd=str(path))

    def edit_config(self) -> None:
        """Open the user's ``~/.xefm/config.py`` in the configured editor
        (``TEXT_EDITOR``), creating it from the template on first use.

        In terminal mode the editor takes over the terminal and blocks, so we
        reload on return (see :meth:`reload_config`). In GUI mode ``TEXT_EDITOR``
        (e.g. VS Code) opens in its own window and ``subprocess.run`` returns
        immediately — before any edit is saved — so auto-reloading here would be
        premature. We leave it to the user to apply changes via
        Tools ▸ Reload Configuration once saved."""
        path = config_manager.config_file
        if not path.exists():
            if config_manager.create_default_config():
                self.log_info(f"Created default config at {path}")
            else:
                self.log_info(f"Could not create config file at {path}")
                return
        editor = getattr(self.config, "TEXT_EDITOR", "vim")
        self._run_in_terminal(shlex.split(editor) + [str(path)])
        if is_desktop_mode():
            self.log_info("Opened config — use Tools ▸ Reload Configuration to "
                          "apply your changes once saved.")
            self.panel.render()
        else:
            self.reload_config()

    def reload_config(self) -> None:
        """Re-read ``~/.xefm/config.py`` and apply what can change at runtime.

        Key bindings and the config reference threaded through the running
        subsystems (file ops, panes, monitoring, views) are refreshed live, so
        rebindings, file associations, external programs, favorites and editor
        settings take effect immediately. Appearance and layout read once at
        launch — theme/colors, fonts, pane and log ratios, monitoring
        intervals — only fully apply on the next start; we say so rather than
        pretend otherwise."""
        new_config = config_manager.reload_config()
        # Surface non-fatal validation problems (out-of-range ratios, bad sort
        # mode, …) but still apply — a reload should reflect what's on disk.
        for err in config_manager.validate_config(new_config):
            self.log_info(f"Config warning: {err}")

        self.config = new_config
        # Rebuild the keymap from the (possibly rebound) KEY_BINDINGS.
        self.keys = KeyBindings(new_config.KEY_BINDINGS)
        # Re-point the config reference every long-lived subsystem holds so
        # their on-demand reads pick up the new values without a rebuild.
        for holder in (self._fileops, self.flm, self.pm, self.file_monitor,
                       self.left_view, self.right_view):
            holder.config = new_config

        self.log_info("Configuration reloaded — key bindings and file settings "
                      "applied; theme, layout and font changes take effect on "
                      "the next launch.")
        self.panel.render()

    def file_details(self) -> None:
        """Show stat details for the focused entry — or an aggregate summary plus
        per-item details for a multi-file selection — in a scrollable Markdown
        dialog (mirrors ttk XeFM's file-details, reusing the shared text-dialog).

        Each entry renders as a heading followed by a GFM table of its stat
        fields, so the values line up in a real column instead of hand-padded."""
        import datetime as _dt
        import stat as _stat
        pane = self.active_pane()
        files = pane["files"]
        if not files:
            self.log_info("No file to show details for")
            return
        selected = [f for f in files if str(f) in pane["selected_files"]]
        targets = selected if selected else [files[pane["focused_index"]]]

        # Content search-results panes carry a per-file matched line/text map;
        # empty for a normal or filename-results pane (no extra row then).
        virtual = pane.get("virtual")
        match_meta = virtual["meta"] if virtual and virtual["mode"] == "content" else {}

        def _md_escape(text: str) -> str:
            # Keep a filename with Markdown-significant characters (``|`` splits a
            # table cell, ``*``/``_``/`` ` `` are emphasis) rendering literally.
            for ch in "\\`*_[]|":
                text = text.replace(ch, "\\" + ch)
            return text

        def details(entry) -> list[str]:
            out = [f"### {_md_escape(entry.name)}", ""]
            try:
                is_symlink = entry.is_symlink()
            except Exception:
                is_symlink = False
            try:
                st = entry.stat()
            except Exception as exc:
                # A broken symlink can't be stat()'d (the target is gone), so
                # fall back to the link's own metadata rather than bailing out.
                try:
                    st = entry.lstat() if is_symlink else None
                except Exception:
                    st = None
                if st is None:
                    out += [f"*stat unavailable: {_md_escape(str(exc))}*", ""]
                    return out
            # ``is_dir``/``is_file`` follow the link, so check ``is_symlink``
            # first — otherwise a symlink to a directory reads as "Directory".
            try:
                if is_symlink:
                    kind = "Symlink → Directory" if entry.is_dir() else \
                           ("Symlink → File" if entry.is_file() else "Symlink (broken)")
                elif entry.is_dir():
                    kind = "Directory"
                else:
                    kind = "File"
            except Exception:
                kind = "Symlink" if is_symlink else "File"
            mtime = _dt.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            out += [
                "| Field | Value |",
                "| --- | --- |",
                f"| Path | `{entry}` |",
                f"| Type | {kind} |",
                f"| Size | {st.st_size:,} bytes |",
                f"| Modified | {mtime} |",
                f"| Permissions | `{_stat.filemode(st.st_mode)}` |",
            ]
            # On a content search-results pane, surface the matched line as extra
            # metadata (kept in virtual['meta']; not shown in the list itself).
            m = match_meta.get(str(entry))
            if m is not None:
                out.append(f"| Match | line {m['line']}: `{_md_escape(m['text'])}` |")
            out.append("")
            return out

        if len(targets) == 1:
            lines = details(targets[0])
        else:
            total = 0
            for t in targets:
                try:
                    total += t.stat().st_size
                except Exception:
                    pass
            lines = [
                f"# {len(targets)} items selected",
                "",
                f"**Total size:** {total:,} bytes",
                "",
            ]
            for t in targets:
                lines += details(t)
        show_markdown(self.panel, "\n".join(lines), title="Details")
        self.panel.render()

    def open_with_os(self) -> None:
        """Hand the focused entry to an external program — the deliberate open,
        bound to Cmd/Ctrl-Enter, as opposed to Enter's open-inside-XeFM.

        A matching ``open`` entry in FILE_ASSOCIATIONS wins; otherwise the OS
        default application ('open' / 'xdg-open' / 'start') handles it. An
        association set explicitly to ``None`` suppresses the launch entirely,
        which is how you stop a file type from being handed to the OS at all.
        Errors are logged, not raised."""
        entry = self._focused_entry()
        if entry is None:
            return
        command = get_program_for_file(entry.name, "open")
        if command:
            if self._launch_associated(entry, command):
                self.log_info(f"Opened {entry.name} with {command[0]}")
                return
        elif has_explicit_association(entry.name, "open"):
            self.log_info(f"No external program configured for {entry.name}")
            return
        system = platform.system()
        try:
            if system == "Darwin":
                subprocess.run(["open", str(entry)], check=True)
            elif system == "Windows":
                subprocess.run(["start", "", str(entry)], shell=True, check=True)
            else:
                subprocess.run(["xdg-open", str(entry)], check=True)
        except Exception as exc:
            self.log_info(f"Failed to open {entry.name}: {exc}")
        else:
            self.log_info(f"Opened {entry.name} with the default app")

    def reveal_in_os(self) -> None:
        """Reveal the focused entry in the OS file manager (Finder / Explorer),
        falling back to opening its parent directory elsewhere."""
        entry = self._focused_entry()
        if entry is None:
            return
        system = platform.system()
        try:
            if system == "Darwin":
                subprocess.run(["open", "-R", str(entry)], check=True)
            elif system == "Windows":
                subprocess.run(["explorer", "/select,", str(entry)], check=True)
            else:
                subprocess.run(["xdg-open", str(entry.parent)], check=True)
        except Exception as exc:
            self.log_info(f"Failed to reveal {entry.name}: {exc}")
        else:
            self.log_info(f"Revealed {entry.name}")

    def _sort_menu(self) -> Menu:
        """The sort-mode menu, shared by the menu-bar's 'Sort By' submenu and the
        keyboard-triggered sort popup (``show_sort_menu``). A live ``checked``
        predicate marks the active pane's current mode."""
        sort_modes = (("Name", "name"), ("Size", "size"), ("Date", "date"), ("Type", "type"))
        return Menu(*[
            MenuItem(label, on_select=(lambda m=mode: self._set_sort(m)),
                     checked=(lambda m=mode: self.active_pane()["sort_mode"] == m))
            for label, mode in sort_modes
        ], title="Sort By")

    def show_sort_menu(self) -> None:
        """Pop the sort menu over the active pane (the 's' key)."""
        rx, rw = self._active_pane_region()
        self.panel.popup_menu(self._sort_menu(), rx + rw / 2.0, 2.0)
        self.panel.render()

    #: Keyboard nudge for the pane boundary / log height (fraction of the split),
    #: and the page size (lines) for keyboard log scrolling.
    _PANE_STEP = 0.05
    _LOG_STEP = 0.05
    _LOG_PAGE = 10.0

    @staticmethod
    def _nudge(splitter, delta: float) -> None:
        """Shift a Splitter's fraction by ``delta`` from the keyboard, clamped to
        a sane range so a pane can't be nudged to nothing (the mouse-drag path has
        its own base-unit min-size clamp; this keeps the keyboard path safe too)."""
        splitter.fraction = max(0.1, min(0.9, splitter.fraction + delta))

    def _theme_menu(self) -> Menu:
        """The theme picker, shared by the View menu's 'Theme' submenu. Lists every
        theme — built-in and user-registered (``config.THEMES``) — with a live
        ``checked`` predicate marking the active one (mirrors ``_sort_menu``)."""
        return Menu(*[
            MenuItem(name, on_select=(lambda i=i: self._select_theme(i)),
                     checked=(lambda i=i: self._theme_index == i))
            for i, (name, _theme) in enumerate(self.themes)
        ], title="Theme")

    def _apply_theme(self, index: int) -> None:
        """Switch the active palette. One assignment recolors every widget: the
        chrome and file lists read the theme at draw time, and the surface-role
        backgrounds re-resolve on the next render. The choice is persisted so the
        next launch reopens on it (see the theme restore in ``__init__``)."""
        self._theme_index = index % len(self.themes)
        name, theme = self.themes[self._theme_index]
        self.panel.theme = theme
        self._apply_post_effect(theme)
        self._apply_background(theme)
        self._apply_surface_opacity(theme)
        self.state_manager.set_state("theme", name)  # remember across restarts
        self.log_info(f"Theme: {name}")

    def _apply_post_effect(self, theme: Theme) -> None:
        """Push the theme's recommended post-processing effect (or ``None`` to
        clear) to the backend, so switching to a CRT-style theme turns the effect
        on and switching away turns it off. A backend without the ``post_effects``
        capability (a terminal) inherits the base no-op, so this never branches on
        the backend."""
        self.backend.set_post_effect(theme.extras.get("post_effect"))

    def _apply_background(self, theme: Theme) -> None:
        """Push the theme's recommended background behind the UI to the backend, or
        ``None`` to clear it — an animated scene (see ``xefm.background_shaders``)
        or a wallpaper image (only Sci-Fi opts in among the built-in themes, and the
        sample Phosphor in ``_config.py``), turned on when the theme becomes active and off when
        you switch away, exactly like ``_apply_post_effect``. The descriptor was
        built per theme in ``_theme`` with its color (theme foreground) and backdrop
        (theme background) baked in, so an animation stays on-palette and reads on
        light themes too. A backend without the ``background_shader`` capability (a
        terminal) inherits the base no-op, so this never branches on the backend."""
        self.backend.set_background(theme.extras.get("background"))

    def _apply_surface_opacity(self, theme: Theme) -> None:
        """Push the theme's ``opacity`` — how opaque the UI's surface fills are, so a
        wallpaper (the 3D cube today, a static image later) shows *through* them where
        it is < 1 — to the backend, ``1`` (fully opaque, the default) when the theme
        names none. Deliberately separate from ``_apply_background``: it is one
        per-theme knob reused across background kinds, not a property of the cube. A
        backend that can't composite (a terminal) inherits the base no-op."""
        self.backend.set_surface_opacity(theme.extras.get("opacity", 1.0))

    def _cycle_theme(self) -> None:
        """Advance to the next palette (the ``toggle_color_scheme`` / T action)."""
        self._apply_theme(self._theme_index + 1)

    def _select_theme(self, index: int) -> None:
        """Pick a specific palette from the menu, then redraw."""
        self._apply_theme(index)
        self.panel.render()

    def _quick_sort(self, mode: str) -> None:
        """Set the active pane's sort mode from a quick-sort key; pressing the
        same mode again toggles the sort direction (mirrors ttk XeFM's quick_sort).
        The current reverse setting is kept when switching to a new mode."""
        pane = self.active_pane()
        if pane["sort_mode"] == mode:
            pane["sort_reverse"] = not pane["sort_reverse"]
        else:
            pane["sort_mode"] = mode
        self.flm.refresh_files(pane)
        self.log_info(f"Sort: {self.flm.get_sort_description(pane)}")

    def _set_sort(self, mode: str) -> None:
        pane = self.active_pane()
        pane["sort_mode"] = mode
        self.flm.refresh_files(pane)
        self.log_info(f"Sort: {self.flm.get_sort_description(pane)}")
        self.panel.render()

    def _toggle_reverse(self) -> None:
        pane = self.active_pane()
        pane["sort_reverse"] = not pane["sort_reverse"]
        self.flm.refresh_files(pane)
        self.log_info(f"Sort: {self.flm.get_sort_description(pane)}")
        self.panel.render()

    def confirm_quit(self) -> None:
        """A modal confirm before quitting — the canonical message-box pattern."""
        show_message_box(
            self.panel, "Quit XeFM?", title="Confirm", icon="warning",
            buttons=("Quit", "Cancel"), default=0, cancel=1,
            on_result=lambda label: self._quit() if label == "Quit" else None,
        )
        self.panel.render()

    def show_favorites(self) -> None:
        """The modal filter-list dialog: pick a favorite directory and jump the
        active pane there. The canonical searchable-list-picker pattern (XeFM's
        ``BaseListDialog`` workhorse), built from PuiKit's TextEdit + ListView."""
        favorites = get_favorite_directories()
        if not favorites:
            show_message_box(self.panel, "No favorite directories configured.",
                             title="Favorites", icon="info")
            self.panel.render()
            return
        # Middle-elide the "name — path" rows so a long path keeps its tail (the
        # leaf directory) rather than being clipped away (issue #211).
        show_filter_list(
            self.panel, favorites, title="Go to Favorite",
            to_label=lambda fav: f"{fav['name']}  —  {fav['path']}",
            on_accept=self._jump_to_favorite,
            region=self._active_pane_region(),
            elide_where="middle",
        )
        self.panel.render()

    def _active_pane_region(self) -> tuple[float, float]:
        """The ``(x, width)`` column span of the active pane, in base units, for
        anchoring pane-targeting dialogs over the pane they act on. Mirrors the
        pane_splitter geometry: the left pane gets ``left_pane_ratio`` of the
        width, the right pane the remainder."""
        sw, _ = self.panel.backend.size_units
        left_w = sw * self.pm.left_pane_ratio
        if self.pm.active_pane == "left":
            return (0.0, left_w)
        return (left_w, sw - left_w)

    def _local_drives(self) -> list[dict]:
        """Home / root / common folders + mounted volumes, as ``{name, path}``
        rows for the drives picker. SSH hosts are added by ``_ssh_drives``; S3
        buckets (an async, credentialed scan) remain a later phase."""
        drives = [{"name": "Home", "path": str(Path.home())},
                  {"name": "Root", "path": "/"}]
        for name in ("Documents", "Downloads", "Desktop"):
            p = Path.home() / name
            try:
                if p.exists() and p.is_dir():
                    drives.append({"name": name, "path": str(p)})
            except Exception:
                pass
        if platform.system() == "Darwin":
            vol_roots = ["/Volumes"]
        else:
            vol_roots = [f"/media/{os.environ.get('USER', '')}", "/media", "/mnt"]
        for root in vol_roots:
            try:
                rp = Path(root)
                if rp.exists() and rp.is_dir():
                    for v in rp.iterdir():
                        if v.is_dir():
                            drives.append({"name": v.name, "path": str(v)})
            except Exception:
                pass
        seen, out = set(), []
        for d in drives:
            if d["path"] not in seen:
                seen.add(d["path"])
                out.append(d)
        return out

    def _ssh_drives(self) -> list[dict]:
        """SSH hosts from ``~/.ssh/config`` as ``ssh://host/`` rows for the drives
        picker. Reads only the local config file (no network); best-effort, so a
        missing or unreadable config — or an absent SSH layer — yields nothing.
        ``Host *`` wildcard blocks are dropped by the parser, not connectable."""
        try:
            from xefm.ssh_config import SSHConfigParser
            hosts = SSHConfigParser().parse()
        except Exception:
            return []
        out = []
        for hostname, cfg in hosts.items():
            user = cfg.get("User", "")
            actual = cfg.get("HostName", hostname)
            label = f"{user}@{actual}" if user else actual
            out.append({"name": label, "path": f"ssh://{hostname}/"})
        return out

    @staticmethod
    def _aws_configured() -> bool:
        """Whether AWS credentials are plausibly available *locally* — env vars or
        an ``~/.aws`` config/credentials file. Used to skip the S3 scan entirely
        when there's nothing to scan, so the picker never blocks (and never waits
        on the IMDS endpoint) for the common no-AWS case."""
        if os.environ.get("AWS_ACCESS_KEY_ID") or os.environ.get("AWS_PROFILE"):
            return True
        aws = Path.home() / ".aws"
        try:
            return (aws / "credentials").exists() or (aws / "config").exists()
        except Exception:
            return False

    def _s3_drives(self) -> list[dict]:
        """S3 buckets as ``s3://bucket/`` rows for the drives picker. A single
        ``list_buckets`` call, gated on local AWS credentials and bounded by short
        timeouts so it fails fast instead of hanging the picker. Best-effort: no
        boto3, no credentials, or any AWS error yields nothing.

        Note: EC2 instance-role (IMDS-only) credentials are intentionally not
        probed here — that is the one path that can hang — so buckets won't list
        on a bare instance role without an env var or ``~/.aws`` file."""
        try:
            from xefm.s3 import HAS_BOTO3
            if not HAS_BOTO3 or not self._aws_configured():
                return []
            import boto3
            from botocore.config import Config as _BotoConfig
            client = boto3.client("s3", config=_BotoConfig(
                connect_timeout=2, read_timeout=3, retries={"max_attempts": 0}))
            resp = client.list_buckets()
        except Exception:
            return []
        return [{"name": b["Name"], "path": f"s3://{b['Name']}/"}
                for b in resp.get("Buckets", [])]

    def show_drives(self) -> None:
        """The drives picker: choose a volume / common location / SSH host / S3
        bucket and jump the active pane there (reuses the searchable-list dialog,
        like favorites). Selecting an ``ssh://`` or ``s3://`` row connects on
        first listing."""
        drives = self._local_drives() + self._ssh_drives() + self._s3_drives()
        show_filter_list(
            self.panel, drives, title="Drives",
            to_label=lambda d: f"{d['name']}  —  {d['path']}",
            on_accept=self._go_to_drive,
            region=self._active_pane_region(),
            elide_where="middle")  # keep the path tail visible (issue #211)
        self.panel.render()

    def _go_to_drive(self, drive: dict) -> None:
        pane = self.active_pane()
        self._remember_cursor(pane)
        self._exit_virtual(pane)
        pane["path"] = Path(drive["path"])
        pane["selected_files"].clear()
        self._refresh(pane, on_ready=self._restore_remembered_cursor)
        self.log_info(f"Drive: {drive['path']}")
        self.panel.render()

    def show_search(self) -> None:
        """Live filename search under the active pane (the Shift-F dialog): opens
        the progressive search dialog in filename mode. Typing walks the tree
        (bounded, honouring the hidden-file setting) and streams matching entries
        into the list as you type; Tab switches to content search; picking a hit
        navigates to its directory and lands the cursor on it."""
        self._open_search("filename")

    def show_content_search(self) -> None:
        """Live content (grep) search under the active pane (the Shift-G dialog):
        opens the progressive search dialog in content mode. Typing walks the tree
        reading text files and streams each matching line; Tab switches to
        filename search; picking a hit navigates to the file and lands on it."""
        self._open_search("content")

    def _open_search(self, initial_mode: str) -> None:
        """Open the progressive search dialog anchored over the active pane. Both
        Shift-F and Shift-G land here — they differ only in the starting mode, and
        Tab toggles between them in place. The dialog runs ``search_iter`` on a
        worker thread and streams results in, so a huge tree never blocks the UI;
        each keystroke supersedes the previous search."""
        root = self.active_pane()["path"]
        root_str = str(root)

        def search_iter(mode, query, cancel):
            if mode == "content":
                regex = re.compile(query, re.IGNORECASE)  # re.error surfaces in the dialog
                yield from self._iter_content_matches(root, regex, cancel)
            else:
                yield from self._iter_filename_matches(root, query, cancel)

        def to_label(mode, value):
            if mode == "content":
                s = str(value["path"])
                rel = s[len(root_str):].lstrip("/") if s.startswith(root_str) else s
                return f"{rel}:{value['line']}: {value['text']}"
            s = str(value)
            return s[len(root_str):].lstrip("/") if s.startswith(root_str) else s

        def on_accept(mode, value):
            # Feed-by-default: accepting doesn't navigate to the one hit — it
            # feeds the *whole* result set into the active pane as a flat virtual
            # listing, so every file operation can act on it. Read the dialog's
            # full results + current query; the accepted ``value`` only decides
            # which row the cursor lands on (issue #224).
            self._feed_search_results(mode, list(dialog.results),
                                      root, dialog.query_edit.text.strip(),
                                      focus=value)

        dialog = show_progressive_search(
            self.panel, initial_mode=initial_mode,
            search_iter=search_iter, to_label=to_label, on_accept=on_accept,
            region=self._active_pane_region())
        self.panel.render()

    def _feed_search_results(self, mode: str, results: list, root, query: str,
                             focus=None) -> None:
        """Turn a search result set into the active pane's flat, virtual listing
        (feed-by-default; see the search dialog's ``on_accept``). Filename results
        are ``Path`` objects; content results are ``{path, line, text}`` hits,
        collapsed to **one entry per file** (ops act on files, not lines) with the
        *first* match's line/text kept in ``virtual['meta']`` for the Info dialog
        and reveal-at-line. Starts unfiltered, keeping the pane's current sort.

        ``focus`` is the hit that was accepted in the dialog (a ``Path``, or a
        content hit dict); the cursor lands on its row rather than at the top, so
        the file you picked is the one under the cursor (issue #224)."""
        pane = self.active_pane()
        meta: dict[str, dict] = {}
        if mode == "content":
            paths, seen = [], set()
            for hit in results:
                p = hit["path"]
                key = str(p)
                if key in seen:
                    continue  # first match per file wins; later lines drop
                seen.add(key)
                paths.append(p)
                meta[key] = {"line": hit["line"], "text": hit["text"]}
        else:
            paths = list(results)
        if not paths:
            self.log_info("No results to open")
            self.panel.render()
            return
        pane["virtual"] = {
            "kind": "search", "root": Path(root), "mode": mode,
            "query": query, "results": paths, "meta": meta,
        }
        pane["filter_pattern"] = ""
        pane["focused_index"] = 0
        pane["scroll_offset"] = 0
        pane["selected_files"].clear()
        self.flm.refresh_files(pane)  # virtual-aware: sorts/filters the set in memory
        self._focus_result(pane, focus)
        self.log_info(f'Search results for "{query}": {len(paths)} item(s)  '
                      f'— O go to location · Shift-O reveal in other pane · ⌫ back')
        self.panel.render()

    def _focus_result(self, pane: dict, focus) -> None:
        """Land ``pane``'s cursor on the fed result ``focus`` (a ``Path`` or a
        content-hit dict), scrolling it into view. Matching is by full path — a
        search set spans directories, so names alone can collide. A missing or
        unmatched ``focus`` leaves the cursor where it is (the top)."""
        if focus is None:
            return
        target = focus["path"] if isinstance(focus, dict) else focus
        target = str(target)
        for i, entry in enumerate(pane["files"]):
            if str(entry) == target:
                pane["focused_index"] = i
                self.pm.adjust_scroll_for_focus(pane, self._display_height())
                return

    def _iter_filename_matches(self, root, pattern, cancel, node_cap: int = 50000):
        """Depth-first walk under ``root`` yielding entries whose name matches
        ``pattern`` (case-insensitive glob), checking ``cancel`` between entries so
        a superseded search stops promptly. The pattern is matched against the
        *whole* filename — an exact glob (issue #231): ``report.txt`` matches only
        that name, and wildcards are used explicitly for partial matches
        (``*.py``, ``report*``, or ``*report*`` for the old "contains" behaviour).
        Hidden entries are skipped unless the pane is showing them; ``node_cap``
        bounds the walk. The result cap is applied by the dialog consuming this
        generator."""
        import fnmatch
        pat = pattern.lower()
        stack, nodes = [root], 0
        while stack and nodes < node_cap:
            if cancel.is_set():
                return
            try:
                entries = list(stack.pop().iterdir())
            except Exception:
                continue
            for e in entries:
                if cancel.is_set():
                    return
                nodes += 1
                if not self.flm.show_hidden and e.name.startswith("."):
                    continue
                try:
                    if fnmatch.fnmatch(e.name.lower(), pat):
                        yield e
                    if e.is_dir():
                        stack.append(e)
                except Exception:
                    continue

    def _go_to_result(self, entry) -> None:
        pane = self.active_pane()
        pane["path"] = entry.parent
        self._refresh(pane, on_ready=lambda p: self._select_by_name(p, entry.name))
        self.log_info(f"Found: {entry}")
        self.panel.render()

    @staticmethod
    def _virtual_focused_entry(pane: dict):
        """The ``Path`` under the cursor of a virtual (search-results) ``pane``, or
        ``None`` if the pane isn't virtual / has no rows. Used by the reveal keys
        to find *which* highlighted result to open."""
        if not pane.get("virtual"):
            return None
        files = pane["files"]
        idx = pane["focused_index"]
        if files and 0 <= idx < len(files):
            return files[idx]
        return None

    @staticmethod
    def _focused_name(pane: dict):
        """The name of the entry under a pane's cursor, or ``None`` if empty."""
        files = pane["files"]
        idx = pane["focused_index"]
        if files and 0 <= idx < len(files):
            return files[idx].name
        return None

    def _go_to_dir(self, dest: dict, target_dir, target_name) -> None:
        """Point ``dest`` at ``target_dir`` and land the cursor on ``target_name``
        (or the top if it's None/gone). Leaves virtual mode if ``dest`` was in it,
        and always re-lists — so it is correct even when ``dest``'s path already
        equals ``target_dir`` (a stale virtual listing still gets replaced, and an
        'already there' sync just moves the cursor)."""
        self._remember_cursor(dest)
        self._exit_virtual(dest)
        dest["path"] = target_dir
        dest["selected_files"].clear()
        self._refresh(
            dest,
            on_ready=(lambda p: self._select_by_name(p, target_name)) if target_name
            else self._restore_remembered_cursor,
        )
        self.panel.render()

    def _reveal_result_other(self) -> bool:
        """Shift-O from the results pane: open the highlighted result's real
        directory in the *other* pane (landing on the file), keeping the result
        set intact here — reveal without leaving virtual mode. Only meaningful when
        the active pane is the virtual one; returns False otherwise."""
        pane = self.active_pane()
        entry = self._virtual_focused_entry(pane)
        if entry is None:
            return False
        other = self.pm.get_inactive_pane()
        self._remember_cursor(other)
        self._exit_virtual(other)
        other["path"] = entry.parent
        other["selected_files"].clear()
        self._refresh(other, on_ready=lambda p: self._select_by_name(p, entry.name))
        self.log_info(f"Revealed in other pane: {entry.parent}")
        self.panel.render()
        return True

    @staticmethod
    def _looks_textual(path, sample_size: int = 1024) -> bool:
        """Cheap binary filter for content search: a NUL byte in the first chunk
        means binary. Empty or unreadable files are treated as non-text — there's
        nothing to grep in them."""
        try:
            with path.open("rb") as f:
                chunk = f.read(sample_size)
        except Exception:
            return False
        return bool(chunk) and b"\x00" not in chunk

    def _iter_content_matches(self, root, regex, cancel, node_cap: int = 50000,
                              max_line: int = 200):
        """Depth-first walk under ``root`` yielding ``{path, line, text}`` for each
        line of a text file that matches ``regex`` (compiled), checking ``cancel``
        between entries so a superseded search stops promptly. Binary and (unless
        the pane shows them) hidden entries are skipped; ``node_cap`` bounds the
        walk. The result cap is applied by the dialog consuming this generator."""
        stack, nodes = [root], 0
        while stack and nodes < node_cap:
            if cancel.is_set():
                return
            try:
                entries = list(stack.pop().iterdir())
            except Exception:
                continue
            for e in entries:
                if cancel.is_set():
                    return
                nodes += 1
                if not self.flm.show_hidden and e.name.startswith("."):
                    continue
                try:
                    if e.is_dir():
                        stack.append(e)
                        continue
                    if not self._looks_textual(e):
                        continue
                    with e.open("r", encoding="utf-8", errors="ignore") as f:
                        for line_num, line in enumerate(f, 1):
                            if cancel.is_set():
                                return
                            if regex.search(line):
                                yield {"path": e, "line": line_num,
                                       "text": line.strip()[:max_line]}
                except Exception:
                    continue

    def _go_to_content_hit(self, hit) -> None:
        entry = hit["path"]
        pane = self.active_pane()
        pane["path"] = entry.parent
        self._refresh(pane, on_ready=lambda p: self._select_by_name(p, entry.name))
        self.log_info(f"Match: {entry}:{hit['line']}")
        self.panel.render()

    def show_history(self) -> None:
        """The recent-directory picker: pick a previously visited directory and
        jump the active pane there. Shows most-recent-first, de-duplicated."""
        items = self._recent_dirs_most_recent_first()
        if not items:
            show_message_box(self.panel, "No directory history yet.",
                             title="History", icon="info")
            self.panel.render()
            return
        # Middle-elide long paths ("/Users/…/deep/dir") so the tail — the actual
        # destination directory — stays visible, instead of an end clip that
        # hides it (issue #211).
        show_filter_list(
            self.panel, items, title="History", to_label=lambda p: p,
            on_accept=self._go_to_history, region=self._active_pane_region(),
            elide_where="middle")
        self.panel.render()

    def _go_to_history(self, path: str) -> None:
        pane = self.active_pane()
        self._remember_cursor(pane)
        self._exit_virtual(pane)
        pane["path"] = Path(path)
        pane["selected_files"].clear()
        self._refresh(pane, on_ready=self._restore_remembered_cursor)
        self.log_info(f"History: {path}")
        self.panel.render()

    def show_programs(self) -> None:
        """The external-programs picker: choose a configured program and launch it
        on the selection (or the focused entry). Launched fire-and-forget with the
        active pane as the working directory — well suited to the GUI launchers in
        the default config (VS Code, BeyondCompare). Programs that need to take
        over the terminal await a backend suspend/resume (see ``edit_file``)."""
        programs = getattr(self.config, "PROGRAMS", None) or []
        if not programs:
            show_message_box(self.panel, "No external programs configured.",
                             title="Programs", icon="info")
            self.panel.render()
            return
        show_filter_list(
            self.panel, programs, title="External Programs",
            to_label=lambda p: p.get("name", "?"),
            on_accept=self._run_program, region=self._active_pane_region())
        self.panel.render()

    def _run_program(self, program: dict) -> None:
        from xefm.external_programs import (ensure_common_paths_in_env,
                                           get_selected_or_cursor_files)
        pane = self.active_pane()
        command = list(program.get("command", []))
        if not command:
            self.log_info(f"Program '{program.get('name')}' has no command")
            return
        virtual = pane.get("virtual")
        if virtual:
            # A virtual (search-results) pane has no single directory: bare names
            # resolved via one cwd can't reach files scattered across the tree.
            # Pass absolute paths, and run from the search root.
            args = [str(p) for p in self._selected_or_focused(pane)]
            cwd = str(virtual["root"])
        else:
            args = get_selected_or_cursor_files(pane)  # bare names, resolved via cwd
            cwd = str(pane["path"])
        env = os.environ.copy()
        ensure_common_paths_in_env(env)
        try:
            subprocess.Popen(command + args, cwd=cwd, env=env)
        except Exception as exc:
            self.log_info(f"Failed to launch {program.get('name')}: {exc}")
        else:
            self.log_info(f"Launched: {program.get('name')}")
        self.panel.render()

    def _jump_to_favorite(self, fav: dict) -> None:
        pane = self.active_pane()
        self._remember_cursor(pane)
        self._exit_virtual(pane)
        pane["path"] = Path(fav["path"])
        self._refresh(pane, on_ready=self._restore_remembered_cursor)
        self.log_info(f"Jumped to {fav['name']} ({fav['path']})")
        self.panel.render()

    def _select_by_name(self, pane: dict, name: str) -> None:
        """Land the cursor on the entry called ``name`` (after create/rename)."""
        for i, entry in enumerate(pane["files"]):
            if entry.name == name:
                pane["focused_index"] = i
                break

    def create_directory(self) -> None:
        """Prompt for a name and create a directory in the active pane — the
        canonical text-input dialog, mirroring ttk XeFM's create-directory flow."""
        pane = self.active_pane()
        if self._is_archive(pane["path"]):
            self.log_info("Cannot create a directory inside a read-only archive")
            return

        def validate(name: str) -> str | None:
            name = name.strip()
            if not name:
                return "Directory name cannot be empty"
            if (pane["path"] / name).exists():
                return f"'{name}' already exists"
            return None

        def accept(name: str) -> None:
            name = name.strip()
            try:
                (pane["path"] / name).mkdir(parents=True, exist_ok=False)
            except OSError as exc:
                self.log_info(f"Failed to create directory '{name}': {exc}")
            else:
                self.log_info(f"Created directory: {name}")
                self._refresh(pane)
                self._select_by_name(pane, name)
            self.panel.render()

        show_input(self.panel, title="New Directory", prompt="Name:",
                   on_accept=accept, validate=validate,
                   completer=FilepathCompleter(base_directory=str(pane["path"])),
                   region=self._active_pane_region())
        self.panel.render()

    def create_file(self) -> None:
        """Prompt for a name and create an empty file in the active pane."""
        pane = self.active_pane()
        if self._is_archive(pane["path"]):
            self.log_info("Cannot create a file inside a read-only archive")
            return

        def validate(name: str) -> str | None:
            name = name.strip()
            if not name:
                return "File name cannot be empty"
            if (pane["path"] / name).exists():
                return f"'{name}' already exists"
            return None

        def accept(name: str) -> None:
            name = name.strip()
            try:
                (pane["path"] / name).touch()
            except OSError as exc:
                self.log_info(f"Failed to create file '{name}': {exc}")
            else:
                self.log_info(f"Created file: {name}")
                self._refresh(pane)
                self._select_by_name(pane, name)
            self.panel.render()

        show_input(self.panel, title="New File", prompt="Name:",
                   on_accept=accept, validate=validate,
                   completer=FilepathCompleter(base_directory=str(pane["path"])),
                   region=self._active_pane_region())
        self.panel.render()

    def rename(self) -> None:
        """Rename in the active pane. With more than one file selected this opens
        the batch-rename dialog; otherwise it prompts for the focused entry."""
        pane = self.active_pane()
        files = pane["files"]
        if not files:
            self.log_info("No file to rename")
            return
        if self._is_archive(pane["path"]):
            self.log_info("Cannot rename inside a read-only archive")
            return
        selected = [f for f in files if str(f) in pane["selected_files"]]
        if len(selected) > 1:
            self.batch_rename(selected)
            return
        entry = files[pane["focused_index"]]
        original = entry.name

        def validate(name: str) -> str | None:
            name = name.strip()
            if not name:
                return "Name cannot be empty"
            if name == original:
                return None  # unchanged is allowed (a no-op on accept)
            if (entry.parent / name).exists():
                return f"'{name}' already exists"
            return None

        def accept(name: str) -> None:
            name = name.strip()
            if name == original:
                self.panel.render()
                return
            try:
                entry.rename(entry.parent / name)
            except OSError as exc:
                self.log_info(f"Failed to rename '{original}': {exc}")
            else:
                self.log_info(f"Renamed '{original}' to '{name}'")
                self._refresh(pane)
                self._select_by_name(pane, name)
            self.panel.render()

        show_input(self.panel, title="Rename", prompt="Rename to:", text=original,
                   on_accept=accept, validate=validate,
                   completer=FilepathCompleter(base_directory=str(entry.parent)),
                   region=self._active_pane_region())
        self.panel.render()

    def batch_rename(self, files: list) -> None:
        """Open the regex batch-rename dialog over the given selected files."""
        pane = self.active_pane()

        def done(success: int, errors: list[str]) -> None:
            for err in errors:
                self.log_info(f"Rename failed: {err}")
            self.log_info(f"Batch rename: {success} file(s) renamed"
                          + (f", {len(errors)} failed" if errors else ""))
            pane["selected_files"].clear()
            self._refresh(pane)
            self.panel.render()

        show_batch_rename(self.panel, files, on_done=done)
        self.panel.render()

    def _ensure_archive_password(self, entry, on_ready) -> None:
        """Gate opening ``entry`` when it lives inside an encrypted zip.

        For a file inside a password-protected ZipCrypto archive with no password
        yet known, prompt (masked), verify, remember it for the session, then run
        ``on_ready()``. AES-encrypted archives (which Python can't decrypt) are
        refused with a clear message. Ordinary files, unencrypted archive entries,
        and archives whose password is already known run ``on_ready()`` at once.

        ``on_ready`` is responsible for its own redraw, since the prompt path
        reaches it from an asynchronous dialog callback."""
        from xefm.archive import (
            archive_password_state, get_member_archive_path, try_archive_password)
        state = archive_password_state(entry)
        if state == "ok":
            on_ready()
            return
        if state == "aes":
            self.log_info(f"Cannot open {entry.name}: AES-encrypted zips are not supported")
            self.panel.render()
            return
        # state == "need": prompt for the ZipCrypto password.
        archive = get_member_archive_path(entry)
        archive_name = archive.name if archive is not None else entry.name

        def accept(password: str) -> None:
            if not password:
                self.panel.render()
                return
            if try_archive_password(entry, password):
                on_ready()
            else:
                prompt("Incorrect password — try again:")

        def prompt(error: str | None = None) -> None:
            show_input(
                self.panel, title="Password Required",
                prompt=error or f"Password for {archive_name}:", password=True,
                on_accept=accept, on_cancel=self.panel.render, select_all=False,
                region=self._active_pane_region())
            self.panel.render()

        prompt()

    def _open_viewer(self, entry, pane: dict | None = None) -> None:
        """Open ``entry`` in the matching built-in viewer and redraw.

        An image opens in the image viewer, handed the other images from ``pane``
        so its prev/next walks the list the user is looking at, in the order they
        see it (already sorted and filtered — see ``xefm.file_list_manager``). The
        list is snapshotted by the viewer, so a background refresh mutating the
        pane cannot shift the index underneath it. Everything else opens in the
        text viewer."""
        if is_image_file(entry):
            siblings = [f for f in (pane or {}).get("files", []) if is_image_file(f)]
            if entry not in siblings:  # a pane we were not given, or a stale list
                siblings = [entry]
            # Suspend the theme's post-effect while a picture is up: on a
            # CRT/Pip-Boy theme the effect is a full-view Core Image filter, so it
            # would tint the image and lay scanlines over it. Show the real
            # pixels instead; _restore_post_effect puts the effect back on close.
            # A no-op on themes without an effect and on terminals (set_post_effect
            # is a no-op there), so this never branches on the backend.
            theme = self.themes[self._theme_index][1]
            has_effect = theme.extras.get("post_effect") is not None
            if has_effect:
                self.backend.set_post_effect(None)
            show_image_viewer(self.panel, entry, siblings=siblings,
                              index=siblings.index(entry),
                              on_close=self._restore_post_effect if has_effect else None)
        else:
            show_text_viewer(self.panel, entry, state_manager=self.state_manager)
        self.panel.render()

    def _restore_post_effect(self) -> None:
        """Re-apply the active theme's post-effect and repaint — the close hook
        for the image viewer, which suspends it for a faithful picture."""
        self._apply_post_effect(self.themes[self._theme_index][1])
        self.panel.render()

    def view_file(self) -> None:
        """View the focused file (directories are skipped).

        A matching ``view`` entry in FILE_ASSOCIATIONS wins; otherwise the
        built-in viewer opens it, showing a placeholder for binaries rather
        than garbage. Setting ``view`` to ``None`` explicitly selects the
        built-in viewer, which is also what a remote or in-archive file gets —
        an external viewer has no path it could open. A file inside a
        password-protected zip prompts for the password first."""
        pane = self.active_pane()
        files = pane["files"]
        if not files:
            return
        entry = files[pane["focused_index"]]
        try:
            if entry.is_dir():
                self.log_info(f"{entry.name} is a directory")
                return
        except Exception:
            pass
        command = get_program_for_file(entry.name, "view")
        if command and self._launch_associated(entry, command):
            self.log_info(f"Viewing {entry.name} with {command[0]}")
            return
        self._ensure_archive_password(entry, lambda: self._open_viewer(entry, pane))

    def diff_files(self) -> None:
        """Compare exactly two selected files side by side. Files may be selected
        across both panes (mirrors ttk XeFM)."""
        selected: list = []
        for name in ("left", "right"):
            pane = self.pane(name)
            for entry in pane["files"]:
                if str(entry) in pane["selected_files"]:
                    selected.append(entry)
        files = []
        for entry in selected:
            try:
                if not entry.is_dir():
                    files.append(entry)
            except Exception:
                pass
        if len(files) != 2:
            self.log_info(f"Select exactly 2 files to compare (selected {len(files)})")
            return
        show_diff_viewer(self.panel, files[0], files[1])
        self.panel.render()

    def diff_directories(self) -> None:
        """Recursively compare the two panes' current directories side by side
        (the Shift-EQUAL action). Mirrors ttk XeFM's directory diff viewer."""
        left = self.pane("left")["path"]
        right = self.pane("right")["path"]
        show_directory_diff_viewer(self.panel, left, right,
                                   show_hidden=self.flm.show_hidden, config=self.config)
        self.panel.render()

    # --- file operations (copy / move / delete) ------------------------------

    def _selected_or_focused(self, pane: dict) -> list:
        """The operation targets: the explicitly selected entries, or — when the
        selection is empty — the single entry under the cursor. Returns Path
        objects (``selected_files`` stores string paths), preserving list order."""
        selected = [f for f in pane["files"] if str(f) in pane["selected_files"]]
        if selected:
            return selected
        entry = self._focused_entry()
        return [entry] if entry is not None else []

    def copy_names_to_clipboard(self) -> None:
        """Copy the active pane's selected file name(s) — or the cursor entry's
        name when nothing is selected — to the system clipboard, one per line
        (ttk XeFM's Cmd-Shift-C). On the curses backend the clipboard is process-
        local, but the copy still succeeds."""
        self._copy_to_clipboard(lambda f: f.name, "name")

    def copy_paths_to_clipboard(self) -> None:
        """Copy the active pane's selected full path(s) — or the cursor entry's
        path when nothing is selected — to the system clipboard, one per line
        (ttk XeFM's Cmd-Shift-P)."""
        self._copy_to_clipboard(str, "path")

    def _copy_to_clipboard(self, render, label: str) -> None:
        """Shared body of the clipboard-copy actions: gather the selection (or
        cursor entry), join ``render(entry)`` for each with newlines, push it to
        the clipboard, and report the count. ``label`` names the unit for the log
        message ("name" / "path")."""
        targets = self._selected_or_focused(self.active_pane())
        if not targets:
            self.log_info(f"No files to copy {label}s from")
            return
        text = "\n".join(render(f) for f in targets)
        self.panel.set_clipboard(text)
        count = len(targets)
        self.log_info(f"Copied {count} {label}{'s' if count != 1 else ''} to clipboard")

    def copy_files(self) -> bool:
        """Copy the active pane's selection (or cursor entry) into the other
        pane's directory (the 'C' key). Mirrors ttk XeFM's copy-to-other-pane.
        Returns True when a guard bailed out synchronously (see ``_transfer``)."""
        return self._transfer("copy")

    def move_files(self) -> bool:
        """Move the active pane's selection (or cursor entry) into the other
        pane's directory (the 'M' key, when a selection exists).
        Returns True when a guard bailed out synchronously (see ``_transfer``)."""
        return self._transfer("move")

    def duplicate_files(self) -> bool:
        """Duplicate the active pane's selection (or cursor entry) in place — a
        Finder-style copy into the same directory, auto-renamed with the shared
        ` (N)` scheme. Reachable from the menu bar and context menu (no default
        key). Returns True when a guard bailed out synchronously (see
        ``_transfer`` for why the caller then needs to redraw), False once the
        operation is handed off to the shared engine."""
        pane = self.active_pane()
        if pane.get("virtual"):
            # A search-results feed spans many directories — there is no single
            # directory to duplicate into. Reveal a real directory first.
            self.log_info("Cannot duplicate: this pane is a search-results view")
            return True
        if self._is_archive(pane["path"]):
            self.log_info("Cannot duplicate inside a read-only archive")
            return True
        targets = self._selected_or_focused(pane)
        if not targets:
            self.log_info("No file to duplicate")
            return True
        return self._run_duplicate(pane, targets)

    def _run_duplicate(self, pane: dict, targets: list) -> bool:
        """Hand a duplicate off to the shared engine, refreshing ``pane`` and
        landing the cursor on the new copy on completion. Callers must have
        already validated the pane (real directory, writable). Always returns
        False — the confirm dialog then drives its own redraws."""
        def on_complete(result: dict) -> None:
            pane["selected_files"].clear()
            created = result.get("created") or []
            on_ready = (lambda p: self._select_by_name(p, created[0])) if created else None
            self._refresh(pane, on_ready=on_ready)
            self.log_info(format_op_summary("Duplicate", result))
            self._report_op_failures("Duplicate", result)
            self.panel.render()

        self._fileops.duplicate(self.panel, targets, pane["path"],
                                on_complete=on_complete, log=self.log_info)
        return False

    def _report_op_failures(self, verb: str, result: dict, z: int = 70) -> None:
        """Pop a message box naming the items that failed (and why), so a failure
        buried in a long run of per-file log lines isn't missed."""
        body = format_op_errors(verb, result)
        if body is not None:
            show_message_box(self.panel, body, title=f"{verb} — errors",
                             icon="warning", buttons=("OK",), markdown=True, z=z)

    def _transfer(self, kind: str) -> bool:
        """Resolve the copy/move targets and destination from the panes, apply the
        pane-specific guards, then hand the run off to the shared
        :class:`~xefm.file_operations.FileOperationService` (which owns the confirm
        dialog, conflict prompt, and threaded progress). ``on_complete`` refreshes
        the panes and logs the summary.

        Returns True when a guard bailed out synchronously — the caller (``dispatch``)
        must then redraw so the just-logged reason is shown at once rather than on
        the next stray event. Returns False once the operation is handed off: the
        confirm dialog then drives its own redraws."""
        verb = "Copy" if kind == "copy" else "Move"
        src_pane = self.active_pane()
        dst_pane = self.pm.get_inactive_pane()
        if dst_pane.get("virtual"):
            # The other pane is a search-results feed, not a directory — there is
            # nowhere to write. Reveal a real destination first (O / Shift-O).
            self.log_info(f"Cannot {kind}: the other pane is a search-results view")
            return True
        if self._is_archive(dst_pane["path"]):
            # Browsed archives are read-only — copy/move out, never in.
            self.log_info(f"Cannot {kind}: the other pane is a read-only archive")
            return True
        if kind == "move" and self._is_archive(src_pane["path"]):
            # Move = copy + delete source; the archive source can't be deleted.
            self.log_info("Cannot move out of an archive — use copy instead")
            return True
        dest_dir = dst_pane["path"]
        targets = self._selected_or_focused(src_pane)
        if not targets:
            self.log_info(f"No file to {kind}")
            return True
        # A virtual source spans many directories, so the single "same directory"
        # guard doesn't apply — the per-target dest-exists check below still holds.
        if not src_pane.get("virtual") and str(dest_dir) == str(src_pane["path"]):
            if kind == "copy":
                # Copying into the source's own directory is a duplicate: auto-rename
                # with ` (N)` instead of erroring (the dest/archive guards above have
                # already cleared this directory as writable).
                return self._run_duplicate(src_pane, targets)
            self.log_info(f"Cannot {kind}: source and destination are the same directory")
            return True

        def on_complete(result: dict) -> None:
            self.flm.refresh_files(dst_pane)
            if kind == "move":
                self.flm.refresh_files(src_pane)
            src_pane["selected_files"].clear()
            self.log_info(format_op_summary(verb, result))
            self._report_op_failures(verb, result)
            self.panel.render()

        op = self._fileops.copy if kind == "copy" else self._fileops.move
        op(self.panel, targets, dest_dir, on_complete=on_complete, log=self.log_info)
        return False

    def delete_files(self) -> bool:
        """Delete the active pane's selection (or cursor entry) via the shared
        :class:`~xefm.file_operations.FileOperationService` (confirm honouring
        ``CONFIRM_DELETE``, directories removed recursively); refresh the pane and
        log the summary on completion.

        Returns True when a guard bailed out synchronously (see ``_transfer`` for
        why the caller then needs to redraw)."""
        pane = self.active_pane()
        targets = self._selected_or_focused(pane)
        if not targets:
            self.log_info("No file to delete")
            return True
        if any(self._is_archive(t) for t in targets):
            self.log_info("Cannot delete inside a read-only archive")
            return True

        def on_complete(result: dict) -> None:
            pane["selected_files"].clear()
            self._refresh(pane)
            self.log_info(format_op_summary("Delete", result))
            self._report_op_failures("Delete", result)
            self.panel.render()

        self._fileops.delete(self.panel, targets, on_complete=on_complete, log=self.log_info)
        return False

    # --- archives (create / extract) -----------------------------------------

    #: Recognised archive extensions → format label, longest suffixes first so
    #: ``.tar.gz`` is matched before ``.tar`` when scanning a filename's end.
    _ARCHIVE_EXTS = (
        (".tar.gz", "tar.gz"), (".tgz", "tar.gz"),
        (".tar.bz2", "tar.bz2"), (".tbz2", "tar.bz2"),
        (".tar.xz", "tar.xz"), (".txz", "tar.xz"),
        (".zip", "zip"), (".tar", "tar"),
    )
    #: tarfile write modes per format label (zip is handled separately).
    _TAR_MODES = {"tar": "w", "tar.gz": "w:gz", "tar.bz2": "w:bz2", "tar.xz": "w:xz"}

    @classmethod
    def _archive_format(cls, name: str) -> str | None:
        """The format label for ``name`` by its extension, or None if it isn't a
        recognised archive."""
        low = name.lower()
        return next((fmt for ext, fmt in cls._ARCHIVE_EXTS if low.endswith(ext)), None)

    @classmethod
    def _archive_basename(cls, name: str) -> str:
        """``name`` with its recognised archive extension stripped (the default
        extraction subdirectory), or unchanged if none matches."""
        low = name.lower()
        for ext, _fmt in cls._ARCHIVE_EXTS:
            if low.endswith(ext):
                return name[: -len(ext)]
        return name

    @staticmethod
    def _add_to_zip(zf, path, arcname: str) -> int:
        """Add ``path`` to an open ZipFile under ``arcname``, recursing into
        directories (tarfile recurses on its own; zipfile does not). Returns the
        number of files written."""
        if path.is_dir() and not path.is_symlink():
            count = 0
            for child in path.iterdir():
                count += XeFMApp._add_to_zip(zf, child, f"{arcname}/{child.name}")
            return count
        zf.write(str(path), arcname)
        return 1

    def _write_archive(self, sources: list, archive_path, fmt: str) -> int:
        """Write ``sources`` into a new archive at ``archive_path`` in ``fmt``.
        Local filesystem paths (this phase); returns the number of files added."""
        import tarfile
        import zipfile
        if fmt == "zip":
            with zipfile.ZipFile(str(archive_path), "w", zipfile.ZIP_DEFLATED) as zf:
                return sum(self._add_to_zip(zf, s, s.name) for s in sources)
        with tarfile.open(str(archive_path), self._TAR_MODES[fmt]) as tf:
            for s in sources:
                tf.add(str(s), arcname=s.name)  # tarfile recurses into directories
            return len(tf.getmembers())

    def _extract_archive(self, archive_path, dest_dir, fmt: str, pwd: bytes | None = None) -> int:
        """Extract ``archive_path`` into ``dest_dir`` (created if absent). Returns
        the number of entries. Tar extraction uses the ``data`` filter where
        available (Python 3.12+) to reject unsafe member paths.

        ``pwd`` (bytes) is the password for an encrypted zip; it is verified up
        front (:func:`xefm.archive.verify_zip_password`) so a missing/wrong
        password raises *before* any file is written, rather than leaving a
        half-extracted directory behind. A missing/wrong password raises
        ``RuntimeError``; AES encryption raises ``NotImplementedError``."""
        import tarfile
        import zipfile
        from xefm.archive import verify_zip_password
        dest_dir.mkdir(parents=True, exist_ok=True)
        if fmt == "zip":
            with zipfile.ZipFile(str(archive_path)) as zf:
                verify_zip_password(zf, pwd)  # no-op unless the zip is encrypted
                zf.extractall(str(dest_dir), pwd=pwd)
                return len(zf.namelist())
        with tarfile.open(str(archive_path)) as tf:
            members = tf.getmembers()
            try:
                tf.extractall(str(dest_dir), filter="data")
            except TypeError:  # older Python without the extraction filter
                tf.extractall(str(dest_dir))
            return len(members)

    def create_archive(self) -> bool:
        """Create an archive from the active pane's selection (or cursor entry)
        in the other pane's directory (the 'P' key). Prompts for a filename whose
        extension picks the format; an unrecognised extension defaults to
        ``.tar.gz``. Mirrors ttk XeFM's create-archive flow.

        Returns True when a guard bailed out synchronously (see ``_transfer`` for
        why the caller then needs to redraw)."""
        pane = self.active_pane()
        sources = self._selected_or_focused(pane)
        if not sources:
            self.log_info("No files to archive")
            return True
        if any(self._is_archive(s) for s in sources):
            self.log_info("Cannot archive files that live inside a read-only archive")
            return True
        dest_dir = self.pm.get_inactive_pane()["path"]
        if self._is_archive(dest_dir):
            self.log_info("Cannot create an archive inside a read-only archive")
            return True
        # Prefill a single item's name plus a dot, ready for the extension.
        initial = ""
        if len(sources) == 1:
            base = sources[0].stem if sources[0].is_file() else sources[0].name
            initial = f"{base}."

        def accept(name: str) -> None:
            name = name.strip()
            if not name:
                self.panel.render()
                return
            fmt = self._archive_format(name)
            if fmt is None:  # no recognised extension → default to .tar.gz
                name += ".tar.gz"
                fmt = "tar.gz"
            archive_path = dest_dir / name

            def go() -> None:
                try:
                    added = self._write_archive(sources, archive_path, fmt)
                except Exception as exc:
                    self.log_info(f"Archive creation failed: {exc}")
                else:
                    self.log_info(f"Created {name} ({added} file(s)) in {dest_dir}")
                self.flm.refresh_files(self.pm.get_inactive_pane())
                self.panel.render()

            if archive_path.exists():
                show_message_box(
                    self.panel, f"`{name}` already exists in the other pane. Overwrite?",
                    title="Create Archive", icon="warning", buttons=("Overwrite", "Cancel"),
                    default=1, cancel=1, markdown=True,
                    on_result=lambda l: go() if l == "Overwrite" else self.panel.render())
                self.panel.render()
            else:
                go()

        def validate(name: str) -> str | None:
            return None if name.strip() else "Archive name cannot be empty"

        show_input(self.panel, title="Create Archive", prompt="Archive filename:",
                   text=initial, on_accept=accept, validate=validate, select_all=False,
                   completer=FilepathCompleter(base_directory=str(dest_dir)),
                   region=self._active_pane_region())
        self.panel.render()
        return False

    def extract_archive(self) -> bool:
        """Extract the focused archive into a subdirectory (named after the
        archive) in the other pane's directory (the 'U' key). Confirms when
        ``CONFIRM_EXTRACT_ARCHIVE`` is set or the destination already exists.

        Returns True when a guard bailed out synchronously (see ``_transfer`` for
        why the caller then needs to redraw)."""
        entry = self._focused_entry()
        if entry is None:
            self.log_info("No file to extract")
            return True
        try:
            if not entry.is_file():
                self.log_info(f"{entry.name} is not a file")
                return True
        except Exception:
            pass
        fmt = self._archive_format(entry.name)
        if fmt is None:
            self.log_info(f"'{entry.name}' is not a supported archive")
            return True
        if self._is_archive(entry):
            self.log_info("Cannot extract an archive nested inside another archive")
            return True
        dest_dir = self.pm.get_inactive_pane()["path"]
        if self._is_archive(dest_dir):
            self.log_info("Cannot extract into a read-only archive")
            return True
        target = dest_dir / self._archive_basename(entry.name)

        def finish(exc: Exception | None, count: int) -> None:
            if exc is not None:
                self.log_info(f"Extraction failed: {exc}")
            else:
                self.log_info(f"Extracted {entry.name} → {target.name}/ ({count} entries)")
            self.flm.refresh_files(self.pm.get_inactive_pane())
            self.panel.render()

        def do_extract(pwd: bytes | None) -> None:
            """Run the extraction with an optional zip password. A wrong/missing
            password surfaces as ``RuntimeError`` (verified before any file is
            written), which re-opens the password prompt with an error."""
            try:
                count = self._extract_archive(entry, target, fmt, pwd=pwd)
            except RuntimeError:
                # Encrypted zip: the password was missing or wrong. Re-prompt
                # (nothing was written, thanks to the up-front verify).
                prompt_password(error="Incorrect password — try again:")
                return
            except NotImplementedError:
                # Defensive: AES is normally caught up front in go(); if a zip
                # slips through, report it clearly rather than as a raw traceback.
                self.log_info(
                    f"Cannot extract {entry.name}: AES-encrypted zips are not supported")
                self.flm.refresh_files(self.pm.get_inactive_pane())
                self.panel.render()
                return
            except Exception as exc:  # noqa: BLE001 — reported to the user
                finish(exc, 0)
                return
            if pwd is not None:
                # Remember the working password so browsing this same zip later
                # doesn't prompt again this session.
                from xefm.archive import set_archive_password
                set_archive_password(entry, pwd)
            finish(None, count)

        def prompt_password(error: str | None = None) -> None:
            show_input(
                self.panel, title="Extract Archive",
                prompt=error or f"Password for {entry.name}:", password=True,
                on_accept=lambda p: do_extract(p.encode("utf-8")) if p else self.panel.render(),
                on_cancel=self.panel.render, select_all=False,
                region=self._active_pane_region())
            self.panel.render()

        def go() -> None:
            # A password-protected zip needs a password before extraction. AES is
            # detected up front and refused with a clear message (Python's zipfile
            # can only decrypt legacy ZipCrypto). Other formats extract directly.
            if fmt == "zip":
                from xefm.archive import zip_encryption_status_path
                status = zip_encryption_status_path(str(entry))
                if status == "aes":
                    self.log_info(
                        f"Cannot extract {entry.name}: AES-encrypted zips are not supported")
                    self.panel.render()
                    return
                if status == "zipcrypto":
                    prompt_password()
                    return
            do_extract(None)

        exists = target.exists()
        if exists or getattr(self.config, "CONFIRM_EXTRACT_ARCHIVE", True):
            # Markdown message: the archive name and destination render as `code`
            # chips (backticks also shield a path's _ / * from markdown). A blank
            # line makes the warning a separate paragraph, not a folded-in clause.
            message = f"Extract `{entry.name}` to `{target}`?"
            if exists:
                message += "\n\nThe destination exists; files may be overwritten."
            show_message_box(
                self.panel, message, title="Extract Archive", icon="info",
                buttons=("Extract", "Cancel"), default=0, cancel=1, markdown=True,
                on_result=lambda l: go() if l == "Extract" else self.panel.render())
            self.panel.render()
        else:
            go()
        return False

    def _active_view(self) -> FilePane:
        return self.left_view if self.pm.active_pane == "left" else self.right_view

    #: First row of the Filter picker — selecting it clears the filter. A
    #: distinctive label so a real ``fnmatch`` glob never collides with it.
    _FILTER_CLEAR = "␀  (clear filter)"

    def enter_filter(self) -> None:
        """Filename-filter picker for the active pane (the ';' key).

        A searchable list of the saved filter history (fed by isearch's Enter and
        by past filters), plus a "clear filter" row on top. Type to narrow the
        list; ``↑/↓`` pick a row; ``Enter`` applies the highlighted pattern. If the
        typed text matches no saved pattern, ``Enter`` applies it verbatim — so a
        brand-new ``fnmatch`` glob (e.g. ``*.py``) still works. Directories are
        always shown; the applied pattern is (re)recorded most-recent-first."""
        pane = self.active_pane()

        def apply(pattern: str) -> None:
            pattern = pattern.strip()
            count = self.flm.apply_filter(pane, pattern)
            if pattern:
                self._record_filter_pattern(pattern)
                self.log_info(f"Filter '{pattern}': {count} item(s)")
            else:
                self.log_info("Filter cleared")
            self.panel.render()

        items = [self._FILTER_CLEAR, *self._filter_history()]
        show_filter_list(
            self.panel, items, title="Filter", to_label=lambda v: v,
            on_accept=lambda v: apply("" if v == self._FILTER_CLEAR else v),
            on_accept_text=apply, region=self._active_pane_region())
        self.panel.render()

    def enter_isearch(self) -> None:
        """Incremental search over the active pane (the 'F' key).

        The prompt is not a centered modal: an ``ISearchBar`` overlay is pinned to
        the active pane's footer bar (same slot, same size), so the list above
        stays visible and its cursor keeps moving as you type.

        Type a case-insensitive *contains* pattern (space-separated tokens all
        match); every hit is highlighted and the cursor jumps to the nearest match
        at/after its current position. ``Up``/``Down`` walk the previous/next
        match; ``Enter`` stops at the current match and records the pattern in the
        filter history (so the ';' Filter prompt can recall it); ``Esc`` cancels
        and restores the pre-search cursor. Reuses ``FileListManager.find_matches``
        for the hits."""
        if self._isearch_active or not self.active_pane()["files"]:
            return
        footer = self._footers.get(self.pm.active_pane)
        if footer is None or footer.rect is None:
            return  # footer not drawn yet — nothing to anchor to
        x, y, w, h = footer.rect
        self._isearch_active = True
        self._isearch_origin = self.active_pane()["focused_index"]
        self._isearch_matches = []
        self._active_view().search_matches = set()
        self._isearch_bar = ISearchBar(
            on_change=self._isearch_recompute,
            on_navigate=self._isearch_step,
            on_submit=self._isearch_stop,
            on_cancel=self._isearch_cancel,
            get_status=self._isearch_status,
        )
        # Positioned exactly over the footer, with its "status" surface so it
        # reads as the footer bar. No shadow/dim: the pane stays fully lit.
        self.panel.push_layer(self._isearch_bar, z=70,
                              hints={"surface": "status", "x": x, "y": y, "w": w, "h": h})
        self.panel.render()

    def _isearch_recompute(self, pattern: str) -> None:
        """Recompute the match set for ``pattern`` (fired live on every edit),
        repaint the pane's highlights, and jump the cursor to the nearest match
        at/after the current position (or back to the origin when nothing
        matches)."""
        pane = self.active_pane()
        matches = self.flm.find_matches(
            pane, pattern, match_all=True, return_indices_only=True)
        self._isearch_matches = matches
        self._active_view().search_matches = set(matches)
        if matches:
            cur = pane["focused_index"]
            pane["focused_index"] = next((m for m in matches if m >= cur), matches[0])
        else:
            pane["focused_index"] = self._isearch_origin
        self.panel.render()

    def _isearch_step(self, delta: int) -> None:
        """Move the cursor to the previous (``delta<0``) or next (``delta>0``)
        match, wrapping around the ends. A no-op when there are no matches."""
        matches = self._isearch_matches
        if not matches:
            return
        pane = self.active_pane()
        cur = pane["focused_index"]
        if cur in matches:
            idx = (matches.index(cur) + delta) % len(matches)
        elif delta > 0:
            idx = next((i for i, m in enumerate(matches) if m > cur), 0)
        else:
            idx = next((i for i in range(len(matches) - 1, -1, -1)
                        if matches[i] < cur), len(matches) - 1)
        pane["focused_index"] = matches[idx]
        self.panel.render()

    def _isearch_status(self) -> tuple[int, int]:
        """``(position, total)`` for the bar's match counter: the 1-based index of
        the cursor within the current matches (0 when it sits off any match) and
        the total number of matches."""
        matches = self._isearch_matches
        cur = self.active_pane()["focused_index"]
        pos = matches.index(cur) + 1 if cur in matches else 0
        return (pos, len(matches))

    def _isearch_close(self) -> None:
        """Tear down the isearch overlay and clear the pane's match highlights."""
        self._isearch_active = False
        self._isearch_matches = []
        self._active_view().search_matches = set()
        if (self.panel.has_layers
                and self.panel._layers[-1].widget is self._isearch_bar):
            self.panel.pop_layer()
        self._isearch_bar = None

    def _isearch_stop(self) -> None:
        """Enter in the field: keep the current match, record the pattern in the
        filter history (as a ready-to-apply glob), and close."""
        raw = self._isearch_bar.pattern.strip() if self._isearch_bar else ""
        self._isearch_close()
        if raw:
            self._record_filter_pattern(self._isearch_to_filter(raw))
        self.panel.render()

    def _isearch_cancel(self) -> None:
        """Esc / outside click: restore the pre-search cursor and close."""
        self.active_pane()["focused_index"] = self._isearch_origin
        self._isearch_close()
        self.panel.render()

    def _record_filter_pattern(self, pattern: str) -> None:
        """Add ``pattern`` to the most-recent-first filter history (persisted via
        the state manager, capped), so the ';' Filter prompt can recall it. Silent
        and best-effort — a history write must never break isearch."""
        pattern = pattern.strip()
        if not pattern:
            return
        try:
            hist = [p for p in self.state_manager.get_state(_FILTER_HISTORY_KEY, [])
                    if p != pattern]
            hist.insert(0, pattern)
            self.state_manager.set_state(_FILTER_HISTORY_KEY, hist[:_FILTER_HISTORY_MAX])
        except Exception:
            pass

    def _filter_history(self) -> list[str]:
        """The saved filter patterns, most-recent first (best-effort)."""
        try:
            hist = self.state_manager.get_state(_FILTER_HISTORY_KEY, [])
            return [p for p in hist if isinstance(p, str)]
        except Exception:
            return []

    @staticmethod
    def _isearch_to_filter(pattern: str) -> str:
        """Translate an isearch pattern into the single ``fnmatch`` glob the pane
        filter stores, so the saved/applied filter keeps the same *contains*
        semantics the search highlighted. A bare token becomes ``*token*``;
        multiple tokens chain (``foo bar`` -> ``*foo*bar*``); a pattern that
        already carries glob metacharacters is passed through untouched."""
        pattern = pattern.strip()
        if not pattern or any(c in pattern for c in "*?["):
            return pattern
        return "*" + "*".join(pattern.split()) + "*"

    def jump_to_path(self) -> None:
        """Prompt for a directory path and navigate the active pane there.
        Accepts ``~``, relative (to the current path), and absolute paths;
        mirrors ttk XeFM's jump-to-path. TAB completes directory names via
        :class:`xefm.completion.FilepathCompleter`."""
        pane = self.active_pane()
        current = str(pane["path"])

        def resolve(text: str) -> Path:
            text = text.strip()
            if text.startswith("~"):
                target = Path.home() / text[1:].lstrip("/")
            elif not os.path.isabs(text):
                target = Path(current) / text
            else:
                target = Path(text)
            return Path(os.path.normpath(str(target)))

        def validate(text: str) -> str | None:
            if not text.strip():
                return "Path cannot be empty"
            target = resolve(text)
            if not target.exists():
                return f"Path does not exist: {target}"
            if not target.is_dir():
                return f"Not a directory: {target}"
            return None

        def accept(text: str) -> None:
            target = resolve(text)
            self._remember_cursor(pane)
            pane["path"] = target
            pane["selected_files"].clear()
            self._refresh(pane, on_ready=self._restore_remembered_cursor)
            self.log_info(f"Jumped to: {target}")
            self.panel.render()

        # Prefill with the current path plus a trailing separator, ready to type
        # a child directory name (the ttk behaviour).
        initial = current if current.endswith(os.sep) else current + os.sep
        show_input(self.panel, title="Jump to Path", prompt="Path:", text=initial,
                   on_accept=accept, validate=validate, select_all=False,
                   completer=FilepathCompleter(base_directory=current, directories_only=True),
                   region=self._active_pane_region())
        self.panel.render()

    def compare_selection(self) -> None:
        """W: open the Compare & Select dialog, then mark items in the active pane
        by comparing each with the same-named item in the other pane. Blocked when
        either pane is a virtual (search-results) view — there's no real listing to
        compare against."""
        pane = self.active_pane()
        other = self.pm.get_inactive_pane()
        if pane.get("virtual") or other.get("virtual"):
            self.log_info("Compare & select needs two real directories")
            return
        if not pane["files"]:
            self.log_info("No items to compare")
            return

        def on_result(criteria) -> None:
            if criteria is None:
                self.log_info("Compare & select cancelled")
            elif criteria.needs_content:
                self._compare_with_content(pane, other, criteria)
                return  # the task drives its own redraw
            else:
                result = compute_compare_selection(
                    pane["files"], other["files"], criteria)
                self._apply_compare_result(pane, criteria, result)
            self.panel.render()

        show_compare_select(self.panel, region=self._active_pane_region(),
                            on_result=on_result)
        self.panel.render()

    def _compare_with_content(self, pane: dict, other: dict, criteria) -> None:
        """Content-comparison path: reads files, so it runs on the task worker with
        a cancellable progress dialog. Snapshots the pane feeds up front (the worker
        must not touch the panel) and applies the result on the main thread."""
        current_files = list(pane["files"])
        other_files = list(other["files"])
        task = Task("Comparing contents", config=self.config, kind="compare")

        def run(t: Task) -> dict:
            prog = t.progress
            prog.start_operation(OperationType.COPY, len(current_files),
                                 description="Comparing")
            prog.update_operation_total(len(current_files))  # leave the counting phase
            processed = [0]

            def advance(entry) -> None:
                processed[0] += 1
                prog.update_progress(entry.name, processed[0])

            result = compute_compare_selection(
                current_files, other_files, criteria,
                checkpoint=t.checkpoint, on_advance=advance)
            return {"result": result, "cancelled": t.cancelled()}

        def on_done(res: dict) -> None:
            if res.get("cancelled"):
                self.log_info("Compare & select cancelled")
            elif res.get("result") is not None:
                self._apply_compare_result(pane, criteria, res["result"])
            self.panel.render()

        self.tasks.submit(task, self.panel, run=run, on_done=on_done)

    def _apply_compare_result(self, pane: dict, criteria, result) -> None:
        """Fold the compared selection into the pane (replace or add) and log a
        file/dir summary."""
        if criteria.mode == "replace":
            pane["selected_files"] = set(result.paths)
        else:
            pane["selected_files"].update(result.paths)

        if result.total == 0:
            self.log_info("Compare & select: no matching items")
            return
        parts = []
        if result.files:
            parts.append(f"{result.files} file{'s' if result.files != 1 else ''}")
        if result.dirs:
            parts.append(f"{result.dirs} director{'ies' if result.dirs != 1 else 'y'}")
        verb = "Selected" if criteria.mode == "replace" else "Added"
        self.log_info(f"{verb} {result.total} item{'s' if result.total != 1 else ''} "
                      f"({' and '.join(parts)})")

    #: Help layout: (section title, [(action, description)]). Only actions the
    #: PuiKit port actually handles are listed, so the help never promises a
    #: feature that isn't wired yet.
    _HELP_SECTIONS = (
        ("Navigation", (
            ("cursor_up", "Move cursor up"),
            ("cursor_down", "Move cursor down"),
            ("page_up", "Scroll up by page"),
            ("page_down", "Scroll down by page"),
            ("open_item", "Open: enter a directory/archive, or view a file"),
            ("go_parent", "Go to parent directory"),
            ("switch_pane", "Switch active pane"),
            ("nav_left", "Focus left pane / go to parent"),
            ("nav_right", "Focus right pane / go to parent"),
            ("favorites", "Go to a favorite directory"),
            ("jump_to_path", "Jump to a typed path"),
            ("drives_dialog", "Open the drives / locations picker"),
            ("history", "Go to a recently-visited directory"),
            ("sync_current_to_other", "Go to the other pane's directory"),
            ("sync_other_to_current", "Send this directory to the other pane"),
        )),
        ("Selection", (
            ("select_file", "Toggle selection, move down"),
            ("select_file_up", "Toggle selection, move up"),
            ("select_all_files", "Toggle all files"),
            ("select_all_items", "Toggle all items"),
            ("select_all", "Select every item"),
            ("unselect_all", "Clear selection"),
            ("compare_selection", "Compare & select vs. other pane"),
        )),
        ("File Operations", (
            ("create_directory", "Create new directory"),
            ("create_file", "Create new file"),
            ("rename_file", "Rename file/directory"),
            ("copy_files", "Copy selection to the other pane"),
            ("copy_names", "Copy selection's name(s) to the clipboard"),
            ("copy_paths", "Copy selection's full path(s) to the clipboard"),
            ("move_files", "Move selection to the other pane"),
            ("delete_files", "Delete selection"),
            ("create_archive", "Create archive from selection"),
            ("extract_archive", "Extract the focused archive"),
            ("file_details", "Show file details"),
            ("edit_file", "Edit the focused file in $EDITOR"),
            ("subshell", "Open a shell in the current directory"),
            ("open_with_os", "Open with the default app"),
            ("reveal_in_os", "Reveal in the OS file manager"),
            ("programs", "Run an external program on the selection"),
        )),
        ("Search", (
            ("search", "Incremental search (jump to match)"),
            ("filter", "Filter list by filename pattern"),
            ("clear_filter", "Clear the filename filter"),
            ("search_dialog", "Recursive filename search"),
            ("search_content", "Recursive content (grep) search"),
        )),
        ("View", (
            ("view_file", "View file (text viewer)"),
            ("diff_files", "Compare two selected files"),
            ("toggle_hidden", "Toggle hidden files"),
            ("toggle_color_scheme", "Cycle color theme"),
            ("sort_menu", "Sort options (menu)"),
            ("quick_sort_name", "Quick-sort by name (repeat: reverse)"),
            ("quick_sort_size", "Quick-sort by size (repeat: reverse)"),
            ("quick_sort_date", "Quick-sort by date (repeat: reverse)"),
            ("quick_sort_ext", "Quick-sort by extension (repeat: reverse)"),
        )),
        ("Other", (
            ("edit_config", "Edit ~/.xefm/config.py, then reload"),
            ("reload_config", "Reload ~/.xefm/config.py"),
            ("help", "Show this help"),
            ("quit", "Quit XeFM"),
        )),
    )

    def _keys_label(self, action: str) -> str:
        """Comma-joined, display-formatted key(s) bound to ``action`` ("—" if
        unbound), for the help dialog."""
        keys, _ = self.keys.get_keys_for_action(action)
        if not keys:
            return "—"
        return ", ".join(self.keys.format_key_for_display(k) for k in keys)

    def show_help(self) -> None:
        """A scrollable key-binding reference, built live from the port's keymap.

        Each section renders as a Markdown heading over a two-column table
        (Key(s) / Action), so bindings align in a real column and the section
        titles stand out."""
        from xefm.const import VERSION
        lines = [f"# XeFM on PuiKit", f"Version {VERSION}", ""]
        for title, entries in self._HELP_SECTIONS:
            lines += [f"## {title}", "", "| Key(s) | Action |", "| --- | --- |"]
            for action, desc in entries:
                keys = self._keys_label(action).replace("|", "\\|")
                lines.append(f"| `{keys}` | {desc} |")
            lines.append("")
        show_markdown(self.panel, "\n".join(lines), title="Help")
        self.panel.render()

    @staticmethod
    def _about_text() -> str:
        """The About box body: name, version, and project URL (mirrors the legacy
        About dialog's content; its cosmetic Matrix-rain background is answered
        now by the theme's arriving-text effect, not a background animation)."""
        from xefm.const import VERSION, GITHUB_URL
        return (f"XeFM on PuiKit — Terminal File Manager\n"
                f"Version {VERSION}\n\n"
                f"{GITHUB_URL}")

    def show_about(self) -> None:
        """The About box.

        Deliberately a plain call: under a theme carrying a ``text_effect``
        (Sci-Fi) the body decodes into place because the box *appeared*, and
        under every other theme it opens plainly. That is the whole point of the
        text-animation system — the effect is theme data, so no call site in XeFM
        asks for it or knows it exists.
        """
        show_message_box(self.panel, self._about_text(),
                         title="About XeFM", icon="info", buttons=("OK",))
        self.panel.render()

    def _show_context_menu(self, pane_name: str, index: int, x: float, y: float) -> None:
        """Right-click on a row: activate that row, then pop a context menu at the
        pointer (native on macOS, a widget popup on curses)."""
        self.pm.active_pane = pane_name
        self._sync_active()
        pane = self.active_pane()
        pane["focused_index"] = index
        entry = pane["files"][index] if 0 <= index < len(pane["files"]) else None
        selected = entry is not None and str(entry) in pane["selected_files"]
        menu = Menu(
            MenuItem("Open", on_select=lambda: self._menu("open_item")),
            MenuItem("View File", on_select=self.view_file, enabled=entry is not None),
            MenuItem("Deselect" if selected else "Select",
                     on_select=lambda: self._menu("select_file")),
            SEPARATOR,
            MenuItem("Rename…", on_select=self.rename, enabled=entry is not None),
            MenuItem("Duplicate", on_select=self.duplicate_files, enabled=entry is not None),
            SEPARATOR,
            MenuItem("Copy to Other Pane", on_select=self.copy_files, enabled=entry is not None),
            MenuItem("Move to Other Pane", on_select=self.move_files, enabled=entry is not None),
            MenuItem("Delete", on_select=self.delete_files, enabled=entry is not None),
            SEPARATOR,
            MenuItem("Copy Name(s)", on_select=self.copy_names_to_clipboard,
                     enabled=entry is not None),
            MenuItem("Copy Full Path(s)", on_select=self.copy_paths_to_clipboard,
                     enabled=entry is not None),
            SEPARATOR,
            MenuItem("Show Hidden Files", on_select=lambda: self._menu("toggle_hidden"),
                     checked=lambda: self.flm.show_hidden),
        )
        self.panel.popup_menu(menu, x, y)
        self.panel.render()

    def _start_drag(self, pane_name: str, index: int, event) -> None:
        """A file row was dragged out: export it (or the whole selection, when the
        dragged row is part of it) as a native OS file drag, so it can be dropped
        onto Finder or another app. Local files only — a remote / archive entry
        has no OS file URL to hand over. On a backend without a drag source (the
        TUI), ``panel.begin_file_drag`` copies the paths to the clipboard instead;
        the caller never branches."""
        pane = self.pane(pane_name)
        files = pane["files"]
        if not (0 <= index < len(files)):
            return
        dragged = files[index]
        selected = pane["selected_files"]
        if selected and str(dragged) in selected:
            # Dragging any selected row carries the whole selection, in list order.
            entries = [f for f in files if str(f) in selected]
        else:
            entries = [dragged]
        paths = [str(f) for f in entries if self._is_local(f)]
        if not paths:
            self.log_info("Only local files can be dragged out")
            return
        # Remember which pane this drag came from *before* starting the session:
        # the TUI clipboard fallback fires on_complete synchronously, which would
        # otherwise clear the source right after we set it (see _on_drag_complete).
        self._drag_source_pane = pane_name
        self._drag_cancelled_in_place = False
        self.panel.begin_file_drag(
            paths, event=event, operations=("copy",),
            on_complete=lambda op: self._on_drag_complete(paths, op),
        )

    def _on_drag_complete(self, paths: list[str], operation: str) -> None:
        """Log the outcome once a drag-out session ends. PuiKit never deletes the
        originals (only ``copy`` is offered), so this is purely informational; a
        cancelled drop reports ``"none"`` and is ignored, as is a drag released in
        place on its own pane (the OS still ends it as ``copy``, but ``_on_drop``
        already cancelled the no-op — #230)."""
        # The session is over; forget its source pane so a later external drop
        # (no drag of ours in flight) is never mistaken for a released-in-place one.
        cancelled_in_place = self._drag_cancelled_in_place
        self._drag_source_pane = None
        self._drag_cancelled_in_place = False
        if cancelled_in_place:
            return
        if operation and operation != "none":
            n = len(paths)
            self.log_info(f"Dragged {n} item{'' if n == 1 else 's'} out ({operation})")

    def _on_drop(self, pane_name: str, index: int, paths: list) -> None:
        """Files were dropped onto a pane from another app (Finder, an editor):
        copy them into the drop target. The target is the directory *row* under
        the drop when it is a folder (like Finder), otherwise the pane's own
        directory. Refuses read-only destinations (a browsed archive) and a
        search-results (virtual) pane, and skips any source already sitting in the
        destination so a drop back onto its own folder is a no-op, not a conflict
        prompt. Reuses the shared copy engine (confirm + conflict resolution +
        threaded progress)."""
        pane = self.pane(pane_name)
        if pane.get("virtual"):
            self.log_info("Cannot drop here: this pane is a search-results view")
            return
        if self._is_archive(pane["path"]):
            self.log_info("Cannot drop here: this is a read-only archive")
            return
        dest_dir = pane["path"]
        files = pane["files"]
        if 0 <= index < len(files):
            entry = files[index]
            info = pane.get("file_info", {}).get(str(entry), {})
            is_dir = info.get("is_dir")
            if is_dir is None:
                try:
                    is_dir = entry.is_dir()
                except Exception:
                    is_dir = False
            if is_dir:
                dest_dir = entry  # drop onto a folder row targets that folder
        targets = []
        for p in paths:
            src = Path(p)
            if str(src.parent) != str(dest_dir):
                targets.append(src)
        if not targets:
            if pane_name == self._drag_source_pane:
                # Released back onto the pane the drag started from, over its own
                # directory: the files are already here, so cancel the drag
                # silently rather than reporting a no-op copy (#230). A drop onto a
                # sub-directory row of the same pane still resolves to real targets
                # above and copies, so only the released-in-place gesture cancels.
                # Flag it so _on_drag_complete also drops its "Dragged … out" log.
                self._drag_cancelled_in_place = True
                return
            self.log_info("Nothing to copy (already in this folder)")
            return

        def on_complete(result: dict) -> None:
            self.flm.refresh_files(pane)
            self.log_info(format_op_summary("Copy", result))
            self._report_op_failures("Copy", result)
            self.panel.render()

        self._fileops.copy(self.panel, targets, dest_dir,
                           on_complete=on_complete, log=self.log_info)
        self.panel.render()

    # --- run -----------------------------------------------------------------

    #: Positioned events routed to the widget under the pointer (the FilePanes own
    #: click + wheel/trackpad scroll and accept an OS FILE_DROP); keyboard uses
    #: XeFM's global keymap.
    _MOUSE = frozenset({
        EventType.MOUSE_DOWN, EventType.MOUSE_UP, EventType.MOUSE_CLICK,
        EventType.MOUSE_DRAG, EventType.MOUSE_SCROLL, EventType.FILE_DROP,
    })

    def _copy_log_selection(self, event) -> bool:
        """Copy the log pane's selected text to the clipboard on the platform
        copy chord (Cmd-C on macOS, Ctrl-C on the TUI / other platforms), then
        clear the selection. Only fires when the log holds keyboard focus and has
        a selection, so the chord otherwise falls through to the global keymap.
        Returns True when it handled the event (a redraw is due)."""
        if event.key != "c" or self._log_copy_mod not in event.modifiers:
            return False
        if self.panel.focused_leaf() is not self.log:
            return False
        text = self.log.selection_text()
        if not text:
            return False
        self.panel.set_clipboard(text)
        self.log.clear_selection()
        return True

    def on_event(self, event) -> None:
        # Flush any filesystem reloads that landed since the last frame, so user
        # input and idle ticks both surface them; render if a pane changed.
        if self._pump_monitoring():
            self.panel.render()
        if event.type is EventType.RESIZE:
            self.panel.render()
            return
        if event.type is EventType.MOUSE_MOVE:
            # Pointer movement only updates hover state — let the Splitters under
            # the cursor swap in their resize cursor (and drop it again on the way
            # out). GUI emits these; the TUI does not, so it's a GUI-only affordance.
            self.panel.dispatch_event(event)
            self.panel.render()
            return
        # A modal layer (message box, menu popup) owns events while open: route
        # everything to it and let XeFM's global keymap stand down.
        if self.panel.has_layers:
            if self.panel.dispatch_event(event):
                self.panel.render()
            return
        if event.type is EventType.KEY:
            # A copy chord over a focused, selected log pane copies the selection
            # (and clears it) before the global keymap sees the key; otherwise it
            # falls through to normal keymap handling.
            if self._copy_log_selection(event):
                self.panel.render()
                return
            has_sel = bool(self.active_pane()["selected_files"])
            action = self.keys.find_action_for_event(event, has_sel)
            if self.dispatch(action):
                self.panel.render()
            return
        if event.type in self._MOUSE:
            if self.panel.dispatch_event(event):
                self.panel.render()

    def run(self) -> None:
        self.panel.render()
        try:
            self.backend.run_event_loop(self.on_event)
        finally:
            self._restore_streams()

    def _restore_streams(self) -> None:
        """Put the real stdout/stderr back so anything printed after the event
        loop (a shutdown traceback, teardown warnings) reaches the terminal
        again. Idempotent: safe if the streams were already restored."""
        for stream in (sys.stdout, sys.stderr):
            if isinstance(stream, _StreamToLog):
                stream.drain_partial()
        if isinstance(sys.stdout, _StreamToLog):
            sys.stdout = self._orig_stdout
        if isinstance(sys.stderr, _StreamToLog):
            sys.stderr = self._orig_stderr


_BACKENDS = {"tui": "tui", "curses": "tui", "gui": "gui", "macos": "gui",
             "web": "web", "webbrowser": "web", "browser": "web"}


def create_parser() -> argparse.ArgumentParser:
    """Build the command-line parser. Factored out of ``main`` so the entry
    point's argument contract (``--version``, ``--help``, the pane flags) can be
    unit-tested without launching the app."""
    parser = argparse.ArgumentParser(
        prog="xefm",
        description=__doc__,
        epilog="Project home: https://github.com/shimomut/xefm",
    )
    parser.add_argument("-v", "--version", action="version",
                        version=f"XeFM {_VERSION}")
    parser.add_argument("--backend", default="tui", help="tui (curses) | gui (macOS)")
    # ``default=None`` lets us tell an explicit ``--left .`` from no flag: an
    # explicitly given directory wins over the one saved from the last session.
    parser.add_argument("--left", default=None, help="left pane startup directory")
    parser.add_argument("--right", default=None, help="right pane startup directory")
    return parser


def main() -> None:
    args = create_parser().parse_args()

    backend_name = _BACKENDS.get(args.backend, args.backend)
    # Publish the resolved backend so is_desktop_mode() (used by the config,
    # e.g. TEXT_EDITOR = 'code' in GUI vs 'vim' in terminal) reads it directly
    # rather than re-sniffing sys.argv. Set before get_config()/XeFMApp load the
    # config below.
    os.environ["XEFM_BACKEND"] = backend_name
    # The native GUI backend persists and restores the window's position and size
    # via the NSWindow frame-autosave feature; curses and the web backend (whose
    # window is a browser tab) ignore it, and WebBackend takes no such kwarg.
    backend_kwargs = {"frame_autosave_name": "XeFMMainWindow"} if backend_name == "gui" else {}
    # Ground the pixel backends' base (grid) font in the user's config: the base
    # unit — hence the on-screen text size — is derived from this font's glyph
    # box, so MONO_FONT_NAME and FONT_SIZE take effect here. The base font must be
    # monospaced; MONO_FONT_NAME=None falls back to PuiKit's bundled Noto Sans
    # Mono. Both the native GUI and the browser backend read it; curses has one
    # terminal font and no base_font parameter, so this is skipped there.
    if backend_name in ("gui", "web"):
        cfg = get_config()
        # Name the window / tab (and, on native GUI, the macOS app menu, e.g.
        # "Quit XeFM"); without this the backend falls back to its default "PuiKit".
        backend_kwargs["title"] = "XeFM"
        backend_kwargs["base_font"] = Font(
            family=cfg.MONO_FONT_NAME,
            size=float(cfg.FONT_SIZE),
            monospace=True,
        )
        # The default proportional face that PuiKit's widgets (markdown, message
        # boxes, text fields) — and XeFM's own proportional draws — resolve to via
        # an unnamed Font(). family=None lets PuiKit fall back to its bundled
        # default (Noto Sans, metrics-matched with the mono grid font), or the OS
        # UI font if the bundled files are unavailable; size comes from base_font
        # (both share FONT_SIZE).
        backend_kwargs["ui_font"] = Font(family=cfg.UI_FONT_NAME)
    backend = create_backend(backend_name, **backend_kwargs)
    with backend:
        XeFMApp(
            backend,
            args.left if args.left is not None else ".",
            args.right if args.right is not None else ".",
            left_provided=args.left is not None,
            right_provided=args.right is not None,
        ).run()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""XeFM — a dual-pane file manager for the desktop and the terminal.

One widget model, realized per backend by PuiKit: a native desktop window on
Windows and macOS, a VT-terminal TUI on Windows, macOS and Linux, or a browser
tab. Pick with ``--backend``; nothing above the backend seam branches on it.

The storage-agnostic core is backend-independent — ``xefm.path.Path`` for
listing (local, S3, SFTP, archives), ``PaneManager`` / ``FileListManager`` for
pane state, ``xefm.config``'s keymap — and the view renders through a custom
``FilePane`` widget hosted in a PuiKit ``Panel`` layout.

Navigation (cursor, pane switch, arrow-key focus, descend / go up), selection,
sort, hidden-file toggle, filename filter and incremental search, the built-in
text and diff viewers, and the create / rename / batch-rename / favorites /
jump-to-path dialogs are all wired — as are file operations (copy / move /
delete, threaded with progress and per-conflict resolution via ``xefm.task``),
archive browsing, and remote storage (S3 / SFTP).

    python -m xefm                       # terminal (VT) — the default
    python -m xefm --backend gui         # native desktop window (Windows/macOS)
    python -m xefm --backend web         # browser tab
    python -m xefm --left ./xefm --right ./test
"""

import argparse
import getpass
import importlib.util
import itertools
import contextlib
import os
import platform
import queue
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import types
import sys
from pathlib import Path as _StdPath
from urllib.parse import quote, unquote, urlsplit

from puikit import EventType, Font, Item, Panel, PostEffect, Style, TextAttribute, Theme, VSplit, WindowStyle, derive_theme, mix
from puikit.background import Shader, Wallpaper
from puikit.posteffect import PRESETS as _POST_EFFECT_PRESETS
from puikit.backends import create_backend
from puikit.menu import Menu, MenuItem, SEPARATOR
from puikit.text import elide
from puikit.layout import SizeRequest
from puikit.widgets import (BusyIndicator, LayoutView, LogView, MenuBar, Splitter,
                            show_message_box)
from puikit.widgets.base import Widget

from xefm import __version__ as _VERSION
from xefm import actions as _ctx
from xefm.actions import registry as _action_registry
from xefm.archive import (ArchiveFormatError, archive_format_for_name,
                          archive_format_label, archive_readable_formats,
                          archive_strip_suffix, archive_writable_formats,
                          get_archive_cache, get_member_archive_path,
                          release_archives_under, tar_zstd_supported)
from xefm.backend_detector import is_desktop_mode
# Every background scene XeFM offers is a fragment shader; a theme's ``animation`` key
# names one of these and ``_resolve_background`` turns it into a puikit ``Shader``.
from xefm.background_shaders import SCENE_OPTIONS, SHADER_KINDS
from xefm.config import (KeyBindings, apply_wide_chars, config_manager,
                         deprecated_names_notice,
                         get_builtin_handler_for_file, get_config,
                         get_drive_locations,
                         get_program_for_file, has_explicit_association,
                         keys_label_for_action, printable_text_notice,
                         terminal_shadowed_notice)
from xefm.dir_scan import is_hidden, alloc_from_stat
from xefm.disk_usage import UsageScan, reports_allocation
from xefm.file_list_manager import FileListManager
from xefm.file_monitor_manager import FileMonitorManager
from xefm.file_pane import DEFAULT_BG, LC_BODY, LC_LARGE, FilePane, _mix
from xefm.filter_list_dialog import show_filter_list
from xefm.history_input_dialog import show_history_input
from xefm.completion import FilepathCompleter
from xefm.connect_dialog import open_connect_server, run_connecting
from xefm.input_dialog import show_input
from xefm.choice_dialog import show_choice_dialog
from xefm import favorites
from xefm import attributes
from xefm import layouts
from xefm import tags
from xefm import trash
from xefm import netmount
from xefm import open_with
from xefm.options import OptionSet
from xefm.progressive_search_dialog import SearchFailed, show_progressive_search
from xefm import search_options as search_opts
from xefm import search_filters
from xefm.isearch_bar import ISearchBar
from xefm import filters
from xefm import name_key
from xefm import (content_read, document_text, keymap_presets, os_index,
                  similar_scan, tree_walk, xft)
from xefm.file_clipboard import FileClipboard, conflicts as clipboard_conflicts
from xefm.quick_view import QuickView
from xefm import event_log
from xefm import key_sequence
from xefm.log_manager import (LOG_ERROR_SOURCE, LOG_SOURCE, clear_log_sink,
                              getLogger, route_library_logger, set_log_sink)
from xefm.pane_manager import PaneManager
from xefm import command_list
from xefm import path_list
from xefm import path_schemes
from xefm.path import Path
from xefm import search_match
from xefm import sort_keys
from xefm.state_manager import get_state_manager
from xefm.str_format import abbreviate_path, format_size
from xefm.user_api import (ActionContext, PaneApi, hooks as _hooks,
                           load_user_entries, menu_items as user_menu_items,
                           preview_notice, report_user_failure, run_guarded)
from xefm.batch_rename_dialog import show_batch_rename
from xefm.remote_edit import EditSessions, RemoteChanged, can_write_back
from xefm.rename_in_editor import (UnlistableName, apply_plan, names_text,
                                   parse_plan)
from xefm.compare_dialog import show_compare_select
from xefm.compare_selection import compute_compare_selection
from xefm.sort_dialog import show_sort_dialog
from xefm.progress_manager import OperationType
from xefm.diff_viewer import show_diff_viewer
from xefm.directory_diff_viewer import show_directory_diff_viewer
from xefm.worker_pool import DaemonPool
from xefm.file_operations import (CloseGate, FileOperationService,
                                  format_op_errors, format_op_summary,
                                  serialized_log, transfer_workers)
from xefm.task import Cancelled, Task, TaskManager, TaskStatus
from xefm.text_dialog import show_markdown
from xefm.tips import tip_count
from xefm.tips_dialog import show_tips_dialog
from xefm import image_decoders
from xefm.image_viewer import is_image_file, show_image_viewer
from xefm.text_viewer import looks_binary, show_text_viewer
from xefm.binary_compare import show_byte_comparison
from xefm.viewer_registry import rich_renderer_for

#: Share of the content area given to the file panes (vs the log pane) before
#: ``DEFAULT_LOG_HEIGHT_RATIO`` became the configurable default (#316). Kept as
#: the fallback default assumed for saved layouts that predate the config wiring
#: (see ``_restore_layout_and_paths``) and for a config that fails to load.
PANES_FRACTION = 0.74

#: Persistent, most-recent-first history of filename-filter patterns (fed by the
#: ';' Filter prompt), and the cap kept in the store.
_FILTER_HISTORY_KEY = "filter.history"
_FILTER_HISTORY_MAX = 100

#: Cap on the recent-directory history behind the History picker, applied both
#: in memory (``_record_history_path``) and when persisted to the state DB.
_HISTORY_MAX = 100

#: Tip-of-the-day rotation state (issue #261): whether the startup dialog is
#: enabled (the dialog's "Don't show tips at startup" checkbox writes it), the
#: index of the next unseen tip, and the local date it last opened at startup —
#: several launches in one day surface at most one tip.
#: What a key label reads when no context binds the action — the help dialog
#: and the tips both render this, and the help tells it apart from a real
#: binding by comparing against it rather than by how it looks.
UNBOUND_KEYS = "—"

#: The scheme of a Help-dialog link to an action's page
#: (``xefm-action:copy_files``). XeFM's own: the dialog's link handler takes
#: it and declines every other link, which PuiKit then opens as usual.
_ACTION_LINK = "xefm-action:"

_TIPS_ENABLED_KEY = "tips.enabled"
_TIPS_INDEX_KEY = "tips.index"
_TIPS_LAST_SHOWN_KEY = "tips.last_shown"


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
      uses for the same intent. A scene listed in ``SCENE_OPTIONS`` also reads its
      own keys from the dict (``earth``: ``shot``, ``lens``, ``clouds``,
      ``exposure``).
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
            options: dict = {}
            if isinstance(animation, dict):
                atype = animation.get("type", _ANIM_DEFAULT_KIND)
                params.update({k: animation[k] for k in _ANIM_PARAMS if k in animation})
                keys = SCENE_OPTIONS.get(atype, ((), None))[0]
                options = {k: animation[k] for k in keys if k in animation}
            else:  # a type string, or True for the tuned default
                atype = animation if isinstance(animation, str) else _ANIM_DEFAULT_KIND
            if atype not in SHADER_KINDS:
                return None
            # A scene with options of its own (earth's shot and lens) rebuilds its
            # fields from them; the rest take their registry entry as it stands.
            fields = SCENE_OPTIONS[atype][1](**options) if options else SHADER_KINDS[atype]
            params.setdefault("color", color)
            params.setdefault("backdrop", backdrop)
            # ``color`` is the theme foreground, which a shader receives as its
            # ``ink`` uniform — same intent, the name the GPU contract uses.
            return Shader(speed=params["speed"], opacity=params["opacity"],
                          ink=params["color"], backdrop=params["backdrop"],
                          **fields)
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
                    # Only the focused pane's cue is amber; the resting pane's is
                    # the derived gray (file_pane._cursor_fg). A dimmed amber next
                    # to a bright one is the same cue twice.
                    cursor={"active": (255, 158, 54)},
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
                   # Focused pane only — the resting one takes the derived gray
                   # (see Sci-Fi above).
                   cursor={"active": (255, 196, 84)},
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
                         # The one theme that still names its resting cue. Everywhere
                         # else it is a neutral gray, which a two-colour LCD panel does
                         # not have — and it needs none: near-black beside mid-green is
                         # already as far apart as this palette goes.
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
                       cursor={"active": (232, 244, 255)},
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
    #
    # Earth: the planet from orbit behind the panes (the ``earth`` scene, see
    # xefm.background_earth) — a deep-space navy for the base, the pale blue of the
    # lit limb for the chrome, and the amber of a sunrise on the atmosphere for the
    # things to find. The scene is physically coloured and ignores ``ink``, so
    # nothing here is chosen to steer it; the palette is chosen to sit on it.
    ("Earth", dict(bg=(6, 10, 20), fg=(226, 234, 244), muted=(140, 158, 186),
                   accent=(126, 190, 250), surface=(16, 24, 40), selection=(30, 62, 104),
                   accent2=(255, 184, 108),
                   status=lambda p: mix(p["bg"], p["accent"], 0.16),
                   footer=lambda p: mix(p["bg"], p["accent"], 0.16),
                   file_types={"directory": (150, 206, 255), "link": (255, 184, 108)},
                   cursor={"active": (255, 184, 108)},
                   syntax={"keyword": (150, 206, 255), "string": (255, 196, 128),
                           "comment": (140, 158, 186), "number": (255, 222, 150),
                           "operator": (196, 176, 255), "builtin": (128, 226, 214)},
                   # Shinagawa's reason, more so: the text sits over imagery, some of
                   # it a sunlit disc, and a shadow is what keeps a glyph's edge.
                   post_effect={"drop_shadow": 0.5},
                   # Every scene is a random pairing of a composition and a lens
                   # look (the scene's defaults), held for about 40 s at this speed
                   # while the camera drifts, then eased into the next over about
                   # 20 s; a new random one on every launch and every return from
                   # idle. The
                   # picture is shown whole (``opacity`` 1) and kept off the text by
                   # the scene's own ceiling instead: no pixel brighter than half
                   # white (its ``brightness`` default), so even a sunlit ocean
                   # cannot wash out a file name. Dimming by opacity would grey the
                   # night side toward the navy while leaving the glint hot.
                   animation={"type": "earth", "speed": 0.8, "opacity": 1.0},
                   opacity=0.72)),   # chrome at 72%: the planet reads, the list wins
    # Blocks: a field of blue-black metal columns in blue fog (the ``blocks``
    # scene, see xefm.background_blocks), rising and falling at their own uneven
    # pace, with light leaking up between them now and then. The base is the
    # scene's own fog, which it takes from the theme background; the leaks are
    # the accent cyan, which the scene takes as its ink; amber, the warm leak of
    # the prototype's palette, marks the things to find.
    ("Blocks", dict(bg=(10, 22, 38), fg=(214, 230, 244), muted=(136, 160, 186),
                    accent=(99, 214, 255), surface=(18, 34, 54), selection=(28, 68, 104),
                    accent2=(255, 179, 92),
                    status=lambda p: mix(p["bg"], p["accent"], 0.16),
                    footer=lambda p: mix(p["bg"], p["accent"], 0.16),
                    file_types={"directory": (130, 214, 255), "link": (255, 179, 92)},
                    cursor={"active": (255, 179, 92)},
                    syntax={"keyword": (130, 214, 255), "string": (255, 196, 128),
                            "comment": (136, 160, 186), "number": (255, 222, 150),
                            "operator": (196, 176, 255), "builtin": (128, 226, 214)},
                    post_effect={"drop_shadow": 0.5},
                    # Tuned at speed 1: the camera's loop is about five minutes.
                    animation={"type": "blocks", "color": (99, 214, 255), "speed": 1.0,
                               "opacity": 1.0},
                    opacity=0.66)),
    # Crystal: the brand's own scene — cyan crystals growing out of black basalt,
    # filmed as a macro (the ``crystal`` scene, see xefm.background_crystal). XeFM
    # is named for the xenolith, the foreign stone caught in rock. Graphite base,
    # the icon's cyan for the accent and for the glass (the scene's ink), amber
    # for what to find.
    ("Crystal", dict(bg=(21, 24, 27), fg=(214, 221, 224), muted=(138, 151, 159),
                     accent=(88, 199, 222), surface=(30, 35, 39), selection=(28, 70, 82),
                     accent2=(255, 154, 82),
                     status=lambda p: mix(p["bg"], p["accent"], 0.14),
                     footer=lambda p: mix(p["bg"], p["accent"], 0.14),
                     file_types={"directory": (88, 199, 222), "link": (255, 154, 82)},
                     cursor={"active": (255, 154, 82)},
                     syntax={"keyword": (88, 199, 222), "string": (255, 182, 120),
                             "comment": (138, 151, 159), "number": (255, 214, 150),
                             "operator": (196, 176, 255), "builtin": (140, 222, 170)},
                     post_effect={"drop_shadow": 0.5},
                     # Tuned at speed 1: one orbit of the rock is about 140 s.
                     animation={"type": "crystal", "color": (88, 199, 222), "speed": 1.0,
                                "opacity": 1.0},
                     opacity=0.6)),
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


def _tuple_colors(val):
    """``val`` with every color written as a list — ``[r, g, b]`` or
    ``[r, g, b, a]`` — turned into the tuple PuiKit expects, at the top level
    and inside nested dicts. A theme contributed as a TOML table can only spell
    a color as a list, and PuiKit hashes colors, so a list one crashed the first
    draw after the theme was selected (#708). Other values pass through."""
    if isinstance(val, dict):
        return {k: _tuple_colors(v) for k, v in val.items()}
    if isinstance(val, list):
        if len(val) in (3, 4) and all(
                isinstance(c, (int, float)) and not isinstance(c, bool) for c in val):
            return tuple(val)
        return [_tuple_colors(v) for v in val]
    return val


def _merge_theme_override(spec: dict, override: dict) -> dict:
    """Merge one user theme's overrides (config.py, friendly keys) onto a base
    theme ``spec`` (``_theme`` keywords). Colors replace; the sub-dict palettes
    (``syntax``, ``file_types``) deep-merge so the user recolors only the entries
    they name (keeping the base's other choices). ``base`` is consumed by the
    caller; unknown keys are ignored. Colors written as lists (the only form a
    TOML manifest has) become tuples."""
    merged = dict(spec)
    for key, kw in _THEME_OVERRIDE_MAP.items():
        if key not in override:
            continue
        val = _tuple_colors(override[key])
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


#: Between a search's banner and the root its rows are named from.
#: The directory context menu's "open this directory in the OS" item, named
#: for the file manager the platform actually has.
_FILE_MANAGER_OPEN_LABEL = {"Darwin": "Open in Finder",
                            "Windows": "Open in Explorer"}.get(
                                platform.system(), "Open in File Manager")

_VIRTUAL_ROOT_SEP = "  ·  "

#: The narrowest a list's title is cut to before its root starts giving way.
_MIN_TITLE = "Cl…"


def _virtual_header_text(virtual: dict, avail: float, measure=len) -> str:
    """The header of a virtual pane, fitted to ``avail``: what the pane holds,
    and the root its rows are named relative to. No row count — the footer
    already has it.

    **A list** — or a flat view, titled ``Flat view`` — reads ``[title] root``,
    in the bracket style of an archive's
    ``[foo.zip]/sub``, and the root has priority. It is derived from the paths,
    not from where the pane was, so the header is the one place that says what
    a row's ``src/main.py`` is relative to. When space runs out the title is
    cut first, down to :data:`_MIN_TITLE`, and only then is the root shortened
    — by whole components, as a directory header is. A list whose rows share
    no root shows the title alone: each row already carries its whole path.

    **A search** reads ``⌕ "query" (mode)  ·  root``, and there the banner has
    priority: the root is the directory the search was started from, which the
    user chose, and it is dropped rather than shown as a fragment."""
    root = virtual.get("root")
    has_root = root is not None and root is not name_key.WHOLE_PATH

    if virtual.get("kind") in ("list", "flat"):
        title = virtual["title"]
        if not has_root:
            return elide(f"[{title}]", avail, where="end", measure=measure)
        root_str = str(root)
        room = avail - measure(f"[] {root_str}")
        if measure(title) > room:
            title = elide(title, max(room, measure(_MIN_TITLE)), where="end",
                          measure=measure)
        tag = f"[{title}] "
        shown = abbreviate_path(root_str, avail - measure(tag), measure=measure)
        return elide(tag + shown, avail, where="end", measure=measure)

    mode = {"content": "content", "index": os_index.engine() or "index"}.get(
        virtual["mode"], "filename")
    narrowed = virtual.get("filters") or ""
    query = virtual["query"]
    if query:
        label = f'⌕ "{query}" ({mode}{" · " + narrowed if narrowed else ""})'
    else:
        label = f'⌕ {narrowed} ({mode})'
    if has_root:
        room = avail - measure(label + _VIRTUAL_ROOT_SEP)
        # Enough for a short leaf; anything less would be a fragment.
        if room >= measure("x" * 8):
            shown = abbreviate_path(str(root), room, measure=measure)
            if measure(shown) <= room:
                return label + _VIRTUAL_ROOT_SEP + shown
    return elide(label, avail, where="end", measure=measure)


def _xft_header_text(path, avail: float, measure=len) -> str:
    """``[results.xft]/group`` for a pane inside an ``.xft`` tree, and —
    while its producer is still rewriting it — that the groups may change,
    with the producer's progress. That part has priority over the path: acting
    on a provisional group without knowing it is the mistake to prevent."""
    file_path, key = xft.split(path)
    label = f"[{_StdPath(file_path).name}]" + (f"/{key}" if key else "")
    try:
        doc = xft.load(file_path)
    except OSError:
        doc = None
    if doc is None or not doc.provisional:
        return abbreviate_path(label, avail, measure=measure)
    pct = doc.progress_text()
    note = f"  ·  scanning{' ' + pct if pct else ''} — groups may change"
    room = avail - measure(note)
    if room < measure("x" * 8):
        return elide(note.strip(" ·"), avail, where="end", measure=measure)
    return abbreviate_path(label, room, measure=measure) + note


def _tab_label(pane: dict) -> str:
    """What a tab is called in the strip: a directory's last component (the
    whole path at a root, so ``/`` and ``s3://bucket/`` still say something),
    an archive by its file name, a list by its title, a search by its query."""
    virtual = pane.get("virtual")
    if virtual:
        if virtual.get("kind") == "search":
            return f'⌕ {virtual.get("query", "")}'
        root = virtual.get("root")
        name = getattr(root, "name", "") if root is not name_key.WHOLE_PATH else ""
        title = virtual.get("title", "")
        return f"[{title}] {name}" if name else f"[{title}]"
    path_str = str(pane["path"])
    if path_str.startswith("archive://"):
        label = _archive_header_label(path_str)
        return label.rsplit("/", 1)[-1] or label
    return pane["path"].name or path_str


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


def _stem_selection(name: str, is_dir: bool) -> tuple[int, int] | None:
    """The rename prompt's initial selection: the span of ``name``'s stem, or
    None to select the whole name. Selecting only the stem lets typing replace
    the name body while the extension survives. Directories, dotfiles, and
    extensionless names have no extension to protect, so they keep the
    whole-name selection."""
    stem = name if is_dir else os.path.splitext(name)[0]
    return (0, len(stem)) if 0 < len(stem) < len(name) else None


def _subshell_command(config) -> list[str]:
    """The command the subshell action launches: ``SUBSHELL`` from the config
    if set, else ``$SHELL``, else the platform default — ``%COMSPEC%``
    (cmd.exe) on Windows, ``/bin/sh`` elsewhere (issue #288). A string names a
    single command; a list carries arguments. No shlex-splitting: a Windows
    path like ``C:\\Windows\\system32\\cmd.exe`` must survive intact."""
    shell = getattr(config, "SUBSHELL", None) or os.environ.get("SHELL")
    if not shell:
        shell = os.environ.get("COMSPEC", "cmd.exe") if os.name == "nt" else "/bin/sh"
    return list(shell) if isinstance(shell, (list, tuple)) else [shell]


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



def _same_volume(sources: list, dest_dir) -> bool:
    """Whether every source lives on the volume ``dest_dir`` is on — the test
    Finder and Explorer use to pick move over copy for an unmodified drop.
    Anything not local, or not stat-able, counts as another volume (copy)."""
    if path_schemes.is_uri(str(dest_dir)):
        return False
    try:
        dest_dev = os.stat(str(dest_dir)).st_dev
    except OSError:
        return False
    for src in sources:
        if path_schemes.is_uri(str(src)):
            return False
        try:
            if os.lstat(str(src)).st_dev != dest_dev:
                return False
        except OSError:
            return False
    return True


def _breadcrumbs(text: str, path, pad_x: float, measure) -> list:
    """The clickable components of a header ``text`` showing ``path``.

    The text is what the header drew — possibly abbreviated (``/…/b/c``,
    ``~/x``, ``[a.zip]/d``) — so components are matched to directories from
    the right: the last name is ``path``, the one before it its parent, and so
    on up ``Path.parent``, which walks archives and remote locations the same
    way Backspace does. An ellipsis is not a place; a leading separator is the
    root."""
    ancestors, seen, p = [], set(), path
    while p is not None and str(p) not in seen:
        ancestors.append(p)
        seen.add(str(p))
        try:
            parent = p.parent
        except Exception:  # noqa: BLE001 — a backend without parents: stop
            break
        if str(parent) == str(p):
            break
        p = parent
    runs = [(m.start(), m.end()) for m in re.finditer(r"[^/\\]+", text)]
    crumbs = []
    for k, (a, b) in enumerate(reversed(runs)):
        if k >= len(ancestors):
            break
        if "…" in text[a:b]:
            continue
        child = ancestors[k - 1].name if k > 0 else None
        crumbs.append((pad_x + measure(text[:a]), pad_x + measure(text[:b]),
                       ancestors[k], child))
    if text[:1] in ("/", "\\") and len(ancestors) > len(runs):
        root = ancestors[-1]
        child = ancestors[-2].name if len(ancestors) > 1 else None
        crumbs.append((pad_x, pad_x + measure(text[:1]), root, child))
    return crumbs

class PaneHeader(Widget):
    """The location bar above a pane: its current path, brighter when active."""

    def __init__(self, app: "XeFMApp", pane_name: str):
        self.app = app
        self.pane_name = pane_name
        # Captured each draw, for menu_anchor: the bar's screen rect and the
        # path text's left inset.
        self._abs: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
        self._pad_x = 0.0
        #: The path's clickable components from the last draw:
        #: ``(x0, x1, directory, child name)`` — a click between x0 and x1 goes
        #: to ``directory`` with the cursor on ``child`` (#589).
        self._crumbs: list = []
        self._path_row: tuple[float, float] | None = None
        #: The tab strip's row and each tab's ``(x0, x1, index)``, captured
        #: each draw so a click can tell which tab it landed on.
        self._tab_row: tuple[float, float] | None = None
        self._tab_hits: list[tuple[float, float, int]] = []

    def _tabs(self) -> list:
        return self.app.pm.tabs[self.pane_name]

    def menu_anchor(self) -> tuple[float, float]:
        """Where the directory's context menu opens from the keyboard: hanging
        from this bar — the line that names the directory — under the start of
        the path, so it reads as a menu for the directory rather than for the
        first row of the listing below."""
        x, y, _w, h = self._abs
        return x + self._pad_x, y + h

    def draw(self, ctx) -> None:
        pane = self.app.pane(self.pane_name)
        active = self.app.pm.active_pane == self.pane_name
        # Inset the text from the top/left/right; the surface fills the whole slot.
        pad_x, pad_y = _bar_pad(ctx)
        self._abs = ctx.screen_rect
        self._pad_x = pad_x
        avail = max(0.0, ctx.size_units[0] - 2 * pad_x)
        virtual = pane.get("virtual")
        if virtual:
            # Not a directory: a search-results feed or an imported list. Say so
            # (and which pane an operation will hit) first, then the root its
            # rows are named from.
            text = _virtual_header_text(virtual, avail, measure=ctx.measure_text)
        elif self.app._is_archive(pane["path"]):
            # A browsed archive: show [archive.zip]/sub rather than the raw URI.
            label = _archive_header_label(str(pane["path"]))
            text = abbreviate_path(label, avail, measure=ctx.measure_text)
        elif xft.is_xft_path(pane["path"]):
            text = _xft_header_text(pane["path"], avail, measure=ctx.measure_text)
        else:
            # Drop whole directory components rather than cutting mid-name, so
            # every name still on screen is one the user can actually read.
            text = abbreviate_path(str(pane["path"]), avail, measure=ctx.measure_text)
        fg = ctx.theme.accent if active else ctx.theme.text
        path_y = pad_y
        tabs = self._tabs()
        if len(tabs) > 1:
            self._draw_tabs(ctx, tabs, pad_x, pad_y, avail, active)
            path_y += 1.0
        else:
            self._tab_row = None
            self._tab_hits = []
        ctx.draw_text(pad_x, path_y, text, Style(fg=fg, attr=TextAttribute.BOLD))
        self._path_row = (path_y, path_y + 1.0)
        self._crumbs = ([] if virtual else
                        _breadcrumbs(text, pane["path"], pad_x, ctx.measure_text))

    #: The rounding of a tab's top corners, in device pixels, where the
    #: backend draws vector shapes.
    _TAB_RADIUS_PX = 6.0

    def _draw_tabs(self, ctx, tabs, pad_x, y, avail, active) -> None:
        """The tab strip: one chip per tab, ``1 src  2 docs  3 ⌕ TODO``, with a
        gap between chips so every tab has an edge. The strip's ground is the
        content surface, set back from the header; the current tab is the
        header's own colour, so it runs on into the path row below like a
        browser's tab, and its label is bold — in the accent on the active pane,
        as the path is. The others sit halfway between ground and header, with
        muted text. Every tab gets an equal share when they do not all fit, each
        label elided to its share.

        Three distinct fills — ground, idle tab, current tab — so every tab has
        an edge and the current one is plain on any theme (#563, #620 hand
        checks). Text is inked against the chip it sits on."""
        theme = ctx.theme
        base = ctx.background or DEFAULT_BG
        ground = theme.surfaces.get("content", DEFAULT_BG)
        idle_bg = _mix(ground, base, 0.5)
        current_bg = base
        idle_fg = ctx.ink(theme.muted_text, on=idle_bg, target=LC_LARGE)
        current_fg = ctx.ink(theme.accent if active else theme.text, on=current_bg,
                             target=LC_BODY)
        # The ground runs the bar's whole width and up over its top inset, so
        # the strip reads as one band above the header.
        ctx.fill_rect(0.0, 0.0, ctx.size_units[0], y + 1.0, Style(bg=ground))
        current = self.app.pm.tab_index[self.pane_name]
        gap = 1.0
        labels = [_tab_label(t) for t in tabs]
        # The label's inset on each side of its chip: half a unit where the
        # backend draws sub-cell, a whole cell on a grid — where a half would
        # floor to nothing on the left and leave the whole padding on the right
        # (#563 hand check).
        inset = 0.5 if ctx.vector_shapes else 1.0
        # The current tab's label is bold, and bold is wider on a proportional
        # font: it is measured, and elided, in that style.
        bold = Style(attr=TextAttribute.BOLD)

        def measure_of(i):
            if i == current:
                return lambda text: ctx.measure_text(text, bold)
            return ctx.measure_text

        widths = [measure_of(i)(lab) + 2 * inset for i, lab in enumerate(labels)]
        share = (avail - gap * (len(tabs) - 1)) / len(tabs)
        if sum(widths) + gap * (len(tabs) - 1) > avail:
            widths = [min(w, max(share, 2.0)) for w in widths]
        x = pad_x
        self._tab_row = (y, y + 1.0)
        self._tab_hits = []
        for i, (label, w) in enumerate(zip(labels, widths)):
            if x >= pad_x + avail:
                break
            w = min(w, pad_x + avail - x)
            shown = elide(label, max(0.0, w - 2 * inset), where="end",
                          measure=measure_of(i))
            chip = current_bg if i == current else idle_bg
            if ctx.vector_shapes:
                # Rounded on top only, the way a tab is: a fully rounded face,
                # then its lower half filled square. Per-corner rounding is not
                # something every vector backend draws (Windows' does not).
                ctx.round_rect(x, y, w, 1.0, Style(bg=chip), radius=self._TAB_RADIUS_PX,
                               hints={"fill": True})
                ctx.fill_rect(x, y + 0.5, w, 0.5, Style(bg=chip))
            else:
                ctx.fill_rect(x, y, w, 1.0, Style(bg=chip))
            if i == current:
                style = Style(fg=current_fg, bg=chip, attr=TextAttribute.BOLD)
            else:
                style = Style(fg=idle_fg, bg=chip)
            ctx.draw_text(x + inset, y, shown, style, ink=False)
            self._tab_hits.append((x, x + w, i))
            x += w + gap

    def handle_event(self, event) -> bool:
        """A click on a tab shows it; a click on a path component goes there —
        the mouse's Backspace and Jump (#589). Anywhere else on the bar just
        makes the pane active."""
        if event.type is not EventType.MOUSE_CLICK or event.button != "left":
            return False
        y = event.y or 0.0
        if self._tab_row is not None and self._tab_row[0] <= y < self._tab_row[1]:
            ex = event.x or 0.0
            for x0, x1, index in self._tab_hits:
                if x0 <= ex < x1:
                    self.app.select_tab(self.pane_name, index)
                    self.app.panel.render()
                    return True
            return False
        app = self.app
        app.pm.active_pane = self.pane_name
        app._sync_active()
        row = self._path_row
        if row is not None and row[0] <= y < row[1]:
            x = event.x or 0.0
            for x0, x1, target, child in self._crumbs:
                if x0 <= x < x1:
                    pane = app.pane(self.pane_name)
                    if str(target) != str(pane["path"]):
                        app._go_to_dir(pane, target, child)
                    break
        return True

    def measure(self, ctx, axis, available) -> SizeRequest:
        # Reserve a strip of top padding above the path (vector backends); the
        # bar is placed with size="content" so this height wins. See _bar_height.
        # A pane with more than one tab adds a row for the tab strip.
        if axis != "y":
            return SizeRequest()
        req = _bar_height(ctx)
        if len(self._tabs()) > 1:
            h = req.preferred + 1.0
            return SizeRequest(min=h, preferred=h, max=h)
        return req


class PaneFooter(Widget):
    """The info bar below a pane: dir/file counts, selection, sort, filter."""

    def __init__(self, app: "XeFMApp", pane_name: str):
        self.app = app
        self.pane_name = pane_name
        #: This footer's absolute rect (base units), captured each draw, so the
        #: controller can position the isearch overlay exactly on top of it.
        self.rect: tuple[float, float, float, float] | None = None
        #: Clickable segments from the last draw: ``(x0, x1, action)``.
        self._hits: list = []

    def draw(self, ctx) -> None:
        self.rect = ctx.screen_rect
        pane = self.app.pane(self.pane_name)
        active = self.app.pm.active_pane == self.pane_name
        pad_x, _ = _bar_pad(ctx)  # left/right inset; the surface fills the slot
        avail = max(0.0, ctx.size_units[0] - 2 * pad_x)
        dirs, files = self.app.counts(pane)
        nsel = len(pane["selected_files"])
        sel = f" ({nsel} selected)" if nsel else ""
        # A registered filter is stored under its name and read back under its
        # label, so the bar says "Images", not "images" (xefm.filters).
        filt = (f"  |  Filter: {filters.label(pane['filter_pattern'])}"
                if pane["filter_pattern"] else "")
        sort = self.app.flm.get_sort_description(pane)
        preview = self.app._paste_preview(pane)
        paste = f"  |  {preview}" if preview else ""
        text = f"{dirs} dirs, {files} files{sel}  |  {sort}{filt}{paste}"
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
        # The sort and the filter read as settings, so a click opens them (#589)
        # — where they are still on screen after eliding.
        self._hits = []
        for part, action in ((sort, "sort"), (filt.strip(" |"), "filter")):
            start = text.find(part) if part else -1
            if start < 0 or start + len(part) > len(left):
                continue
            # Measured in the style the line is drawn in: bold on the active
            # pane, and a proportional bold is wider — measured plain, the
            # targets drifted left of the words on the desktop.
            x0 = pad_x + ctx.measure_text(text[:start], style)
            self._hits.append((x0, x0 + ctx.measure_text(part, style), action))

    def handle_event(self, event) -> bool:
        if event.type is not EventType.MOUSE_CLICK or event.button != "left":
            return False
        self.app.pm.active_pane = self.pane_name
        self.app._sync_active()
        x = event.x or 0.0
        for x0, x1, action in self._hits:
            if x0 <= x < x1:
                self.app._run_action(_ctx.FILER, action)
                break
        return True


class StatusBar(Widget):
    """The bottom bar: global key hints (XeFM's dynamic status line, simplified).

    The key labels are derived from the live keymap (§2.3) so the bar tracks
    user rebindings rather than repeating hardcoded strings."""

    #: (action, label) pairs shown as ``<key> <label>``, in bar order. The key
    #: for each is looked up from the keymap and formatted for display.
    #: ``help`` leads: the bar elides from the right on narrow windows, and the
    #: help dialog is the hint that reveals every other binding.
    _HINTS = (
        ("help", "help"),
        ("quit", "quit"),
        ("switch_pane", "switch"),
        ("toggle_select_down", "select"),
        ("open_item", "open"),
        ("go_parent", "parent"),
        ("copy_files", "copy"),
        ("move_files", "move"),
        ("delete_files", "delete"),
        ("create_directory", "mkdir"),
        ("isearch", "find"),
    )

    #: Shown in place of the hints while the footer isearch is open, so the bottom
    #: bar explains the isearch keys rather than the (now-inaccessible) global
    #: ones. ``(action, action, label)`` — a pair renders as ``k1/k2 label``, a
    #: lone action (second entry ``None``) as ``k label``. Read from the keymap
    #: like ``_HINTS``, since the isearch keys are rebindable actions of their
    #: own context.
    _ISEARCH_HINTS = (
        ("isearch.prev_match", "isearch.next_match", "prev/next match"),
        ("isearch.toggle_select_up", "isearch.toggle_select_down", "select"),
        ("isearch.select_matches", None, "all"),
        ("isearch.accept", None, "stop"),
        ("isearch.cancel", None, "cancel"),
    )

    _HINT_GAP = "   "

    def __init__(self, app: "XeFMApp"):
        self.app = app
        self._hints_cache: str | None = None
        self._isearch_cache: str | None = None
        self._hint_parts: list = []
        #: Clickable hints from the last draw: ``(x0, x1, action)`` (#589).
        self._hits: list = []
        #: The spinner in front of a running job (#599 hand check): PuiKit's
        #: own, so it turns on its own and is one cell wide everywhere.
        self._busy = BusyIndicator()

    def invalidate(self) -> None:
        """Drop both cached lines, so the next draw rebuilds them from the
        keymap as it stands now. Called when a config reload rebinds keys —
        the one moment the keymap changes under a running bar (issue #382)."""
        self._hints_cache = None
        self._isearch_cache = None

    def _hints(self) -> str:
        """Build (and cache) the hint line from the keymap — the bar redraws
        every frame, so the lookups are done once and kept until
        :meth:`invalidate` says the keymap has moved."""
        if self._hints_cache is None:
            parts = []
            for action, label in self._HINTS:
                keys, _ = self.app.keys.get_keys_for_action(action)
                if keys:
                    key = self.app.keys.format_key_for_display(keys[0])
                    parts.append((f"{key} {label}", action))
            self._hint_parts = parts
            self._hints_cache = self._HINT_GAP.join(p for p, _ in parts)
        return self._hints_cache

    def _isearch_key(self, action: str) -> str:
        """The first key bound to ``action`` in the isearch context, display-
        formatted — empty when the action is unbound there."""
        keys, _ = self.app.keys.get_keys_for_action(action, _ctx.ISEARCH)
        return self.app.keys.format_key_for_display(keys[0]) if keys else ""

    def _isearch_hints(self) -> str:
        """The isearch hint line, cached from the isearch keymap like
        :meth:`_hints`. An unbound action drops out of the line entirely rather
        than printing a label nothing triggers."""
        if self._isearch_cache is None:
            parts = ["I-Search"]
            for first, second, label in self._ISEARCH_HINTS:
                keys = [k for k in (self._isearch_key(first),
                                    self._isearch_key(second) if second else "")
                        if k]
                if keys:
                    parts.append(f"{'/'.join(keys)} {label}")
            self._isearch_cache = "   ".join(parts)
        return self._isearch_cache

    def _quick_hints(self) -> str:
        """The Orthodox type-ahead search's line: it owns only these keys, and
        every other one acts on the file list — which is what the line has to
        say."""
        walk = "/".join(k for k in (self._isearch_key("isearch.prev_match"),
                                    self._isearch_key("isearch.next_match")) if k)
        close = self._isearch_key("isearch.cancel")
        parts = ["I-Search"]
        if walk:
            parts.append(f"{walk} prev/next match")
        if close:
            parts.append(f"{close} close")
        parts.append("other keys act on the file")
        return "   ".join(parts)

    def _text(self) -> str:
        """What the bar says right now.

        A modal owns the keyboard while it is up, and names its own keys in its
        own hint row — so the bar goes quiet rather than listing the file list's
        keys, none of which would do anything (issue #271 follow-up). The search
        bar is the exception: it is a layer too, but it hands its keys to the bar
        to show, which is the point of a footer overlay.
        """
        if self.app._isearch_active:
            if getattr(self.app, "_isearch_quick", False):
                return self._quick_hints()
            return self._isearch_hints()
        if self.app.panel.has_layers:
            return ""
        sequence = getattr(self.app, "key_sequence", None)
        if sequence is not None and sequence.pending:
            # Vim's showcmd: the keys of a sequence not finished yet (#587).
            return f"{sequence.pending_text()} …   Esc cancel"
        return self._hints()

    def draw(self, ctx) -> None:
        # Left/right inset; the bottom padding is the extra row height reserved
        # by measure(), so the text stays at the top (y=0) of the taller slot.
        pad_x, _ = _bar_pad(ctx)
        # Plus one whole cell on vector backends: the bar sits in the window's
        # bottom corners, which the OS rounds (16pt on macOS Tahoe) — deep
        # enough to shave the first/last glyph's ink at BAR_PAD_PX alone. A
        # terminal keeps the bare inset; the emulator owns its window corners.
        if ctx.vector_shapes:
            pad_x += 1.0
        avail = max(0.0, ctx.size_units[0] - 2 * pad_x)
        # What the file clipboard carries leads the bar (#577), in every state
        # the bar has — a search included, since "search for the destination,
        # then paste" is how it is used.
        x = pad_x
        carried = self.app.clipboard.status()
        self._clip_hit = None
        if carried:
            carried = elide(carried, avail, where="end", measure=ctx.measure_text)
            carried_style = Style(fg=ctx.theme.accent, attr=TextAttribute.BOLD)
            ctx.draw_text(x, 0, carried, carried_style)
            # A click on it shows what is held (#577 hand check).
            carried_w = ctx.measure_text(carried, carried_style)
            self._clip_hit = (x, x + carried_w)
            # Measured in its own bold style: bold is wider on a proportional
            # font, and measuring it plain ate the gap before the hints.
            used = carried_w + ctx.measure_text("  ")
            x += used
            avail = max(0.0, avail - used)
        # Background jobs (#567) take the right end, ahead of the hints: the
        # hints are always the same, a job's progress is news.
        parts = self.app._jobs_parts()
        if parts:
            jw = self._draw_jobs(ctx, parts, x, avail)
            avail = max(0.0, avail - jw - 2.0)
        else:
            self._jobs_hit = None
        full = self._text()
        text = elide(full, avail, where="end", measure=ctx.measure_text)
        ctx.draw_text(x, 0, text, Style(fg=ctx.theme.muted_text))
        # Each hint runs its action when clicked (#589): the bar is generated
        # from the live keymap, so the targets follow the user's bindings.
        self._hits = []
        if full == self._hints_cache:
            start, gap = x, ctx.measure_text(self._HINT_GAP)
            for part, action in self._hint_parts:
                x1 = x + ctx.measure_text(part)
                if x1 > start + avail:
                    break
                self._hits.append((x, x1, action))
                x = x1 + gap

    #: The glyph in front of a job part that is not running; a running one
    #: gets the spinner instead.
    _JOB_MARKS = {"attention": "⚠", "done": "✓", "failed": "⚠"}
    _JOB_GAP = "  "

    def _draw_jobs(self, ctx, parts, x: float, avail: float) -> float:
        """Draw the job segment flush right in what is left of the bar and
        return its width: each part's mark — the spinner for a running one —
        then its text. The text gives way, elided at its end, before the
        marks do. A click anywhere on it opens the jobs list."""
        style = Style(fg=ctx.theme.accent, attr=TextAttribute.BOLD)
        mark_w = ctx.measure_text("⠋")
        gap_w = ctx.measure_text(self._JOB_GAP, style)
        fixed = len(parts) * (mark_w + 1.0) + gap_w * (len(parts) - 1)
        text = self._JOB_GAP.join(t for _kind, t in parts)
        room = max(0.0, avail - fixed)
        if ctx.measure_text(text, style) > room:
            # Elide the joined texts as one run, then hand each part its share.
            text = elide(text, room, where="end", measure=ctx.measure_text)
        texts = text.split(self._JOB_GAP)
        texts += [""] * (len(parts) - len(texts))
        width = fixed + sum(ctx.measure_text(t, style) for t in texts)
        jx = x + avail - width
        cx = jx
        for i, ((kind, _t), shown) in enumerate(zip(parts, texts)):
            if i:
                cx += gap_w
            if kind == "busy":
                ctx.draw_child(self._busy, cx, 0, mark_w, 1.0)
            else:
                ctx.draw_text(cx, 0, self._JOB_MARKS.get(kind, "•"), style)
            cx += mark_w + 1.0
            ctx.draw_text(cx, 0, shown, style)
            cx += ctx.measure_text(shown, style)
        # A click on it opens the jobs list (#599 hand check).
        self._jobs_hit = (jx, jx + width)
        return width

    def handle_event(self, event) -> bool:
        if event.type is not EventType.MOUSE_CLICK or event.button != "left":
            return False
        if self.app.panel.has_layers:
            return False
        x = event.x or 0.0
        clip = getattr(self, "_clip_hit", None)
        if clip is not None and clip[0] <= x < clip[1]:
            self.app.clipboard_show()
            return True
        jobs = getattr(self, "_jobs_hit", None)
        if jobs is not None and jobs[0] <= x < jobs[1]:
            self.app.show_jobs()
            return True
        for x0, x1, action in self._hits:
            if x0 <= x < x1:
                self.app._run_action(_ctx.FILER, action)
                return True
        return False

    def measure(self, ctx, axis, available) -> SizeRequest:
        # Reserve a strip of bottom padding below the hints (vector backends);
        # placed with size="content" so this height wins. See _bar_height.
        return _bar_height(ctx) if axis == "y" else SizeRequest()


class _StreamToLog:
    """A ``sys.stdout`` / ``sys.stderr`` stand-in that funnels writes into the
    log pane, mirroring the terminal build's stdout/stderr capture so real-world
    output — a stray ``print``, a library warning, an uncaught traceback — stays
    visible even when there is no terminal behind the GUI. XeFM's own loggers do
    not come this way: they reach the same queue through the log sink (see
    ``_enqueue_log``), already formatted.

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


class _ExtractionPool:
    """Extraction workers that outlive any one archive of a batch.

    Workers used to be started and joined per archive, and that boundary cost
    the tail of every one of them: the last members' closes ran with the other
    workers already idle, and the next archive could not begin reading until
    they finished. Where the destination defers a file's transfer to its close,
    that tail is the expensive part of the archive.

    Here the workers are started once and *park* between archives. The batch's
    own thread keeps everything it had — the password gate, the title, one
    archive read at a time — because it still publishes one archive and waits.
    What it waits for is that archive's **reading**: it moves on to open and
    decompress the next while the previous one's files are still landing.

    Concurrency stays at ``workers`` throughout, which is the point of the
    setting — it says how many writes the destination will take, and a boundary
    that briefly doubled it would be a worse bargain than the one it removed.

    A member that fails takes its archive out of the batch and no more:
    ``_retire`` ends that archive early, the error is kept against its key, and
    the workers go on to the next archive. Cancellation is the batch's, so it
    stops everything. Both are reported by :meth:`close`, because neither is
    known while the archive that caused it is still being read.

    ``close_gate`` is the same :class:`~xefm.file_operations.CloseGate` a copy
    uses, and for the same reason: a member's close is a transfer the
    destination may not want two of. Its own documentation says why."""

    def __init__(self, workers: int, *, task=None, prog=None, log=None,
                 close_gate=None):
        self._task = task
        self._prog = prog
        self._log = log
        self._close_gate = close_gate or CloseGate()
        self._cond = threading.Condition()
        self._job = None           # (key, pass, root, archive path, dest dir)
        self._exhausted = True     # nothing published yet
        self._closed = False
        self._cancelled = None     # the Cancelled that ended the batch
        self._results: dict = {}   # key -> [members written, first error]
        self._threads = [
            threading.Thread(target=self._work, name="xefm-extract", daemon=True)
            for _ in range(max(1, workers))]
        for thread in self._threads:
            thread.start()

    # --- the batch thread's side ---------------------------------------------

    def run_archive(self, key, pass_, root, archive_path, dest_dir) -> None:
        """Hand this archive to the workers and return once it has been *read*
        to the end — or abandoned. Its files may still be landing."""
        with self._cond:
            self._results.setdefault(key, [0, None])
            self._job = (key, pass_, root, archive_path, dest_dir)
            self._exhausted = False
            self._cond.notify_all()
            while not self._exhausted and self._cancelled is None:
                self._cond.wait()
            self._job = None
            cancelled = self._cancelled
        if cancelled is not None:
            raise cancelled

    def close(self) -> dict:
        """Stop the workers once their outstanding files have landed, and report
        ``{key: (members written, first error)}`` — the tally no archive could
        give while it was still being read."""
        with self._cond:
            self._closed = True
            self._cond.notify_all()
        for thread in self._threads:
            thread.join()
        return {key: tuple(value) for key, value in self._results.items()}

    # --- a worker's side ------------------------------------------------------

    def _work(self) -> None:
        while True:
            with self._cond:
                while self._job is None or self._exhausted:
                    if self._closed or self._cancelled is not None:
                        return
                    self._cond.wait()
                job = self._job
            self._one_member(job)

    def _one_member(self, job) -> None:
        """Claim one member and carry it to a closed file — the whole of its
        life on this thread, which is what keeps its handle's lifetime local and
        lets an error be raised where the member is still known."""
        key, pass_, root, archive_path, dest_dir = job
        name = archive_path.name if archive_path is not None else ""
        pending = None
        slot = -1
        entry = None
        try:
            with pass_.claim_next() as member:
                if member is None:
                    self._retire(job)
                    return
                if self._task is not None:
                    self._task.checkpoint()
                entry = member.entry
                written = 0
                if self._prog is not None:
                    slot = self._prog.file_begin(
                        XeFMApp._member_label(name, entry.internal_path),
                        0 if entry.is_dir else entry.size)

                def on_bytes(count: int) -> None:
                    nonlocal written
                    written += count
                    self._prog.file_bytes(slot, written)

                pending = member.write_to(
                    root, on_bytes if self._prog is not None else None)
            # The claim is released; the rest is this member's alone.
            if pending is not None:
                if self._prog is not None:
                    # Where the destination defers a file's transfer to its
                    # close, everything below this line is that transfer — and
                    # the row would otherwise hold at its total, showing none of
                    # it. Marked before any queueing below, so the row accounts
                    # for the whole wait rather than only its own turn.
                    self._prog.file_closing(slot)
                with self._close_gate.closing():
                    pending.finish()
                pending = None
            if self._prog is not None:
                self._prog.file_end(slot)
            if self._log is not None and not entry.is_dir:
                self._log(XeFMApp._extracted_line(entry.internal_path,
                                                  archive_path, dest_dir))
            with self._cond:
                self._results[key][0] += 1
        except Cancelled as exc:
            with self._cond:
                if self._cancelled is None:
                    self._cancelled = exc
                self._cond.notify_all()
        except BaseException as exc:  # noqa: BLE001 — reported by close()
            with self._cond:
                if self._results[key][1] is None:
                    self._results[key][1] = exc
            self._retire(job)  # this archive is over; the batch is not
        finally:
            if pending is not None:
                pending.discard()

    def _retire(self, job) -> None:
        """This archive has no more members to give — read to the end, or ended
        early by a failure. Releases the batch thread to publish the next one."""
        with self._cond:
            if self._job is job:
                self._exhausted = True
                self._cond.notify_all()


class _StepBehindLog:
    """Logs one unit of work at a time, always one behind.

    ``zipfile.extractall``, ``tarfile.add`` and libarchive's writer drive their
    own member loop and hand out a seam only at the *start* of a member. A line
    written there would call a member done before it was — and would call the
    one that then failed done when it wasn't. Holding each line until the next
    member begins, and flushing whatever is left when the run finishes, makes
    every line mean what it says: what it names has landed. A run that dies
    mid-member never flushes that member's line, which is the right silence.

    Where a seam does exist after the member — the zip create loop, and the
    extraction workers, which own their member from claim to closed file — the
    line is written directly and this is not needed."""

    __slots__ = ("_log", "_pending")

    def __init__(self, log):
        self._log = log
        self._pending = None

    def announce(self, message: str) -> None:
        """The previous member landed; this one is starting."""
        self.flush()
        self._pending = message

    def flush(self) -> None:
        """The run ended cleanly — the member still held did land after all."""
        pending, self._pending = self._pending, None
        if pending is not None and self._log is not None:
            self._log(pending)



def _search_rules(show_hidden: bool, recursive: bool):
    """``(shows, descend)`` for a search walk: ``shows(entry, attrs)`` says
    whether the search looks at an entry at all (not a hidden one, unless the
    pane is showing them), ``descend`` whether the walk goes into it — every
    directory the search looks at, unless it searches this directory alone."""
    def shows(entry, attrs) -> bool:
        return show_hidden or not is_hidden(entry.name, attrs)

    def descend(entry, attrs) -> bool:
        return recursive and attrs["is_dir"] and shows(entry, attrs)

    return shows, descend

def _real_entry(entry):
    """The file an entry stands for, where that is not the entry itself: a
    ``.xft`` tree's entries are references (#573), and anything that leaves
    XeFM — the OS's open and reveal, an editor, a copied path — needs the real
    file, not the ``xft://`` address (#612). None for a reference that
    points nowhere."""
    if entry is not None and xft.is_xft_path(entry):
        return entry.target()
    return entry


def _tag_dot(color: int) -> tuple:
    """A tag's dot as a dialog run or mark (#792): in its Finder color, or the
    muted ink for none — as the file list draws it."""
    return (layouts.TAG_DOT, tags.RGB.get(tags.COLORS.get(color)))


#: Listing generations, unique across every pane and tab. A result names the
#: side it was listed for and the generation it was started under; with tabs, a
#: side's pane can be a different dict by the time it lands, and per-pane
#: counters could hand that dict a number matching the stale result (#563).
_LOAD_GENS = itertools.count(1)


def _flat_files(root, cancel, show_hidden: bool):
    """Yield ``(entry, attrs)`` for every file below ``root`` — flat view's
    walk. A hidden entry is skipped unless the pane shows them, and is not
    descended either; a symbolic link to a directory is neither listed nor
    descended, so a link pointing back up the tree cannot loop."""
    def shows(entry, attrs) -> bool:
        return show_hidden or not is_hidden(entry.name, attrs)

    def descend(entry, attrs) -> bool:
        return attrs["is_dir"] and not attrs["is_link"] and shows(entry, attrs)

    for entry, attrs in tree_walk.walk(root, cancel, descend):
        if not attrs["is_dir"] and shows(entry, attrs):
            yield entry, attrs


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
        # Load via ConfigManager (the shared singleton): this creates
        # ~/.xefm/config.py from the template on first run and reads the user's
        # config, filling any missing fields from the template. Instantiating
        # _config.Config() directly (as the port did) skipped both — the file was
        # never created and the user's settings were ignored.
        self.config = get_config()
        # Before anything is measured: the characters WIDE_CHARS names count as
        # two columns from the first layout on (#611).
        apply_wide_chars(self.config)
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
        # The keymap preset (Tools > Advanced > Keymap, or KEY_PRESET in config.py) is
        # written into KEY_BINDINGS itself, so every surface reads one table.
        self._apply_keymap_preset()
        self._left_provided = left_provided
        self._right_provided = right_provided
        self.flm = FileListManager(self.config)
        self.pm = PaneManager(self.config, self._resolve_dir(left_dir),
                              self._resolve_dir(right_dir),
                              state_manager=self.state_manager,
                              file_list_manager=self.flm)
        # Restore saved window layout and pane paths/sort/filter *before* the
        # splitters are built (they read ``pm.left_pane_ratio`` /
        # ``_panes_fraction``) and before anything lists a directory — the
        # listing reads the restored path, sort and filter.
        self._restore_layout_and_paths()
        # The first listings are NOT started here: like every other listing they
        # run on a worker thread, and that needs the panel, the result queue and
        # the pump — none of which exist yet. See ``_start_initial_listings``,
        # kicked at the end of __init__.
        #: Recent-directory history for the History picker — a bounded, in-order
        #: list of visited paths, recorded on every directory change (see
        #: ``_record_history_path``) and persisted across restarts (#220).
        self._seed_history()

        #: Pane footers by name, so ``enter_isearch`` can read the active footer's
        #: captured rect and position the isearch overlay exactly on it.
        self._footers: dict[str, PaneFooter] = {}
        self._headers: dict[str, PaneHeader] = {}
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
        self._isearch_quick = False
        self._isearch_active = False
        self._isearch_origin = 0
        self._isearch_matches: list[int] = []
        #: The last pattern the search bar closed on, for search_next/_prev.
        self._last_isearch_pattern = ""
        #: Whether the pane being searched holds a name Migemo could match at
        #: all (any non-ASCII one), captured when the bar opens.
        self._isearch_migemo = True
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
        # Bindings of more than one key ('g g', #587) in the file list: the keys
        # pressed so far, shown in the status bar until the sequence ends.
        self.key_sequence = key_sequence.KeySequencer(
            lambda: self.keys, _ctx.FILER,
            timeout=lambda: getattr(self.config, "KEY_SEQUENCE_TIMEOUT",
                                    key_sequence.DEFAULT_TIMEOUT),
            call_later=self.panel.call_later,
            on_timeout=self._sequence_timed_out,
            on_change=self.panel.render)
        #: True while the quit confirm is up, so a second request (the close
        #: button pressed again) does not stack a second one.
        self._quit_confirming = False
        #: True once _quit has started, so a second request does not repeat it.
        self._quitting = False
        # The platform's own ways to quit -- the macOS application menu's Quit
        # and the Dock's, the window's close button -- go through the quit action
        # like the keymap's quit key: asked, background jobs stopped, state saved.
        # The menu's Quit item shows, and answers to, the keymap's key for it.
        self.panel.set_quit_handler(self._on_quit_request, self._quit_shortcut())
        # The file clipboard (#577): XeFM's own, with the OS one as a bridge
        # where the backend has it (macOS / Windows desktop).
        self.clipboard = FileClipboard(self.panel)
        # Where to learn which image formats this backend draws from a path —
        # ImageIO's list on macOS, the installed WIC codecs on Windows, Pillow's
        # registry in a terminal. It decides both which files the image viewer
        # offers to open and which of them XeFM has to decode itself, and it is a
        # fact about the machine, so it is read from the backend rather than
        # assumed. Handed over *uncalled*: the backend is asked at the first
        # question anyone has, not while it is still starting up.
        image_decoders.set_native_suffixes(self.panel.image_formats)
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
            on_click=lambda i, mods=frozenset(), clicks=1: self._on_click("left", i, mods, clicks),
            on_context=lambda i, x, y: self._show_context_menu("left", i, x, y),
            on_drag=lambda i, ev: self._start_drag("left", i, ev),
            on_drop=lambda i, paths, op=None: self._on_drop("left", i, paths, op),
            on_middle=lambda i: self._on_middle_click("left", i),
            on_drop_query=lambda i, paths, op: self._drop_effect("left", i, paths, op),
            on_nav=lambda step: self._on_nav_button("left", step),
        )
        self.right_view = FilePane(
            self.pm.right_pane,
            config=self.config,
            on_click=lambda i, mods=frozenset(), clicks=1: self._on_click("right", i, mods, clicks),
            on_context=lambda i, x, y: self._show_context_menu("right", i, x, y),
            on_drag=lambda i, ev: self._start_drag("right", i, ev),
            on_drop=lambda i, paths, op=None: self._on_drop("right", i, paths, op),
            on_middle=lambda i: self._on_middle_click("right", i),
            on_drop_query=lambda i, paths, op: self._drop_effect("right", i, paths, op),
            on_nav=lambda step: self._on_nav_button("right", step),
        )
        # Attribute values (#633) — tags, a layout's extra columns — are
        # computed on workers, which flag a repaint through the pump when they
        # land.
        self._attrs_dirty = False
        attributes.on_ready = self._on_attrs_ready
        # Same chrome inset as the bars: the log's surface fills its slot, its
        # text breathes in from the frame (BAR_PAD_PX on GUI, flush on the grid).
        self.log = LogView(max_lines=2000, auto_scroll=True, wrap=True, padding_px=BAR_PAD_PX)
        self.status = StatusBar(self)
        # One Menu model drives the OS-native menu bar on macOS (an NSMenu) and an
        # in-window strip in the terminal — the Panel resolves which, so we never branch.
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
                # The MenuBar self-sizes via "content": a 1-row strip in the terminal,
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
        self.log_info(f"XeFM — {self.pm.left_pane['path']}")
        # Scans run on without XeFM (#571): say what finished while it was
        # closed, and keep watching what is still running.
        self._refresh_scans()
        unseen = [j for j, st, _t in self._scan_rows
                  if st in similar_scan.FINISHED and not j.seen]
        running = [j for j, st, _t in self._scan_rows if st not in similar_scan.FINISHED]
        if unseen or running:
            parts = []
            if unseen:
                parts.append(f"{len(unseen)} finished while XeFM was closed")
            if running:
                parts.append(f"{len(running)} still running")
            self.log_info(f"Similar-file scans: {', '.join(parts)} — "
                          f"{self._keys_label('jobs')} shows them")

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
        # File operations silence the watchers on the directories they mutate
        # for their duration (issue #243); the monitor doesn't exist yet where
        # ``_fileops`` is built, so it is attached here.
        self._fileops.monitor = self.file_monitor
        self._monitored: dict[str, object] = {"left": None, "right": None}
        self._sync_monitored_dirs()
        # A pane inside an archive owns it: the archive stays open while the
        # pane is there and closes soon after it leaves (issue #516).
        get_archive_cache().add_pin_source(self._archive_pins)

        # Idle-CPU strategy. When the backend can accept work from other threads
        # (native run loop → ``dispatches_to_main_thread``), go fully event-driven:
        # each producer (fs watcher, listing worker, stdout/stderr streams) wakes
        # the UI thread to drain, so there is NO idle polling timer at all. A burst
        # of producer signals coalesces into at most one pending main-thread hop
        # (``_wake_lock``/``_wake_pending``). On a poll-loop backend (the TUI) that
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
        #: Callables :meth:`_call_later` queued for the UI thread's next pump.
        self._later: queue.Queue = queue.Queue()
        #: The thread that builds the app runs its event loop and is the only
        #: one that may touch the LogView; ``log_info`` queues from any other.
        self._ui_thread = threading.current_thread()
        #: Set while :meth:`_terminal_suspended` has the terminal handed over.
        self._terminal_handed_over = False
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr
        sys.stdout = _StreamToLog("STDOUT", self._log_queue, on_write=self._wake_pump)
        sys.stderr = _StreamToLog("STDERR", self._log_queue, on_write=self._wake_pump)
        # ...and the loggers onto the same queue. Everything logged before this
        # point - module imports, ``get_config()`` above, the whole of app
        # construction - was buffered by the sink and is replayed here, so a
        # startup diagnostic (a config that failed to load, say) lands in the
        # pane instead of on a stderr the GUI backends do not have.
        set_log_sink(self._enqueue_log)

        # The customization API (Preview). ``_handlers`` is the filer's
        # name -> bound-method table, built on first dispatch; ``_user_ctx`` is
        # the single ActionContext handed to every user action and hook.
        self._handlers: dict | None = None
        self._user_ctx = ActionContext(self)
        self._load_user_entries(self.config)
        # Again, now that config.py's own actions are registered: a key bound
        # to one is taken off the preset action that had it only once the
        # keymap can tell where that action is reached (#662).
        self._rebuild_keymap()

        # Everything the listing path needs is up: read the two directories.
        self._start_initial_listings()

    def _load_user_entries(self, config) -> None:
        """Install the config's ``ACTIONS`` / ``EVENT_HOOKS`` / ``SORT_KEYS`` /
        ``FILTERS`` / ``IMAGE_DECODERS`` / ``PATH_SCHEMES`` / ``LEXERS`` and
        report on them.

        Shared by startup and reload — the loader drops every previously loaded
        user entry first, so re-running it *is* the reload. Problems are reported
        as ordinary log lines, one per bad entry, and a config that uses a
        Preview table gets the one-line preview notice: that part may still
        change, and the log pane is where a user finds that out."""
        self._report_extensions()
        self._report_python_packages()
        loaded = load_user_entries(config)
        for warning in loaded.warnings:
            self.log_info(f"Config warning: {warning}")
        notice = preview_notice(hooks=loaded.hooks,
                                image_decoders=loaded.image_decoders,
                                lexers=loaded.lexers,
                                menu_items=loaded.menu_items,
                                attributes=loaded.attributes,
                                layouts=loaded.layouts,
                                extras=loaded.extras,
                                scheme_overrides=loaded.scheme_overrides)
        if notice:
            self.log_info(notice)
        # Action names that have been corrected since this config was written.
        # The old spellings still resolve, so this is a nudge — and one line
        # however many there are, since a config predating several renames would
        # otherwise open every session with a wall of warnings.
        renamed = deprecated_names_notice(getattr(config, "KEY_BINDINGS", None) or {})
        if renamed:
            self.log_info(f"Config warning: {renamed}")
        # A key bound to a printable one on a surface that takes typing — the
        # search bar, a list picker, the search dialog — can never fire, since
        # the field takes every glyph first, and would look like the binding was
        # ignored at random. Say so once, for the same reason as the rename
        # nudge above: nothing else tells the author.
        swallowed = printable_text_notice(
            getattr(config, "KEY_BINDINGS", None) or {})
        if swallowed:
            self.log_info(f"Config warning: {swallowed}")
        # Ctrl-I/J/M/H arrive as Tab/Enter/Backspace in a terminal, so a binding
        # there looks ignored at random too. Only where the backend says so: a
        # PuiKit too old to declare ctrl_letter_keys is not taken as a terminal.
        caps = self.backend.capabilities
        if "ctrl_letter_keys" in caps and not caps.supports("ctrl_letter_keys"):
            shadowed = terminal_shadowed_notice(keymap_presets.overrides(config))
            if shadowed:
                self.log_info(f"Config warning: {shadowed}")

    def install_extension(self) -> None:
        """Ask for an extension package to install: a folder holding
        ``xefm-extension.toml``, a ``.zip`` of one, an ``https://`` zip URL or
        ``github:owner/repo[/path][@ref]`` — pasted, typed, or the package
        under the cursor, which fills the field. It is fetched and checked on
        a worker thread (a GitHub source is a download), then what it adds is
        shown before anything is installed. A package that fails the check
        ``xefm ext check`` runs is refused with every finding listed."""
        pane = self.active_pane()
        entry = self._focused_entry()
        text = ""
        if entry is not None and self._is_local(entry) and (
                str(entry).lower().endswith(".zip")
                or _StdPath(str(entry), "xefm-extension.toml").is_file()):
            text = str(entry)
        base = str(pane["path"]) if self._is_local(pane["path"]) else None

        def accept(value: str) -> None:
            source = value.strip()
            if not source:
                self.panel.render()
                return
            # A relative path is the active pane's, as everywhere else.
            if base and not source.startswith(("github:", "https://", "~")) \
                    and not os.path.isabs(source):
                source = os.path.join(base, source)
            self._fetch_extension(source)
            self.panel.render()

        show_input(self.panel,
                   title="Install Extension — folder, .zip, URL or github:owner/repo",
                   prompt="Source:", text=text, on_accept=accept, width=100.0)
        self.panel.render()

    #: Set while Install Extension fetches and checks a package; the worker
    #: leaves ``(source, work dir, root, manifest, problems)`` or an exception
    #: in ``_ext_fetch_done`` for the pump.
    _ext_fetch_busy = False
    _ext_fetch_done = None

    def _fetch_extension(self, source: str) -> None:
        from xefm import extensions as _ext
        if self._ext_fetch_busy:
            self.log_info("Install Extension is already fetching a package")
            return
        self._ext_fetch_busy = True
        if source.startswith(("github:", "https://")):
            self.log_info(f"Install Extension: downloading {source}…")
        layout = _ext.Layout(config_manager.config_dir)

        def worker() -> None:
            work = tempfile.mkdtemp(prefix="xefm-ext-")
            try:
                root = _ext.fetch(source, _StdPath(work))
                manifest = _ext.read_manifest(root)
                problems = _ext.check_manifest(
                    manifest, others=[m for m in _ext.discover(layout)
                                      if m.id != manifest.id])
                outcome = (source, work, root, manifest, problems)
            except Exception as e:
                shutil.rmtree(work, ignore_errors=True)
                outcome = e
            self._ext_fetch_done = outcome
            self._wake_pump()

        threading.Thread(target=worker, name="xefm-ext-fetch", daemon=True).start()

    def _pump_extension_fetch(self) -> bool:
        """On the UI thread: refuse a package that failed, or show what it adds
        and install it on Install."""
        from xefm import extensions as _ext
        outcome, self._ext_fetch_done = self._ext_fetch_done, None
        if outcome is None:
            return False
        self._ext_fetch_busy = False
        if isinstance(outcome, (_ext.InstallError, _ext.ManifestError, OSError)):
            self.log_info(f"Install Extension: {outcome}")
            return True
        if isinstance(outcome, Exception):
            getLogger("Main").error(f"Install Extension failed: {outcome}")
            return True
        source, work, root, manifest, problems = outcome
        if _ext.errors(problems):
            shutil.rmtree(work, ignore_errors=True)
            show_message_box(
                self.panel, "\n".join(str(p) for p in problems),
                title=f"{manifest.id or source} cannot be installed", icon="error")
            return True
        lines = _ext.summarize(manifest) or ["(nothing)"]
        warnings = [f"⚠ {p.where}: {p.message}" for p in problems]

        def answered(label: str) -> None:
            try:
                if label != "Install":
                    return
                try:
                    installed = _ext.install(source, _ext.Layout(config_manager.config_dir),
                                             fetched=root)
                except (_ext.InstallError, _ext.ManifestError, OSError) as exc:
                    self.log_info(f"Install Extension failed: {exc}")
                    return
                self.log_info(f"Installed extension {installed.id} {installed.version}")
                self.reload_config()
                # Its packages come from PyPI; the dialog said so, and Install
                # was the consent. The sync reloads the config again when done.
                if installed.requires.get("python_packages"):
                    self.sync_python_packages()
            finally:
                shutil.rmtree(work, ignore_errors=True)
                self.panel.render()

        pypi = (["", "Installing also downloads its Python packages from PyPI."]
                if manifest.requires.get("python_packages") else [])
        show_message_box(
            self.panel,
            "\n".join([f"From {source}", ""] + lines + warnings + pypi
                      + ["", "Extensions run inside XeFM with your permissions."]),
            title=f"Install {manifest.name} {manifest.version}?",
            icon="question", buttons=("Install", "Cancel"), default=1, cancel=1,
            on_result=answered)
        return True

    def show_extensions(self) -> None:
        """What the last config load did with each extension package: loaded,
        disabled, or left out and why. Managing them is ``xefm ext``."""
        from xefm import extensions as _ext
        report = getattr(config_manager, "extension_report", None)
        rows = []
        if report is not None:
            rows += [f"✓ {m.id} {m.version}" for m in report.loaded]
            rows += [f"– {label}: {reason}" for label, reason in report.skipped]
            rows += [f"⚠ {w}" for w in report.warnings]
        if not rows:
            rows = [f"No extension packages in {_ext.Layout(config_manager.config_dir).packages}"]
        rows += ["", "Check for Extension Updates (Tools ▸ Advanced) looks for "
                 "newer versions.",
                 "Manage them from a shell with `xefm ext list | install | "
                 "uninstall | enable | disable | outdated | upgrade`."]
        show_message_box(self.panel, "\n".join(rows), title="Extensions")
        self.panel.render()

    #: Set while Check for Extension Updates is looking or upgrading (#676);
    #: the worker leaves ``(stage, outcome)`` in ``_ext_updates_done`` for the
    #: pump — stage "checked" with the checks, "upgraded" with report lines.
    _ext_updates_busy = False
    _ext_updates_done = None

    def check_extension_updates(self) -> None:
        """Ask each installed package's update source for a newer version, on
        a worker thread: it reaches GitHub. Only ever run when the user asks —
        XeFM never looks on its own (#676). What it finds is offered in a
        dialog; Upgrade installs through the same check an install runs."""
        from xefm import extensions as _ext
        if self._ext_updates_busy:
            self.log_info("Check for Extension Updates is already running")
            return
        layout = _ext.Layout(config_manager.config_dir)
        self._ext_updates_busy = True
        self.log_info("Checking extension packages for newer versions…")

        def worker() -> None:
            try:
                outcome = _ext.check_updates(layout)
            except Exception as e:
                outcome = e
            self._ext_updates_done = ("checked", outcome)
            self._wake_pump()

        threading.Thread(target=worker, name="xefm-ext-updates", daemon=True).start()
        self.panel.render()

    def _upgrade_extensions(self, checks: list) -> None:
        from xefm import extensions as _ext
        layout = _ext.Layout(config_manager.config_dir)
        self._ext_updates_busy = True
        self.log_info("Upgrading " + ", ".join(f"{c.id} to {c.latest}" for c in checks)
                      + "…")

        def worker() -> None:
            lines, needs_packages = [], False
            for check in checks:
                try:
                    manifest = _ext.upgrade(check, layout)
                except Exception as e:
                    lines.append(f"Could not upgrade {check.id}: {e}")
                    continue
                lines.append(f"Upgraded extension {manifest.id} to {manifest.version}")
                needs_packages |= bool(manifest.requires.get("python_packages"))
            self._ext_updates_done = ("upgraded", (lines, needs_packages))
            self._wake_pump()

        threading.Thread(target=worker, name="xefm-ext-upgrade", daemon=True).start()

    def _pump_extension_updates(self) -> bool:
        """On the UI thread: show what a check found, or report an upgrade
        and reload the config so the new versions load."""
        done, self._ext_updates_done = self._ext_updates_done, None
        if done is None:
            return False
        self._ext_updates_busy = False
        stage, outcome = done
        if stage == "upgraded":
            lines, needs_packages = outcome
            for line in lines:
                self.log_info(line)
            self.reload_config()
            # Their packages come from PyPI; the dialog said so, and Upgrade
            # was the consent. The sync reloads the config again when done.
            if needs_packages:
                self.sync_python_packages()
            return True
        if isinstance(outcome, Exception):
            self.log_info(f"Check for Extension Updates failed: {outcome}")
            return True
        newer = [c for c in outcome if c.outdated]
        notes = [f"{c.id}: could not check — {c.problem}" for c in outcome if c.failed]
        notes += [f"{c.id}: not checked — {c.problem}"
                  for c in outcome if c.problem and not c.failed]
        if not newer:
            current = [c for c in outcome if c.updates and not c.problem]
            head = ([f"Every extension is up to date ({len(current)} checked)."]
                    if current else ["No newer versions found."]) if outcome \
                else ["No extension packages are installed."]
            show_message_box(self.panel, "\n".join(head + ([""] + notes if notes else [])),
                             title="Extension Updates")
            return True

        def answered(label: str) -> None:
            if label == "Upgrade":
                self._upgrade_extensions(newer)
            self.panel.render()

        rows = [f"{c.id}  {c.version} → {c.latest}" for c in newer]
        show_message_box(
            self.panel,
            "\n".join(rows + ([""] + notes if notes else [])
                      + ["", "Each new version is checked before it replaces the "
                         "old one.", "Extensions run inside XeFM with your permissions."]),
            title=f"Upgrade {len(newer)} extension{'s' if len(newer) > 1 else ''}?",
            icon="question", buttons=("Upgrade", "Cancel"), default=0, cancel=1,
            on_result=answered)
        return True

    def _report_extensions(self) -> None:
        """One log line for the extension packages the config load folded in,
        and one per package that was left out or had an entry skipped, with
        the reason — the only place a user learns why an extension is quiet."""
        from xefm import extensions as _extensions
        _extensions.state_manager_for_handles = self.state_manager
        report = getattr(config_manager, "extension_report", None)
        if report is None:
            return
        if report.loaded:
            names = ", ".join(f"{m.id} {m.version}" for m in report.loaded)
            self.log_info(f"Extensions: {names} (API "
                          f"{_extensions._api_version()})")
            for manifest in report.loaded:
                sections = _extensions.preview_sections(manifest)
                if sections:
                    self.log_info(f"Extension {manifest.id} uses Preview "
                                  f"manifest sections: {', '.join(sections)}")
        for label, reason in report.skipped:
            if reason != "disabled":
                self.log_info(f"Extension {label} not loaded: {reason}")
        for warning in report.warnings:
            self.log_info(f"Extension warning: {warning}")

    #: Set while a Sync Python Packages runs; the worker leaves its outcome
    #: (a SyncResult or the exception) in ``_python_packages_done`` for the pump.
    _python_packages_syncing = False
    _python_packages_done = None

    def _report_python_packages(self) -> None:
        """One log line when ~/.xefm/requirements.txt and the directory synced
        from it disagree (#664). The check is offline and never syncs: a sync
        reaches the network, so it waits to be asked for."""
        status = getattr(config_manager, "python_packages_status", None)
        if status is not None and status.message:
            self.log_info(status.message)

    def sync_python_packages(self) -> None:
        """Install what ~/.xefm/requirements.txt lists into
        ~/.xefm/site-packages, on a worker thread: pip reaches the network and
        can take minutes. Its output streams into the log as it comes; the
        outcome is reported, and the config reloaded, by the pump."""
        from xefm import python_packages
        if self._python_packages_syncing:
            self.log_info("Sync Python Packages is already running")
            return
        layout = python_packages.Layout(config_manager.config_dir)
        self._python_packages_syncing = True
        self.log_info(f"Syncing Python packages from {layout.requirements}…")

        def pip_line(line: str) -> None:
            self._log_queue.put(("STDOUT", line))
            self._wake_pump()

        def worker() -> None:
            try:
                outcome = python_packages.sync(layout, log=pip_line)
            except Exception as e:
                outcome = e
            self._python_packages_done = outcome
            self._wake_pump()

        threading.Thread(target=worker, name="xefm-deps-sync", daemon=True).start()
        self.panel.render()

    def _pump_python_packages(self) -> bool:
        """On the UI thread: report a finished sync and reload the config, so a
        config.py import that failed for want of a package gets another try."""
        from xefm import python_packages
        outcome, self._python_packages_done = self._python_packages_done, None
        if outcome is None:
            return False
        self._python_packages_syncing = False
        if isinstance(outcome, python_packages.SyncError):
            self.log_info(f"Sync Python Packages failed: {outcome}")
            return True
        if isinstance(outcome, Exception):
            getLogger("Main").error(f"Sync Python Packages failed: {outcome}")
            return True
        names = ", ".join(outcome.installed) or "nothing"
        self.log_info(f"Python packages synced: {names}")
        if outcome.pruned:
            self.log_info(f"Already provided by XeFM, left out: {', '.join(outcome.pruned)}")
        if outcome.pending_restart:
            self.log_info("The packages in use are replaced when XeFM next starts.")
            return True
        self.log_info("Packages already imported keep their old version until "
                      "XeFM restarts.")
        self.reload_config()
        return True

    def _start_initial_listings(self) -> None:
        """Kick off the two startup listings, on worker threads like every other
        listing — so launching into a slow mount, a spun-down disk or a remote
        (S3/SSH) startup directory brings the window up immediately instead of
        freezing before the first frame.

        Deferred to the very end of ``__init__`` because ``_list_pane`` needs the
        panel, the result queue and the pump, all of which are built after the
        panes. The saved cursor is matched *by filename*, so it can only be placed
        once the files are in — it rides along as each pane's ``on_ready`` rather
        than running inline as it did when startup listed synchronously."""
        for name in ("left", "right"):
            self._list_pane(name, on_ready=self._restore_remembered_cursor)

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
        header = PaneHeader(self, name)
        # Kept so context_menu_dir can open its menu from the path bar.
        self._headers[name] = header
        return LayoutView(VSplit(
            # "content" (not size=1): the header measures itself a touch taller so
            # it can pad the path text down from the window's top edge (§_bar_pad).
            Item(header, size="content", hints={"surface": "header"}),
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

    def _default_log_height(self) -> float:
        """The configured default log-pane height (``DEFAULT_LOG_HEIGHT_RATIO``),
        clamped to its documented 0.1–0.5 range so an out-of-range value degrades
        to the nearest legal one (validation already warned about it)."""
        try:
            ratio = float(self.config.DEFAULT_LOG_HEIGHT_RATIO)
        except (AttributeError, TypeError, ValueError):
            ratio = 1.0 - PANES_FRACTION
        return max(0.1, min(0.5, ratio))

    def _restore_layout_and_paths(self) -> None:
        """Restore window layout and each pane's directory / sort / filter from
        the saved session, *before* the splitters and file lists are built.

        A pane's saved directory is only re-applied when the user did not pass an
        explicit startup directory for it on the command line, and only if that
        directory still exists; sort mode and filter are always restored. Fully
        best-effort — the log view does not exist yet, so failures stay silent
        rather than blocking startup on a corrupt or absent state store."""
        # The log pane starts at the configured DEFAULT_LOG_HEIGHT_RATIO (#316).
        # A saved height only overrides it when the user actually dragged the
        # splitter away from whatever the default was when that layout was saved
        # (the layout carries that default too) — a layout saved untouched keeps
        # following the config, so editing the config and restarting works.
        self._panes_fraction = max(0.1, min(0.95, 1.0 - self._default_log_height()))
        try:
            self.state_manager.update_session_heartbeat()
            self.state_manager.cleanup_non_existing_directories()

            layout = self.state_manager.load_window_layout()
            if layout:
                ratio = layout.get('left_pane_ratio', self.pm.left_pane_ratio)
                self.pm.left_pane_ratio = max(0.1, min(0.9, ratio))
                log_h = layout.get('log_height_ratio')
                # Layouts saved before #316 carry no default; they were saved
                # under the old hardcoded share, so assume that.
                saved_default = layout.get('log_height_default', 1.0 - PANES_FRACTION)
                if log_h is not None and abs(log_h - saved_default) > 1e-4:
                    self._panes_fraction = max(0.1, min(0.95, 1.0 - log_h))

            self._restore_one_pane('left', self.pm.left_pane, self._left_provided)
            self._restore_one_pane('right', self.pm.right_pane, self._right_provided)
            self._restore_tabs('left', self._left_provided)
            self._restore_tabs('right', self._right_provided)
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
        # A registered sort can disappear between sessions — the config that
        # defined it was edited. Fall back rather than restore a mode nothing
        # answers to, which would leave the pane's own listing unsorted and the
        # status bar naming a key that no longer exists.
        saved_mode = sort_keys.canonical(state.get('sort_mode', pane['sort_mode']))
        pane['sort_mode'] = (saved_mode if sort_keys.is_known(saved_mode)
                             else pane['sort_mode'])
        pane['sort_reverse'] = state.get('sort_reverse', pane['sort_reverse'])
        pane['layout'] = state.get('layout') if isinstance(state.get('layout'), str) else None
        pane['extras'] = self._saved_extras(state.get('extras'))
        pane['filter_pattern'] = state.get('filter_pattern', pane['filter_pattern'])

    def _display_height(self) -> int:
        """Rows available for a file list, used to keep a restored cursor on
        screen. Best-effort: falls back to a sane default before first layout."""
        try:
            _w, h = self.backend.size
            return max(1, int(h) - 4)
        except Exception:
            return 20

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
                # Stored alongside so the next launch can tell an untouched
                # height (keep following the config) from a dragged one (#316).
                log_height_default=self._default_log_height(),
            )
            self.state_manager.save_pane_state('left', self.pm.left_pane)
            self.state_manager.save_pane_state('right', self.pm.right_pane)
            self.pm.save_cursor_position(self.pm.left_pane)
            self.pm.save_cursor_position(self.pm.right_pane)
            self._save_tabs()

            # Persist the full visited-directory trail (most-recent-first,
            # de-duplicated) so the History picker survives restarts (#220),
            # rather than only the two panes' final paths.
            self.state_manager.save_recent_directories(
                self._recent_dirs_most_recent_first(), _HISTORY_MAX)

            self.state_manager.cleanup_session()
        except Exception as e:
            self.log_info(f"Could not save application state: {e}")

    def _quit(self) -> None:
        """Stop monitoring, save state, then end the event loop. Once only:
        Alt-F4 can arrive both as a key and as the window's close request."""
        if self._quitting:
            return
        self._quitting = True
        # Before anything is torn down, so a 'quit' hook still sees live panes
        # (saving a session is the motivating case).
        _hooks.fire("quit", self._user_ctx)
        if getattr(self, "file_monitor", None) is not None:
            self.file_monitor.stop_monitoring()
        self._close_edit_sessions()
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
        # A watcher can die under a pane (a volume goes away, the OS drops the
        # stream) and say nothing about it, leaving the pane quietly stale for
        # the rest of the session. Only a liveness check finds that; the manager
        # rate-limits itself, so asking on every drain is free (#416).
        self.file_monitor.check_observer_health()
        # Drained for its side effect only — *starting* a reload no longer changes
        # anything on screen, because the pane keeps its entries throughout the
        # re-read (see _list_pane's keep_visible). Whether a frame is owed is
        # decided when the result lands, and only if it differs from what is
        # already drawn; counting the start as a change re-rendered the pane once
        # per spurious event, which is most of them (#239).
        self._process_reload_queue()
        listed = self._process_result_queue()
        loading = self._pump_loading_indicator()
        captured = self._drain_captured_output()
        scans = self._pump_scans()
        trees = self._pump_xft()
        tagged, self._attrs_dirty = getattr(self, "_attrs_dirty", False), False
        synced = self._pump_python_packages()
        updates = self._pump_extension_updates()
        fetched = self._pump_extension_fetch()
        later = self._pump_later()
        return (listed or loading or captured or scans or trees or tagged or synced
                or updates or fetched or later)

    def _call_later(self, fn: "Callable[[], None]") -> None:
        """Run ``fn`` on the UI thread on a later pump, never inside the current
        call — what lets a public API promise its ``on_done`` never runs before
        the call that took it returns (#716). Callable from any thread."""
        self._later.put(fn)
        self._wake_pump()

    def _pump_later(self) -> bool:
        """UI thread: run what :meth:`_call_later` queued. Returns True if
        anything ran, so the pump repaints."""
        ran = False
        later = getattr(self, "_later", None)
        while later is not None:
            try:
                fn = later.get_nowait()
            except queue.Empty:
                return ran
            ran = True
            try:
                fn()
            except Exception as exc:  # noqa: BLE001 — one callback, not the pump
                getLogger("Main").error(f"Deferred call failed: {exc}")
        return ran

    def _on_attrs_ready(self) -> None:
        """Worker thread: attribute values landed; ask for a repaint."""
        self._attrs_dirty = True
        self._wake_pump()

    #: Log-pane styles for captured streams. stdout leaves its color unset so it
    #: resolves to ``theme.text`` at draw time (tracking the theme like
    #: ``log_info``) but dimmed, so captured output reads as recessive under XeFM's
    #: own messages. stderr keeps a fixed warning red so an error stands out on
    #: any theme.
    _STDERR_STYLE = Style(fg=(230, 130, 120))
    _STDOUT_STYLE = Style(attr=TextAttribute.DIM)

    #: Queue source -> style. Logger records join captured output on the same
    #: queue and read the same way: diagnostics recessive under XeFM's own
    #: ``log_info`` lines, a warning or error in the same red as stderr. They are
    #: still told apart at a glance by their ``HH:MM:SS [Name] LEVEL:`` prefix.
    #: ``log_info`` from a worker thread, queued: drawn in the log's own style
    #: (None), like the lines ``log_info`` appends on the UI thread.
    _LOG_INFO_SOURCE = "LOG_INFO"
    #: Queue source -> the ``source`` an event-log message carries (#682):
    #: ``info`` for ``log_info``, ``log`` / ``error`` for logger records below
    #: and at WARNING, ``stdout`` / ``stderr`` for captured output.
    _EVENT_SOURCES = {_LOG_INFO_SOURCE: "info", LOG_SOURCE: "log",
                      LOG_ERROR_SOURCE: "error", "STDOUT": "stdout",
                      "STDERR": "stderr"}
    _LOG_STYLES = {
        "STDERR": _STDERR_STYLE,
        LOG_ERROR_SOURCE: _STDERR_STYLE,
        "STDOUT": _STDOUT_STYLE,
        LOG_SOURCE: _STDOUT_STYLE,
        _LOG_INFO_SOURCE: None,
    }

    def _enqueue_log(self, source: str, line: str) -> None:
        """Sink for :func:`xefm.log_manager.set_log_sink`: put a formatted record
        on the same queue the captured streams feed. Called from whichever thread
        logged, so it does exactly what ``_StreamToLog.write`` does and no more -
        the ``LogView`` is touched only by the UI thread, in the drain below."""
        self._log_queue.put((source, line))
        self._wake_pump()

    def _drain_captured_output(self) -> bool:
        """Append any stdout/stderr lines captured since the last pump to the log
        pane. Runs on the UI thread (only place the ``LogView`` is touched); the
        queue is fed by the ``_StreamToLog`` streams and by the log sink, possibly
        from worker threads. Returns True if anything was appended (so the caller
        redraws)."""
        appended = False
        while True:
            try:
                source, line = self._log_queue.get_nowait()
            except queue.Empty:
                break
            self.log.append(line, self._LOG_STYLES.get(source, self._STDOUT_STYLE))
            event_log.write("message", source=self._EVENT_SOURCES.get(source, "stdout"),
                            text=line)
            appended = True
        return appended

    def _pane_name_of(self, pane: dict) -> str:
        """The side ``pane`` belongs to, whichever of its tabs it is."""
        return self.pm.side_of(pane) or "right"

    def _hold_if_hidden(self, pane: dict) -> bool:
        """For a pane that is a tab not on screen: note that it owes a re-list,
        and return True so the caller does nothing now — a listing is installed
        on whichever tab its side is showing, so it must not start for another.
        :meth:`_show_tab` re-lists it on the way in."""
        if self.pm.is_shown(pane):
            return False
        pane["_stale"] = True
        return True

    #: How long a listing may run before the pane shows a "Loading…" indicator.
    #: Below this, a fast (local) listing lands and swaps in with no flash; only a
    #: genuinely slow directory (a network mount, a spun-down disk, a huge dir, or
    #: a remote path) ever shows the indicator. See ``_pump_loading_indicator``.
    _LOADING_INDICATOR_DELAY = 0.12

    def _list_pane(self, pane_name: str, *, on_ready=None,
                   keep_visible: bool = False) -> None:
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
        for cursor placement etc.

        ``keep_visible`` re-reads the directory *without* first emptying the pane —
        the current listing stays on screen and stays actionable for the whole
        re-read, and no "Loading…" indicator is armed. It is for a re-list nothing
        asked for, where the expected outcome is "identical to what is already
        shown": a filesystem-monitor reload (see ``_handle_reload_request``). The
        blanking below is right for a *navigation*, where the old directory's
        entries must not stay actionable under the new path, but on a monitor
        reload it empties the pane for the length of a full re-scan in response to
        a change the user never made — see #239."""
        pane = self.pane(pane_name)
        if xft.is_xft_path(pane["path"]):
            self._note_xft_anchor(pane)
        self._fire_directory_changed(pane_name, pane)
        gen = pane["_load_gen"] = next(_LOAD_GENS)
        # "A listing is in flight", tracked separately from ``loading`` because
        # the two answer different questions: ``loading`` means "this pane is
        # blanked and showing (or about to show) an indicator", which a
        # keep_visible re-list deliberately never does. Callers that must know
        # whether the filesystem read has landed — ``_listings_pending`` — need
        # this one, or a keep_visible listing looks settled the moment it starts.
        pane["_load_pending"] = True
        if not keep_visible:
            pane["loading"] = True
            pane["_load_started"] = time.monotonic()
            pane["_loading_shown"] = False
            # Clear the old listing so a stale entry can't be acted on under the
            # new path; the pane shows blank (then "Loading…" only if slow) until
            # the result lands.
            pane["files"] = []
            pane["file_info"] = {}
        # Snapshot the inputs so the worker never reads the pane dict — the UI
        # thread owns it.
        path = pane["path"]
        filter_pattern = pane["filter_pattern"]
        sort_mode = pane["sort_mode"]
        sort_reverse = pane["sort_reverse"]
        overlay = self._sort_overlay(pane)

        def worker() -> None:
            result = self.flm.compute_listing(
                path, filter_pattern=filter_pattern,
                sort_mode=sort_mode, sort_reverse=sort_reverse,
                overlay=overlay,
            )
            if result.get("ok"):
                # An extra's 'when' may touch the filesystem (is this a Git
                # working tree?), so it is asked here rather than on the UI
                # thread.
                result["extras_auto"] = layouts.extras_for(path)
            # drop_if_unchanged tracks keep_visible here: a re-list nobody
            # asked for is the case worth dropping. The re-sort path posts False.
            self._result_queue.put((pane_name, gen, result, on_ready,
                                    keep_visible, keep_visible))
            self._wake_pump()  # wake the UI thread to install the listing

        threading.Thread(target=worker, name=f"xefm-list-{pane_name}", daemon=True).start()

        # Event-driven mode has no permanent tick, so a slow listing would never
        # surface its "Loading…" indicator; a transient tick runs while any pane
        # is loading and retires itself the moment the listing lands. A
        # keep_visible re-list shows no indicator, so it needs no tick — the
        # worker's _wake_pump still delivers the result.
        if self._event_driven and not keep_visible:
            self.panel.request_animation_ticks(self._loading_tick)

    def _fire_directory_changed(self, pane_name: str, pane: dict) -> None:
        """Fire the 'directory_changed' hook when a pane is about to list a
        *different* directory from the one it last reported.

        Every listing funnels through ``_list_pane``, which makes this the one
        place that sees all of them — navigation, the O-sync that lists directly,
        a jump, a drive change. Comparing against the last reported path is what
        keeps the event meaning "changed": a post-operation reload, a
        filesystem-monitor reload and a sort change all re-list the same
        directory and must stay silent.

        The startup listings are silent too — ``_hook_path`` is seeded from the
        pane's opening directory — because 'startup' is the event for that."""
        new_path = pane.get("path")
        # Recorded unconditionally, hooks or not, so a hook added by a config
        # reload mid-session starts from where the pane actually is rather than
        # missing the first change after it loaded.
        old_path = pane.get("_hook_path", new_path)
        pane["_hook_path"] = new_path
        if str(old_path) != str(new_path):
            # The back / forward history (#589): a step through it moves the
            # entry itself; any other change starts a new branch.
            if pane.pop("_history_step", False):
                pass
            elif old_path is not None:
                back = pane.setdefault("_back", [])
                back.append(old_path)
                del back[:-self._BACK_MAX]
                pane["_forward"] = []
        if str(old_path) == str(new_path) or not _hooks.get("directory_changed"):
            return
        _hooks.fire("directory_changed", self._user_ctx,
                    pane=PaneApi(self, pane_name), old_path=old_path,
                    new_path=new_path)

    @staticmethod
    def _listing_unchanged(pane: dict, result: dict) -> bool:
        """True if ``result`` would redraw the pane exactly as it already looks.

        ``files`` is the rows and their order; ``file_info`` is every column drawn
        from disk (size, date, dir/link flags). Together they are precisely what a
        pane renders, so comparing equal means installing the result could not
        change one cell on screen.

        Deliberately ignores anything the listing read but never shows — an xattr
        write, a permission change, a `chmod`, a same-minute mtime bump. Those are
        what makes a monitor reload spurious in the first place (#239): macOS
        reports them as ordinary "modified" events, indistinguishable from a real
        write, and playing a video file emits a stream of them."""
        if not result.get("ok"):
            return False  # an error result really does change the pane
        return (result.get("files") == pane.get("files")
                and result.get("file_info") == pane.get("file_info"))

    def _process_result_queue(self) -> bool:
        """Install completed async listings on the UI thread, dropping any that a
        newer navigation superseded (stale generation) or that would not change
        anything on screen (a spurious monitor reload)."""
        applied = False
        while True:
            try:
                item = self._result_queue.get_nowait()
            except queue.Empty:
                break
            (pane_name, gen, result, on_ready, keep_visible,
             drop_if_unchanged) = item[:6]
            # An optional seventh element: ``prepare(pane, result) -> bool``,
            # run on this thread before the listing is installed. It readies the
            # pane for what is landing (a virtual listing's set, pruned) and may
            # refuse it outright — an imported list none of whose paths exist
            # leaves the pane as it was.
            prepare = item[6] if len(item) > 6 else None
            pane = self.pane(pane_name)
            if gen != pane.get("_load_gen"):
                # Superseded by a newer navigation. Leave _load_pending set — it
                # tracks the *latest* generation, which is still in flight.
                continue
            pane["_load_pending"] = False
            if prepare is not None and not prepare(pane, result):
                # Refused, but a refusal says why in the log pane, and that
                # line is owed a frame.
                applied = True
                continue

            # Only a keep_visible re-list can be dropped, and only while the pane
            # is actually showing the listing it is compared against: one still
            # blanked by an in-flight navigation must install the result even when
            # it compares equal (an empty directory would otherwise match the
            # blank pane and leave it stuck "loading" forever).
            if "extras_auto" in result and \
                    result["extras_auto"] != pane.get("_extras_auto"):
                pane["_extras_auto"] = result["extras_auto"]
                applied = True
            if (drop_if_unchanged and not pane.get("loading")
                    and self._listing_unchanged(pane, result)):
                # Nothing to redraw, but the entries are a fresher snapshot than
                # the one held — keep it current so a later sort or filter change
                # rebuilds from what is on disk now, at no cost.
                pane["_listing_entries"] = result.get("entries")
                continue

            self.flm.apply_listing(pane, result)
            pane["loading"] = False
            pane["_loading_shown"] = False
            self._animate_pane_text(pane_name)
            if on_ready:
                on_ready(pane)
            applied = True
        if applied:
            # A directory change settles its cursor when the listing lands,
            # after the key that asked for it — follow it then too, or the
            # preview stays on the empty, still-loading pane (#569 hand check).
            self._quick_view_follow()
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
        or its result not yet drained) — including a keep_visible re-list, which
        never raises ``loading``."""
        return any(self.pane(n).get("_load_pending") for n in ("left", "right"))

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
        # render. stdout/stderr and the loggers are routed into the log pane, so a
        # single stray write from the draw path (a `logger.warning`, a stray
        # `print`) would otherwise self-sustain:
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
        cursor on the same file if it survives, otherwise on the row that took
        its place (:meth:`_apply_cursor_anchor`), and hold the scroll offset
        where it can still show it.

        Re-lists with ``keep_visible``: the pane nobody asked to reload keeps
        showing its entries throughout, and the result is dropped outright unless
        it differs from them (see ``_listing_unchanged``). Most reloads reaching
        here change nothing on screen — macOS reports a metadata-only write
        (xattr, permissions) as an ordinary "modified" event, so merely opening a
        file in an app fires one (#239).

        Returns True if a re-list was started, False for an unknown pane name."""
        if pane_name == "left":
            pane = self.pm.left_pane
        elif pane_name == "right":
            pane = self.pm.right_pane
        else:
            return False

        # A virtual (search-results) pane isn't a directory listing — a
        # filesystem event on its old watched root must not re-list and blow the
        # result set away. Monitoring is effectively suspended while it is virtual;
        # a mutating op reconciles it explicitly via _relist, which rebuilds the
        # result set in memory rather than reading a directory.
        if pane.get("virtual"):
            return False

        # A listing is already in flight for this pane (a navigation, a sort, a
        # post-operation refresh). It will install contents at least as fresh as
        # this request, and superseding it would throw away the cursor placement
        # its on_ready carries — landing on the child you came up from, say.
        if pane.get("loading"):
            return False

        anchor = self._cursor_anchor(pane)

        def restore(pane: dict) -> None:
            self._apply_cursor_anchor(pane, anchor)

        # Always on a worker, local or remote, so a reload nobody asked for can
        # never block the tick. ``restore`` runs on the UI thread when the result
        # lands — and only if it lands: a result matching what the pane already
        # shows is dropped, leaving the cursor and scroll exactly where the user
        # put them.
        self._list_pane(pane_name, on_ready=restore, keep_visible=True)
        return True

    # --- state ---------------------------------------------------------------

    def active_pane(self) -> dict:
        return self.pm.get_current_pane()

    def pane(self, name: str) -> dict:
        return self.pm.left_pane if name == "left" else self.pm.right_pane

    def _archive_pins(self):
        """The archive files the panes are inside, for the archive cache. Called
        from the cache's reaper thread, so it only reads (issue #516)."""
        for name in ("left", "right"):
            archive = get_member_archive_path(self.pane(name).get("path"))
            if archive is not None:
                yield f"shown in the {name} pane", archive

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
        queue_ = getattr(self, "_log_queue", None)
        if queue_ is not None and threading.current_thread() is not self._ui_thread:
            # A file operation logs every file from its worker. LogView is not
            # thread-safe: an append that trims the buffer while the UI thread
            # draws it raised in the draw — inside a background job's tick, which
            # PuiKit then dropped, so the job never released the queue (#620).
            queue_.put((self._LOG_INFO_SOURCE, message))
            self._wake_pump()
            return
        self.log.append(message)
        event_log.write("message", source="info", text=message)

    def _log_result(self, result) -> None:
        """Log the (success, message) a FileListManager action returns."""
        if isinstance(result, tuple) and len(result) == 2 and result[1]:
            self.log_info(result[1])

    def _sync_active(self) -> None:
        self.left_view.active = self.pm.active_pane == "left"
        self.right_view.active = self.pm.active_pane == "right"
        # The preview is not a pane to work in: making its side active —
        # Tab, a click, focus_left / focus_right — closes it.
        if getattr(self, "_quick_view", None) is not None \
                and self.pm.active_pane == self._quick_view_side:
            self._close_quick_view()

    # --- quick view (#569) ---------------------------------------------------

    _quick_view = None

    #: Actions aimed at the other pane, refused while quick view stands in for
    #: it: the target directory would be one that is not on screen.
    _OTHER_PANE_ACTIONS = frozenset({
        "copy_files", "move_files", "sync_current_to_other",
        "sync_other_to_current", "compare_selection", "diff_files",
        "diff_directories",
    })

    def quick_view(self) -> None:
        """Toggle the inactive pane into a preview of the active pane's cursor
        item (:mod:`xefm.quick_view`). The inactive pane's own directory,
        cursor and selection are untouched, and come back when it closes."""
        if self._quick_view is not None:
            self._close_quick_view()
            self.log_info("Quick view closed")
            return
        side = "right" if self.pm.active_pane == "left" else "left"
        view = QuickView(self.panel)
        column = LayoutView(VSplit(Item(view, weight=1, hints={"surface": "content"})))
        if side == "left":
            self._quick_view_saved = self.pane_splitter.first
            self.pane_splitter.first = column
        else:
            self._quick_view_saved = self.pane_splitter.second
            self.pane_splitter.second = column
        self._quick_view = view
        self._quick_view_side = side
        self._quick_view_follow()
        self.log_info(f"Quick view — {self._keys_label('quick_view')} or Esc "
                      f"closes it")

    def _close_quick_view(self) -> None:
        view = self._quick_view
        if view is None:
            return
        view.close()
        if self._quick_view_side == "left":
            self.pane_splitter.first = self._quick_view_saved
        else:
            self.pane_splitter.second = self._quick_view_saved
        self._quick_view = None
        self._quick_view_saved = None

    def _quick_view_follow(self) -> None:
        """Tell the preview where the cursor is; it decides whether that is
        news. Called after every event the file list handles."""
        view = self._quick_view
        if view is None:
            return
        pane = self.active_pane()
        entry = self._focused_entry()
        info = (pane.get("file_info") or {}).get(str(entry)) if entry else None
        view.follow(entry, info)

    def _on_click(self, pane_name: str, index: int,
                  modifiers: frozenset = frozenset(), clicks: int = 1) -> None:
        """A FilePane was left-clicked: make it active and move the cursor.

        ``index`` is ``-1`` when the click landed past the last row — the empty
        space below a short listing, or anywhere in a pane showing an empty
        directory. The pane still becomes the active one, which is what the
        click was asking for; the cursor stays where it is, there being no row
        to put it on (issue #371).

        On a row, the mouse maps onto XeFM's cursor-and-marks model (#589):

        - a plain click moves the cursor and leaves the marks alone — marks are
          deliberate, often built up over a while, and a stray click must not
          wipe them;
        - Cmd-click (Ctrl-click off macOS; on the Mac, Control-click is the
          secondary click) toggles that row's mark;
        - Shift-click marks every row from the anchor — the last plain or
          Cmd/Ctrl-clicked row, else the cursor — to this one, adding to the
          marks as every other way of marking does;
        - a plain double-click opens what the row holds, as Enter does."""
        self.pm.active_pane = pane_name
        self._sync_active()
        if index < 0:
            return
        pane = self.active_pane()
        files = pane["files"]
        toggle = bool({"cmd", "ctrl"} & set(modifiers))
        if "shift" in modifiers:
            anchor = pane.get("_click_anchor")
            if not isinstance(anchor, int) or not 0 <= anchor < len(files):
                anchor = pane.get("focused_index", index)
            lo, hi = sorted((anchor, index))
            for entry in files[lo:hi + 1]:
                if entry.name != "..":
                    pane["selected_files"].add(str(entry))
            pane["focused_index"] = index
            return
        pane["focused_index"] = index
        pane["_click_anchor"] = index
        if toggle:
            entry = files[index]
            if entry.name != "..":
                key = str(entry)
                if key in pane["selected_files"]:
                    pane["selected_files"].discard(key)
                else:
                    pane["selected_files"].add(key)
            return
        if clicks == 2:
            self._open(pane)

    def _on_middle_click(self, pane_name: str, index: int) -> None:
        """Middle-click on a directory row opens it in the other pane — the
        two-pane reading of "open in a new tab"."""
        pane = self.pane(pane_name)
        files = pane["files"]
        if not 0 <= index < len(files):
            return
        entry = files[index]
        info = pane.get("file_info", {}).get(str(entry), {})
        if not info.get("is_dir") or entry.name == "..":
            return
        other_name = "right" if pane_name == "left" else "left"
        other = self.pane(other_name)
        self.pm.active_pane = other_name
        self._sync_active()
        self._go_to_dir(other, entry, None)
        self.panel.render()

    def _on_nav_button(self, pane_name: str, step: str) -> None:
        """The mouse's back / forward buttons, over a pane: step that pane
        through the directories it has shown."""
        self.pm.active_pane = pane_name
        self._sync_active()
        if step == "back":
            self.go_back()
        else:
            self.go_forward()

    # --- back / forward (#589) ---------------------------------------------

    #: How many directories each pane remembers to step back through.
    _BACK_MAX = 100

    def go_back(self) -> None:
        """Step the active pane back to the directory it showed before, the
        way a browser's Back does. Distinct from Backspace (the parent) and
        from H (any recent directory)."""
        self._step_history("_back", "_forward", "back")

    def go_forward(self) -> None:
        """Undo a :meth:`go_back`."""
        self._step_history("_forward", "_back", "forward")

    def _step_history(self, source: str, other: str, word: str) -> None:
        pane = self.active_pane()
        stack = pane.get(source) or []
        if not stack:
            self.log_info(f"Nothing to go {word} to")
            return
        target = stack.pop()
        here = pane.get("path")
        pane.setdefault(other, []).append(here)
        pane["_history_step"] = True
        # Land on the directory we came from when stepping back to its parent.
        focus = here.name if here is not None and str(here.parent) == str(target) else None
        self._go_to_dir(pane, target, focus)
        self.panel.render()

    @staticmethod
    def _cursor_anchor(pane: dict):
        """Snapshot what the cursor is on — the focused row *and the rows around
        it*, in the order they are shown — so a re-list can put it back.

        The whole order goes in, not just the focused entry, because the focused
        entry may be precisely what the re-list will not find: it was the file
        just deleted, moved or renamed. What the cursor should then fall to is
        defined by the order the user was looking at, which only this snapshot
        still holds. Returns None when there is no cursor to restore — an empty
        pane, or one already blanked by a listing in flight."""
        files = pane.get("files") or []
        index = pane.get("focused_index", 0)
        if not files or not 0 <= index < len(files):
            return None
        return ([str(f) for f in files], index)

    def _apply_cursor_anchor(self, pane: dict, anchor) -> None:
        """Put the cursor back where :meth:`_cursor_anchor` found it.

        Exact when the focused entry is still listed. When it is gone the cursor
        walks the *old* order outward from it — the first surviving row below it,
        then the first above — which is the "next item" a delete should land on,
        and is right under any sort order. Guessing by name instead would only be
        right for a name-sorted pane, and this one may be sorted by size or date,
        or reversed. Falls back to the old row number when nothing around it
        survived, and to the top when the directory is now empty."""
        files = pane.get("files") or []
        if not files:
            pane["focused_index"] = 0
            pane["scroll_offset"] = 0
            return
        if anchor is None:
            return
        old, index = anchor
        row_of = {str(f): i for i, f in enumerate(files)}
        # Outward from the anchor: down first (the row that took its place),
        # then up, so the first survivor found is the nearest one below it.
        outward = list(range(index, len(old))) + list(range(index - 1, -1, -1))
        landing = next((row_of[old[j]] for j in outward if old[j] in row_of), None)
        pane["focused_index"] = (landing if landing is not None
                                 else min(index, len(files) - 1))
        self._scroll_to_focus(pane)

    def _scroll_to_focus(self, pane: dict) -> None:
        """Clamp the pane's scroll offset to a listing that may have shrunk, then
        pull the focused row back into view."""
        height = self._display_height()
        max_offset = max(0, len(pane.get("files") or []) - height)
        pane["scroll_offset"] = max(0, min(pane.get("scroll_offset", 0), max_offset))
        self.pm.adjust_scroll_for_focus(pane, height)

    def _relist(self, pane: dict, *, keep_cursor: bool = True, on_ready=None) -> None:
        """Re-list ``pane`` **in place** — same directory, cursor held on the same
        file — on a worker thread (see ``_list_pane``), so a sort change, a filter
        change or a post-operation reload never blocks the UI on a slow mount.
        ``on_ready(pane)`` runs once the files are in place, on the UI thread;
        anything that reads the new listing (an item count, a cursor placed by
        name) belongs there, because ``pane['files']`` is empty from here until
        the result lands — and it runs *after* the cursor is restored, so a
        caller that places the cursor itself still wins.

        ``keep_cursor`` anchors the cursor to the focused **file** rather than to
        its row number (:meth:`_cursor_anchor`): the listing this re-reads is
        usually one an operation just changed, and a row number means something
        different once entries above it have come or gone. False is for the two
        callers that reset the cursor on purpose — :meth:`_refresh`, and a filter
        change reaching here through :meth:`_resort`.

        For a **virtual pane** (a search-results feed, an imported list) there
        is no directory to read: the flat listing is rebuilt from the set,
        re-reading each path's attributes on a worker thread
        (:meth:`_list_virtual`), and ``on_ready`` fires when it lands.

        This is the "no directory change" sibling of :meth:`_refresh`, which adds
        the cursor reset and the history record a navigation needs."""
        if self._hold_if_hidden(pane):
            return
        anchor = self._cursor_anchor(pane) if keep_cursor else None

        def landed(p: dict) -> None:
            if keep_cursor:
                self._apply_cursor_anchor(p, anchor)
            if on_ready is not None:
                on_ready(p)

        virtual = pane.get("virtual")
        if virtual:
            self._list_virtual(pane, virtual, on_ready=landed)
            return
        self._list_pane(self._pane_name_of(pane), on_ready=landed)

    def _list_virtual(self, pane: dict, virtual: dict, *, on_ready=None,
                      on_empty=None, on_result=None, load=None,
                      entries=None) -> None:
        """(Re)build a virtual pane's listing from ``virtual['results']`` on a
        worker thread — the virtual counterpart of :meth:`_list_pane`.

        Each path's attributes are read once, and that read is the existence
        check (:meth:`FileListManager.compute_virtual_listing`). That is N
        round trips for N rows, which on an ``ssh://`` or ``s3://`` list — or
        a long local one — is exactly what must not run on the UI thread. The
        pane keeps showing its rows while the worker runs, as a monitor reload
        does: nothing about it is navigating anywhere.

        Two callers, told apart by whether ``virtual`` is already the pane's:

        - **Entering** — a search feed or an imported list. The pane changes
          only once the listing lands, and only if at least one path survived;
          if none did, ``on_empty(result)`` runs instead and the pane is left
          as it was. Entering starts unfiltered, with no selection, cursor at
          the top.
        - **Refreshing** — after an operation. Paths found gone leave the set,
          so they do not come back on the next refresh; a result that lands
          after the pane left this set (⌫, a navigation) is dropped.

        A ``virtual`` entering with no ``root`` has one derived on the worker,
        from the paths that survived (:func:`xefm.path_list.common_root`) — a
        path that turned out not to exist must not drag the root up — or
        :data:`~xefm.name_key.WHOLE_PATH` where they share none.

        ``load()``, when given, runs first on the worker and returns the
        :class:`~xefm.path_list.Resolved` set to list in place of
        ``virtual['results']`` — for a source whose reading is itself I/O, such
        as a list file on a remote host. Its ``relative`` count and
        ``problems`` ride along in the result, with ``total``, the number of
        paths listed.

        ``entries`` — ``[(Path, attrs), …]`` a walk has already read (flat
        view) — are installed as they are, with no probe: the walk's own
        listings were the existence check.

        ``on_result(result)`` runs just before a listing is installed, for a
        caller that reports what was left out (``missing``, ``unreachable``);
        ``on_ready(pane)`` runs once the rows are in place. Both on the UI
        thread; so does ``on_empty(result)``."""
        if self._hold_if_hidden(pane):
            return
        pane_name = self._pane_name_of(pane)
        gen = pane["_load_gen"] = next(_LOAD_GENS)
        pane["_load_pending"] = True
        entering = pane.get("virtual") is not virtual
        # Snapshot every input: the worker must not read the pane dict.
        paths = list(virtual["results"])
        filter_pattern = "" if entering else pane.get("filter_pattern")
        sort_mode = pane["sort_mode"]
        sort_reverse = pane["sort_reverse"]
        rel_root = virtual.get("root")
        derive_root = entering and rel_root is None
        overlay = None if entering else self._sort_overlay(pane)

        def prepare(p: dict, result: dict) -> bool:
            if entering:
                if not result["survivors"]:
                    if on_empty is not None:
                        on_empty(result)
                    return False
                if derive_root:
                    virtual["root"] = result["root"]
                p["virtual"] = virtual
                p["filter_pattern"] = ""
                p["focused_index"] = 0
                p["scroll_offset"] = 0
                p["selected_files"].clear()
            elif p.get("virtual") is not virtual:
                return False
            self.flm.prune_virtual(virtual, result)
            if on_result is not None:
                on_result(result)
            return True

        def worker() -> None:
            listed, extra = paths, {}
            if load is not None:
                resolved = load()
                listed = resolved.paths
                extra = {"relative": resolved.relative,
                         "problems": list(resolved.problems)}
            read = {} if entries is None else {"entries": entries}
            result = self.flm.compute_virtual_listing(
                listed, filter_pattern=filter_pattern, sort_mode=sort_mode,
                sort_reverse=sort_reverse, rel_root=rel_root,
                derive_root=derive_root, overlay=overlay, **read)
            result["total"] = len(listed)
            result.update(extra)
            self._result_queue.put((pane_name, gen, result, on_ready,
                                    True, False, prepare))
            self._wake_pump()

        threading.Thread(target=worker, name=f"xefm-list-{pane_name}",
                         daemon=True).start()

    def _resort(self, pane: dict, *, keep_cursor: bool = True, on_ready=None) -> None:
        """Re-sort / re-filter ``pane`` from the snapshot its last listing left
        behind, without touching the filesystem — the path every sort and filter
        change takes.

        A sort change needs nothing the previous listing did not already read:
        the entry list and each entry's size, date and type are still in hand, so
        the new order is derived from that snapshot. That matters most where it
        used to hurt most — re-sorting a 1,680-entry directory on a NAS cost a
        full re-read (tens of seconds of per-file round trips, #183) to produce a
        list the pane could already have derived.

        **On a worker thread**, like every other listing. It used to land
        synchronously, because the work was microseconds of arithmetic over data
        in hand and landing on the tick avoided the blank-then-repopulate flicker
        of ``_relist``. A sort key can now come from a user's config
        (``SORT_KEYS``), which makes it arbitrary code run once per entry — a
        thing that must never be able to hold the UI thread. The flicker argument
        still holds and is answered differently: this posts its result the way a
        filesystem-monitor reload does, **without blanking the pane**, so the
        current rows stay on screen and stay actionable for the whole re-sort
        rather than the pane emptying. Unlike that reload it is never dropped as
        an unchanged redraw, because a caller waiting on ``on_ready`` — the filter
        path, reporting a count — must hear back even when the order is identical.

        Falls back to :meth:`_relist` when the pane has no snapshot (nothing
        listed yet, or the last listing failed), so behaviour is unchanged when
        there is nothing to reuse.

        ``keep_cursor`` holds the cursor on the *same file* across the reorder
        rather than the same row number. Callers that deliberately reset the
        cursor — a filter change, via ``FileListManager.set_filter`` — pass
        False. The file is the one focused when the sort was *asked for*: the old
        rows stay live while the worker runs, so a cursor moved in the meantime
        lands back on what the user was looking at when they pressed the key."""
        if self._hold_if_hidden(pane):
            return
        entries = pane.get("_listing_entries")
        if entries is None:
            self._relist(pane, keep_cursor=keep_cursor, on_ready=on_ready)
            return

        pane_name = self._pane_name_of(pane)
        gen = pane["_load_gen"] = next(_LOAD_GENS)
        pane["_load_pending"] = True

        # Snapshot every input: the worker must not read the pane dict, which the
        # UI thread owns and goes on mutating (cursor, selection) while it runs.
        filter_pattern = pane.get("filter_pattern")
        sort_mode = pane["sort_mode"]
        sort_reverse = pane["sort_reverse"]
        virtual = pane.get("virtual")
        rel_root = virtual.get("root") if virtual else None
        overlay = self._sort_overlay(pane)

        anchor = self._cursor_anchor(pane) if keep_cursor else None

        def landed(p: dict) -> None:
            if keep_cursor:
                self._apply_cursor_anchor(p, anchor)
            if on_ready is not None:
                on_ready(p)

        def worker() -> None:
            result = self.flm.recompute_from_snapshot(
                entries, filter_pattern=filter_pattern, sort_mode=sort_mode,
                sort_reverse=sort_reverse, rel_root=rel_root, overlay=overlay)
            self._result_queue.put((pane_name, gen, result, landed, True, False))
            self._wake_pump()

        threading.Thread(target=worker, name=f"xefm-sort-{pane_name}",
                         daemon=True).start()

    def _sort_overlay(self, pane: dict):
        """``(name, values, reverse)`` for the attribute sort put over
        ``pane``'s own, or None.

        An attribute sort holds for the directory it was chosen in, across
        re-reads of it, and is dropped the moment the pane is somewhere else —
        the pane's own sort mode, which it never replaced, applies again. The
        values are what the pane already has (``AttributeStore.snapshot``): a
        sort never waits for one, and a row without one goes last."""
        spec = pane.get("sort_overlay")
        if not spec:
            return None
        if spec["path"] != str(pane["path"]) or not attributes.is_known(spec["attr"]):
            pane["sort_overlay"] = None
            return None
        entries = pane.get("_listing_entries") or ()
        records = {str(p): a for p, a in entries}
        values = attributes.store_of(pane).snapshot(
            spec["attr"], [p for p, _a in entries], records)
        return (spec["attr"], values, spec["reverse"])

    def _refresh(self, pane: dict, *, on_ready=None) -> None:
        """Re-list ``pane`` after a directory change: reset the cursor, record
        history, and (re)list on a worker thread (see :meth:`_relist`).
        ``on_ready(pane)`` runs once the files are in place, for callers that then
        place the cursor by name.

        A **virtual pane** (a search-results feed) is rebuilt from its result set
        rather than re-listed, and keeps its cursor rather than resetting it —
        there is no directory here to have navigated to. This is the post-op
        reconciliation path — every existing ``self._refresh(pane)`` call site
        keeps working after a mutating op."""
        if pane.get("virtual"):
            # Nothing navigated: hold the cursor on its file, the way every other
            # post-operation reload does.
            self._relist(pane, on_ready=on_ready)
            return
        pane["focused_index"] = 0
        pane["scroll_offset"] = 0

        def landed(p: dict) -> None:
            # History is the list of directories the user has *been* in, and a
            # directory that could not be read is not one of them — recording it
            # before the listing landed put unreachable paths in the History
            # picker, where selecting one would fail all over again.
            if p.get("listing_ok", True):
                self._record_history_path(str(p["path"]))
            if on_ready is not None:
                on_ready(p)

        self._relist(pane, keep_cursor=False, on_ready=landed)

    def _apply_filter(self, pane: dict, pattern: str, *, on_count=None) -> None:
        """Set ``pane``'s filename filter and re-list it off the UI thread — the
        async counterpart of ``FileListManager.apply_filter`` (which stays as the
        synchronous API for non-UI callers).

        ``on_count(n)`` runs once the filtered listing is in place, with the
        number of visible items. A caller that reports the count must go through
        it: the count does not exist until the listing lands, so reading
        ``pane['files']`` straight after this call sees an empty pane."""
        self.flm.set_filter(pane, pattern)
        on_ready = None if on_count is None else (lambda p: on_count(len(p["files"])))
        # set_filter has just reset the cursor to the top, which a filter change
        # should do — so don't restore it over that.
        self._resort(pane, keep_cursor=False, on_ready=on_ready)

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

    def _forget_history_path(self, path: str) -> bool:
        """Drop ``path`` from the recent-directory history (the History picker's
        remove key). Returns whether anything went, which is what tells the
        picker to drop the row.

        *Every* occurrence goes. ``_history`` keeps one entry per visit and the
        picker shows the de-duplicated view, so the single row the user is
        looking at stands for all of them — removing only the last would leave
        the row on screen, apparently untouched.

        Persisted immediately rather than at quit, where the rest of the history
        is written: a directory the user has just asked to forget must not come
        back because the session ended badly. It can still return on the next
        visit — this forgets where you have been, it does not blacklist.
        """
        remaining = [p for p in self._history if p != path]
        if len(remaining) == len(self._history):
            return False
        self._history = remaining
        try:
            self.state_manager.save_recent_directories(
                self._recent_dirs_most_recent_first(), _HISTORY_MAX)
        except Exception as e:
            self.log_info(f"Could not save directory history: {e}")
        self.log_info(f"Removed from history: {path}")
        return True

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

    def _filer_handlers(self) -> dict:
        """The ``filer`` context's ``{action name: (handler, redraw)}`` table —
        what the long ``if/elif`` chain in ``dispatch`` used to be.

        ``redraw`` says what running the handler means for the screen: ``True``
        for an action that changes the panes and wants a repaint, ``False`` for
        one that hands off to a dialog, a viewer or another process and drives
        its own redraw, and ``None`` for the handful that decide per call and
        return the flag themselves.

        Built once per app and cached: the values are bound methods, so the table
        cannot live in :mod:`xefm.actions` alongside the action *metadata* — the
        registry describes what an action is, this says how this app performs it.
        """
        if self._handlers is None:
            self._handlers = {
                # --- application ---
                "quit": (self.confirm_quit, False),
                "quit_app": (lambda: self.confirm_quit(only_if_busy=True), False),
                "help": (self.show_help, False),
                "command_palette": (self.show_command_palette, False),
                "quick_view": (self.quick_view, True),
                "jobs": (self.show_jobs, False),
                "find_similar": (self.find_similar, False),
                "menu": (self.menu_bar.open_menu, None),
                "redraw": (lambda: None, True),
                "reread": (self.reread, False),
                "choose_layout": (self.choose_layout, False),
                "choose_extras": (self.choose_extras, False),
                "resolve_attribute": (self.resolve_attribute, False),
                "choose_keymap": (self.choose_keymap, False),
                # --- cursor ---
                "cursor_up": (self._act_cursor_up, True),
                "cursor_down": (self._act_cursor_down, True),
                "page_up": (self._act_page_up, True),
                "page_down": (self._act_page_down, True),
                "half_page_up": (lambda: self._act_half_page(-1), True),
                "half_page_down": (lambda: self._act_half_page(+1), True),
                "search_next": (lambda: self._act_search_again(+1), True),
                "search_prev": (lambda: self._act_search_again(-1), True),
                "cursor_top": (self._act_cursor_top, True),
                "cursor_bottom": (self._act_cursor_bottom, True),
                "cursor_next_selected": (
                    lambda: self._focus_adjacent_selected(self.active_pane(), +1), True),
                "cursor_prev_selected": (
                    lambda: self._focus_adjacent_selected(self.active_pane(), -1), True),
                # --- selection (reuses FileListManager) ---
                "toggle_select_down": (self._act_select_file, True),
                "toggle_select_up": (self._act_select_file_up, True),
                "toggle_select_in_place": (self._toggle_select_in_place, True),
                "select_range": (self._act_select_range, True),
                "toggle_select_files": (self._act_select_all_files, True),
                "toggle_select_items": (self._act_select_all_items, True),
                "select_all": (self._act_select_all, True),
                "unselect_all": (self._act_unselect_all, True),
                "select_by_pattern": (lambda: self.select_by_pattern(True), False),
                "unselect_by_pattern": (lambda: self.select_by_pattern(False), False),
                "select_same_extension": (self._act_select_same_extension, True),
                # --- navigation ---
                "switch_pane": (self._act_switch_pane, True),
                "open_item": (lambda: self._open(self.active_pane()), True),
                "go_parent": (lambda: self._go_parent(self.active_pane()), True),
                "go_root": (lambda: self._go_root(self.active_pane()), True),
                "new_tab": (self.new_tab, True),
                "open_in_new_tab": (self.open_in_new_tab, True),
                "close_tab": (self.close_tab, True),
                "next_tab": (self.next_tab, True),
                "prev_tab": (self.prev_tab, True),
                "flat_view": (self.flat_view, True),
                "nav_left": (self._act_nav_left, True),
                "nav_right": (self._act_nav_right, True),
                "focus_left": (lambda: self._activate_pane("left"), True),
                "focus_right": (lambda: self._activate_pane("right"), True),
                "sync_current_to_other": (self._act_sync_current_to_other, True),
                "sync_other_to_current": (self._act_sync_other_to_current, True),
                # --- listing ---
                "toggle_hidden": (self._act_toggle_hidden, True),
                "toggle_color_scheme": (self._cycle_theme, True),
                "quick_sort_name": (lambda: self._quick_sort("filename"), True),
                "quick_sort_size": (lambda: self._quick_sort("size"), True),
                "quick_sort_date": (lambda: self._quick_sort("timestamp"), True),
                "quick_sort_ext": (lambda: self._quick_sort("extension"), True),
                "sort": (self.show_sort_menu, False),
                "clear_filter": (self._act_clear_filter, True),
                "filter": (self.enter_filter, False),
                "isearch": (self.enter_isearch, False),
                # --- layout ---
                "adjust_pane_left": (
                    lambda: self._nudge(self.pane_splitter, -self._PANE_STEP), True),
                "adjust_pane_right": (
                    lambda: self._nudge(self.pane_splitter, +self._PANE_STEP), True),
                "reset_pane_boundary": (self._act_reset_pane_boundary, True),
                "adjust_log_up": (
                    lambda: self._nudge(self.content_splitter, -self._LOG_STEP), True),
                "adjust_log_down": (
                    lambda: self._nudge(self.content_splitter, +self._LOG_STEP), True),
                "reset_log_height": (self._act_reset_log_height, True),
                "scroll_log_up": (lambda: self.log.scroll_by(-1.0), True),
                "scroll_log_down": (lambda: self.log.scroll_by(+1.0), True),
                "scroll_log_page_up": (
                    lambda: self.log.scroll_by(-self._LOG_PAGE), True),
                "scroll_log_page_down": (
                    lambda: self.log.scroll_by(+self._LOG_PAGE), True),
                "copy_log_selection": (self.copy_log_selection, True),
                "copy_log_all": (self.copy_log_all, True),
                # --- dialogs and pickers ---
                "file_details": (self.file_details, False),
                "drives": (self.show_drives, False),
                "connect_server": (self.show_connect_server, False),
                "find_files": (self.show_search, False),
                "index_search": (self.index_search, False),
                "find_by_tag": (self.show_tag_search, False),
                "find_in_files": (self.show_content_search, False),
                "history": (self.show_history, False),
                "go_back": (self.go_back, False),
                "go_forward": (self.go_forward, False),
                "programs": (self.show_programs, False),
                "favorites": (self.show_favorites, False),
                "add_favorite": (self.add_favorite, False),
                "context_menu": (self.context_menu, False),
                "context_menu_dir": (self.context_menu_dir, False),
                "jump_to_path": (self.jump_to_path, False),
                "compare_selection": (self.compare_selection, False),
                # --- opening things ---
                "open_with_os": (self.open_with_os, False),
                "open_with": (self.open_with, False),
                "reveal_in_os": (self.reveal_in_os, False),
                "edit_file": (self.edit_file, False),
                "view_file": (self.view_file, False),
                "diff_files": (self.diff_files, False),
                "diff_directories": (self.diff_directories, False),
                "subshell": (self.subshell, False),
                "edit_config": (self.edit_config, False),
                "reload_config": (self.reload_config, False),
                "install_extension": (self.install_extension, False),
                "extensions": (self.show_extensions, False),
                "check_extension_updates": (self.check_extension_updates, False),
                "sync_python_packages": (self.sync_python_packages, False),
                # --- file operations ---
                "create_directory": (self.create_directory, False),
                "create_file": (self.create_file, False),
                "rename": (self.rename, False),
                "rename_in_editor": (self.rename_in_editor, False),
                "copy_names": (self.copy_names_to_clipboard, True),
                "clipboard_copy": (lambda: self.clipboard_put(cut=False), True),
                "clipboard_cut": (lambda: self.clipboard_put(cut=True), True),
                "clipboard_paste": (self.clipboard_paste, True),
                "clipboard_clear": (self.clipboard_clear, True),
                "clipboard_show": (self.clipboard_show, False),
                "copy_paths": (self.copy_paths_to_clipboard, True),
                "open_list_from_clipboard": (self.open_list_from_clipboard, True),
                "open_list_from_command": (self.open_list_from_command, False),
                "open_list_from_file": (self.open_list_from_file, True),
                "copy_files": (self.copy_files, None),
                "move_files": (self.move_files, None),
                "copy_files_to": (self.copy_files_to, None),
                "move_files_to": (self.move_files_to, None),
                "duplicate_files": (self.duplicate_files, None),
                "delete_files": (self.delete_files, None),
                "delete_permanently": (self.delete_permanently, None),
                "create_archive": (self.create_archive, None),
                "extract_archive": (self.extract_archive, None),
            }
        return self._handlers

    def dispatch(self, action: str | None) -> bool:
        """Apply an action to the active pane. Returns True if a redraw is needed."""
        if action is None:
            return False
        return self._run_action(_ctx.FILER, action)

    def _run_action(self, context: str, action: str,
                    ctx: "ActionContext | None" = None) -> bool:
        """Run one named action in one context, user definitions first.

        ``context`` is always ``filer`` today — the viewers own their surfaces
        and run their own handler tables, and user functions are accepted only
        in the file list for now (see :func:`xefm.user_api._build_action`). It is
        a parameter rather than a constant because widening either of those is
        the expected next step, and this is where it lands.

        A config's ``ACTIONS`` entry wins over the built-in of the same name only
        when it asked to (``'override': True``) — the registry has already
        refused it otherwise. The ``_invoking`` guard is what lets an overriding
        action reach the built-in it replaced: ``ctx.invoke('quit')`` from inside
        the user's ``quit`` finds its own name already running and falls through
        to the built-in rather than recurring. The guard lives on the app's own
        context object, so it holds however the caller reached here.

        Returns whether the screen needs a repaint.
        """
        user = _action_registry.resolve(context, action)
        if (user is not None and user.is_user and user.func is not None
                and action not in self._user_ctx._invoking):
            ctx = ctx if ctx is not None else self._user_ctx
            self._user_ctx._invoking.add(action)
            try:
                run_guarded(f"action '{action}'", user.func, ctx)
            finally:
                self._user_ctx._invoking.discard(action)
            # A user action can change anything about the panes, and has no way
            # to say so — always repaint.
            return True

        handler, redraw = self._filer_handlers().get(action, (None, False))
        if handler is None:
            return False
        if self._quick_view is not None and action in self._OTHER_PANE_ACTIONS:
            # The other pane is a preview: its directory is hidden behind it,
            # so an operation aimed there would land somewhere not on screen.
            self.log_info(f"Quick view is open — close it "
                          f"({self._keys_label('quick_view')} or Esc) to "
                          f"work with the other pane")
            return True
        # Guarded like a user action, and for the same reason: a built-in
        # handler reads the config too, so a mistake there (#428) must cost one
        # logged traceback in the log pane, not the running file manager.
        result = run_guarded(f"action '{action}'", handler)
        return bool(result) if redraw is None else redraw

    # --- filer action handlers ------------------------------------------------
    #
    # One method per action that is more than a call to an existing one. They
    # stay small on purpose: the table above is meant to be read as the list of
    # what the file list can do, which only works while the entries are names.

    def _act_cursor_up(self) -> None:
        pane = self.active_pane()
        pane["focused_index"] = max(0, pane["focused_index"] - 1)

    def _act_cursor_down(self) -> None:
        pane = self.active_pane()
        last = max(0, len(pane["files"]) - 1)
        pane["focused_index"] = min(last, pane["focused_index"] + 1)

    def _act_page_up(self) -> None:
        pane = self.active_pane()
        pane["focused_index"] = max(0, pane["focused_index"] - 10)

    def _act_page_down(self) -> None:
        pane = self.active_pane()
        last = max(0, len(pane["files"]) - 1)
        pane["focused_index"] = min(last, pane["focused_index"] + 10)

    def _act_half_page(self, direction: int) -> None:
        """Vim's Ctrl-D / Ctrl-U: half the rows the pane shows."""
        pane = self.active_pane()
        step = max(1, self._display_height() // 2)
        last = max(0, len(pane["files"]) - 1)
        pane["focused_index"] = max(0, min(last, pane["focused_index"] + direction * step))

    def _act_search_again(self, direction: int) -> None:
        """Vim's n / N: the next (or previous) entry matching the last
        incremental search, wrapping at the ends, with the bar closed. The
        match is the bar's own (``find_matches``), so romaji still finds
        Japanese."""
        pattern = self._last_isearch_pattern
        if not pattern:
            self.log_info("No previous search")
            return
        pane = self.active_pane()
        matches = self.flm.find_matches(
            pane, pattern, match_all=True, return_indices_only=True)
        if not matches:
            self.log_info(f"Not found: {pattern}")
            return
        cur = pane["focused_index"]
        if direction > 0:
            pane["focused_index"] = next((m for m in matches if m > cur), matches[0])
        else:
            pane["focused_index"] = next((m for m in reversed(matches) if m < cur),
                                         matches[-1])

    def _act_cursor_top(self) -> None:
        self.active_pane()["focused_index"] = 0

    def _act_cursor_bottom(self) -> None:
        pane = self.active_pane()
        pane["focused_index"] = max(0, len(pane["files"]) - 1)

    def _act_select_file(self) -> None:
        """SPACE: toggle the focused item, then move down."""
        self._log_result(self.flm.toggle_selection(
            self.active_pane(), move_cursor=True, direction=1))

    def _act_select_file_up(self) -> None:
        """``toggle_select_up``: toggle, then move up."""
        self._log_result(self.flm.toggle_selection(
            self.active_pane(), move_cursor=True, direction=-1))

    def _toggle_select_in_place(self) -> None:
        """The context menu's Select / Deselect, and ``toggle_select_in_place``
        (vifm's ``t``): toggle the item and leave the cursor on it. SPACE moves
        down so a run of presses marks a run of rows; a menu names one row, and
        stepping off it made the menu's subject look like the next one."""
        self._log_result(self.flm.toggle_selection(self.active_pane(), move_cursor=False))
        self.panel.render()

    def _act_select_range(self) -> None:
        """``select_range``: fill the span between the nearest marked item and the
        cursor (#266) — a Shift-click done with the keyboard, which is why its
        default key is Shift-SPACE.

        The cursor stays where it is: the item under it is the end of the span,
        not a step on the way. Deliberately a file-list action alone: an open
        search has no range key, because its cursor is a match and the span
        between a mark and a match is not something the search is talking about
        (see the isearch block of xefm/actions.py). Enter leaves the search with
        the cursor on the match, which is where this key applies."""
        self._log_result(self.flm.select_range(self.active_pane()))

    def _act_select_all_files(self) -> None:
        """A: toggle selection of every file."""
        self._log_result(self.flm.toggle_all_files_selection(self.active_pane()))

    def _act_select_all_items(self) -> None:
        """``toggle_select_items``: toggle selection of every item (files + dirs)."""
        self._log_result(self.flm.toggle_all_items_selection(self.active_pane()))

    def _act_select_all(self) -> None:
        pane = self.active_pane()
        pane["selected_files"] = {str(f) for f in pane["files"]}

    def _act_unselect_all(self) -> None:
        self.active_pane()["selected_files"].clear()

    def _act_select_same_extension(self) -> None:
        self._log_result(self.flm.select_same_extension(self.active_pane()))

    def _act_switch_pane(self) -> None:
        self.pm.active_pane = "right" if self.pm.active_pane == "left" else "left"
        self._sync_active()

    def _activate_pane(self, name: str) -> None:
        # Unlike nav_left / nav_right, focusing the pane already active is a
        # no-op rather than a trip to the parent (#509).
        if self.pm.active_pane != name:
            self.pm.active_pane = name
            self._sync_active()

    def _act_nav_left(self) -> None:
        # Context-aware LEFT: from the right pane, move focus to the
        # left pane; already in the left pane, go to its parent directory.
        if self.pm.active_pane == "right":
            self.pm.active_pane = "left"
            self._sync_active()
        else:
            self._go_parent(self.active_pane())

    def _act_nav_right(self) -> None:
        # Context-aware RIGHT: from the left pane, move focus to the
        # right pane; already in the right pane, go to its parent directory.
        if self.pm.active_pane == "left":
            self.pm.active_pane = "right"
            self._sync_active()
        else:
            self._go_parent(self.active_pane())

    def _act_toggle_hidden(self) -> None:
        self.flm.show_hidden = not self.flm.show_hidden
        # _relist, not _list_pane: on a virtual (search-results) pane a raw
        # directory read would replace the result set with the search root's
        # listing while the pane still claimed to be a results view (#259).
        # The virtual-aware path keeps the set; the new flag applies to the
        # next real listing (the hidden filter never applies to a result set).
        self._relist(self.active_pane())
        self.log_info(f"Hidden files: {'shown' if self.flm.show_hidden else 'hidden'}")

    def _act_clear_filter(self) -> None:
        pane = self.active_pane()
        if pane["filter_pattern"]:
            self._apply_filter(pane, "")
            self.log_info("Filter cleared")
        else:
            self.log_info("No filter to clear")

    def _act_reset_pane_boundary(self) -> None:
        self.pane_splitter.fraction = 0.5

    def _act_reset_log_height(self) -> None:
        self.content_splitter.fraction = 1.0 - self._default_log_height()

    def _act_sync_current_to_other(self) -> None:
        # O = go to the other pane's location, landing the cursor there.
        pane = self.active_pane()
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

    def _act_sync_other_to_current(self) -> None:
        # From the results pane, this reveals the highlighted result in the
        # *other* pane, keeping the results here. If instead the *other* pane
        # is the results view, there is nowhere to send a directory — block it.
        pane = self.active_pane()
        if self._reveal_result_other():
            pass
        elif self.pm.get_inactive_pane().get("virtual"):
            self.log_info("The other pane is a search-results view")
        elif pane["path"] == self.pm.get_inactive_pane()["path"]:
            # Both panes already show the same directory: a second press
            # moves the other pane's cursor onto this pane's focused file.
            self.pm.sync_cursor_from_current_pane(self.log_info)
        elif self.pm.sync_other_to_current(self.log_info):
            self._list_pane(self._pane_name_of(self.pm.get_inactive_pane()))

    def _focus_adjacent_selected(self, pane: dict, direction: int) -> None:
        """Move the cursor to the nearest selected entry below (``+1``) or
        above (``-1``) the current position (#265). The cursor stays put — with
        a log line saying why — when there is no selected item that way; the
        pane widget auto-scrolls to the cursor whenever it moves."""
        files = pane["files"]
        selected = pane["selected_files"]
        idx = pane["focused_index"]
        span = (range(idx + 1, len(files)) if direction > 0
                else range(idx - 1, -1, -1))
        for i in span:
            if str(files[i]) in selected:
                pane["focused_index"] = i
                return
        if not selected:
            self.log_info("No selection")
        else:
            self.log_info("No selected item "
                          + ("below" if direction > 0 else "above"))

    def _exit_virtual(self, pane: dict) -> None:
        """Drop a pane out of virtual (search-results) mode so a subsequent
        ``_refresh`` lists a real directory. Called by every navigation that sets
        a real ``pane['path']``; a no-op on a normal pane."""
        pane["virtual"] = None

    #: The pane state a provisional jump puts back when the destination turns
    #: out to be unreadable — everything the pane was showing, which is enough
    #: to restore it without reading the old directory again.
    _PANE_VIEW_KEYS = ("path", "virtual", "files", "file_info",
                       "_listing_entries", "focused_index", "scroll_offset")

    def _jump_pane_to(self, pane: dict, path: Path, *, log: str,
                      select_name: str | None = None) -> None:
        """Send ``pane`` to ``path`` — the move behind every picker that names a
        directory the user cannot see: favorites, drives, history.

        The destination is not probed first. Probing is what made the pickers
        themselves slow to open (#430), and it would be the wrong place for the
        wait anyway. So the move is **provisional**: the pane goes to ``path``,
        the directory is read on a worker thread like any other, and if it
        cannot be read the pane goes back to exactly what it was showing —
        directory, entries, cursor and all, with no second read, because the
        listing it had was never thrown away.

        Without that, picking a favorite that is gone left the pane parked on a
        path that was never there: no entries, no way to tell why, and a
        filesystem watcher working its way down a retry ladder against it. The
        one line the user gets now is the listing's own ("Directory not found:
        …"), which is the whole story.

        ``log`` is the line to write once the move has actually happened.
        ``select_name`` lands the cursor on that entry instead of where the
        pane last left it — a favorite that names a file.

        A ``path`` that turns out to be a file is taken the same way: the pane
        goes to its directory and lands on it. That is how a favorite written in
        ``FAVORITES`` can name a file (#525) without anything being
        probed up front — the listing that would have shown it is the probe.
        """
        before = {k: pane.get(k) for k in self._PANE_VIEW_KEYS}
        # Copied, not referenced: the clear() below empties the very set the
        # pane holds, so a restore has to have its own.
        marked = set(pane["selected_files"])
        self._remember_cursor(pane)
        self._exit_virtual(pane)
        pane["path"] = path
        pane["selected_files"].clear()
        if select_name is None:
            pane["_lands_on_file"] = True

        def landed(p: dict) -> None:
            if p.get("listing_ok", True):
                self.log_info(log)
                if select_name:
                    self._select_by_name(p, select_name)
                else:
                    self._restore_remembered_cursor(p)
            elif p.get("listing_not_dir") and select_name is None:
                # A file: go to where it is and land on it. The pane is restored
                # first so that, should the directory fail too, it goes back to
                # what it was showing and not to the file.
                p.update(before)
                p["selected_files"].update(marked)
                self._jump_pane_to(p, path.parent, log=log, select_name=path.name)
                return
            else:
                # The navigation did not happen — so nothing about it happened,
                # marked files included. compute_listing has already said why,
                # in one line, and nothing is added to it here.
                p.update(before)
                p["selected_files"].update(marked)
            self.panel.render()

        self._refresh(pane, on_ready=landed)
        self.panel.render()

    def _open(self, pane: dict) -> None:
        files = pane["files"]
        if not files:
            return
        entry = files[pane["focused_index"]]
        # A 'file_open' hook sees the entry before XeFM decides what to do with
        # it and may claim it by returning True — which is how a config routes
        # one file type somewhere of its own without touching FILE_ASSOCIATIONS.
        # Directories are excluded: entering one is navigation, not opening.
        try:
            if _hooks.get("file_open") and not entry.is_dir():
                if _hooks.fire("file_open", self._user_ctx, path=entry):
                    return
        except Exception as exc:
            self.log_info(f"Cannot open {entry.name}: {exc}")
            return
        try:
            if entry.is_dir():
                self._remember_cursor(pane)  # remember where we were in this dir
                self._exit_virtual(pane)  # entering a dir leaves the result set
                pane["path"] = entry
                self._refresh(pane, on_ready=self._restore_remembered_cursor)
                self.log_info(f"Entered {entry.name}/")
            elif (self._readable_archive_format(entry.name) and not self._is_archive(entry)
                  and not get_builtin_handler_for_file(entry.name)[0]):
                # A recognised archive file with no 'enter' rule of its own (a
                # rule can say 'viewer' or None for an .apk, #776, and _enter_file
                # browses it the same way for 'navigate'): browse it as a virtual
                # directory via
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
                # (``open_with_os`` is the one that hands off to another app), so
                # a FILE_ASSOCIATIONS 'enter' rule selects a built-in handler
                # rather than a program to launch.
                self._enter_file(pane, entry)
        except Exception as exc:
            self.log_info(f"Cannot open {entry.name}: {exc}")

    def _enter_file(self, pane: dict, entry) -> None:
        """Handle Enter on a plain file, inside XeFM.

        An ``enter`` rule in FILE_ASSOCIATIONS picks the handler: ``'viewer'``
        for the built-in viewer, ``'navigate'`` to browse the file as an
        archive (for one whose name XeFM does not recognise; the archive cache
        then tells the format from its bytes, #776), ``'list'`` to open it as a file
        list (an ``.m3u8`` playlist, a ``.lst``), or ``None`` to do nothing.

        With no rule, the default stands: the built-in viewer — the same one V
        uses, which routes *.md to the Markdown renderer and shows a
        placeholder for binaries (issue #212). A file inside a
        password-protected zip prompts for the password first (#180).
        """
        # A Finder saved search (Smart Folder) is a query, not a document:
        # Enter runs it (#579).
        if getattr(entry, "suffix", "") == ".savedSearch" and os_index.engine() == "Spotlight":
            self._open_saved_search(pane, entry)
            return
        # A reference in an .xft tree that points at a directory goes there:
        # wrapping the real directory inside the tree would turn a snapshot
        # into a live view (#573).
        target = entry.target()
        if target is not None:
            try:
                is_dir = target.is_dir()
            except Exception:  # noqa: BLE001 — unreachable: open it as a file
                is_dir = False
            if is_dir:
                self._go_to_dir(pane, target, None)
                self.log_info(f"Go to: {target}")
                return
        # A .xft file is entered like an archive, whatever FILE_ASSOCIATIONS
        # says: the extension means nothing else, and a config written before
        # it existed has no rule for it.
        if xft.is_tree_file(entry.name) and not xft.is_xft_path(entry):
            self._remember_cursor(pane)
            self._exit_virtual(pane)
            pane["path"] = Path(xft.uri_for(entry.absolute()))
            self._refresh(pane, on_ready=self._restore_remembered_cursor)
            self.log_info(f"Opened {entry.name}")
            self._watch_xft()
            return
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
        if handler == "list":
            self._open_list_files(self._pane_name_of(pane), [entry])
            return
        # Nothing built in can render this: warn in the log rather than spending
        # a full-screen viewer on a placeholder. Images are binary but the image
        # viewer renders them, and a rich renderer likewise claims its type even
        # when binary — so both bypass this guard.
        if handler != "viewer" and rich_renderer_for(entry) is None \
                and not is_image_file(entry) and not document_text.handles(entry) \
                and looks_binary(entry):
            self.log_info(self._no_builtin_viewer_message(entry))
            return
        self._ensure_archive_password(entry, lambda: self._open_viewer(entry, pane))

    @staticmethod
    def _no_builtin_viewer_message(entry) -> str:
        """Warning for a file XeFM has no built-in way to display.

        Names the key actually bound to ``open_with_os`` rather than assuming
        one — that binding is configurable, and the desktop cases add a chord the
        terminal cannot have. Says nothing about a key at all when the action is
        unbound.
        """
        keys = keys_label_for_action("open_with_os")
        if keys:
            return (f"No built-in viewer for {entry.name} — "
                    f"press {keys} to open it in an external program")
        return (f"No built-in viewer for {entry.name} — bind 'open_with_os' "
                f"to open it in an external program")

    def _go_parent(self, pane: dict) -> None:
        # From a virtual pane, "up" leaves the result set and lists the search
        # root (pane['path'] still holds it). A list opened from a directory
        # lands back on the row it was opened from — the list file, so walking a
        # folder of lists is up, down, Enter; otherwise the cursor lands
        # generically.
        virtual = pane.get("virtual")
        if virtual:
            back_to = virtual.get("return_to")
            self._exit_virtual(pane)

            def land_on_origin(p: dict) -> None:
                for i, f in enumerate(p["files"]):
                    if f.name == back_to:
                        p["focused_index"] = i
                        break

            self._refresh(pane, on_ready=land_on_origin if back_to else None)
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

    @staticmethod
    def _top_level_name(path, root) -> str | None:
        """The name of the branch directly under ``root`` that ``path`` sits in,
        so a jump to the root can land the cursor the way ``go_parent`` lands on
        the child it came from. ``None`` when the walk never meets ``root``.

        The walk is bounded rather than trusting every backend's chain to
        terminate: this runs on the UI thread, and a path implementation whose
        parents never reach a fixed point would otherwise hang the app.
        """
        node = path
        for _ in range(256):
            parent = node.parent
            if str(parent) == str(node):
                return None
            if str(parent) == str(root):
                return node.name
            node = parent
        return None

    def _go_root(self, pane: dict) -> None:
        """Jump straight to the top of wherever the pane is.

        ``Path.anchor`` names that place for every backend — the drive root on
        Windows, ``/`` on POSIX, the bucket root on S3, the host root over SFTP
        — so the one behavior is right on every platform without a branch, which
        is what made the feature worth building in (#353) rather than leaving to
        a per-OS favorite.
        """
        path = pane["path"]
        root = Path(path.anchor)
        if not pane.get("virtual") and str(root) == str(path):
            self.log_info(f"Already at {root}")
            return
        self._go_to_dir(pane, root, self._top_level_name(path, root))
        self.log_info(f"Up to {root}")

    # --- folder tabs (#563) --------------------------------------------------

    def new_tab(self) -> None:
        """Open a new tab in the active pane at the place it shows, after the
        current one, cursor on the same row. A virtual pane's new tab is its
        directory: the results stay where they are, in their own tab."""
        side = self.pm.active_pane
        pane = self.pane(side)
        files = pane["files"]
        idx = pane["focused_index"]
        focus = files[idx].name if files and 0 <= idx < len(files) \
            and not pane.get("virtual") else None
        self._open_tab(side, pane["path"], focus=focus)

    def open_in_new_tab(self) -> None:
        """Open the directory under the cursor in a new tab of the active pane
        — the tab to go into it in, keeping this one where it is."""
        pane = self.active_pane()
        entry = self._focused_entry()
        info = (pane.get("file_info") or {}).get(str(entry)) if entry else None
        if entry is None or not (info or {}).get("is_dir"):
            self.log_info("Open in New Tab: put the cursor on a directory")
            return
        self._open_tab(self.pm.active_pane, entry)

    def _open_tab(self, side: str, path, *, focus: str | None = None) -> None:
        pane = self.pane(side)
        self._remember_cursor(pane)
        tab = self.pm.new_pane(path, like=pane)
        self.pm.open_tab(side, tab)
        self._show_tab(side, focus=focus)
        n = len(self.pm.tabs[side])
        self.log_info(f"New tab: {path}  ({self.pm.tab_index[side] + 1} of {n})")

    def close_tab(self) -> None:
        """Close the active pane's current tab and show the next one. A pane's
        only tab stays: a pane always shows something."""
        side = self.pm.active_pane
        pane = self.pane(side)
        if len(self.pm.tabs[side]) < 2:
            self.log_info("This is the pane's only tab")
            return
        self._remember_cursor(pane)
        self.pm.close_tab(side)
        self._show_tab(side)
        self.log_info(f"Closed tab: {_tab_label(pane)}")

    def next_tab(self) -> None:
        self._step_tab(+1)

    def prev_tab(self) -> None:
        self._step_tab(-1)

    def _step_tab(self, delta: int) -> None:
        side = self.pm.active_pane
        if len(self.pm.tabs[side]) < 2:
            self.log_info("This pane has one tab — "
                          f"{self._keys_label('new_tab')} opens another")
            return
        self.select_tab(side, self.pm.tab_index[side] + delta)

    def select_tab(self, side: str, index: int) -> None:
        """Show tab ``index`` of ``side`` (wrapping), and make that pane
        active — what a click on a tab means."""
        self.pm.active_pane = side
        self._sync_active()
        if index % len(self.pm.tabs[side]) == self.pm.tab_index[side]:
            return
        self._remember_cursor(self.pane(side))
        self.pm.select_tab(side, index)
        self._show_tab(side)

    def _show_tab(self, side: str, *, focus: str | None = None) -> None:
        """Put ``side``'s current tab on screen.

        A directory tab is re-read on the way in, keeping its rows on screen
        while it is (a monitor reload's ``keep_visible``): its directory went
        unwatched while hidden, and a file operation in the other pane may
        have changed it. A tab never listed yet — a new one, or one restored
        from the last session — is listed like a navigation. A virtual tab is
        re-read only if something asked it to be while it was hidden (see
        :meth:`_hold_if_hidden`); otherwise it is shown as it was left."""
        pane = self.pane(side)
        view = self.left_view if side == "left" else self.right_view
        view.pane = pane
        stale = pane.pop("_stale", False)
        if pane.get("virtual"):
            if stale or pane.get("_load_pending"):
                self._relist(pane)
            return
        if pane.get("_listing_entries") is None and not pane.get("files"):
            def landed(p: dict) -> None:
                if focus is not None:
                    self._select_by_name(p, focus)
                else:
                    self._restore_remembered_cursor(p)

            self._refresh(pane, on_ready=landed)
            return
        anchor = self._cursor_anchor(pane)
        self._list_pane(side, keep_visible=True,
                        on_ready=lambda p: self._apply_cursor_anchor(p, anchor))

    def _save_tabs(self) -> None:
        """Every pane's tabs — path, sort, filter — and which is current, for
        the next session. A virtual tab is saved as its directory."""
        for side in ("left", "right"):
            tabs = [{"path": str(t["path"]), "sort_mode": t["sort_mode"],
                     "sort_reverse": t["sort_reverse"],
                     "layout": t.get("layout"),
                     "extras": dict(t.get("extras") or {}),
                     "filter_pattern": t.get("filter_pattern", "")}
                    for t in self.pm.tabs[side]]
            self.state_manager.set_state(
                f"tabs.{side}", {"active": self.pm.tab_index[side], "tabs": tabs})

    def _restore_tabs(self, side: str, cmdline_provided: bool) -> None:
        """Rebuild ``side``'s saved tabs around its current one, which
        :meth:`_restore_one_pane` already restored. Nothing is read here: the
        others are listed the first time they are shown, so a tab on a remote
        host does not connect at startup. A pane opened on a directory from the
        command line opens that alone."""
        if cmdline_provided:
            return
        saved = self.state_manager.get_state(f"tabs.{side}", None)
        if not isinstance(saved, dict):
            return
        entries = saved.get("tabs")
        active = saved.get("active", 0)
        if (not isinstance(entries, list) or len(entries) < 2
                or not isinstance(active, int) or not 0 <= active < len(entries)):
            return
        current = self.pane(side)
        tabs = []
        for i, entry in enumerate(entries):
            if i == active:
                tabs.append(current)
                continue
            try:
                tab = self.pm.new_pane(Path(entry["path"]), like=current)
            except Exception:  # noqa: BLE001 — a bad entry costs that tab only
                continue
            mode = sort_keys.canonical(entry.get("sort_mode", tab["sort_mode"]))
            if sort_keys.is_known(mode):
                tab["sort_mode"] = mode
            tab["sort_reverse"] = bool(entry.get("sort_reverse", tab["sort_reverse"]))
            layout = entry.get("layout")
            tab["layout"] = layout if isinstance(layout, str) else None
            tab["extras"] = self._saved_extras(entry.get("extras"))
            tab["filter_pattern"] = entry.get("filter_pattern", "") or ""
            tabs.append(tab)
        self.pm.tabs[side] = tabs
        self.pm.tab_index[side] = next(i for i, t in enumerate(tabs) if t is current)

    # --- menus & dialogs -----------------------------------------------------

    def _build_menu(self) -> Menu:
        """The app menu model — one tree, realized as the macOS menu bar or an
        in-window strip. Items reuse the same callbacks the keymap and context
        menu drive, and ``checked``/``enabled`` predicates re-evaluate on open so
        the menu always mirrors live pane state."""
        def has_files() -> bool:
            return bool(self.active_pane()["files"])

        def has_log_selection() -> bool:
            return bool(self.log.selection_text())

        def has_log_lines() -> bool:
            return bool(self.log.lines)

        # Shortcut hints are derived from the live keymap (§2.3) so menu labels
        # track user rebindings instead of drifting from hardcoded strings.
        sc = self._menu_shortcut
        sort_menu = self._sort_menu()

        tabs_open = lambda: len(self.pm.tabs[self.pm.active_pane]) > 1  # noqa: E731
        file_menu = Menu(
            MenuItem("Open", on_select=lambda: self._menu("open_item"),
                     enabled=has_files, shortcut=sc("open_item")),
            # Which program opens it — XeFM's viewer, the text editor, the
            # system's choice — one level down: Open itself (Enter) is the one
            # reached for most, and File has to fit 23 rows with room for
            # MENU_ITEMS.
            MenuItem("Open With", submenu=Menu(
                MenuItem("Viewer", on_select=self.view_file,
                         enabled=has_files, shortcut=sc("view_file")),
                MenuItem("Text Editor", on_select=self.edit_file,
                         enabled=has_files, shortcut=sc("edit_file")),
                MenuItem("Default App", on_select=self.open_with_os,
                         enabled=has_files, shortcut=sc("open_with_os")),
                MenuItem("Choose App…", on_select=self.open_with,
                         enabled=has_files, shortcut=sc("open_with")),
                title="Open With")),
            MenuItem("Details…", on_select=self.file_details, enabled=has_files,
                     shortcut=sc("file_details")),
            MenuItem("Reveal in File Manager", on_select=self.reveal_in_os,
                     enabled=has_files, shortcut=sc("reveal_in_os")),
            SEPARATOR,
            MenuItem("New Folder…", on_select=self.create_directory, shortcut=sc("create_directory")),
            MenuItem("New File…", on_select=self.create_file, shortcut=sc("create_file")),
            MenuItem("Rename", submenu=Menu(
                MenuItem("Rename…", on_select=self.rename, enabled=has_files,
                         shortcut=sc("rename")),
                MenuItem("Rename in Editor…", on_select=self.rename_in_editor,
                         enabled=has_files, shortcut=sc("rename_in_editor")),
                title="Rename")),
            MenuItem("Duplicate", on_select=self.duplicate_files,
                     enabled=has_files, shortcut=sc("duplicate_files")),
            MenuItem("Copy to Other Pane", on_select=self.copy_files,
                     enabled=has_files, shortcut=sc("copy_files")),
            MenuItem("Move to Other Pane", on_select=self.move_files,
                     enabled=has_files, shortcut=sc("move_files")),
            MenuItem("Copy to…", on_select=self.copy_files_to,
                     enabled=has_files, shortcut=sc("copy_files_to")),
            MenuItem("Move to…", on_select=self.move_files_to,
                     enabled=has_files, shortcut=sc("move_files_to")),
            MenuItem(f"Move to {trash.NAME}…", on_select=self.delete_files,
                     enabled=has_files, shortcut=sc("delete_files")),
            MenuItem("Delete Permanently…", on_select=self.delete_permanently,
                     enabled=has_files, shortcut=sc("delete_permanently")),
            MenuItem("Archive", submenu=Menu(
                MenuItem("Create…", on_select=self.create_archive,
                         enabled=has_files, shortcut=sc("create_archive")),
                MenuItem("Extract…", on_select=self.extract_archive,
                         enabled=has_files, shortcut=sc("extract_archive")),
                title="Archive")),
            *self._user_menu_items("file"),
            SEPARATOR,
            MenuItem("Quit", on_select=self.confirm_quit, shortcut=sc("quit")),
            title="File",
        )
        # Everything that ends on the clipboard, in the menu users look in for
        # it: the file-name / path copies that used to sit in File, and the log
        # pane's own two (#360). The log items need a menu more than most —
        # a log selection is made with the mouse, and "Copy All Logs" ships
        # unbound — so this is where that feature is discovered at all.
        #
        # All four go through _menu (dispatch + render) rather than the bare
        # method: their only feedback is a log line, and a native menu
        # activation renders nothing on its own, so the line would sit
        # unpainted until the next event (#253).
        edit_menu = Menu(
            MenuItem("Copy", on_select=lambda: self._menu("clipboard_copy"),
                     enabled=has_files, shortcut=sc("clipboard_copy")),
            MenuItem("Cut", on_select=lambda: self._menu("clipboard_cut"),
                     enabled=has_files, shortcut=sc("clipboard_cut")),
            MenuItem("Paste", on_select=lambda: self._menu("clipboard_paste"),
                     enabled=lambda: self.clipboard.contents() is not None,
                     shortcut=sc("clipboard_paste")),
            MenuItem("Show Clipboard…", on_select=lambda: self._menu("clipboard_show"),
                     shortcut=sc("clipboard_show")),
            MenuItem("Clear Clipboard", on_select=lambda: self._menu("clipboard_clear"),
                     enabled=lambda: bool(self.clipboard.paths),
                     shortcut=sc("clipboard_clear")),
            SEPARATOR,
            MenuItem("Copy Name(s)", on_select=lambda: self._menu("copy_names"),
                     enabled=has_files, shortcut=sc("copy_names")),
            MenuItem("Copy Full Path(s)", on_select=lambda: self._menu("copy_paths"),
                     enabled=has_files, shortcut=sc("copy_paths")),
            SEPARATOR,
            MenuItem("Copy Log Selection",
                     on_select=lambda: self._menu("copy_log_selection"),
                     enabled=has_log_selection, shortcut=sc("copy_log_selection")),
            MenuItem("Copy All Logs", on_select=lambda: self._menu("copy_log_all"),
                     enabled=has_log_lines, shortcut=sc("copy_log_all")),
            title="Edit",
        )
        go_menu = Menu(
            MenuItem("Parent Directory", on_select=lambda: self._menu("go_parent"),
                     shortcut=sc("go_parent")),
            MenuItem("Root Directory", on_select=lambda: self._menu("go_root"),
                     shortcut=sc("go_root")),
            MenuItem("Go to Favorite…", on_select=self.show_favorites, shortcut=sc("favorites")),
            MenuItem("Add to Favorites…", on_select=self.add_favorite,
                     shortcut=sc("add_favorite")),
            MenuItem("Jump to Path…", on_select=self.jump_to_path, shortcut=sc("jump_to_path")),
            MenuItem("Drives…", on_select=self.show_drives, shortcut=sc("drives")),
            MenuItem("Connect to Server…", on_select=self.show_connect_server,
                     shortcut=sc("connect_server"),
                     # The cheap platform test rather than
                     # ``netmount.is_supported()``: this predicate runs while
                     # the menu is built, and the real check loads a system
                     # framework the user may never need. The action itself
                     # asks properly, and says so if the answer is no.
                     enabled=lambda: platform.system() in ("Darwin", "Windows")),
            MenuItem("History…", on_select=self.show_history, shortcut=sc("history")),
            MenuItem("Back", on_select=self.go_back, shortcut=sc("go_back")),
            MenuItem("Forward", on_select=self.go_forward, shortcut=sc("go_forward")),
            SEPARATOR,
            # Folder tabs (#563), per pane, all five together. Not in File,
            # where Finder and the browsers open and close theirs: File is the
            # longest menu, and three more rows took it past the 23 rows an
            # 80x24 terminal has under the bar, so its pulldown covered the bar.
            # Switching panes heads the group: it moves between the two
            # panes as the tab items move within one.
            MenuItem("Switch Pane", on_select=lambda: self._menu("switch_pane"),
                     shortcut=sc("switch_pane")),
            MenuItem("New Tab", on_select=lambda: self._menu("new_tab"),
                     shortcut=sc("new_tab")),
            MenuItem("Open in New Tab", on_select=lambda: self._menu("open_in_new_tab"),
                     enabled=has_files, shortcut=sc("open_in_new_tab")),
            MenuItem("Close Tab", on_select=lambda: self._menu("close_tab"),
                     enabled=tabs_open, shortcut=sc("close_tab")),
            MenuItem("Next Tab", on_select=lambda: self._menu("next_tab"),
                     enabled=tabs_open, shortcut=sc("next_tab")),
            MenuItem("Previous Tab", on_select=lambda: self._menu("prev_tab"),
                     enabled=tabs_open, shortcut=sc("prev_tab")),
            SEPARATOR,
            # A list of paths in place of a directory (#453): where the pane
            # goes, like everything above, and left again with Parent
            # Directory. One submenu for the three sources rather than three
            # rows each starting "Open List from".
            MenuItem("Open List", submenu=Menu(
                MenuItem("From Clipboard",
                         on_select=lambda: self._menu("open_list_from_clipboard"),
                         shortcut=sc("open_list_from_clipboard")),
                MenuItem("From Command…", on_select=self.open_list_from_command,
                         shortcut=sc("open_list_from_command")),
                MenuItem("From File",
                         on_select=lambda: self._menu("open_list_from_file"),
                         enabled=has_files, shortcut=sc("open_list_from_file")),
            )),
            title="Go",
        )
        tools_menu = Menu(
            MenuItem("Command Palette…", on_select=self.show_command_palette,
                     shortcut=sc("command_palette")),
            SEPARATOR,
            # The jobs list beside the longest job that lands in it.
            MenuItem("Background Jobs…", on_select=self.show_jobs,
                     enabled=lambda: bool(self.tasks.background_tasks()),
                     shortcut=sc("jobs")),
            MenuItem("Find Similar Files…", on_select=self.find_similar,
                     shortcut=sc("find_similar")),
            MenuItem("External Programs…", on_select=self.show_programs, shortcut=sc("programs")),
            MenuItem("Subshell Here", on_select=self.subshell, shortcut=sc("subshell")),
            SEPARATOR,
            # Editing the config and reloading it are the loop a user tuning
            # XeFM goes round, so they stay at the top. What is set up once or
            # now and then — the keymap, extensions, Python packages — waits
            # one level down.
            MenuItem("Edit Configuration…", on_select=self.edit_config,
                     shortcut=sc("edit_config")),
            MenuItem("Reload Configuration", on_select=self.reload_config,
                     shortcut=sc("reload_config")),
            MenuItem("Advanced", submenu=Menu(
                # A preset is how the keys work, not how things look, so it
                # sits with the configuration rather than the theme.
                # The presets' names say little alone; the dialog shows what
                # each one does.
                MenuItem("Keymap…", on_select=self.choose_keymap,
                         shortcut=sc("choose_keymap")),
                SEPARATOR,
                MenuItem("Extensions…", on_select=self.show_extensions,
                         shortcut=sc("extensions")),
                MenuItem("Check for Extension Updates…",
                         on_select=self.check_extension_updates,
                         enabled=lambda: not self._ext_updates_busy,
                         shortcut=sc("check_extension_updates")),
                MenuItem("Install Extension…", on_select=self.install_extension,
                         enabled=lambda: not self._ext_fetch_busy,
                         shortcut=sc("install_extension")),
                MenuItem("Sync Python Packages", on_select=self.sync_python_packages,
                         enabled=lambda: not self._python_packages_syncing,
                         shortcut=sc("sync_python_packages")),
            )),
            title="Tools",
        )
        select_menu = Menu(
            MenuItem("Toggle Selection", on_select=lambda: self._menu("toggle_select_down"),
                     enabled=has_files, shortcut=sc("toggle_select_down")),
            MenuItem("Select to Cursor", on_select=lambda: self._menu("select_range"),
                     enabled=lambda: bool(self.active_pane()["selected_files"]),
                     shortcut=sc("select_range")),
            MenuItem("Select All Items", on_select=lambda: self._menu("select_all"),
                     shortcut=sc("select_all")),
            MenuItem("Clear Selection", on_select=lambda: self._menu("unselect_all"),
                     enabled=lambda: bool(self.active_pane()["selected_files"]),
                     shortcut=sc("unselect_all")),
            MenuItem("Select by Pattern…", on_select=lambda: self._menu("select_by_pattern"),
                     enabled=has_files, shortcut=sc("select_by_pattern")),
            MenuItem("Unselect by Pattern…", on_select=lambda: self._menu("unselect_by_pattern"),
                     enabled=lambda: bool(self.active_pane()["selected_files"]),
                     shortcut=sc("unselect_by_pattern")),
            MenuItem("Select Same Extension",
                     on_select=lambda: self._menu("select_same_extension"),
                     enabled=has_files, shortcut=sc("select_same_extension")),
            MenuItem("Compare and Select…", on_select=self.compare_selection,
                     enabled=has_files, shortcut=sc("compare_selection")),
            SEPARATOR,
            MenuItem("Compare Selected Files…", on_select=self.diff_files, shortcut=sc("diff_files")),
            MenuItem("Compare Directories…", on_select=self.diff_directories,
                     shortcut=sc("diff_directories")),
            title="Select",
        )
        view_menu = Menu(
            MenuItem("Find…", on_select=self.enter_isearch, enabled=has_files, shortcut=sc("isearch")),
            MenuItem("Filter…", on_select=self.enter_filter, shortcut=sc("filter")),
            MenuItem("Search Files…", on_select=self.show_search, shortcut=sc("find_files")),
            MenuItem("Search Content…", on_select=self.show_content_search, shortcut=sc("find_in_files")),
            # The OS index (#579): named for what it is on this platform.
            MenuItem(f"Search {os_index.engine() or 'Index'}…",
                     on_select=lambda: self._menu("index_search"),
                     enabled=lambda: os_index.engine() is not None,
                     shortcut=sc("index_search")),
            MenuItem("Search Tags…", on_select=lambda: self._menu("find_by_tag"),
                     enabled=lambda: tags.store_for(self.active_pane()["path"]) is not None,
                     shortcut=sc("find_by_tag")),
            SEPARATOR,
            MenuItem("Reread", on_select=lambda: self._menu("reread"),
                     shortcut=sc("reread")),
            MenuItem("Show Hidden Files", on_select=lambda: self._menu("toggle_hidden"),
                     checked=lambda: self.flm.show_hidden, shortcut=sc("toggle_hidden")),
            MenuItem("Layout", submenu=self._layout_menu()),
            MenuItem("Show", submenu=self._extras_menu()),
            MenuItem("Resolve Attribute…", on_select=lambda: self._menu("resolve_attribute"),
                     enabled=has_files, shortcut=sc("resolve_attribute")),
            MenuItem("Sort By", submenu=sort_menu),
            SEPARATOR,
            MenuItem("Theme", submenu=self._theme_menu(sc)),
            SEPARATOR,
            MenuItem("Quick View", on_select=lambda: self._menu("quick_view"),
                     checked=lambda: self._quick_view is not None,
                     shortcut=sc("quick_view")),
            # How the folder is shown, not where the pane goes: beside Quick
            # View rather than in Go.
            MenuItem("Flat View", on_select=lambda: self._menu("flat_view"),
                     checked=lambda: (self.active_pane().get("virtual") or {})
                     .get("kind") == "flat",
                     shortcut=sc("flat_view")),
            title="View",
        )
        help_menu = Menu(
            MenuItem("Keyboard Shortcuts…", on_select=self.show_help, shortcut=sc("help")),
            MenuItem("Tip of the Day…", on_select=self.show_tips),
            SEPARATOR,
            MenuItem("About XeFM", on_select=self.show_about),
            title="Help",
        )
        return Menu(
            MenuItem("File", submenu=file_menu),
            MenuItem("Edit", submenu=edit_menu),
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

    def _user_menu_items(self, menu: str) -> list:
        """The config's and the extensions' ``MENU_ITEMS`` for ``menu``
        (#632), as a group of their own behind a separator — nothing when
        there are none, and a Custom submenu when there are more than
        ``_USER_MENU_INLINE``. Each runs its action as a key bound to it would, and
        shows the key when one is."""
        items = []
        for entry in user_menu_items(menu):
            items.append(MenuItem(
                entry.label, on_select=lambda name=entry.action: self._menu(name),
                enabled=self._menu_condition(entry.when),
                shortcut=self._menu_shortcut(entry.action)))
        if len(items) > self._USER_MENU_INLINE:
            # More than a few would push the menu past what a terminal shows
            # (File is near its 23 rows), so they gather one level down.
            items = [MenuItem("Custom", submenu=Menu(*items, title="Custom"))]
        return [SEPARATOR, *items] if items else []

    #: How many MENU_ITEMS a menu lists inline before they go under Custom ▸.
    _USER_MENU_INLINE = 3

    def _menu_condition(self, when: str):
        """A ``MENU_ITEMS`` ``when`` as the predicate a MenuItem re-evaluates
        on open (see :data:`xefm.user_api.MENU_WHEN`)."""
        if when == "entry":
            return lambda: self._focused_entry() is not None
        if when == "selection":
            return lambda: bool(self.active_pane()["selected_files"])
        return True

    def _menu_shortcut(self, action: str) -> str | None:
        """The display-formatted first key bound to ``action`` for a MenuItem
        shortcut hint, or ``None`` when unbound — so menu labels track the live
        keymap (and user rebindings) instead of hardcoded strings.

        Resolved in the ``filer`` context (every menu item dispatches a file-list
        action), which is what makes the hint right for a name the user's config
        never mentions: the flat lookup reads ``KEY_BINDINGS`` alone and would
        show nothing at all for an action added after that config was written."""
        keys, _ = self.keys.get_keys_for_action(action, _ctx.FILER)
        return self.keys.format_key_for_display(keys[0]) if keys else None

    def _focused_entry(self):
        """The entry under the cursor in the active pane, or None if empty."""
        pane = self.active_pane()
        files = pane["files"]
        if not files:
            return None
        return files[pane["focused_index"]]

    @classmethod
    def _is_local(cls, path) -> bool:
        """Whether ``path`` is a plain local-filesystem path — the only kind a
        terminal editor or subshell can operate on directly.

        Which prefixes are not is :mod:`xefm.path_schemes`' business. Keeping a
        second copy here is how ``reg://`` used to reach Jump to Path as a
        *relative* path and come back "does not exist"."""
        return not path_schemes.is_uri(str(path))

    @staticmethod
    def _is_archive(path) -> bool:
        """Whether ``path`` is inside a browsed archive (an ``archive://`` URI).
        Such paths are read-only, so write-side operations refuse them."""
        return str(path).startswith("archive://")

    def _run_in_terminal(self, argv: list, cwd: str | None = None,
                         env: dict | None = None,
                         pause_on_error: bool = False) -> int | None:
        """Run a full-screen child process (editor / shell) with the display
        handed over via ``backend.suspended()``, then refresh both panes and
        repaint — the child may have changed files while we were away. With
        ``pause_on_error``, a nonzero exit holds the terminal until Enter, so
        the child's parting error output stays readable before the repaint
        wipes it. Returns the child's exit code, or ``None`` when it could not
        be started."""
        from xefm.external_programs import resolve_command
        result = None
        try:
            with self._terminal_suspended():
                result = subprocess.run(resolve_command(argv, env),
                                        cwd=cwd, env=env)
                if pause_on_error and result.returncode != 0:
                    # sys.stdout is captured into the log pane; the prompt must
                    # reach the real tty the child just wrote its errors to.
                    print(f"\n{argv[0]} exited with code {result.returncode}"
                          " - press Enter to return to XeFM",
                          file=sys.__stdout__)
                    input()
        except FileNotFoundError:
            self.log_info(f"Command not found: {argv[0]}")
        except Exception as exc:
            self.log_info(f"Command failed: {exc}")
        return result.returncode if result is not None else None

    @contextlib.contextmanager
    def _terminal_suspended(self):
        """Hand the terminal to whatever runs inside, then take it back: the
        backend's ``suspended()``, and on the way out — an exception included —
        both panes re-read and a repaint, since the child may have changed files
        while we were away. Shared by :meth:`_run_in_terminal` and
        ``ctx.terminal_backend_suspended()`` (#755).

        Not reentrant: a second hand-over while the terminal is already handed
        over is a RuntimeError — there is nothing left to hand."""
        if self._terminal_handed_over:
            raise RuntimeError("the terminal is already handed over")
        self._terminal_handed_over = True
        try:
            with self.backend.suspended():
                yield
        finally:
            self._terminal_handed_over = False
            self._relist(self.pm.left_pane)
            self._relist(self.pm.right_pane)
            self.panel.render()

    def _open_terminal(self, argv: list, *, cwd: str | None, env: dict,
                       pause_on_error: bool = False) -> bool:
        """Desktop mode's stand-in for :meth:`_run_in_terminal`: open the
        ``TERMINAL`` application running ``argv`` and return at once (see
        :mod:`xefm.external_terminal`). Returns False — having logged why —
        when no terminal could be opened."""
        from xefm.external_terminal import (NoTerminalError, launch_in_terminal,
                                           terminal_command)
        terminal = terminal_command(self.config)
        try:
            launch_in_terminal(terminal, argv, cwd=cwd, env=env,
                               pause_on_error=pause_on_error)
        except NoTerminalError:
            self.log_info("No terminal configured: set TERMINAL in "
                          "~/.xefm/config.py")
            return False
        except FileNotFoundError:
            self.log_info(f"Terminal not found: {terminal[0]}")
            return False
        except Exception as exc:
            self.log_info(f"Could not open a terminal: {exc}")
            return False
        return True

    def _launch_associated(self, entries, command: list) -> bool:
        """Run the FILE_ASSOCIATIONS program ``command`` on ``entries`` — one
        launch, with every path appended to the argv.

        Whether to hand over the display is a property of *our backend*, not of
        the program, so associations do not describe it:

        * Terminal mode — the child shares our tty, so we suspend the TUI, wait
          for it, and restore. Correct for ``less``/``vim``; a launcher like
          ``open -a`` merely returns straight away and we repaint.
        * Desktop mode — there is no tty to hand over and blocking would freeze
          the window, so the child is detached and we keep running.

        Returns False — having logged why — when the program could not be run,
        so callers can fall back to their built-in behavior rather than leaving
        the key press doing nothing. An external program needs a real path on
        disk, so remote and in-archive entries always take that fallback.
        """
        for entry in entries:
            if not self._is_local(entry):
                self.log_info(f"{entry.name}: external programs need a local file")
                return False
        argv = list(command) + [str(e) for e in entries]
        if not is_desktop_mode():
            self._run_in_terminal(argv)
            return True
        return self._spawn_detached(argv, self._files_label(entries))

    def _spawn_detached(self, argv: list, subject: str) -> bool:
        """Desktop mode's launch for a program with a window of its own: start
        it and return at once, never waiting for it to exit — the UI thread is
        ours, and waiting would freeze the window. Returns False, having logged
        why, when it could not be started."""
        from xefm.external_programs import resolve_command
        try:
            subprocess.Popen(resolve_command(argv))
        except FileNotFoundError:
            self.log_info(f"Command not found: {argv[0]}")
            return False
        except Exception as exc:
            self.log_info(f"Failed to open {subject}: {exc}")
            return False
        return True

    def _run_editor(self, argv: list, subject: str) -> bool:
        """Run ``TEXT_EDITOR`` (``argv`` already carries the paths) the way our
        backend calls for (#644): in terminal mode it gets the tty and we wait
        for it, as with any full-screen child; in desktop mode it is detached
        like a FILE_ASSOCIATIONS launch, so an editor told to wait for the file
        to close (``code --wait``, ``subl -w``) cannot freeze the window.
        Nothing in desktop mode relies on the editor having exited — config
        reload, rename and remote upload all wait for saves instead. Returns
        whether the editor was started. A desktop launch does not repaint on
        success: the caller logs what happened first, then repaints, or its
        line would wait for some later repaint to appear."""
        if not is_desktop_mode():
            return self._run_in_terminal(argv) is not None
        launched = self._spawn_detached(argv, subject)
        if not launched:
            self.panel.render()
        return launched

    @staticmethod
    def _files_label(entries) -> str:
        """A log-message subject for a batch of entries: the file's name for
        one, a count for several."""
        return entries[0].name if len(entries) == 1 else f"{len(entries)} files"

    def _editor_argv(self) -> list:
        """The configured ``TEXT_EDITOR`` as an argv list — a string command
        line (``'code --wait'``) or a list already in argv form
        (``['wt', 'nt', 'vim']``), both of which the config template offers.
        Empty when the setting is unset; see :func:`command_argv` for why we
        do not hand that straight to shlex."""
        from xefm.external_programs import command_argv
        return command_argv(getattr(self.config, "TEXT_EDITOR", "vim"))

    def edit_file(self) -> None:
        """Open the selected files — or the focused file when nothing is
        selected — for editing (#273). See :meth:`_edit_entries`."""
        targets = [_real_entry(t) for t in self._selected_or_focused(self.active_pane())]
        self._edit_entries([t for t in targets if t is not None])

    def _edit_entries(self, targets: list) -> None:
        """Open ``targets`` for editing — the ``edit_file`` machinery, shared
        by the file list and the text viewer (which passes the viewed file as
        the single target).

        Per file, a matching ``edit`` entry in FILE_ASSOCIATIONS wins;
        otherwise the configured ``TEXT_EDITOR`` gets the terminal via
        suspend/resume. Files resolving to the same program are handed to it
        in one launch (``vim a b``), so a multi-file edit is one editor
        session, not a chain of them. An association set explicitly to
        ``None`` means "no editor for this kind of file" and is honored rather
        than falling back. Directories are skipped. A remote file is edited
        through a local copy that is uploaded on each save
        (:meth:`_edit_remote`); one in an archive or another read-only place is
        skipped with a note."""
        files = []
        remote = []
        for entry in targets:
            if not self._is_local(entry):
                if self._is_archive(entry) or not can_write_back(entry):
                    self.log_info(f"{entry.name}: read-only here — copy it out "
                                  "to edit it")
                else:
                    remote.append(entry)
                continue
            try:
                if entry.is_dir():
                    self.log_info(f"{entry.name} is a directory")
                    continue
            except Exception:
                pass
            files.append(entry)
        if remote:
            self._edit_remote(remote)
        if not files:
            return
        # Resolve each file's editor, batching files that share one. A failed
        # associated launch falls back to TEXT_EDITOR, as it always has.
        fallback: list = []
        groups: dict[tuple, list] = {}
        for entry in files:
            command = get_program_for_file(entry.name, "edit")
            if command:
                groups.setdefault(tuple(command), []).append(entry)
            elif has_explicit_association(entry.name, "edit"):
                # Explicitly None: the config says this type has no editor (a
                # PDF, say). Falling back to TEXT_EDITOR would ignore that on
                # purpose.
                self.log_info(f"No editor configured for {entry.name}")
            else:
                fallback.append(entry)
        # Terminal mode logs once the editor is done; a desktop launch returns
        # at once, before anything is edited, so it says what it did instead.
        desktop = is_desktop_mode()
        for command, batch in groups.items():
            if self._launch_associated(batch, list(command)):
                verb = "Opened" if desktop else "Edited"
                self.log_info(f"{verb} {self._files_label(batch)} with {command[0]}")
            else:
                fallback.extend(batch)
        if fallback:
            argv = self._editor_argv()
            if not argv:
                self.log_info("No editor configured: set TEXT_EDITOR in "
                              "~/.xefm/config.py")
                self.panel.render()
                return
            label = self._files_label(fallback)
            if self._run_editor(argv + [str(e) for e in fallback], label):
                self.log_info(f"Opened {label} in {argv[0]}" if desktop
                              else f"Edited {label}")
        self.panel.render()

    # --- edit anywhere (#581) ---------------------------------------------------

    #: Seconds between looks at the edited copies of remote files.
    _EDIT_POLL_SECONDS = 1.0

    @property
    def edit_sessions(self) -> EditSessions:
        sessions = getattr(self, "_edit_sessions", None)
        if sessions is None:
            sessions = self._edit_sessions = EditSessions(
                config_manager.config_dir / "edit")
        return sessions

    def _edit_remote(self, entries: list) -> None:
        """Edit remote ``entries`` through local copies: download them (a task —
        the remote may be slow), open the copies with the ordinary editor
        machinery, and from then on upload each copy whenever it is saved
        (:meth:`_poll_edit_sessions`). Skipping the directories happens here,
        on the worker, because asking a remote is a round trip."""
        sessions = self.edit_sessions
        task = Task("Downloading for edit", config=self.config, kind="edit_download")

        def run(t: Task) -> dict:
            opened, failed = [], []
            for entry in entries:
                t.checkpoint()
                try:
                    if entry.is_dir():
                        failed.append(f"{entry.name} is a directory")
                        continue
                    opened.append(sessions.open(entry))
                except Exception as exc:
                    failed.append(f"{entry.name}: {exc}")
            return {"opened": opened, "failed": failed, "cancelled": t.cancelled()}

        def on_done(res: dict) -> None:
            for message in res.get("failed", []):
                self.log_info(f"Could not open for editing: {message}")
            opened = res.get("opened", [])
            if not opened:
                self.panel.render()
                return
            for session in opened:
                self.log_info(f"Editing {session.remote} — saves are uploaded "
                              f"from {session.local}")
            self._edit_entries([Path(str(s.local)) for s in opened])
            # A terminal editor has returned by now, so its saves are already on
            # disk: send them without waiting for the next poll.
            self._poll_edit_sessions(reschedule=False)
            self._schedule_edit_poll()

        self.tasks.submit(task, self.panel, run=run, on_done=on_done)

    def _schedule_edit_poll(self) -> None:
        """Keep one poll timer running while any edit session lives."""
        if getattr(self, "_edit_poll_cancel", None) is not None:
            return
        if not len(self.edit_sessions):
            return
        self._edit_poll_cancel = self.panel.call_later(
            self._EDIT_POLL_SECONDS, self._poll_edit_sessions)

    def _poll_edit_sessions(self, reschedule: bool = True) -> None:
        """Upload the copies saved since the last look. One upload task at a
        time: while another task owns the screen the saves wait for the next
        poll — they are found again, since an unsent copy stays pending."""
        if reschedule:
            self._edit_poll_cancel = None
        if self.tasks.has_active():
            if reschedule:
                self._schedule_edit_poll()
            return
        saved = self.edit_sessions.saved()
        if saved:
            self._upload_edits(saved)
        if reschedule:
            self._schedule_edit_poll()

    def _upload_edits(self, sessions: list) -> None:
        """Send saved copies back, asking first about any whose remote file
        changed since it was downloaded or last uploaded. Failures are loud — a
        message box naming the copy that still holds the edit — because a quiet
        one would lose the user's work the moment they stopped looking."""
        manager = self.edit_sessions
        task = Task("Uploading edit", config=self.config, kind="edit_upload")

        def ask_overwrite(session):
            def show(panel, deliver):
                show_message_box(
                    panel,
                    f"{session.remote}\n\nchanged on the server since you "
                    "opened it. Overwrite it with your edit?\n\nYour edit "
                    f"stays in {session.local} either way.",
                    title="Remote file changed", icon="warning",
                    buttons=("Overwrite", "Keep Remote"), default=1, cancel=1,
                    on_result=lambda label: deliver(label == "Overwrite"))
            return show

        def run(t: Task) -> dict:
            sent, kept = [], []
            for session in sessions:
                t.checkpoint()
                try:
                    try:
                        manager.upload(session)
                    except RemoteChanged:
                        if not t.ask(ask_overwrite(session), headless=False):
                            session.error = "the remote file changed; not overwritten"
                            kept.append(session)
                            continue
                        manager.upload(session, force=True)
                    sent.append(session)
                except Cancelled:
                    raise
                except Exception as exc:
                    session.error = str(exc)
                    kept.append(session)
            return {"sent": sent, "kept": kept, "cancelled": t.cancelled()}

        def on_done(res: dict) -> None:
            for session in res.get("sent", []):
                self.log_info(f"Uploaded {session.remote}")
                self._relist_showing(session.remote)
            kept = res.get("kept", [])
            for session in kept:
                self.log_info(f"Upload of {session.remote} failed: "
                                  f"{session.error}; the edit is kept in "
                                  f"{session.local}")
            if kept:
                body = "\n\n".join(f"{s.remote}: {s.error}\nYour edit is in "
                                    f"{s.local}" for s in kept)
                show_message_box(self.panel, body, title="Not uploaded",
                                 icon="error")
            self.panel.render()

        self.tasks.submit(task, self.panel, run=run, on_done=on_done)

    def _relist_showing(self, path) -> None:
        """Re-read each pane that lists ``path``'s directory, so an upload's new
        size and time show without waiting out a remote listing cache."""
        parent = str(path.parent)
        for pane in (self.pm.left_pane, self.pm.right_pane):
            if str(pane["path"]) == parent:
                self._relist(pane)

    def _close_edit_sessions(self) -> None:
        """End every edit session at exit: copies the remote already matches are
        removed; a copy holding an unsent edit stays, and the log says where."""
        sessions = getattr(self, "_edit_sessions", None)
        if sessions is None:
            return
        for session in sessions.close_all():
            self.log_info(f"Unsent edit of {session.remote} kept in "
                                f"{session.local}")

    def subshell(self) -> None:
        """Drop to an interactive shell in the active pane's directory. In
        terminal mode the terminal is handed over via suspend/resume and the
        panes refresh on return; in desktop mode the shell opens in the
        ``TERMINAL`` application instead (#472) and XeFM carries on — file
        monitoring stands in for the refresh. Local directories only. The
        shell is ``SUBSHELL`` from the config,
        falling back to ``$SHELL`` and then the platform default (cmd.exe on
        Windows, ``/bin/sh`` elsewhere) — see :func:`_subshell_command`. The
        shell gets the ``XEFM_*`` variables (pane directories, selections,
        ``XEFM_ACTIVE``) and a best-effort ``[XeFM]`` prefix on the prompt
        variable that *that* shell reads — ``PS1``/``PROMPT`` for a POSIX shell,
        cmd.exe's ``$``-code ``PROMPT`` for cmd.exe, nothing for PowerShell."""
        from xefm.external_programs import (build_xefm_env,
                                           ensure_common_paths_in_env,
                                           prefix_prompt_markers)
        path = self.active_pane()["path"]
        if not self._is_local(path):
            self.log_info("Subshell is only available for local directories")
            return
        command = _subshell_command(self.config)
        env = os.environ.copy()
        ensure_common_paths_in_env(env)
        env.update(build_xefm_env(self.pm.left_pane, self.pm.right_pane,
                                  self.pm.get_current_pane(),
                                  self.pm.get_inactive_pane()))
        prefix_prompt_markers(env, command)
        if is_desktop_mode():
            if self._open_terminal(command, cwd=str(path), env=env):
                self.log_info(f"Opened a terminal in {path}")
            self.panel.render()
            return
        self.log_info(f"Subshell in {path} — exit the shell to return")
        self._run_in_terminal(command, cwd=str(path), env=env)

    def edit_config(self) -> None:
        """Open the user's ``~/.xefm/config.py`` in the configured editor
        (``TEXT_EDITOR``), creating it from the template on first use.

        In terminal mode the editor takes over the terminal and blocks, so we
        reload on return (see :meth:`reload_config`). In GUI mode the editor is
        detached into a window of its own (:meth:`_run_editor`) and we return
        before any edit is saved, so auto-reloading here would be premature. We
        leave it to the user to apply changes via Tools ▸ Reload Configuration
        once saved."""
        path = config_manager.config_file
        if not path.exists():
            if config_manager.create_default_config():
                self.log_info(f"Created default config at {path}")
            else:
                self.log_info(f"Could not create config file at {path}")
                return
        argv = self._editor_argv()
        if not argv:
            self.log_info(f"No editor configured: set TEXT_EDITOR in {path}")
            return
        if not self._run_editor(argv + [str(path)], path.name):
            return
        if is_desktop_mode():
            self.log_info("Opened config — use Tools ▸ Reload Configuration to "
                          "apply your changes once saved.")
            self.panel.render()
        else:
            self.reload_config()

    #: State key for the keymap preset chosen at first launch or from View >
    #: Keymap.
    _KEYMAP_STATE = "keymap.preset"
    def _apply_keymap_preset(self) -> None:
        """Lay the preset in force over ``config.KEY_BINDINGS`` and rebuild
        every keymap built from it: the app's, and the shared one the help
        dialog and the menus resolve through. ``_keymap_preset`` is None until
        a preset has been chosen; :data:`keymap_presets.FALLBACK` stands in
        until :meth:`run` has asked."""
        chosen = self.state_manager.get_state(self._KEYMAP_STATE, None)
        self._keymap_preset = keymap_presets.resolve(self.config, chosen)
        keymap_presets.apply(self.config, self._keymap_preset)
        self.keys = KeyBindings(self.config.KEY_BINDINGS)
        config_manager._key_bindings = None

    def _rebuild_keymap(self) -> None:
        """:meth:`_apply_keymap_preset`, then the two surfaces that quote a key
        name instead of reading one on demand: the status bar caches its hint
        line, and the menu holds the shortcut strings resolved when it was
        built. Both were left naming the pre-reload key — the help dialog said
        'D' while the bar and the menu still said 'K' (issue #382)."""
        self._apply_keymap_preset()
        self.key_sequence.cancel()
        self.panel.set_quit_handler(self._on_quit_request, self._quit_shortcut())
        self.status.invalidate()
        self.menu_bar.set_menu(self._build_menu())

    def _ask_keymap_preset(self) -> None:
        """Which keymap, asked at the first launch with none chosen — a new
        install and one from before presets alike (#597). None is the
        default, so there is no Cancel and Esc does nothing; one must be
        chosen. Quit before choosing, and the next launch asks again."""
        self._keymap_dialog(first_launch=True)

    def choose_keymap(self) -> None:
        """Tools > Advanced > Keymap…: the first launch's dialog, with each
        preset described, the current one under the cursor, and a Cancel."""
        self._keymap_dialog(first_launch=False)

    def _keymap_dialog(self, first_launch: bool) -> None:
        names = list(keymap_presets.PRESETS)
        labels = [keymap_presets.PRESETS[n].label for n in names]
        lines = ["Choose how XeFM's keys work. **Tools > Advanced > Keymap…** "
                 "changes it at any time.", ""]
        for name, label in zip(names, labels):
            current = " (current)" if not first_launch and name == self._keymap_preset else ""
            lines.append(f"- **{label}**{current} — "
                         f"{keymap_presets.PRESETS[name].description}")
        lines.append("")
        configured = keymap_presets.canonical(getattr(self.config, "KEY_PRESET", None))
        if not first_launch and configured in keymap_presets.PRESETS:
            lines.append(f"`KEY_PRESET = {configured!r}` in config.py decides the "
                         "keymap; change it there.")

        def answered(label: str) -> None:
            if label in labels:
                self.set_keymap_preset(names[labels.index(label)])
            self.panel.render()

        buttons = labels if first_launch else labels + ["Cancel"]
        current = names.index(self._keymap_preset) \
            if self._keymap_preset in names else 0
        show_message_box(
            self.panel, "\n".join(lines).rstrip(), title="Keymap",
            icon="question", buttons=tuple(buttons),
            default=0 if first_launch else current,
            cancel=None if first_launch else len(labels),
            on_result=answered, markdown=True, dismissable=not first_launch)
        self.panel.render()

    def set_keymap_preset(self, name: str) -> None:
        """Switch to keymap preset ``name`` now and for later sessions. Help,
        the menus and the status bar relabel at once. ``KEY_PRESET`` in
        ``config.py`` wins over this, and is said to."""
        configured = keymap_presets.canonical(getattr(self.config, "KEY_PRESET", None))
        name = keymap_presets.canonical(name)
        if configured and configured != name:
            self.log_info(f"KEY_PRESET = {configured!r} in config.py decides "
                          f"the keymap — change it there")
            return
        self.state_manager.set_state(self._KEYMAP_STATE, name)
        self._rebuild_keymap()
        hint = (" — typing a letter searches; F1 lists every key"
                if keymap_presets.type_ahead(self.config) else "")
        self.log_info(f"Keymap: {keymap_presets.LABELS[self._keymap_preset]}{hint}")
        replaced = keymap_presets.replaced(self.config, name)
        if replaced:
            # A config.py from before the presets were peers carries the whole
            # AFX table, which now replaces this preset's keys too.
            self.log_info(
                f"KEY_BINDINGS in config.py replaces this keymap's keys for "
                f"{len(replaced)} action(s): {', '.join(replaced[:5])}"
                f"{' …' if len(replaced) > 5 else ''} — delete the entries you "
                f"did not mean to keep")
        self.panel.render()

    def _type_ahead(self, event) -> bool:
        """Under a preset that frees the letters, an unbound typed key starts
        incremental search with that character. True when it did."""
        if not keymap_presets.type_ahead(self.config):
            return False
        char = getattr(event, "char", None)
        if (not char or len(char) != 1 or not char.isprintable() or char == " "
                or set(event.modifiers or ()) & {"ctrl", "alt", "cmd"}):
            return False
        self.enter_isearch(quick=True)
        if not self._isearch_active:
            return False
        # The bar is the top layer now; the key that opened it is its first
        # character.
        self.panel.dispatch_event(event)
        return True

    def choose_layout(self) -> None:
        """View > Layout…: how the active pane presents its rows (#756) — a
        matter of taste and width, chosen per tab and kept across sessions.
        What the folder adds (Git status, tags) is :meth:`choose_extras`."""
        pane = self.active_pane()
        rows = [(layout.name, layout.label) for layout in layouts.all_layouts()]

        def chosen(value) -> None:
            if value is not None:
                self._set_layout(pane, value)
            self.panel.render()

        show_choice_dialog(self.panel, "Layout", rows,
                           current=layouts.layout_of(pane).name, on_result=chosen)
        self.panel.render()

    def _set_layout(self, pane: dict, name: str) -> None:
        pane["layout"] = name
        self.log_info(f"Layout: {layouts.layout_of(pane).label}")
        self.panel.render()

    def _layout_menu(self) -> Menu:
        """View > Layout ▸ — the same choice as :meth:`choose_layout`, rebuilt
        on open so a config reload's layouts appear in it."""
        def is_current(name):
            return lambda: layouts.layout_of(self.active_pane()).name == name
        return Menu(*[
            MenuItem(layout.label,
                     on_select=(lambda n=layout.name: self._set_layout(self.active_pane(), n)),
                     checked=is_current(layout.name))
            for layout in layouts.all_layouts()], title="Layout")

    @staticmethod
    def _saved_extras(saved) -> dict:
        """A tab's saved extra states, keeping only well-formed ones. A state
        for an extra the config no longer has is kept: it applies again if the
        extra comes back."""
        if not isinstance(saved, dict):
            return {}
        return {k: v for k, v in saved.items()
                if isinstance(k, str) and v in ("on", "off")}

    def _set_extra(self, pane: dict, name: str, state: str) -> None:
        """Auto / On / Off for one extra in ``pane``'s tab, as sort and filter
        are the tab's."""
        extras = dict(pane.get("extras") or {})
        if state == "auto":
            extras.pop(name, None)
        else:
            extras[name] = state
        pane["extras"] = extras
        extra = layouts.get_extra(name)
        shown = extra in layouts.active_extras(pane)
        self.log_info(f"{extra.label if extra else name}: {state.capitalize()}"
                      f"{' (shown here)' if shown else ' (not shown here)'}")
        self.panel.render()

    def _extras_menu(self) -> Menu:
        """View > Show ▸ — one submenu per extra with Auto / On / Off, for the
        active pane's tab."""
        def item(extra):
            def is_state(state):
                return lambda: layouts.extra_state(self.active_pane(), extra.name) == state
            return MenuItem(extra.label, submenu=Menu(*[
                MenuItem(state.capitalize(),
                         on_select=(lambda st=state: self._set_extra(
                             self.active_pane(), extra.name, st)),
                         checked=is_state(state))
                for state in layouts.EXTRA_STATES], title=extra.label))
        return Menu(*[item(e) for e in layouts.all_extras()], title="Show")

    def choose_extras(self) -> None:
        """Pick an extra, then Auto / On / Off for it in this tab — the same
        choice as View > Show ▸, from the keyboard."""
        pane = self.active_pane()
        active = layouts.active_extras(pane)

        def label(extra) -> str:
            state = layouts.extra_state(pane, extra.name).capitalize()
            return f"{extra.label} — {state}{', shown here' if extra in active else ''}"

        rows = [(e.name, label(e)) for e in layouts.all_extras()]

        def picked(name) -> None:
            if name is None:
                self.panel.render()
                return
            states = [(st, st.capitalize()) for st in layouts.EXTRA_STATES]
            show_choice_dialog(
                self.panel, layouts.get_extra(name).label, states,
                current=layouts.extra_state(pane, name),
                on_result=lambda st: (self._set_extra(pane, name, st)
                                      if st else self.panel.render()))
            self.panel.render()

        show_choice_dialog(self.panel, "Show", rows, on_result=picked)
        self.panel.render()

    def resolve_attribute(self) -> None:
        """Resolve an attribute the active pane shows that is worked out only
        when asked — a folder's total size, an ``ATTRIBUTES`` entry with
        ``'compute': 'on_request'`` — for the selection, or the item under the
        cursor. A dialog names the targets and lists those values by name,
        even when there is one, so what is about to run is never a guess.
        Leaving the folder stops it."""
        pane = self.active_pane()
        targets = self._selected_or_focused(pane)
        names = self._resolvable(pane)
        if not names:
            self.log_info("Nothing to resolve: this pane shows no attribute "
                          "that is worked out on request")
            return
        if not targets:
            self.log_info("Nothing to resolve: no item selected or under the cursor")
            return
        what = (f"{len(targets)} selected item(s)" if pane["selected_files"]
                else f"'{name_key.compare_name(targets[0])}'")
        rows = [(n, attributes.get(n).label) for n in names]

        def chosen(name) -> None:
            if name is not None:
                self._resolve(pane, name, targets)
            self.panel.render()

        show_choice_dialog(self.panel, f"Resolve Attribute — {what}", rows,
                           on_result=chosen)
        self.panel.render()

    @staticmethod
    def _resolvable(pane: dict) -> list:
        """The on-request attributes ``pane`` shows, in the order it shows them."""
        names = []
        layout = layouts.effective(pane)
        for col in layout.columns:
            for n in [col.attr, *(m.attr for m in col.markers)]:
                attr = attributes.get(n)
                if attr is not None and attr.compute == "on_request" and n not in names:
                    names.append(n)
        return names

    def _resolve(self, pane: dict, name: str, targets: list) -> None:
        """Run one on-request attribute over ``targets`` in the background,
        logging the start and the end."""
        attr = attributes.get(name)
        records = {str(p): a for p, a in pane.get("_listing_entries") or ()}
        if name == "size":
            # A file's size is already shown: only folders count.
            targets = [p for p in targets if records.get(str(p), {}).get("is_dir")]
            if not targets:
                self.log_info("Size: no folder among the items")
                return
        self.log_info(f"Resolving {attr.label} for {len(targets)} item(s)…")

        def done(count: int, cancelled: bool) -> None:
            self._call_later(lambda: self.log_info(
                f"{attr.label}: {'stopped' if cancelled else f'{count} resolved'}"))

        attributes.store_of(pane).request(name, targets, records, on_done=done)

    def reread(self) -> None:
        """Read both panes' directories again — Total Commander's F2. File
        monitoring usually makes it unnecessary; it is for a location nothing
        watches (a network share, a remote) and for a listing in doubt. Every
        attribute value is asked for again too (#633)."""
        attributes.store_of(self.pm.left_pane).clear()
        attributes.store_of(self.pm.right_pane).clear()
        self._relist(self.pm.left_pane)
        self._relist(self.pm.right_pane)
        self.log_info("Re-read both panes")
        self.panel.render()

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
        # User actions and event hooks reload the same way everything else does:
        # every 'user' entry is dropped and rebuilt from the file just read, so
        # iterating on a custom action is edit-then-reload, with no restart.
        # Before the keymap, which needs them registered to know where a key
        # bound to one of them is reached (#662).
        self._load_user_entries(new_config)
        # The theme list as well, before the menu that lists it is rebuilt:
        # a theme added in config.py or by a newly installed extension joins
        # the picker and the cycle without a restart (#708).
        self._reload_themes(new_config)
        # Rebuild the keymap from the (possibly rebound) KEY_BINDINGS, with
        # the keymap preset laid over it again.
        self._rebuild_keymap()
        # Re-point the config reference every long-lived subsystem holds so
        # their on-demand reads pick up the new values without a rebuild.
        for holder in (self._fileops, self.flm, self.pm, self.file_monitor,
                       self.left_view, self.right_view):
            holder.config = new_config

        self.log_info("Configuration reloaded — key bindings, themes and file "
                      "settings applied; layout and font changes take effect on "
                      "the next launch.")
        self.panel.render()

    def _reload_themes(self, config) -> None:
        """Rebuild ``self.themes`` from ``config`` and stay on the active theme by
        name, re-applied so edits to it show at once. A theme that is gone falls
        back to the first one, as a launch would."""
        name = self.themes[self._theme_index][0]
        self.themes = _build_theme_list(config)
        index = next((i for i, (n, _t) in enumerate(self.themes) if n == name), 0)
        self._apply_theme(index)

    def file_details(self) -> None:
        """Show stat details for the focused entry — or an aggregate summary plus
        per-item details for a multi-file selection — in a scrollable Markdown
        dialog, reusing the shared text-dialog.

        Each entry renders as a heading followed by a GFM table of its stat
        fields, so the values line up in a real column instead of hand-padded.

        Directories additionally get live "Total size" / "On disk" / "Contents"
        rows: a background walk (:class:`xefm.disk_usage.UsageScan`) totals their
        recursive size and item counts while the dialog is already open, and a
        throttled animation tick swaps updated Markdown in place — the dialog
        opens instantly and the numbers climb until the walk finishes. Closing
        the dialog cancels the walk.

        "Total size" and "On disk" are Finder's two numbers — how long the files
        are, and how much of the volume they take up. They only differ on a tree
        holding something sparse, compressed or cloned, and one row called "Disk
        usage" used to show the former under the latter's name (issue #275). The
        "On disk" row appears only for a backend that can report an allocation,
        decided per root before the document is built so its shape stays fixed
        across the in-place swaps."""
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
        match_meta = virtual["meta"] if virtual and virtual.get("mode") == "content" else {}

        def _md_escape(text: str) -> str:
            # Keep a filename with Markdown-significant characters (``|`` splits a
            # table cell, ``*``/``_``/`` ` `` are emphasis) rendering literally.
            for ch in "\\`*_[]|":
                text = text.replace(ch, "\\" + ch)
            return text

        # Directories whose recursive size/counts the background walk fills in.
        # Symlinks to directories are excluded — the walk never follows links.
        dir_roots = []
        for t in targets:
            try:
                if t.is_dir() and not t.is_symlink():
                    dir_roots.append(t)
            except Exception:
                pass
        scan = UsageScan(dir_roots)
        # Which roots get an "On disk" row. Settled before the document exists,
        # so a rebuild never adds or drops a line under the restored scroll
        # offset — see reports_allocation.
        alloc_roots = {str(r) for r in dir_roots if reports_allocation(r)}

        def _size_cell(nbytes, done, errors) -> str:
            value = f"{format_size(nbytes)} ({nbytes:,} bytes)"
            if done:
                return value + (f" — *{errors} unreadable*" if errors else "")
            if scan.cancelled:
                # Only visible on a backend with no animation ticks (the walk
                # was dropped before it started) — never claim "scanning".
                return "*n/a*"
            return value + " — *scanning…*"

        def _alloc_cell(nbytes, done) -> str:
            # None means the walk met an entry whose allocation the volume did
            # not report, so the sum is missing terms — say so rather than show
            # a total that reads low.
            if nbytes is None:
                return "*unavailable*"
            return _size_cell(nbytes, done, 0)

        def _usage_rows(root):
            # Two or three live table rows bound to one root's running totals;
            # called on every rebuild, so it reads the counters fresh each time.
            totals = scan.totals[str(root)]
            on_disk_row = str(root) in alloc_roots
            def rows() -> str:
                if scan.cancelled and not totals.done:
                    counts = "*n/a*"
                else:
                    counts = f"{totals.files:,} files, {totals.dirs:,} folders"
                # The unreadable-directories note belongs to the pair of size
                # rows once, not to each of them.
                out = [f"| Total size | {_size_cell(totals.bytes, totals.done, totals.errors)} |"]
                if on_disk_row:
                    out.append(f"| On disk | {_alloc_cell(totals.on_disk, totals.done)} |")
                out.append(f"| Contents | {counts} |")
                return "\n".join(out)
            return rows

        # The attributes the entries have beyond the table's own fields — tags,
        # an ATTRIBUTES entry, an extension's (#789). What the pane already
        # holds shows at once; the rest is computed for these entries while the
        # dialog is open, as their folder totals are.
        store = attributes.store_of(pane)
        records = {str(p): a for p, a in pane.get("_listing_entries") or ()}
        shown = ("name", "ext", "size", "mtime")
        attr_names = [n for n in attributes.names() if n not in shown]
        fill = {"names": set(), "cancel": None, "done": True}

        def _attr_rows(entry):
            key = str(entry)
            names = [n for n in attr_names if attributes.get(n).applies_to(entry)]
            if not names:
                return None
            fill["names"].update(n for n in names if not store.value(key, n)[0])
            def rows() -> str:
                out, pending = [], False
                for n in names:
                    found, value = store.value(key, n)
                    if not found:
                        pending = True
                    elif attributes.has_value(value):
                        attr = attributes.get(n)
                        out.append(f"| {_md_escape(attr.label)} | "
                                   f"{_md_escape(layouts.words(attr, value))} |")
                if pending and not fill["done"]:
                    out.append("| Attributes | *reading…* |")
                return "\n".join(out)
            return rows

        def details(entry) -> list:
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
            ]
            if str(entry) in scan.totals:
                out.append(_usage_rows(entry))
            out += [
                f"| Modified | {mtime} |",
                f"| Permissions | `{_stat.filemode(st.st_mode)}` |",
            ]
            # On a content search-results pane, surface the matched line as extra
            # metadata (kept in virtual['meta']; not shown in the list itself).
            m = match_meta.get(str(entry))
            if m is not None:
                out.append(f"| Match | line {m['line']}: `{_md_escape(m['text'])}` |")
            # Last in the table: the rows come and go as values land, and an
            # empty line here would end the table early only where nothing
            # follows it.
            rows = _attr_rows(entry)
            if rows is not None:
                out.append(rows)
            out.append("")
            return out

        if len(targets) == 1:
            segments = details(targets[0])
        else:
            # Non-directory targets' own sizes, summed once; the directories'
            # recursive share comes from the scan's live grand totals. Their
            # allocations are summed the same way, and one target that cannot
            # report its own leaves the selection's on-disk figure unknown —
            # the same rule RootTotals.on_disk applies inside a directory.
            plain_bytes = 0
            plain_alloc = 0
            plain_alloc_known = True
            plain_files = 0
            for t in targets:
                if str(t) in scan.totals:
                    continue
                plain_files += 1
                try:
                    st = t.stat()
                except Exception:
                    plain_alloc_known = False
                    continue
                plain_bytes += st.st_size
                alloc = alloc_from_stat(st)
                if alloc is None:
                    plain_alloc_known = False
                else:
                    plain_alloc += alloc

            # The aggregate can only name an on-disk figure when every part of
            # the selection reports one — every plain file, and every directory
            # whose walk contributes to the total.
            show_alloc = (plain_alloc_known and
                          len(alloc_roots) == len(dir_roots))

            def totals_lines() -> str:
                b, f, d, errors = scan.grand_totals()
                total_files = plain_files + f
                total_dirs = len(dir_roots) + d
                if scan.cancelled and not scan.done:
                    items = "*n/a*"
                else:
                    items = (f"{total_files + total_dirs:,} "
                             f"({total_files:,} files, {total_dirs:,} folders)")
                lines = [
                    f"**Total size:** {_size_cell(plain_bytes + b, scan.done, errors)}"]
                if show_alloc:
                    walked = scan.grand_alloc()
                    lines.append(
                        "**On disk:** " + _alloc_cell(
                            None if walked is None else plain_alloc + walked,
                            scan.done))
                lines.append(f"**Total items:** {items}")
                return "\n\n".join(lines)

            segments = [f"# {len(targets)} items selected", "", totals_lines, ""]
            for t in targets:
                segments += details(t)

        # The document is a mix of fixed lines and callables for the live rows:
        # a rebuild re-renders only the counters, never re-stats the entries.
        def render() -> str:
            return "\n".join(s if isinstance(s, str) else s() for s in segments)

        if fill["names"]:
            fill["done"] = False
        source = render()
        closed = []

        def close() -> None:
            closed.append(True)
            scan.cancel()
            if fill["cancel"] is not None:
                fill["cancel"].set()

        dialog = show_markdown(self.panel, source, title="Details", on_close=close)

        if dir_roots or not fill["done"]:
            cache = {"src": source}

            def refresh() -> None:
                src = render()
                if src == cache["src"]:
                    return
                cache["src"] = src
                # set_source resets the scroll to the top; put it back before
                # the next draw so an update never yanks the view.
                offset = dialog.md.offset
                dialog.md.set_source(src)
                dialog.md.offset = offset
                self.panel.render()

            # Ticks fire every frame, but re-parsing the document that often is
            # waste — ~5 Hz reads live; a big multi-selection document (one
            # table per entry) re-parses slower still.
            interval = 0.2 if source.count("\n") < 400 else 0.5
            deadline = [time.monotonic() + interval]

            def tick() -> bool:
                if closed:
                    return False
                if (scan.done or not dir_roots) and fill["done"]:
                    refresh()
                    return False
                now = time.monotonic()
                if now >= deadline[0]:
                    deadline[0] = now + interval
                    refresh()
                return True

            if self.panel.request_animation_ticks(tick):
                if dir_roots:
                    scan.start()
                if not fill["done"]:
                    fill["cancel"] = store.fill(
                        fill["names"], targets, records,
                        on_done=lambda cancelled: fill.update(done=True))
            else:
                # Still backend (no timer to repaint on): drop the walk and
                # the attribute reads rather than leave "scanning…" or
                # "reading…" up forever.
                scan.cancel()
                fill["done"] = True
                refresh()
        self.panel.render()

    def open_with_os(self) -> None:
        """Hand the focused entry to an external program — the deliberate open,
        as opposed to ``open_item``'s open-inside-XeFM.

        A matching ``open`` entry in FILE_ASSOCIATIONS wins; otherwise the OS
        default application ('open' / 'xdg-open' / 'start') handles it. An
        association set explicitly to ``None`` suppresses the launch entirely,
        which is how you stop a file type from being handed to the OS at all.
        Errors are logged, not raised."""
        focused = self._focused_entry()
        entry = _real_entry(focused)
        if entry is None:
            if focused is not None:
                self.log_info(f"{focused.name} points at no file")
            return
        command = get_program_for_file(entry.name, "open")
        if command:
            if self._launch_associated([entry], command):
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
                # ShellExecute directly, not cmd.exe's `start`: the shell=True
                # command line quotes only ASCII blanks, so cmd.exe split a
                # name at a full-width space (U+3000) and opened its first
                # half (#508).
                os.startfile(str(entry))
            else:
                subprocess.run(["xdg-open", str(entry)], check=True)
        except Exception as exc:
            self.log_info(f"Failed to open {entry.name}: {exc}")
        else:
            self.log_info(f"Opened {entry.name} with the default app")

    #: State key of the app last chosen in Open With, per file type.
    _OPEN_WITH_STATE = "open_with.last"

    def open_with(self) -> None:
        """Choose, this time, the application that opens the selected files —
        or the focused file (#634). See :mod:`xefm.open_with` for where the
        candidates come from.

        XeFM's ``open_with`` entries are listed first, then the OS's
        applications where they mean something. For several files only the
        candidates that open every one of them are offered, and all the files
        go to the chosen one in one launch. Directories are skipped, and so are
        remote and in-archive files: an application needs a path on disk. The
        app chosen last for a file type is listed first next time."""
        pane = self.active_pane()
        files = []
        for target in self._selected_or_focused(pane):
            entry = _real_entry(target)
            if entry is None:
                self.log_info(f"{target.name} points at no file")
                continue
            if not self._is_local(entry):
                self.log_info(f"{entry.name}: external programs need a local file")
                continue
            try:
                if entry.is_dir():
                    self.log_info(f"{entry.name} is a directory")
                    continue
            except Exception:
                pass
            files.append(entry)
        if not files:
            self.panel.render()
            return
        paths = [str(e) for e in files]
        candidates = open_with.xefm_candidates([e.name for e in files])
        if open_with.os_apps_available(is_desktop_mode()):
            candidates += open_with.os_candidates(paths)
        if not candidates:
            message = ("No app can open all selected files." if len(files) > 1
                       else f"No app to open {files[0].name} with.")
            show_message_box(self.panel, message, title="Open With", icon="info")
            self.panel.render()
            return
        kind = open_with.type_key(paths)
        remembered = self.state_manager.get_state(self._OPEN_WITH_STATE, None)
        remembered = remembered if isinstance(remembered, dict) else {}
        candidates = open_with.remembered_first(candidates, remembered.get(kind))

        def on_accept(candidate) -> None:
            self.state_manager.set_state(self._OPEN_WITH_STATE,
                                         {**remembered, kind: candidate.key})
            self._open_with_candidate(candidate, files, pane)

        show_filter_list(
            self.panel, candidates,
            title=f"Open {self._files_label(files)} With",
            to_label=lambda c: c.name,
            to_right=lambda c: "default" if c.default else "",
            to_detail=lambda c: c.detail,
            on_accept=on_accept, region=self._active_pane_region())
        self.panel.render()

    def _open_with_candidate(self, candidate, files: list, pane: dict) -> None:
        """Launch the Open With row ``candidate`` on ``files``. XeFM's entries
        run as a ``PROGRAMS`` entry does — the pane's directory, the ``XEFM_*``
        environment, ``'terminal': True`` honored — but with absolute paths;
        the OS's applications get the files the way Finder or Explorer hands
        them over."""
        label = self._files_label(files)
        if candidate.source == open_with.XEFM:
            program = candidate.program
            env, cwd = self._program_env(pane)
            options = program.get("options") or {}
            self._launch_program(program["name"],
                                 list(program["command"]) + [str(e) for e in files],
                                 cwd=cwd, env=env,
                                 terminal=bool(options.get("terminal")))
            return
        try:
            open_with.launch(candidate, [str(e) for e in files])
        except Exception as exc:
            self.log_info(f"Failed to open {label} with {candidate.name}: {exc}")
        else:
            self.log_info(f"Opened {label} with {candidate.name}")
        self.panel.render()

    def reveal_in_os(self) -> None:
        """Reveal the focused entry in the OS file manager (Finder / Explorer),
        falling back to opening its parent directory elsewhere."""
        focused = self._focused_entry()
        entry = _real_entry(focused)
        if entry is None:
            if focused is not None:
                self.log_info(f"{focused.name} points at no file")
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
        """The menu-bar's 'Sort By' submenu, over the same keys the sort dialog
        offers (the keyboard path — ``show_sort_menu`` — opens the specialized
        dialog instead, see :mod:`xefm.sort_dialog`). A live ``checked``
        predicate marks the active pane's current mode.

        Built from :func:`xefm.sort_keys.rows` rather than a fixed four, so a key
        a config registered appears here as well as in the dialog. The menu is
        rebuilt on demand, which is what makes a config reload show up in it."""
        return Menu(*[
            MenuItem(label, on_select=(lambda m=mode: self._set_sort(m)),
                     checked=(lambda m=mode: self.active_pane()["sort_mode"] == m))
            for mode, label, _hotkey in sort_keys.rows()
        ], SEPARATOR,
            MenuItem("Reverse Sort", on_select=self._toggle_reverse,
                     checked=lambda: self.active_pane()["sort_reverse"]),
            title="Sort By")

    def show_sort_menu(self) -> None:
        """Open the sort dialog over the active pane (the 's' key): Up/Down pick
        the key, Left/Right the order, F/E/S/T apply a key directly, with an
        example of the resulting order at the bottom (issue #237)."""
        pane = self.active_pane()
        overlay = self._sort_overlay(pane)

        def on_result(result) -> None:
            if result is not None:
                mode, reverse = result
                if mode.startswith(self._ATTR_SORT):
                    pane["sort_overlay"] = {"attr": mode[len(self._ATTR_SORT):],
                                            "reverse": reverse,
                                            "path": str(pane["path"])}
                else:
                    pane["sort_mode"], pane["sort_reverse"] = mode, reverse
                    pane["sort_overlay"] = None
                self._resort(pane)
                self.log_info(f"Sort: {self.flm.get_sort_description(pane)}")
            self.panel.render()

        if overlay is not None:
            mode, reverse = self._ATTR_SORT + overlay[0], overlay[2]
        else:
            mode, reverse = pane["sort_mode"], pane["sort_reverse"]
        show_sort_dialog(self.panel, mode=mode, reverse=reverse,
                         extra=self._attribute_sort_rows(pane),
                         region=self._active_pane_region(), on_result=on_result)
        self.panel.render()

    #: The sort dialog's mode prefix for an attribute sort (``attr:git.status``).
    _ATTR_SORT = "attr:"

    def _attribute_sort_rows(self, pane: dict) -> list:
        """The sort dialog's rows for what the pane shows: one per column of
        its layout, and per attribute of its active extras, that is not already
        a sort key — offered once every row has its value (an on-request one
        at once — rows not computed go last)."""
        layout = layouts.layout_of(pane)
        store = attributes.store_of(pane)
        entries = pane.get("_listing_entries") or ()
        records = {str(p): a for p, a in entries}
        files = pane.get("files") or []
        names = [c.attr for c in layout.columns]
        for extra in layouts.active_extras(pane):
            names += [c.column.attr for c in extra.columns]
            names += [m.marker.attr for m in extra.markers]
        rows, seen = [], set()
        for name in names:
            attr = attributes.get(name)
            if attr is None or name in seen:
                continue
            if name in attributes.SORT_MODE_OF and attr.compute != "on_request":
                continue
            seen.add(name)
            ready = store.ready(name, files, records)
            note = ("this folder only" if ready
                    else "still computing — this folder only")
            label = attr.label
            if attr.compute == "on_request":
                note = "this folder only — rows not calculated go last"
            if name in attributes.SORT_MODE_OF:
                # Beside the built-in Size, which orders files only.
                label, note = (f"{label} with folder totals",
                               "this folder only — folders not calculated go last")
            rows.append((self._ATTR_SORT + name, label, ready, note))
        return rows

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

    def _theme_menu(self, sc=lambda _name: None) -> Menu:
        """The View menu's 'Theme' submenu: Next Theme first, then every theme
        — built-in and user-registered (``config.THEMES``) — with a live
        ``checked`` predicate marking the active one (mirrors ``_sort_menu``).
        ``sc`` gives an action's shortcut label."""
        return Menu(
            MenuItem("Next Theme", on_select=lambda: self._menu("toggle_color_scheme"),
                     shortcut=sc("toggle_color_scheme")),
            SEPARATOR,
            *[MenuItem(name, on_select=(lambda i=i: self._select_theme(i)),
                       checked=(lambda i=i: self._theme_index == i))
              for i, (name, _theme) in enumerate(self.themes)],
            title="Theme")

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
        """Advance to the next palette (the ``toggle_color_scheme`` action)."""
        self._apply_theme(self._theme_index + 1)

    def _select_theme(self, index: int) -> None:
        """Pick a specific palette from the menu, then redraw."""
        self._apply_theme(index)
        self.panel.render()

    def _quick_sort(self, mode: str) -> None:
        """Set the active pane's sort mode from a quick-sort key; pressing the
        same mode again toggles the sort direction.
        The current reverse setting is kept when switching to a new mode."""
        pane = self.active_pane()
        pane["sort_overlay"] = None
        if pane["sort_mode"] == mode:
            pane["sort_reverse"] = not pane["sort_reverse"]
        else:
            pane["sort_mode"] = mode
        self._resort(pane)
        self.log_info(f"Sort: {self.flm.get_sort_description(pane)}")

    def _set_sort(self, mode: str) -> None:
        pane = self.active_pane()
        pane["sort_overlay"] = None
        pane["sort_mode"] = mode
        self._resort(pane)
        self.log_info(f"Sort: {self.flm.get_sort_description(pane)}")
        self.panel.render()

    def _toggle_reverse(self) -> None:
        pane = self.active_pane()
        if self._sort_overlay(pane) is not None:
            pane["sort_overlay"]["reverse"] = not pane["sort_overlay"]["reverse"]
            self._resort(pane)
            self.panel.render()
            return
        pane["sort_reverse"] = not pane["sort_reverse"]
        self._resort(pane)
        self.log_info(f"Sort: {self.flm.get_sort_description(pane)}")
        self.panel.render()

    def _quit_shortcut(self) -> str | None:
        """The keymap's first key for the platform's way to quit
        (``quit_app``), as the macOS application menu's Quit item shows
        it — ``Cmd-Q`` under the OS native preset — or None when nothing binds
        it."""
        keys, _ = self.keys.get_keys_for_action("quit_app", _ctx.FILER)
        return self.keys.format_key_for_display(keys[0]) if keys else None

    def _on_quit_request(self) -> None:
        """The platform asked to quit — the application menu's Quit, the Dock,
        the window's close button — or a ``quit_app`` key was pressed (Cmd-Q,
        Alt-F4), whatever was open. It asks only while a task runs, and always
        saves the state on the way out. A second request while the confirm is
        up is the same question."""
        if self._quit_confirming:
            return
        self.confirm_quit(only_if_busy=True)
        self.panel.render()

    def _busy_tasks(self) -> list:
        """Every task quitting would stop: running in front or in the
        background, or waiting for its turn."""
        tasks = list(self.tasks.active_tasks())
        tasks += [t for t in self.tasks.background_tasks() if t not in tasks]
        return tasks

    def confirm_quit(self, only_if_busy: bool = False) -> None:
        """A modal confirm before quitting — the canonical message-box pattern.

        ``quit`` always asks. ``quit_app`` — the platform's Cmd-Q,
        Alt-F4 and close button — asks only when quitting would stop a task,
        and otherwise quits at once (the state is saved either way).

        With tasks running or queued, in front or in the background, it says
        so and defaults to Cancel: quitting stops a copy part-way, which is not
        what a reflexive Enter should do."""
        if self._quit_confirming:
            return
        jobs = self._busy_tasks()
        if only_if_busy and not jobs:
            self._quit()
            return
        self._quit_confirming = True
        if not jobs:
            def answered(label: str) -> None:
                self._quit_confirming = False
                if label == "Quit":
                    self._quit()

            show_message_box(
                self.panel, "Quit XeFM?", title="Confirm", icon="warning",
                buttons=("Quit", "Cancel"), default=0, cancel=1,
                on_result=answered,
            )
            self.panel.render()
            return
        n = len(jobs)

        def on_result(label: str) -> None:
            self._quit_confirming = False
            if label == "Quit":
                # Let each worker reach its next checkpoint and remove the
                # file it was half-way through, rather than die mid-write.
                if not self.tasks.cancel_all(timeout=3.0):
                    getLogger("Main").warning("A job did not stop in time; "
                                              "a partly written file may be left behind")
                self._quit()

        show_message_box(
            self.panel,
            f"**{n}** job{'' if n == 1 else 's'} "
            f"{'is' if n == 1 else 'are'} still running or queued. Quitting "
            f"stops {'it' if n == 1 else 'them'} part-way.",
            title="Quit XeFM?", icon="warning", buttons=("Quit", "Cancel"),
            default=1, cancel=1, on_result=on_result, markdown=True)
        self.panel.render()

    # --- background jobs (#567) ----------------------------------------------

    def _jobs_parts(self) -> list:
        """The status bar's job segment, kept short (#599 hand check), as
        ``(kind, text)`` parts: ``busy`` for the running job — its progress
        and how many wait behind it, ``Copy 42% +2`` — or ``attention`` when
        one waits on a prompt; then the similar-file scans (#571), running
        (``busy``) or finished and not looked at yet (``done`` / ``failed``).
        The bar draws the spinner or a mark in front of each. No key hint: a
        click on it opens the list."""
        parts = []
        jobs = self.tasks.background_tasks()
        waiting = next((t for t in jobs if t.needs_attention), None)
        running = self.tasks.running_task()
        queued = self.tasks.queued_count()
        more = f" +{queued}" if queued else ""
        if waiting is not None:
            parts.append(("attention", f"{waiting.title.rstrip('… ')}{more}"))
        elif running is not None:
            pct = int(running.progress.get_progress_percentage())
            parts.append(("busy", f"{running.title.rstrip('… ')} {pct}%{more}"))
        elif queued:
            parts.append(("busy", f"+{queued}"))
        for job, state, text in self._scan_rows:
            if state in (similar_scan.RUNNING, similar_scan.STARTING):
                parts.append(("busy", f"{job.label} {text}"))
            elif not job.seen:
                kind = "done" if state == similar_scan.DONE else "failed"
                parts.append((kind, f"{job.label}: {text}"))
        return parts

    # --- similar-file scans (#571) -------------------------------------------

    #: The scans shown in the status bar and the jobs list: ``(job, state,
    #: text)``, refreshed by :meth:`_refresh_scans` (and its poller) rather than
    #: read from disk on every frame.
    _scan_rows: list = []
    _scans_base = None
    _scan_poller = None

    def _refresh_scans(self) -> bool:
        """Re-read the scan folders; True when what the bar would say changed.
        Starts the poller while a scan runs."""
        rows = []
        try:
            for job in similar_scan.jobs(self._scans_base):
                state = job.state()
                if state in similar_scan.FINISHED and job.seen and len(rows) >= 5:
                    continue
                rows.append((job, state, job.summary()))
        except Exception as e:  # noqa: BLE001 — a scan folder never breaks the bar
            getLogger("Main").error(f"Could not read the scan folders: {e}")
        changed = [(j.id, st, t) for j, st, t in rows] != \
            [(j.id, st, t) for j, st, t in self._scan_rows]
        self._scan_rows = rows
        if any(st in (similar_scan.RUNNING, similar_scan.STARTING) for _j, st, _t in rows):
            self._ensure_scan_poller()
        return changed

    def _ensure_scan_poller(self) -> None:
        """A daemon thread that re-reads the scans every two seconds while one
        runs, and wakes the UI only when something changed. It ends with the
        last running scan."""
        poller = self._scan_poller
        if poller is not None and poller.is_alive():
            return

        def poll() -> None:
            while True:
                time.sleep(2.0)
                self._scans_dirty = True
                self._wake_pump()
                if not any(st in (similar_scan.RUNNING, similar_scan.STARTING)
                           for _j, st, _t in self._scan_rows):
                    return

        self._scan_poller = threading.Thread(target=poll, name="xefm-scan-poll",
                                             daemon=True)
        self._scan_poller.start()

    def _pump_scans(self) -> bool:
        """On the UI thread, from the pump: refresh the scans when the poller
        asked, and say whether the bar needs a frame. A scan that has just
        finished is announced in the log."""
        if not getattr(self, "_scans_dirty", False):
            return False
        self._scans_dirty = False
        before = {j.id: st for j, st, _t in self._scan_rows}
        changed = self._refresh_scans()
        for job, state, text in self._scan_rows:
            if before.get(job.id) in (similar_scan.RUNNING, similar_scan.STARTING) \
                    and state in similar_scan.FINISHED:
                self.log_info(f"{job.label} scan: {text} — "
                              f"{self._keys_label('jobs')} to open it")
        return changed

    def find_similar(self) -> None:
        """Start a similar-files scan of the selection — or of the directory —
        that keeps running after XeFM closes (#571). Its groups land as one
        playlist per group, opened from the jobs list."""
        pane = self.active_pane()
        if pane.get("virtual"):
            self.log_info("Find Similar Files scans a directory; this pane shows a list")
            return
        selected = [f for f in pane["files"] if str(f) in pane["selected_files"]]
        roots = selected or [pane["path"]]
        remote = [r for r in roots if path_schemes.is_uri(str(r))]
        if remote:
            self.log_info("Find Similar Files scans local folders (a mounted share "
                          f"counts); this is {roots[0]}")
            return
        rows = []
        for method, label in similar_scan.METHODS:
            why = similar_scan.unavailable(method)
            rows.append((method, label if why is None else f"{label} — {why}"))
        what = f"{len(roots)} selected item(s)" if selected else str(pane["path"])

        def chosen(method) -> None:
            self.panel.render()
            if method is None:
                return
            why = similar_scan.unavailable(method)
            if why is not None:
                self.log_info(f"{similar_scan.LABELS[method]}: {why}")
                return
            try:
                job = similar_scan.start([str(r) for r in roots], method,
                                         base=self._scans_base)
            except OSError as e:
                self.log_info(f"Could not start the scan: {e}")
                return
            self._refresh_scans()
            self.log_info(f"{job.label} scan of {what} started — it keeps running "
                          f"if you quit XeFM; {self._keys_label('jobs')} shows it")
            self.panel.render()

        show_choice_dialog(self.panel, "Find Similar Files", rows, on_result=chosen)
        self.panel.render()

    def _open_scan(self, job) -> None:
        """A scan chosen in the jobs list: a running one offers to stop; a
        finished one takes the pane to its groups — Enter opens a group as a
        list — or, when it did not finish, to its log."""
        state = job.state()
        if state in (similar_scan.RUNNING, similar_scan.STARTING):
            rows = []
            if job.result_path.exists():
                # The tree is rewritten with provisional groups as the scan
                # goes (#573): they can be looked at already.
                rows.append(("look", "Look at the groups so far (they may change)"))
            rows += [("stop", "Stop the scan"), ("log", "Show its log")]

            def act(choice) -> None:
                if choice == "look":
                    self._open_scan_result(job)
                elif choice == "stop":
                    job.stop()
                    self.log_info(f"{job.label} scan: stopping — the groups found "
                                  f"so far will be kept")
                elif choice == "log":
                    self._show_scan_log(job)
                self.panel.render()

            show_choice_dialog(self.panel, f"{job.label} — {job.progress_text()}",
                               rows, on_result=act)
            return
        job.mark_seen()
        self._refresh_scans()
        if state in (similar_scan.DONE, similar_scan.CANCELLED) and job.result_path.exists():
            self._open_scan_result(job)
            self.log_info(f"{job.label}: {job.summary()} — Enter opens a group")
        elif state in (similar_scan.DONE, similar_scan.CANCELLED):
            self.log_info(f"{job.label}: nothing found")
        else:
            self._show_scan_log(job)

    def _open_scan_result(self, job) -> None:
        """Open a scan's tree file in a **new tab** of the active pane: its
        groups are folders, ``Shift-O`` reaches the real files (#573). A tab,
        so the folder the pane was in stays where it was, and closing the tab
        is the way back (#612)."""
        self._open_tab(self.pm.active_pane, Path(xft.uri_for(job.result_path)))

    def _show_scan_log(self, job) -> None:
        if job.log_path.exists():
            show_text_viewer(self.panel, Path(str(job.log_path)))
        else:
            self.log_info(f"{job.label}: no log")

    def show_jobs(self) -> None:
        """List the background jobs and the similar-file scans. Choosing a
        running job brings it forward — its progress dialog, where a waiting
        prompt is answered and Esc can cancel it; a queued one is dropped from
        the queue. A scan opens its groups, or offers to stop it."""
        self._refresh_scans()
        jobs = self.tasks.background_tasks()
        if not jobs and not self._scan_rows:
            self.log_info("No background jobs")
            return

        def label(task) -> str:
            """What the job does, where, and how far it is (#599): "Copy 12
            items  ~/photos → s3://bucket/ — 42% (1.2 GB / 2.9 GB)"."""
            name = task.title.rstrip("… ")
            if task.detail:
                name = f"{name} {task.detail}"
            if self.tasks.is_queued(task):
                if task.status is TaskStatus.RUNNING:
                    return f"{name} — paused, queued (Enter runs it now)"
                return f"{name} — queued (Enter removes it)"
            if task.needs_attention:
                return f"{name} — needs you"
            state = f"{int(task.progress.get_progress_percentage())}%"
            op = task.progress.get_current_operation() or {}
            if op.get("total_bytes"):
                state += (f" ({format_size(op.get('processed_bytes', 0), compact=True)}"
                          f" / {format_size(op['total_bytes'], compact=True)})")
            return f"{name} — {state}"

        def scan_label(job, state, text) -> str:
            when = job.id[:13].replace("-", " ")
            new = "" if job.seen or state not in similar_scan.FINISHED else " · new"
            return f"{job.label} — {text}{new}  ({when[:4]}-{when[4:6]}-{when[6:8]} {when[9:11]}:{when[11:13]})"

        def chosen(value) -> None:
            if value is not None:
                kind, item = value
                if kind == "task":
                    dropped = (self.tasks.is_queued(item)
                               and item.status is not TaskStatus.RUNNING)
                    self.tasks.bring_forward(item)
                    if dropped:
                        self.log_info(f"Removed from the queue: {item.title.rstrip('… ')}")
                else:
                    self._open_scan(item)
            self.panel.render()

        def rows() -> list:
            """The list as it stands now: the dialog asks again a few times a
            second, so the progress moves while it is open (#599)."""
            items = [(("task", t), label(t)) for t in self.tasks.background_tasks()]
            items += [(("scan", j), scan_label(j, st, tx))
                      for j, st, tx in self._scan_rows]
            return items

        show_choice_dialog(self.panel, "Background Jobs", rows(), on_result=chosen,
                           refresh=rows)
        self.panel.render()

    def show_favorites(self) -> None:
        """The modal filter-list dialog: pick a favorite and jump the active pane
        there. The canonical searchable-list-picker pattern (XeFM's
        ``BaseListDialog`` workhorse), built from PuiKit's TextEdit + ListView.

        The rows are ``FAVORITES`` followed by the favorites added
        with :meth:`add_favorite` (see :mod:`xefm.favorites`). The picker's
        remove key forgets an added one; a config row stays, since the next
        config load would only bring it back."""
        rows = list(favorites.get_favorites())
        if not rows:
            key = keys_label_for_action("add_favorite")
            hint = f" Press {key} to add one." if key else ""
            show_message_box(self.panel, f"No favorites yet.{hint}",
                             title="Favorites", icon="info")
            self.panel.render()
            return

        # Middle-elide the "name — path" rows so a long path keeps its tail (the
        # leaf directory) rather than being clipped away (issue #211).
        show_filter_list(
            self.panel, rows, title="Go to Favorite",
            to_label=lambda row: f"{row.name}  —  {row.path}",
            on_accept=self._jump_to_favorite,
            on_remove=self._forget_favorite,
            region=self._active_pane_region(),
            elide_where="middle",
        )
        self.panel.render()

    def _forget_favorite(self, fav: favorites.FavoriteEntry) -> bool:
        if not favorites.remove_favorite(fav):
            if not fav.removable:
                self.log_info(f"'{fav.name}' is set in FAVORITES "
                              "in config.py; remove it there")
            return False
        self.log_info(f"Removed favorite: {fav.name} ({fav.path})")
        return True

    def add_favorite(self) -> None:
        """B: mark something — a place in the favorites picker (J), or files
        with tags (#585, the tag rows after the favorite ones).

        Two favorite candidates, offered as a choice: the directory the pane is showing
        (first, so Enter alone takes it) and the item under the cursor — which
        may be a file, so a favorite can name the thing to land on and not only
        the place to go. Where there is only one candidate (a search-results
        pane has no directory of its own; an empty directory has nothing under
        the cursor) the choice is skipped.

        Whether the cursor item is a file comes from the listing the pane
        already holds, so adding reads nothing from disk."""
        pane = self.active_pane()
        candidates = []
        if not pane.get("virtual"):
            here = pane["path"]
            candidates.append((("fav", (here, False)),
                               f"Favorite: This directory: {here.name or str(here)}"))
        cursor = self._cursor_favorite_target(pane)
        if cursor is not None:
            entry, is_file = cursor
            label = entry.name + ("" if is_file else "/")
            candidates.append((("fav", cursor), f"Favorite: Under the cursor: {label}"))
        # The same key marks things in the other way too: tags (#585), on the
        # selection or the cursor item, where their storage keeps tags at all.
        candidates += self._tag_rows(pane)
        if not candidates:
            self.log_info("Nothing to add to favorites")
            return
        # Manage tags… is always there where tags are, so it does not count
        # against going straight to the one favorite there is.
        marks = [c for c in candidates if c[0][0] != "tag-manage"]
        if len(marks) == 1 and marks[0][0][0] == "fav":
            self._name_favorite(*marks[0][0][1])
            return

        def on_result(choice) -> None:
            if choice is None:
                self.panel.render()
                return
            kind, value = choice
            if kind == "fav":
                self._name_favorite(*value)
            elif kind == "tag-toggle":
                self._toggle_tag(self._tag_targets(pane), *value)
            elif kind == "tag-edit":
                self._edit_tags(self._tag_targets(pane))
            elif kind == "tag-manage":
                self._manage_tags(pane["path"])

        show_choice_dialog(self.panel, "Bookmark or Tag", candidates,
                           on_result=on_result)
        self.panel.render()

    # --- tags (#585) ------------------------------------------------------------

    #: How many known tags the B dialog offers as one-key toggles.
    _TAG_ROWS = 8
    #: How many tags XeFM remembers having applied, for the pickers.
    _KNOWN_TAGS_MAX = 40
    #: Above this many targets, B skips reading their tags to mark the rows.
    _TAG_MARK_LIMIT = 200

    def _tag_targets(self, pane: dict) -> list:
        """What a tag operation acts on: the selection, else the cursor item."""
        return [e for e in self._selected_or_focused(pane) if e.name != ".."]

    def _tag_store_of(self, targets: list):
        """The one store all ``targets`` share, or None (unsupported, or mixed)."""
        stores = {id(s): s for s in (tags.store_for(t) for t in targets)}
        if len(stores) != 1:
            return None
        return next(iter(stores.values()))

    def _known_tags(self) -> list:
        """Tags to offer: the ones XeFM applied (most recent first), then the
        ones seen on files this session."""
        out, seen = [], set()
        for item in self.state_manager.get_state("tags.known", []) or []:
            try:
                tag = tags.Tag(str(item[0]), int(item[1]))
            except (TypeError, ValueError, IndexError):
                continue
            if tag.name.casefold() not in seen:
                seen.add(tag.name.casefold())
                out.append(tag)
        for key, tag in list(tags.SEEN.items()):
            if key not in seen:
                seen.add(key)
                out.append(tag)
        return out

    def _remember_tags(self, applied: list) -> None:
        known = [[t.name, t.color] for t in applied]
        names = {t.name.casefold() for t in applied}
        for item in self.state_manager.get_state("tags.known", []) or []:
            if isinstance(item, list) and item and str(item[0]).casefold() not in names:
                known.append(item)
        self.state_manager.set_state("tags.known", known[:self._KNOWN_TAGS_MAX])

    def _forget_known_tag(self, tag) -> bool:
        self._drop_known_tag(tag.name)
        self.log_info(f"Forgot tag {tag.name} (files keep it)")
        return True

    def _drop_known_tag(self, name: str) -> None:
        known = [i for i in self.state_manager.get_state("tags.known", []) or []
                 if not (isinstance(i, list) and i
                         and str(i[0]).casefold() == name.casefold())]
        self.state_manager.set_state("tags.known", known)
        tags.SEEN.pop(name.casefold(), None)

    def _tag_rows(self, pane: dict) -> list:
        """The B dialog's tag rows for the current targets: one toggle per known
        tag, checked where every target has it, then a free-form editor, then
        Manage tags… (#792), which acts on tags, not on the targets — so it is
        offered wherever the pane's directory keeps tags."""
        manage = []
        if not pane.get("virtual") and tags.store_for(pane["path"]) is not None:
            manage = [(("tag-manage", None), "Tag: Manage tags…")]
        targets = self._tag_targets(pane)
        store = self._tag_store_of(targets) if targets else None
        if store is None:
            return manage
        current = None
        if store.cheap and len(targets) <= self._TAG_MARK_LIMIT:
            found = store.read_many(targets)
            if not any(isinstance(v, Exception) for v in found.values()):
                current = {t.name.casefold() for t in tags.common(list(found.values()))}
        rows = []
        for tag in self._known_tags()[:self._TAG_ROWS]:
            on = current is not None and tag.name.casefold() in current
            mark = "✓" if on else " "
            rows.append((("tag-toggle", (tag, on if current is not None else None)),
                         [f"Tag: {mark} ", _tag_dot(tag.color), f" {tag.name}"]))
        what = targets[0].name if len(targets) == 1 else f"{len(targets)} selected"
        rows.append((("tag-edit", None), f"Tag: Edit tags… ({what})"))
        return rows + manage

    def _read_tags_then(self, targets: list, then) -> None:
        """Read ``targets``' tags — inline from a cheap store, in a task from
        one that pays per call (S3, SSH) — and hand ``{path: tags}`` to
        ``then``; a target that failed maps to its error."""
        store = self._tag_store_of(targets)
        if store is None:
            self.log_info("Tags are not supported here")
            return
        if store.cheap:
            then(store.read_many(targets))
            return
        task = Task("Reading tags", config=self.config, kind="tags",
                    busy_label="Reading tags…")
        self.tasks.submit(task, self.panel,
                          run=lambda t: {"found": store.read_many(targets)},
                          on_done=lambda res: then(res.get("found", {})))

    def _write_tags(self, targets: list, compute, message: str) -> None:
        """Read the targets' tags, give each the list ``compute(current)``
        returns, write them back, and report — inline or as a task, as
        :meth:`_read_tags_then` reads."""
        store = self._tag_store_of(targets)
        if store is None:
            self.log_info("Tags are not supported here")
            return

        def done(res: dict) -> None:
            self._report_tag_writes(targets, res, message)
            self.panel.render()

        if store.cheap:
            done(self._rewrite_tags(store, targets, compute))
            return
        task = Task("Writing tags", config=self.config, kind="tags",
                    busy_label="Writing tags…")
        self.tasks.submit(task, self.panel,
                          run=lambda t: self._rewrite_tags(store, targets, compute),
                          on_done=done)

    @staticmethod
    def _rewrite_tags(store, targets: list, compute, checkpoint=lambda: None) -> dict:
        """Give each of ``targets`` the tags ``compute(current)`` returns,
        writing only those that change. Safe off the UI thread."""
        found = store.read_many(targets)
        checkpoint()
        changes, failed = [], []
        for target in targets:
            current = found.get(str(target), [])
            if isinstance(current, Exception):
                failed.append(f"{target.name}: {current}")
                continue
            new = compute(current)
            if new != current:
                changes.append((target, new))
        failed += store.write_many(changes)
        return {"changed": len(changes) - len(failed), "failed": failed}

    def _report_tag_writes(self, targets: list, res: dict, message: str) -> None:
        """Log what :meth:`_rewrite_tags` did and let every tab redraw the
        targets' tags."""
        for line in res.get("failed", []):
            self.log_info(f"Tags not changed: {line}")
        self.log_info(message + f" ({res.get('changed', 0)} item(s))")
        for side in ("left", "right"):
            for tab in self.pm.tabs[side]:
                attributes.store_of(tab).forget(targets, "tags")

    def _toggle_tag(self, targets: list, tag, on) -> None:
        """B's tag row: take ``tag`` off when every target has it, else put it
        on every target. ``on`` is None when B could not afford to look; the
        write reads the tags anyway, so it decides there."""
        store = self._tag_store_of(targets)
        if store is None:
            return
        self._remember_tags([tag])

        def decide(found: dict) -> None:
            lists = [v for v in found.values() if not isinstance(v, Exception)]
            has_all = bool(lists) and all(
                any(t.name.casefold() == tag.name.casefold() for t in l) for l in lists)
            if has_all:
                self._write_tags(targets, lambda cur: tags.apply_change(cur, remove=[tag.name]),
                                 f"Removed tag {tag.name}")
            else:
                new = tags.new_tag(tag.name, store, [tag])
                self._write_tags(targets, lambda cur: tags.apply_change(cur, add=[new]),
                                 f"Tagged {tag.name}")

        if on is not None:
            decide({"_": [tag]} if on else {"_": []})
        else:
            self._read_tags_then(targets, decide)

    def _edit_tags(self, targets: list) -> None:
        """B's "Edit tags…": the tags every target shares, as a comma-separated
        line to edit. Names taken out are removed from every target, names
        added are added to every target; tags only some targets have are left
        as they are."""
        store = self._tag_store_of(targets)
        if store is None:
            self.log_info("Tags are not supported here")
            return

        def show(found: dict) -> None:
            lists = [v for v in found.values() if not isinstance(v, Exception)]
            shared = tags.common(lists) if lists else []
            known = self._known_tags() + [t for l in lists for t in l]

            def accept(text: str) -> None:
                names = tags.parse_names(text)
                before = {t.name.casefold() for t in shared}
                after = {n.casefold() for n in names}
                add = [tags.new_tag(n, store, known) for n in names
                       if n.casefold() not in before]
                remove = [t.name for t in shared if t.name.casefold() not in after]
                if not add and not remove:
                    self.panel.render()
                    return
                # A tag new to XeFM gets its color chosen now (#792), where
                # the store keeps one; a known tag or a color's own name
                # already has its color.
                known_names = {t.name.casefold() for t in known}
                fresh = [i for i, t in enumerate(add) if store.has_colors
                         and t.name.casefold() not in known_names
                         and not tags.names_color(t.name)]

                def commit() -> None:
                    self._remember_tags(add + [t for t in shared
                                               if t.name.casefold() in after])
                    self._write_tags(
                        targets, lambda cur: tags.apply_change(cur, add=add, remove=remove),
                        "Tags updated")

                def ask(k: int) -> None:
                    if k == len(fresh):
                        commit()
                        return
                    i = fresh[k]

                    def chosen(color: int) -> None:
                        add[i] = tags.Tag(add[i].name, color)
                        ask(k + 1)
                    self._choose_tag_color(add[i].name, add[i].color, chosen)

                ask(0)

            what = targets[0].name if len(targets) == 1 else f"{len(targets)} items"
            show_input(self.panel, title=f"Tags — {what}",
                       prompt="Tags, separated by commas:",
                       text=", ".join(t.name for t in shared), on_accept=accept,
                       region=self._active_pane_region())
            self.panel.render()

        self._read_tags_then(targets, show)

    def _choose_tag_color(self, name: str, current: int, then) -> None:
        """Pick a color for tag ``name`` from Finder's seven plus none, and
        hand its index to ``then``; Esc cancels and calls nothing."""
        rows = [(c, [_tag_dot(c), " " + (tags.COLORS[c] or "none").capitalize()])
                for c in tags.COLOR_CHOICES]

        def on_result(color) -> None:
            if color is None:
                self.panel.render()
                return
            then(color)

        show_choice_dialog(self.panel, f"Color of tag {name}", rows,
                           current=current, on_result=on_result)
        self.panel.render()

    def _manage_tags(self, root) -> None:
        """B's "Manage tags…" (#792): pick a tag, then change its color,
        rename it or delete it. Each acts on the tag itself, as Finder's do:
        every file carrying it, not only the selection."""
        store = tags.store_for(root)
        if store is None:
            self.log_info("Tags are not supported here")
            return
        known = self._known_tags()
        if not known:
            self.log_info("No tags yet: add one with Edit tags…")
            self.panel.render()
            return

        def on_result(tag) -> None:
            if tag is None:
                self.panel.render()
                return
            self._manage_tag(root, store, tag)

        show_choice_dialog(self.panel, "Manage Tags",
                           [(tag, [_tag_dot(tag.color), f" {tag.name}"]) for tag in known],
                           on_result=on_result)
        self.panel.render()

    def _manage_tag(self, root, store, tag) -> None:
        rows = []
        if store.has_colors:
            rows.append(("color", "Change color…"))
        rows.append(("rename", "Rename tag…"))
        rows.append(("delete", "Delete tag…"))

        def on_result(choice) -> None:
            if choice == "color":
                self._choose_tag_color(
                    tag.name, tag.color,
                    lambda color: self._recolor_tag(root, store, tag.name, color))
            elif choice == "rename":
                self._ask_tag_rename(root, store, tag)
            elif choice == "delete":
                self._delete_tag(root, store, tag.name)
            else:
                self.panel.render()

        show_choice_dialog(self.panel, f"Tag {tag.name}", rows, on_result=on_result)
        self.panel.render()

    def _find_tagged(self, t, root, store, name: str) -> tuple[list, str]:
        """Every file carrying tag ``name`` that XeFM can reach, and where it
        looked: the store's index everywhere (Spotlight), else its index or a
        walk under ``root``. Each hit is read back, so an index's loose match
        never changes a file without the tag. Runs in a task."""
        hits, where = store.find_everywhere(name), "found by Spotlight"
        if hits is None:
            hits, where = store.find(root, name, checkpoint=t.checkpoint), f"under {root}"
            if hits is None:
                hits = self._walk_for_tag(t, root, store, name)
        paths = list(path_list.resolve(hits, root).paths)
        t.checkpoint()
        found = store.read_many(paths)
        folded = name.casefold()
        return [p for p in paths if isinstance(found.get(str(p)), list)
                and any(tg.name.casefold() == folded for tg in found[str(p)])], where

    def _recolor_tag(self, root, store, name: str, color: int) -> None:
        """Make tag ``name`` this color: on every file that carries it, and for
        the next time XeFM adds it."""
        tag = tags.Tag(name, color)
        self._remember_tags([tag])
        if name.casefold() in tags.SEEN:
            tags.SEEN[name.casefold()] = tag
        what = tag.color_name or "no color"
        task = Task(f"Coloring tag {name}", config=self.config, kind="tags",
                    busy_label="Coloring tag…")

        def run(t: Task) -> dict:
            paths, where = self._find_tagged(t, root, store, name)
            res = self._rewrite_tags(store, paths, lambda cur: tags.recolor(cur, name, color),
                                     t.checkpoint)
            return {**res, "paths": paths, "where": where}

        def on_done(res: dict) -> None:
            if "paths" not in res:
                why = res.get("error") or "cancelled"
                self.log_info(f"Tag {name} is now {what} for new tags; "
                              f"files not changed ({why})")
            else:
                self._report_tag_writes(res["paths"], res,
                                        f"Tag {name} is now {what}, {res['where']}")
            self.panel.render()

        self.tasks.submit(task, self.panel, run=run, on_done=on_done)

    def _ask_tag_rename(self, root, store, tag) -> None:
        def accept(text: str) -> None:
            names = tags.parse_names(text)
            if len(names) != 1 or names[0] == tag.name:
                if len(names) > 1:
                    self.log_info("A tag name cannot contain a comma")
                self.panel.render()
                return
            self._rename_tag(root, store, tag, names[0])

        show_input(self.panel, title=f"Rename Tag {tag.name}", prompt="New name:",
                   text=tag.name, on_accept=accept, region=self._active_pane_region())
        self.panel.render()

    def _rename_tag(self, root, store, tag, new: str) -> None:
        """Call tag ``tag`` ``new`` on every file that carries it, keeping its
        color, and in XeFM's list. Where a file already has ``new``, the two
        become one."""
        old = tag.name
        self._drop_known_tag(old)
        self._remember_tags([tags.Tag(new, tag.color)])
        task = Task(f"Renaming tag {old}", config=self.config, kind="tags",
                    busy_label="Renaming tag…")

        def run(t: Task) -> dict:
            paths, where = self._find_tagged(t, root, store, old)
            res = self._rewrite_tags(store, paths, lambda cur: tags.rename(cur, old, new),
                                     t.checkpoint)
            return {**res, "paths": paths, "where": where}

        def on_done(res: dict) -> None:
            if "paths" not in res:
                self.log_info(f"Rename tag {old}: files not changed "
                              f"({res.get('error') or 'cancelled'})")
            else:
                self._report_tag_writes(res["paths"], res,
                                        f"Renamed tag {old} to {new}, {res['where']}")
            self.panel.render()

        self.tasks.submit(task, self.panel, run=run, on_done=on_done)

    def _delete_tag(self, root, store, name: str) -> None:
        """Take tag ``name`` off every file that carries it, after saying how
        many and where, and forget it."""
        task = Task(f"Finding tag {name}", config=self.config, kind="tags",
                    busy_label="Searching…")

        def run(t: Task) -> dict:
            paths, where = self._find_tagged(t, root, store, name)
            return {"paths": paths, "where": where}

        def found(res: dict) -> None:
            if "paths" not in res:
                self.log_info(f"Delete tag {name}: {res.get('error') or 'cancelled'}")
                self.panel.render()
                return
            paths, where = res["paths"], res["where"]
            if not paths:
                self._drop_known_tag(name)
                self.log_info(f"Deleted tag {name} (no files carry it, {where})")
                self.panel.render()
                return

            def answered(label: str) -> None:
                if label == "Delete":
                    self._drop_known_tag(name)
                    self._untag_all(store, paths, name, where)
                else:
                    self.panel.render()

            show_message_box(
                self.panel,
                f"Remove tag {name} from {len(paths)} item(s) {where}?",
                title="Delete Tag", icon="warning",
                buttons=("Delete", "Cancel"), default=1, cancel=1,
                on_result=answered)
            self.panel.render()

        self.tasks.submit(task, self.panel, run=run, on_done=found)

    def _untag_all(self, store, paths: list, name: str, where: str) -> None:
        """The second half of :meth:`_delete_tag`, once confirmed."""
        task = Task(f"Deleting tag {name}", config=self.config, kind="tags",
                    busy_label="Writing tags…")

        def on_done(res: dict) -> None:
            self._report_tag_writes(paths, res, f"Deleted tag {name}, {where}")
            self.panel.render()

        self.tasks.submit(
            task, self.panel,
            run=lambda t: self._rewrite_tags(
                store, paths, lambda cur: tags.apply_change(cur, remove=[name]), t.checkpoint),
            on_done=on_done)

    def show_tag_search(self) -> None:
        """Search Tags (#605): pick a tag — or type one not listed — and the
        pane lists the files under its directory that carry it. A search, so
        it has its own action rather than riding the favorites picker (J),
        which goes to places. The remove key forgets a tag from the list; the
        files keep it."""
        root = self.active_pane()["path"]
        if tags.store_for(root) is None:
            self.log_info("Tags are not supported here")
            self.panel.render()
            return
        rows = self._known_tags()
        show_filter_list(
            self.panel, rows, title="Search Tags",
            to_label=lambda tag: tag.name,
            to_marks=lambda tag: [_tag_dot(tag.color)],
            on_accept=lambda tag: self.find_by_tag(tag.name),
            on_accept_text=lambda text: text.strip() and self.find_by_tag(text.strip()),
            on_remove=self._forget_known_tag,
            region=self._active_pane_region())
        self.panel.render()

    def find_by_tag(self, name: str) -> None:
        """List the files under the active pane's directory that carry tag
        ``name``, as a virtual listing. An index answers where one exists
        (Spotlight on macOS, locally or on a macOS host over SSH; getfattr -R
        on a Linux host); otherwise the tree is walked, reading tags as it
        goes, in a cancellable task."""
        pane_name = self.pm.active_pane
        root = self.active_pane()["path"]
        store = tags.store_for(root)
        if store is None:
            self.log_info("Tags are not supported here")
            return
        task = Task(f"Finding tag {name}", config=self.config, kind="tags",
                    busy_label="Searching…")

        def run(t: Task) -> dict:
            hits = store.find(root, name, checkpoint=t.checkpoint)
            if hits is None:
                hits = self._walk_for_tag(t, root, store, name)
            return {"hits": hits, "cancelled": t.cancelled()}

        def on_done(res: dict) -> None:
            hits = res.get("hits") or []
            if res.get("cancelled"):
                self.log_info(f"Finding tag {name}: cancelled")
            elif not hits:
                self.log_info(f"No files tagged {name} under {root}")
            else:
                self.open_path_list(pane_name, hits, title=f"Tag: {name}")
            self.panel.render()

        self.tasks.submit(task, self.panel, run=run, on_done=on_done)

    @staticmethod
    def _walk_for_tag(t, root, store, name: str) -> list:
        """The walk :meth:`find_by_tag` falls back on, batching reads so a
        per-call store reads a directory's worth at a time."""
        folded, hits, stack = name.casefold(), [], [root]
        while stack:
            t.checkpoint()
            directory = stack.pop()
            try:
                children = list(directory.iterdir())
            except (OSError, Exception):  # noqa: BLE001 — unreadable: skip
                continue
            found = store.read_many(children)
            for child in children:
                got = found.get(str(child))
                if isinstance(got, list) and any(tg.name.casefold() == folded for tg in got):
                    hits.append(str(child))
                try:
                    if child.is_dir() and not child.is_symlink():
                        stack.append(child)
                except Exception:  # noqa: BLE001
                    pass
            t.counted += len(children)
        return hits

    def _cursor_favorite_target(self, pane: dict):
        """``(entry, is_file)`` for the item under ``pane``'s cursor, or ``None``
        when there is none. ``is_file`` comes from the pane's own listing, so
        nothing is read from disk."""
        files = pane["files"]
        idx = pane["focused_index"]
        if not (files and 0 <= idx < len(files)):
            return None
        entry = files[idx]
        is_dir = pane.get("file_info", {}).get(str(entry), {}).get("is_dir", False)
        return entry, not is_dir

    def _add_cursor_favorite(self) -> None:
        """The context menu's Add to Favorites: a right-click names its row, so
        that row is what is added — no "this directory or the cursor item"
        choice, which :meth:`add_favorite` (B) still offers."""
        cursor = self._cursor_favorite_target(self.active_pane())
        if cursor is not None:
            self._name_favorite(*cursor)

    def _name_favorite(self, path, is_file: bool) -> None:
        """Ask for the name ``path`` is listed under, then save it. A path that
        is already a saved favorite opens as a rename, prefilled with its
        current name; one the config lists is left alone."""
        existing = favorites.find_favorite(str(path))
        if existing is not None and not existing.removable:
            self.log_info(f"Already a favorite (from config.py): {existing.name}")
            self.panel.render()
            return

        def accept(text: str) -> None:
            name = text.strip()
            status = favorites.add_favorite(name, str(path), is_file=is_file)
            if status == favorites.ADDED:
                self.log_info(f"Added favorite: {name} ({path})")
            elif status == favorites.RENAMED:
                self.log_info(f"Renamed favorite: {name} ({path})")
            else:
                self.log_info(f"Could not save favorite: {path}")
            self.panel.render()

        default = existing.name if existing else (path.name or str(path))
        show_input(self.panel,
                   title="Rename Favorite" if existing else "Add to Favorites",
                   prompt="Name:", text=default, on_accept=accept,
                   on_cancel=self.panel.render,
                   validate=lambda t: None if t.strip() else "Name cannot be empty",
                   region=self._active_pane_region())
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
        """Fixed locations + mounted volumes, as ``{name, path}`` rows for the
        drives picker. The fixed part comes from ``DRIVE_LOCATIONS`` in the
        config — Home / Root / Documents / Downloads / Desktop unless the user
        defines their own list (issue #356) — while the volumes below it are
        always whatever the machine has mounted. SSH hosts are added by
        ``_ssh_drives``; S3 buckets (a credentialed network scan) stream in
        afterwards via ``_s3_drives_iter`` on the picker's loader thread."""
        system = platform.system()
        drives = get_drive_locations()
        if system == "Windows":
            for root in self._windows_drive_roots():
                drives.append({"name": root.rstrip("\\/"), "path": root})
        else:
            if system == "Darwin":
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
        drives.extend(self._network_mount_drives())
        seen, out = set(), []
        for d in drives:
            if d["path"] not in seen:
                seen.add(d["path"])
                out.append(d)
        return out

    @staticmethod
    def _network_mount_drives() -> list[dict]:
        """Live network mounts as picker rows (issue #406).

        On macOS these are already in the ``/Volumes`` scan above and dedupe
        away. Windows is why this exists: XeFM connects **deviceless** by
        default, and a connection with no drive letter appears in no
        drive-letter listing — so without this row the picker could neither
        reach the share nor offer to disconnect it.

        Cheap by contract (``netmount.list_mounts`` is one syscall on macOS and
        the mount table on Windows); nothing here may grow into a probe.
        """
        rows = []
        for info in netmount.list_mounts():
            if info.kind != netmount.NETWORK:
                continue
            rows.append({"name": XeFMApp._volume_name(info.path),
                         "path": info.path})
        return rows

    @staticmethod
    def _volume_name(path: str) -> str:
        """The last component of a mount path, for a label.

        Both separators are handled rather than ``os.path.basename``: the paths
        that reach here include Windows UNC connections, and on a POSIX host
        ``basename`` would hand back the whole ``\\\\nas\\photo`` unsplit.
        That matters for the tests as much as for a machine — the naming is
        worth being able to check anywhere.
        """
        trimmed = path.rstrip("/\\")
        return trimmed.replace("\\", "/").rsplit("/", 1)[-1] or path

    @staticmethod
    def _windows_drive_roots() -> list[str]:
        """Drive roots (``C:\\``, ``D:\\``, …) on Windows. ``os.listdrives`` on
        Python ≥ 3.12, the ``GetLogicalDrives`` bitmask below that; both only ask
        the OS which letters exist, so an unready removable or network drive
        cannot stall the picker. Best-effort: an empty list on failure."""
        try:
            return list(os.listdrives())
        except AttributeError:
            pass
        except OSError:
            return []
        try:
            import ctypes
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        except Exception:
            return []
        return [f"{chr(ord('A') + i)}:\\" for i in range(26) if bitmask & (1 << i)]

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

    def _s3_scan_available(self) -> bool:
        """Whether the drives picker should scan S3 at all: boto3 importable and
        AWS credentials plausibly present locally. Checked before attaching the
        background scan, so the common no-AWS case starts no thread and shows no
        spinner."""
        try:
            from xefm.s3 import HAS_BOTO3
        except Exception:
            return False
        return HAS_BOTO3 and self._aws_configured()

    def _s3_drives_iter(self, cancel: threading.Event):
        """S3 buckets as ``s3://bucket/`` rows for the drives picker, yielded as
        they arrive. Runs on the picker's background loader thread (never the UI
        thread — issue #274), so the dialog opens instantly and bucket rows
        stream in below the local ones. Pages through ``ListBuckets`` where the
        SDK supports it, so a large account fills progressively rather than all
        at once. Bounded by short timeouts and best-effort: any AWS error simply
        ends the scan with the rows yielded so far.

        Note: EC2 instance-role (IMDS-only) credentials are intentionally not
        probed — ``_s3_scan_available`` requires an env var or ``~/.aws`` file —
        so that endpoint is never waited on."""
        try:
            from xefm.s3 import get_s3_probe_client, note_bucket_region
            client = get_s3_probe_client()
            if client.can_paginate("list_buckets"):
                pages = client.get_paginator("list_buckets").paginate()
            else:  # older botocore: ListBuckets has no paginator — one full call
                pages = [client.list_buckets()]
            for page in pages:
                if cancel.is_set():
                    return
                for b in page.get("Buckets", []):
                    # ListBuckets says where each bucket lives, which spares the
                    # first request to it a cross-region redirect (issue #418).
                    note_bucket_region(b["Name"], b.get("BucketRegion"))
                    yield {"name": b["Name"], "path": f"s3://{b['Name']}/"}
        except Exception:
            return

    def show_drives(self) -> None:
        """The drives picker: choose a volume / common location / SSH host / S3
        bucket and jump the active pane there (reuses the searchable-list dialog,
        like favorites). Local and SSH rows are ready instantly; S3 buckets — a
        credentialed network scan — stream in on the dialog's background loader
        while it is already open (issue #274). Selecting an ``ssh://`` or
        ``s3://`` row connects on first listing.

        The picker's remove key (``remove_list_item``) here **disconnects** a
        network mount or **ejects** a
        removable volume (issue #406). That rides the picker's existing remove
        hook: a row it declines stays put, which is exactly the behaviour every
        other row needs.
        """
        drives = self._local_drives() + self._ssh_drives()
        if platform.system() in ("Darwin", "Windows"):
            # First row, because it is the one thing in this list that is not
            # already reachable — everything else is somewhere the machine can
            # already go.
            drives.insert(0, {"name": "Connect to Server…", "path": "",
                              "action": "connect_server"})
        self._drives_dialog = show_filter_list(
            self.panel, drives, title="Drives",
            to_label=self._drive_label,
            on_accept=self._go_to_drive,
            on_remove=self._drive_remove,
            remove_label="disconnect",
            region=self._active_pane_region(),
            elide_where="middle",  # keep the path tail visible (issue #211)
            load_more=self._s3_drives_iter if self._s3_scan_available() else None)
        self.panel.render()

    @staticmethod
    def _drive_label(drive: dict) -> str:
        """``name — path``, or just the name for the action row, which has no
        path to show."""
        path = drive.get("path") or ""
        return f"{drive['name']}  —  {path}" if path else drive["name"]

    def _go_to_drive(self, drive: dict) -> None:
        if drive.get("action") == "connect_server":
            self.show_connect_server()
            return
        self._jump_pane_to(self.active_pane(), Path(drive["path"]),
                           log=f"Drive: {drive['path']}")

    # --- connecting to a server (issue #406) ---------------------------------

    def show_connect_server(self) -> None:
        """The Connect to Server picker: saved servers, which of them are
        mounted, and a way to reach one that is not in the list yet. Mounting is
        the operating system's (``xefm.netmount``), so what comes back is an
        ordinary local path and the pane goes there like any other."""
        if not netmount.is_supported():
            show_message_box(
                self.panel,
                "Connecting to a server is only available on macOS and Windows.",
                title="Connect to Server", icon="info")
            self.panel.render()
            return
        open_connect_server(self.panel, on_connected=self._connected_to_server,
                            region=self._active_pane_region())

    def _connected_to_server(self, path: str, label: str) -> None:
        """A share is mounted (or already was): send the pane into it."""
        self._jump_pane_to(self.active_pane(), Path(path),
                           log=f"Connected: {label} — {path}")

    def _drive_remove(self, drive: dict) -> bool:
        """The drives picker's remove key (``remove_list_item``): disconnect a
        share, eject a disk, or decline the row.

        Always returns False, for two different reasons. A row that is neither a
        network mount nor a removable volume — Home, a drive letter, an S3
        bucket, an SSH host — has nothing to remove, and declining is what
        leaves it in the list. A row that *does* have something to remove is not removed here
        either: unmounting can take real time (a server that has gone away is
        precisely when someone reaches for this), so it runs on a worker thread,
        and a row that vanished before the work finished would be claiming an
        outcome nobody knows yet. The picker closes instead, and the log says
        what happened.
        """
        path = drive.get("path") or ""
        info = netmount.classify(path) if path else None
        if info is None or info.kind not in (netmount.NETWORK, netmount.REMOVABLE):
            return False
        dialog = getattr(self, "_drives_dialog", None)
        if dialog is not None:
            self.panel.remove_layer(dialog)
            self._drives_dialog = None
        self._release_volume(info)
        return False

    def _release_volume(self, info) -> None:
        """Let go of a volume, then unmount or eject it on a worker thread.

        XeFM's own hold on the volume is the likeliest reason for a "resource
        busy" refusal, and the only one XeFM can do something about: a pane
        sitting inside it and the filesystem watcher pointed at that directory.
        So the panes are moved out first — to the volume's parent, which is
        where the user would have gone anyway — and the watcher is re-pointed
        before the unmount is attempted. Re-pointing is asynchronous (#410), so
        the worker waits for the monitor to settle rather than racing it.
        """
        ejecting = info.kind == netmount.REMOVABLE
        name = self._volume_name(info.path)
        escape = Path(self._volume_parent(info.path))
        for pane in (self.pm.left_pane, self.pm.right_pane):
            if self._inside_volume(pane.get("path"), info.path):
                self._jump_pane_to(pane, escape,
                                   log=f"Left {info.path} before disconnecting")
        self._sync_monitored_dirs()

        def work(_cancel) -> str:
            self.file_monitor.wait_for_idle(2.0)
            if ejecting:
                netmount.eject(info.path)
            else:
                netmount.unmount(info.path)
            return info.path

        def done(_result, error, cancelled) -> None:
            if cancelled:
                return
            if error is None:
                self.log_info(f"{'Ejected' if ejecting else 'Disconnected'}: "
                              f"{info.path}")
            else:
                show_message_box(self.panel, str(error),
                                 title="Eject" if ejecting else "Disconnect",
                                 icon="error")
            self.panel.render()

        run_connecting(self.panel,
                       f"{'Ejecting' if ejecting else 'Disconnecting'} {name}…",
                       work, done, title="Eject" if ejecting else "Disconnect")

    @staticmethod
    def _volume_parent(volume: str) -> str:
        """Where to send a pane that is standing on a volume about to go away.

        ``/Volumes`` for a Mac volume: local, instant, and where the user would
        have gone anyway. Home for everything else, because the alternatives are
        not directories to stand in — the parent of a deviceless UNC connection
        is the *server* (``\\\\nas``), and listing that would be a network
        round trip against the very machine being disconnected from, while the
        parent of ``Z:\\`` is nothing at all.
        """
        parent = os.path.dirname(volume.rstrip("/\\"))
        if parent and not parent.startswith("\\\\"):
            return parent
        return os.path.expanduser("~")

    @staticmethod
    def _inside_volume(pane_path, volume: str) -> bool:
        """Whether a pane is standing on the volume or somewhere below it.
        String comparison, not ``resolve()``: this is asked about a volume that
        may be half gone already, and no navigation in XeFM resolves paths."""
        try:
            path = str(pane_path)
        except Exception:
            return False
        root = volume.rstrip("/\\")
        if not root:
            return False
        return path == root or path == volume or path.startswith(root + os.sep)

    def show_search(self) -> None:
        """Live filename search under the active pane (``find_files``): opens
        the progressive search dialog in filename mode. Typing walks the tree
        (bounded, honouring the hidden-file setting) and streams matching entries
        into the list as you type; Tab switches to content search; Enter feeds the
        *whole* result set into the pane and lands the cursor on the hit you were
        standing on (``_feed_search_results``)."""
        self._open_search("filename")

    def show_content_search(self) -> None:
        """Live content (grep) search under the active pane (``find_in_files``):
        opens the progressive search dialog in content mode. Typing walks the tree
        reading text files and streams each matching line; Tab switches to
        filename search; Enter feeds the *whole* result set into the pane —
        collapsed to one row per file — and lands the cursor on the hit you were
        standing on (``_feed_search_results``)."""
        self._open_search("content")

    #: State keys for each search mode's query history (#609). The index's is
    #: the one #579 already kept.
    _SEARCH_HISTORY = {"filename": "search.history.filename",
                       "content": "search.history.content",
                       "index": "index_search.history"}

    def _index_scope(self, pane: dict) -> str | None:
        """Why the OS index cannot search ``pane``, or None when it can."""
        why = os_index.unavailable()
        if why:
            return why
        scope = pane["path"]
        if pane.get("virtual") or path_schemes.is_uri(str(scope)):
            return (f"{os_index.engine()} searches local folders; this pane "
                    f"is showing {scope}")
        return None

    def _open_search(self, initial_mode: str) -> None:
        """Open the progressive search dialog anchored over the active pane.
        ``find_files``, ``find_in_files`` and ``index_search`` all land here —
        they differ only in the starting mode, and Tab steps through the modes
        in place: filenames, content, and the OS index where this pane can use
        it (#609). The dialog runs ``search_iter`` on a worker thread and
        streams results in, so a huge tree never blocks the UI; each keystroke
        supersedes the previous search.

        An active pane filter narrows *content* search to the files it matches
        (issue #305) — the same files the user is looking at — and the dialog
        title names the pattern so the narrowing is visible. Filename search
        ignores it: its query is itself a filename pattern.

        The dialog's live options (issue #312) are read here, in the closure the
        dialog runs, rather than by the dialog itself: it shows them and re-runs
        when one changes, and this is the only place that knows what they mean.
        Their meaning is :mod:`xefm.search_options`, and the filter chips' —
        kind, date, size, in every mode — :mod:`xefm.search_filters`."""
        pane = self.active_pane()
        root = pane["path"]
        root_str = str(root)
        name_filter = pane.get("filter_pattern") or ""
        options = self._search_option_set()
        engine = os_index.engine() or "Index"
        modes = ("filename", "content")
        if self._index_scope(pane) is None:
            modes += ("index",)
        if initial_mode not in modes:
            initial_mode = "filename"

        def keep():
            return search_filters.predicate(options.snapshot())

        def can_search(mode, query):
            if query:
                return True
            # The chips can search on their own — "every image here, changed
            # this week" — except in content, which needs words to look for.
            return mode != "content" and search_filters.active(options.snapshot())

        def search_iter(mode, query, cancel):
            case = options[search_opts.CASE]
            recursive = options[search_opts.SUBDIRS]
            if mode == "content":
                # re.error still surfaces in the dialog — and a search with the
                # regex option off can no longer raise one at all.
                pattern = search_opts.content_regex(
                    query, case=case, word=options[search_opts.WORD],
                    regex=options[search_opts.REGEX])
                yield from self._iter_content_matches(root, pattern, cancel,
                                                      name_filter=name_filter,
                                                      recursive=recursive,
                                                      keep=keep())
            elif mode == "index":
                yield from self._iter_index_matches(root_str, query, cancel,
                                                    options.snapshot())
            else:
                yield from self._iter_filename_matches(root, query or "*", cancel,
                                                       case=case,
                                                       recursive=recursive,
                                                       keep=keep())

        def rel(s: str) -> str:
            # os.sep too: a local path on Windows continues with "\".
            return s[len(root_str):].lstrip("/" + os.sep) if s.startswith(root_str) else s

        def to_label(mode, value):
            if mode == "content":
                return f"{rel(str(value['path']))}:{value['line']}: {value['text']}"
            return rel(str(value))

        def on_accept(mode, value):
            # Feed-by-default: accepting doesn't navigate to the one hit — it
            # feeds the *whole* result set into the active pane as a flat virtual
            # listing, so every file operation can act on it. Read the dialog's
            # full results + current query; the accepted ``value`` only decides
            # which row the cursor lands on (issue #224).
            query = dialog.query_edit.text.strip()
            if query:
                self._record_history(self._SEARCH_HISTORY[mode], query)
            self._feed_search_results(mode, list(dialog.results), root, query,
                                      focus=value,
                                      filters=search_filters.describe(options.snapshot()))

        titles = {"filename": "Search Files", "content": "Search Content",
                  "index": f"Search {engine}"}
        if name_filter:
            titles["content"] = f"Search Content ({filters.label(name_filter)})"
        dialog = show_progressive_search(
            self.panel, initial_mode=initial_mode,
            search_iter=search_iter, to_label=to_label, on_accept=on_accept,
            titles=titles, accept_hint="feed", options=options,
            region=self._active_pane_region(), modes=modes,
            mode_names={"filename": "filenames", "content": "content",
                        "index": engine},
            can_search=can_search,
            history=lambda mode: self._query_history(self._SEARCH_HISTORY[mode]),
            on_history_remove=lambda mode, query: self._forget_history(
                self._SEARCH_HISTORY[mode], query))
        self.panel.render()

    def _iter_index_matches(self, root: str, query: str, cancel, values: dict):
        """The OS index's answer for ``query`` under ``root``, checked against
        the filter chips (#609). With no words, the chips alone are the query.
        A failure is said in the dialog's status line."""
        engine = os_index.engine() or ""
        text = query or search_filters.index_query(engine, values)
        if not text:
            return
        result = os_index.search(text, root, cancelled=cancel.is_set)
        if result.cancelled or cancel.is_set():
            return
        if result.error:
            raise SearchFailed(result.error)
        keep = search_filters.predicate(values)
        for raw in result.paths:
            if cancel.is_set():
                return
            if keep is not None:
                attrs = search_filters.stat_attrs(raw)
                if attrs is None or not keep(os.path.basename(raw), attrs):
                    continue
            yield Path(raw)

    def _search_option_set(self) -> OptionSet:
        """The search dialog's options, built once and kept for the session.

        Kept on the app rather than on the dialog so a case choice survives
        closing and reopening the search — the one thing a per-dialog set would
        lose that anyone would miss. What does *not* survive is anything the
        declaration marked transient: ``reset_transient`` puts the walk's scope
        back to "everything under here" on every open, so a search narrowed to
        one directory never silently narrows the next one
        (:mod:`xefm.search_options`)."""
        options = getattr(self, "_search_options", None)
        if options is None:
            options = self._search_options = OptionSet(
                search_opts.SEARCH_OPTIONS + search_filters.SEARCH_FILTERS)
        options.reset_transient()
        return options

    def _feed_search_results(self, mode: str, results: list, root, query: str,
                             focus=None, filters: str = "") -> None:
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
        virtual = {
            "kind": "search", "root": Path(root), "mode": mode,
            "query": query, "results": paths, "meta": meta,
            # The filter chips in force, in words, for the header (#609).
            "filters": filters,
        }
        said = " · ".join(part for part in (f'"{query}"' if query else "", filters) if part)

        def landed(p: dict) -> None:
            self._focus_result(p, focus)
            self.log_info(f'Search results for {said}: '
                          f'{len(virtual["results"])} item(s)  '
                          f'— {self._virtual_keys_hint()}')

        self._list_virtual(pane, virtual, on_ready=landed,
                           on_empty=lambda _result: self.log_info("No results to open"))
        self.panel.render()

    def _virtual_keys_hint(self) -> str:
        """The keys that work a virtual pane, for the line announcing one."""
        return (f'{self._keys_label("sync_current_to_other")} go to location · '
                f'{self._keys_label("sync_other_to_current")} reveal in other '
                f'pane · {self._keys_label("go_parent")} back')

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

    def _iter_filename_matches(self, root, pattern, cancel, *,
                               case: bool = False, recursive: bool = True,
                               keep=None):
        """Walk under ``root`` (:func:`xefm.tree_walk.walk` — several directories
        at once over SSH) yielding entries whose name matches
        ``pattern`` (a glob), checking ``cancel`` between entries so
        a superseded search stops promptly. The pattern is matched against the
        *whole* filename — an exact glob (issue #231): ``report.txt`` matches only
        that name, and wildcards are used explicitly for partial matches
        (``*.py``, ``report*``, or ``*report*`` for the old "contains" behaviour).
        Hidden entries are skipped unless the pane is showing them. The walk is
        unbounded (issue #305 — a size cap silently hid far-away matches); the
        result cap and cancellation are applied by the dialog consuming this
        generator.

        ``case`` is the dialog's case option, off by default, so a pattern
        matches either case unless it is turned on. ``recursive=False`` searches
        this directory alone: subdirectories still *match* by name, they are
        just not descended."""
        match = search_opts.filename_matcher(pattern, case=case)
        # One listing per directory answers both questions asked of every entry
        # — is it hidden, is it a directory to descend — instead of a stat
        # apiece; the walk lists several at once where that pays (SSH).
        shows, descend = _search_rules(self.flm.show_hidden, recursive)
        for e, attrs in tree_walk.walk(root, cancel, descend):
            if shows(e, attrs) and match(name_key.compare_name(e)) \
                    and (keep is None or keep(e.name, attrs)):
                yield e

    def _go_to_result(self, entry) -> None:
        pane = self.active_pane()
        pane["path"] = entry.parent
        self._refresh(pane, on_ready=lambda p: self._select_by_name(p, entry.name))
        self.log_info(f"Found: {entry}")
        self.panel.render()

    @staticmethod
    def _virtual_focused_entry(pane: dict):
        """The real ``Path`` under the cursor of a ``pane`` that shows entries
        standing for places elsewhere — the row of a virtual (search-results)
        pane, or the target of a reference in an ``.xft`` tree (#573) — or
        ``None``. Used by the reveal keys to find *which* place to open."""
        files = pane["files"]
        idx = pane["focused_index"]
        if not (files and 0 <= idx < len(files)):
            return None
        if pane.get("virtual"):
            return files[idx]
        if xft.is_xft_path(pane["path"]):
            return files[idx].target()
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
        """``sync_other_to_current`` from the results pane: open the result's real
        directory in the *other* pane (landing on the file), keeping the result
        set intact here — reveal without leaving virtual mode. Only meaningful when
        the active pane is the virtual one; returns False otherwise."""
        pane = self.active_pane()
        if xft.is_xft_path(pane["path"]) and pane["selected_files"]:
            return self._reveal_selected_targets(pane)
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

    def _reveal_selected_targets(self, pane: dict) -> bool:
        """``sync_other_to_current`` over a selection in an ``.xft`` tree:
        open every selected reference's real file in the other pane as one
        list, where duplicates spread over many folders can be dealt with
        together (#549 decision 4). A provisional tree asks first — its groups
        may still change under the selection."""
        selected = [f for f in pane["files"] if str(f) in pane["selected_files"]]
        targets = []
        for entry in selected:
            target = entry.target()
            if target is not None:
                targets.append(target)
            elif entry.is_dir():
                targets.extend(t for t in (c.target() for c in entry.iterdir()) if t)
        if not targets:
            self.log_info("Nothing selected points at a file")
            return True
        file_path, _key = xft.split(pane["path"])
        title = f"{_StdPath(file_path).name}: {len(targets)} selected"
        other_name = "right" if self.pm.active_pane == "left" else "left"

        def go() -> None:
            self.open_path_list(other_name, [str(t) for t in targets], title=title)
            self.panel.render()

        try:
            doc = xft.load(file_path)
        except OSError:
            doc = None
        if doc is not None and doc.provisional:
            def on_result(label: str) -> None:
                if label == "Open":
                    go()
                self.panel.render()

            show_message_box(
                self.panel,
                f"This tree is still being written ({doc.progress_text() or 'in progress'}), "
                f"and its groups may change.\n\nOpen the **{len(targets)}** selected "
                f"file(s) in the other pane anyway?",
                title="Provisional groups", icon="warning", buttons=("Open", "Cancel"),
                default=1, cancel=1, on_result=on_result, markdown=True)
            self.panel.render()
            return True
        go()
        return True

    # --- .xft trees being rewritten (#573) ---------------------------------

    _xft_poller = None

    def _watch_xft(self) -> None:
        """While a pane shows a provisional ``.xft`` tree, look at the file
        every two seconds and re-read the pane when a producer has rewritten
        it. The poller ends once no pane shows a provisional tree."""
        poller = self._xft_poller
        if poller is not None and poller.is_alive():
            return

        def provisional_files() -> set:
            files = set()
            for name in ("left", "right"):
                path = self.pane(name)["path"]
                if xft.is_xft_path(path):
                    file_path, _key = xft.split(path)
                    try:
                        if xft.load(file_path).provisional:
                            files.add(file_path)
                    except OSError:
                        pass
            return files

        def poll() -> None:
            stamps = {}
            while True:
                time.sleep(2.0)
                files = provisional_files()
                if not files:
                    self._xft_dirty = True
                    self._wake_pump()
                    return
                for f in files:
                    try:
                        stamp = xft.load(f).stamp
                    except OSError:
                        continue
                    if stamps.get(f) not in (None, stamp):
                        self._xft_dirty = True
                        self._wake_pump()
                    stamps[f] = stamp

        self._xft_poller = threading.Thread(target=poll, name="xefm-xft-poll",
                                              daemon=True)
        self._xft_poller.start()

    def _pump_xft(self) -> bool:
        """On the UI thread: re-read every pane inside an ``.xft`` tree that
        changed. A pane whose group a rewrite renamed follows it by its
        anchor; one whose group is gone returns to the top, and says why."""
        if not getattr(self, "_xft_dirty", False):
            return False
        self._xft_dirty = False
        changed = False
        for name in ("left", "right"):
            pane = self.pane(name)
            if not xft.is_xft_path(pane["path"]):
                continue
            changed = True
            file_path, key = xft.split(pane["path"])
            if pane["path"].exists():
                self._relist(pane)
                continue
            top = key.split("/", 1)[0]
            old = pane.get("_xft_anchor")
            try:
                doc = xft.load(file_path)
                moved = xft.find_group(doc, old) if old else None
            except OSError:
                moved = None
            if moved:
                rest = key.split("/", 1)[1] if "/" in key else ""
                new = Path(xft.uri_for(file_path) + moved + (f"/{rest}" if rest else ""))
                pane["path"] = new if new.exists() else Path(xft.uri_for(file_path) + moved)
                self._refresh(pane)
            else:
                pane["path"] = Path(xft.uri_for(file_path))
                self._refresh(pane)
                self.log_info(f"The group '{top}' changed while the scan went on; "
                              f"back at the top of the tree")
        return changed

    def _note_xft_anchor(self, pane: dict) -> None:
        """Called as a pane lists an ``.xft`` path: remember the anchor of the
        group it is in, so a rewrite that renames the group can be followed
        (:meth:`_pump_xft`), and watch the file if it is provisional."""
        path = pane["path"]
        pane["_xft_anchor"] = None
        if not xft.is_xft_path(path):
            return
        file_path, key = xft.split(path)
        try:
            doc = xft.load(file_path)
        except OSError:
            return
        if doc.provisional:
            self._watch_xft()
        top = key.split("/", 1)[0]
        node = doc.root.child(top) if top else None
        if node is not None and node.is_group:
            pane["_xft_anchor"] = node.anchor_target()

    @staticmethod
    def _sniff_text_encoding(path, sample_size: int = 1024) -> str | None:
        """The codec content search reads ``path`` with, or ``None`` for a file
        with nothing to grep (binary, empty, unreadable) — see
        :func:`xefm.content_read.text_encoding`. The search itself sniffs from
        the handle it reads with (:func:`xefm.content_read.open_text`)."""
        try:
            with path.open("rb") as f:
                chunk = f.read(sample_size)
        except Exception:
            return None
        return content_read.text_encoding(chunk)

    def _iter_content_matches(self, root, regex, cancel, max_line: int = 200,
                              name_filter: str = "", *, recursive: bool = True,
                              keep=None):
        """Walk under ``root`` (:func:`xefm.tree_walk.walk`) yielding
        ``{path, line, text}`` for each
        line of a text file that matches ``regex`` (compiled), checking ``cancel``
        between entries so a superseded search stops promptly. ``name_filter`` is
        the pane's filter (issue #305): when set, only the files it shows are
        read — resolved through :mod:`xefm.filters`, so a typed glob and a filter
        the config defined narrow the search alike — while directories are still
        descended. Binary and (unless
        the pane shows them) hidden entries are skipped, with Unicode BOMs
        deciding text-ness before the binary sniff (``_sniff_text_encoding``).
        The walk is unbounded (issue #305 — a size cap silently hid far-away
        matches); the result cap and cancellation are applied by the dialog
        consuming this generator. ``recursive=False`` greps this directory
        alone — the dialog's subfolder option, and the one that changes what the
        search *costs* rather than how it reads the query.

        Case sensitivity, word boundaries and whether the query is a regular
        expression at all are not decided here: the pattern arrives compiled,
        which is what keeps three of the dialog's four options out of the walk
        entirely (:mod:`xefm.search_options`)."""
        # The pane's filter, whichever kind it is — a typed glob or a filter the
        # config registered — applied to the same entries the pane would show.
        match = filters.matcher(name_filter) if name_filter else None
        shows, descend = _search_rules(self.flm.show_hidden, recursive)

        # On a remote storage the walk's listings and the read-ahead share
        # one pool, so the search as a whole stays within what the storage
        # serves at once (#539). Locally there is no pool: one file at a time.
        # Daemon threads: quitting mid-search drops the reads in flight.
        workers = tree_walk.parallel_reads(root)
        pool = (DaemonPool(workers, name="xefm-search-read")
                if workers > 1 else None)

        def candidates():
            for e, attrs in tree_walk.walk(root, cancel, descend, pool=pool):
                if attrs["is_dir"] or not shows(e, attrs):
                    continue
                # The filter chips (#609), before a byte is read.
                if keep is not None and not keep(e.name, attrs):
                    continue
                try:
                    if match is not None and not match(e, attrs):
                        continue
                except Exception:
                    continue
                yield e, attrs

        if pool is None:
            files = ((e, attrs, None) for e, attrs in candidates())
        else:
            files = content_read.read_ahead(
                candidates(), cancel, pool, workers,
                lambda e, _attrs: not document_text.handles(e))
        try:
            for e, _attrs, read in files:
                stream = None
                try:
                    if document_text.handles(e):
                        # A PDF or an Office file is searched through its
                        # text, the same text the viewer shows (#575).
                        lines = document_text.extract(e).lines
                    else:
                        if read is not None and not content_read.finished(
                                read, cancel):
                            return
                        data = read.result() if read is not None else None
                        stream = lines = (
                            content_read.text_of(data) if data is not None
                            else content_read.open_text(e))
                        if lines is None:
                            continue
                    for line_num, line in enumerate(lines, 1):
                        if cancel.is_set():
                            return
                        if regex.search(line):
                            yield {"path": e, "line": line_num,
                                   "text": line.strip()[:max_line]}
                except Exception:
                    continue
                finally:
                    if stream is not None:
                        stream.close()
        finally:
            if pool is not None:
                # Reads and listings not started are dropped; ones running
                # finish on their own and are discarded.
                pool.shutdown(wait=False, cancel_futures=True)

    def _go_to_content_hit(self, hit) -> None:
        entry = hit["path"]
        pane = self.active_pane()
        pane["path"] = entry.parent
        self._refresh(pane, on_ready=lambda p: self._select_by_name(p, entry.name))
        self.log_info(f"Match: {entry}:{hit['line']}")
        self.panel.render()

    def show_history(self) -> None:
        """The recent-directory picker: pick a previously visited directory and
        jump the active pane there. Shows most-recent-first, de-duplicated.

        The picker's remove key forgets the highlighted directory (#271) — see
        :meth:`_forget_history_path`."""
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
            on_accept=self._go_to_history, on_remove=self._forget_history_path,
            region=self._active_pane_region(), elide_where="middle")
        self.panel.render()

    def _go_to_history(self, path: str) -> None:
        self._jump_pane_to(self.active_pane(), Path(path),
                           log=f"History: {path}")

    def show_programs(self) -> None:
        """The external-programs picker: choose a configured program and launch it
        on the selection (or the focused entry). Launched without blocking the UI,
        with the active pane as the working directory, the ``XEFM_*`` variables in
        the environment, and stdout/stderr streamed into the log pane. An entry
        with ``options {'terminal': True}`` instead gets the terminal via
        suspend/resume (like ``edit_file``) so full-screen programs (vim, less)
        work — in desktop mode, a terminal window of its own. Other
        programs' stdin reads EOF."""
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
        from xefm.external_programs import get_selected_or_cursor_files
        pane = self.active_pane()
        command = list(program.get("command", []))
        if not command:
            self.log_info(f"Program '{program.get('name')}' has no command")
            return
        env, cwd = self._program_env(pane)
        if pane.get("virtual"):
            # A virtual (search-results) pane has no single directory: bare names
            # resolved via one cwd can't reach files scattered across the tree.
            # Pass absolute paths, and run from the search root.
            args = [str(p) for p in self._selected_or_focused(pane)]
        else:
            args = get_selected_or_cursor_files(pane)  # bare names, resolved via cwd
        options = program.get("options") or {}
        self._launch_program(program.get("name", "?"), command + args,
                             cwd=cwd, env=env,
                             terminal=bool(options.get("terminal")))

    def _program_env(self, pane: dict) -> tuple[dict, str]:
        """``(env, cwd)`` for an external program launched from ``pane``: our
        environment plus the ``XEFM_*`` variables, and the pane's directory —
        the root on a virtual pane (a search-results feed, an imported list).
        Shared by the ``PROGRAMS`` picker and ``ctx.run_program()`` so the two can never hand
        a program different contracts."""
        from xefm.external_programs import (build_xefm_env,
                                           ensure_common_paths_in_env,
                                           quote_filenames_with_double_quotes)
        env = os.environ.copy()
        ensure_common_paths_in_env(env)
        env.update(build_xefm_env(self.pm.left_pane, self.pm.right_pane,
                                  self.pm.get_current_pane(),
                                  self.pm.get_inactive_pane()))
        virtual = pane.get("virtual")
        if not virtual:
            return env, str(pane["path"])
        # Same env contract as anywhere else — SELECTED is the selection
        # alone, FOCUSED the cursor — but spelled with absolute paths from
        # the search root rather than bare names, mirroring the argv
        # _run_program builds. A list with no common root runs from the
        # directory the pane showed before it, the one ⌫ goes back to.
        root = virtual["root"]
        cwd = str(pane["path"] if root is name_key.WHOLE_PATH else root)
        env["XEFM_THIS_DIR"] = cwd
        picked = [f for f in pane["files"] if str(f) in pane["selected_files"]]
        env["XEFM_THIS_SELECTED"] = " ".join(
            quote_filenames_with_double_quotes([str(f) for f in picked]))
        hit = self._virtual_focused_entry(pane)
        env["XEFM_THIS_FOCUSED"] = " ".join(
            quote_filenames_with_double_quotes([str(hit)] if hit else []))
        return env, cwd

    def _launch_program(self, name: str, argv: list, *, cwd: str | None,
                        env: dict, terminal: bool) -> int | None:
        """Launch ``argv`` one of two ways. ``terminal`` hands the child the
        tty via suspend/resume and waits, returning its exit code — or, in
        desktop mode, opens it in the ``TERMINAL`` application and returns
        ``None`` at once. Otherwise it runs in the background
        with stdout/stderr streamed into the log pane, and this returns
        ``None`` at once."""
        from xefm.external_programs import SUBPROCESS_NO_WINDOW, resolve_command
        if terminal:
            if is_desktop_mode():
                # No tty of ours to lend: the program gets a terminal window
                # of its own, and we do not wait for it (#472).
                if self._open_terminal(argv, cwd=cwd, env=env,
                                       pause_on_error=True):
                    self.log_info(f"Launched in a terminal: {name}")
                self.panel.render()
                return None
            # Full-screen child (vim, less, a REPL): hand over the tty and wait.
            return self._run_in_terminal(argv, cwd=cwd, env=env,
                                         pause_on_error=True)
        try:
            # Pipes, never the terminal: in TUI mode a direct write would corrupt
            # the screen we own; in desktop mode there may be no terminal at all.
            # stdin reads EOF so an interactive program can't hang on input.
            # SUBPROCESS_NO_WINDOW keeps a console program from flashing a window
            # of its own on Windows, where the GUI backend has no console to lend.
            proc = subprocess.Popen(
                resolve_command(argv, env), cwd=cwd, env=env,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, errors="replace",
                **SUBPROCESS_NO_WINDOW)
        except Exception as exc:
            self.log_info(f"Failed to launch {name}: {exc}")
        else:
            self.log_info(f"Launched: {name}")
            self._watch_program(name, proc)
        self.panel.render()
        return None

    def _watch_program(self, name: str, proc: subprocess.Popen) -> None:
        """Stream a launched program's output into the log pane without blocking
        the UI. Reader threads post complete lines to ``_log_queue`` — the same
        channel as captured stdout/stderr, drained only by the UI thread — and a
        waiter thread reports a nonzero exit code once both streams close."""
        def reader(stream, source):
            for line in stream:
                self._log_queue.put((source, line.rstrip("\n")))
                self._wake_pump()
            stream.close()

        readers = [
            threading.Thread(target=reader, args=(proc.stdout, "STDOUT"),
                             name="xefm-program-out", daemon=True),
            threading.Thread(target=reader, args=(proc.stderr, "STDERR"),
                             name="xefm-program-err", daemon=True),
        ]
        for t in readers:
            t.start()

        def waiter():
            for t in readers:
                t.join()
            code = proc.wait()
            if code != 0:
                self._log_queue.put(("STDERR", f"'{name}' exited with code {code}"))
                self._wake_pump()

        threading.Thread(target=waiter, name="xefm-program-wait",
                         daemon=True).start()

    def _jump_to_favorite(self, fav: favorites.FavoriteEntry) -> None:
        log = f"Jumped to {fav.name} ({fav.path})"
        target = Path(fav.path)
        if fav.is_file:
            self._jump_pane_to(self.active_pane(), target.parent, log=log,
                               select_name=target.name)
        else:
            self._jump_pane_to(self.active_pane(), target, log=log)

    def _select_by_name(self, pane: dict, name: str) -> None:
        """Land the cursor on the entry called ``name`` (after create/rename).

        Compared composed, because ``name`` came from a dialog field and the
        listing holds whatever the filesystem stored."""
        name = name_key.nfc(name)
        for i, entry in enumerate(pane["files"]):
            if name_key.nfc(entry.name) == name:
                pane["focused_index"] = i
                break

    def create_directory(self) -> None:
        """Prompt for a name and create a directory in the active pane — the
        canonical text-input dialog."""
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
                # mkdir(parents=True) accepts "a/b"; the entry that appears in
                # this pane is the first component.
                top = _StdPath(name).parts[0]
                self._relist(pane, on_ready=lambda p: self._select_by_name(p, top))
            self.panel.render()

        show_input(self.panel, title="New Directory", prompt="Name:",
                   on_accept=accept, validate=validate,
                   completer=FilepathCompleter(base_directory=str(pane["path"]),
                                               show_hidden=self.flm.show_hidden),
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
                self._relist(pane, on_ready=lambda p: self._select_by_name(p, name))
            self.panel.render()

        show_input(self.panel, title="New File", prompt="Name:",
                   on_accept=accept, validate=validate,
                   completer=FilepathCompleter(base_directory=str(pane["path"]),
                                               show_hidden=self.flm.show_hidden),
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
        # The name the pane shows, which is the composed one (xefm.name_key), so
        # the field seeds with what the user is looking at and an untouched name
        # compares equal below — no rename, no re-spelling. Editing it writes the
        # composed form back, as a batch rename does.
        original = name_key.nfc(entry.name)
        select_range = _stem_selection(original, entry.is_dir())

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
                release_archives_under(entry)
                entry.rename(entry.parent / name)
            except OSError as exc:
                self.log_info(f"Failed to rename '{original}': {exc}")
            else:
                self.log_info(f"Renamed '{original}' to '{name}'")
                self._relist(pane, on_ready=lambda p: self._select_by_name(p, name))
            self.panel.render()

        show_input(self.panel, title="Rename", prompt="Rename to:", text=original,
                   on_accept=accept, validate=validate, select_range=select_range,
                   completer=FilepathCompleter(base_directory=str(entry.parent),
                                               show_hidden=self.flm.show_hidden),
                   region=self._active_pane_region())
        self.panel.render()

    def batch_rename(self, files: list) -> None:
        """Open the regex batch-rename dialog over the given selected files."""
        pane = self.active_pane()
        # The cursor entry, captured before the modal opens (it owns the keyboard
        # until it closes, so this is still the row the cursor is on then).
        entry = self._focused_entry()
        focused = str(entry) if entry is not None else None

        def done(success: int, errors: list[str], renamed: dict[str, str]) -> None:
            for err in errors:
                self.log_info(f"Rename failed: {err}")
            self.log_info(f"Batch rename: {success} file(s) renamed"
                          + (f", {len(errors)} failed" if errors else ""))
            pane["selected_files"].clear()
            # The focused file is usually one of the renamed ones, so the generic
            # "same file" anchor cannot find it — follow it to its new name, and
            # leave the rest to the anchor (#414).
            new_name = renamed.get(focused) if focused else None
            self._relist(pane, on_ready=(
                (lambda p: self._select_by_name(p, new_name)) if new_name else None))
            self.panel.render()

        show_batch_rename(self.panel, files, on_done=done)
        self.panel.render()

    #: An editor that hands control back faster than this, leaving the list
    #: untouched, is taken to have opened a window of its own and not to be
    #: done yet — so the user is asked to say when they are.
    _EDITOR_RETURNED_AT_ONCE = 1.0
    #: Changes listed by name in the rename confirmation; the rest are counted.
    _RENAME_PREVIEW_ROWS = 20

    def rename_in_editor(self) -> None:
        """Rename the selection — or the focused entry — by editing its names
        in ``TEXT_EDITOR`` (#581): the names go to a temp file one per line, and
        every line changed when the editor is done is a rename of the file that
        line stood for, confirmed before anything moves. Planning and applying
        live in :mod:`xefm.rename_in_editor`; this is the editor round trip."""
        pane = self.active_pane()
        if self._is_archive(pane["path"]):
            self.log_info("Cannot rename inside a read-only archive")
            return
        files = [f for f in self._selected_or_focused(pane) if f.name != ".."]
        if not files:
            self.log_info("No file to rename")
            return
        try:
            text = names_text(files)
        except UnlistableName as exc:
            self.log_info(f"Cannot rename in the editor: {exc}")
            return
        argv = self._editor_argv()
        if not argv:
            self.log_info("No editor configured: set TEXT_EDITOR in "
                          "~/.xefm/config.py")
            return
        fd, name = tempfile.mkstemp(prefix="xefm-rename-", suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        self._rename_edit_round(pane, files, name, argv, text)

    def _rename_edit_round(self, pane: dict, files: list, list_path: str,
                           argv: list, written: str) -> None:
        """One trip to the editor and back for :meth:`rename_in_editor`; the
        review that follows may send the user round again ("Edit Again")."""
        started = time.monotonic()
        if not self._run_editor(argv + [list_path], "the name list"):
            self._discard_rename_list(list_path, "Rename cancelled")
            return
        quick = time.monotonic() - started < self._EDITOR_RETURNED_AT_ONCE
        if self._read_rename_list(list_path) == written and (
                is_desktop_mode() or quick):
            # The editor came straight back without the list changing: a
            # window of its own, still open — always so in desktop mode, where
            # it is detached. Wait for the user to say so.
            def answered(label: str) -> None:
                if label == "Apply":
                    self._review_rename_list(pane, files, list_path, argv)
                else:
                    self._discard_rename_list(list_path, "Rename cancelled")

            show_message_box(
                self.panel,
                f"Edit the names in your editor and save the file, then "
                f"choose Apply.\n\n{list_path}",
                title="Rename in Editor", icon="info",
                buttons=("Apply", "Cancel"), default=0, cancel=1,
                on_result=answered)
            self.panel.render()
            return
        self._review_rename_list(pane, files, list_path, argv)

    @staticmethod
    def _read_rename_list(list_path: str) -> str | None:
        try:
            with open(list_path, encoding="utf-8", newline="") as f:
                return f.read()
        except (OSError, UnicodeDecodeError):
            return None

    def _discard_rename_list(self, list_path: str, message: str) -> None:
        try:
            os.unlink(list_path)
        except OSError:
            pass
        self.log_info(message)
        self.panel.render()

    def _review_rename_list(self, pane: dict, files: list, list_path: str,
                            argv: list) -> None:
        """Read the edited list back, refuse it with reasons or list what it
        would rename, and rename only on the user's say-so."""
        text = self._read_rename_list(list_path)
        if text is None:
            self._discard_rename_list(list_path, "Rename cancelled: the name "
                                      "list could not be read as UTF-8")
            return
        plan = parse_plan(files, text)

        def again_or_cancel(label: str) -> None:
            if label == "Edit Again":
                self._rename_edit_round(pane, files, list_path, argv,
                                        self._read_rename_list(list_path))
            elif label == "Rename":
                self._apply_rename_plan(pane, plan, list_path)
            else:
                self._discard_rename_list(list_path, "Rename cancelled")

        if not plan.ok:
            show_message_box(self.panel, "\n".join(plan.errors),
                             title="Cannot rename", icon="error",
                             buttons=("Edit Again", "Cancel"), default=0,
                             cancel=1, on_result=again_or_cancel)
            self.panel.render()
            return
        if not plan.renames:
            self._discard_rename_list(list_path, "No names changed")
            return
        rows = [f"{name_key.nfc(e.name)}  →  {new}"
                for e, new in plan.renames[:self._RENAME_PREVIEW_ROWS]]
        more = len(plan.renames) - len(rows)
        if more:
            rows.append(f"… and {more} more")
        show_message_box(self.panel, "\n".join(rows),
                         title=f"Rename {len(plan.renames)} item(s)?",
                         icon="question",
                         buttons=("Rename", "Edit Again", "Cancel"), default=0,
                         cancel=2, on_result=again_or_cancel)
        self.panel.render()

    def _apply_rename_plan(self, pane: dict, plan, list_path: str) -> None:
        entry = self._focused_entry()
        focused = str(entry) if entry is not None else None

        def rename(src, dst) -> None:
            release_archives_under(src)
            src.rename(dst)

        renamed, errors = apply_plan(plan, rename)
        for err in errors:
            self.log_info(f"Rename failed: {err}")
        self._discard_rename_list(
            list_path, f"Renamed {len(renamed)} item(s) in the editor"
            + (f", {len(errors)} failed" if errors else ""))
        pane["selected_files"].clear()
        new_name = renamed.get(focused) if focused else None
        self._relist(pane, on_ready=(
            (lambda p: self._select_by_name(p, new_name)) if new_name else None))
        self.panel.render()

    def _ensure_archive_password(self, entry, on_ready) -> None:
        """Gate opening ``entry`` when it lives inside an encrypted archive.

        For a file inside a password-protected archive with no password yet known,
        prompt (masked), verify, remember it for the session, then run
        ``on_ready()``. Archives whose encryption XeFM cannot decrypt at all — a
        WinZip AES zip, or any encrypted 7z, since libarchive decrypts only zip —
        are refused with a message instead of a prompt no password could satisfy.
        Ordinary files, unencrypted archive entries, and archives whose password is
        already known run ``on_ready()`` at once.

        ``on_ready`` is responsible for its own redraw, since the prompt path
        reaches it from an asynchronous dialog callback."""
        from xefm.archive import (
            archive_password_state, get_member_archive_path, try_archive_password)
        state = archive_password_state(entry)
        if state == "ok":
            on_ready()
            return
        if state == "unsupported":
            self.log_info(f"Cannot open {entry.name}: its encryption is not supported")
            self.panel.render()
            return
        # state == "need": prompt for the password.
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
            # Prev/next in the viewer drags the pane's cursor along, so the list
            # beneath tracks the tour and closing lands on the image last shown.
            on_navigate = None
            if pane is not None and len(siblings) > 1:
                on_navigate = lambda path: self._follow_viewer_cursor(pane, path)
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
                              on_close=self._restore_post_effect if has_effect else None,
                              on_navigate=on_navigate)
        elif document_text.handles(entry):
            # A PDF or an Office file: read its text first, on a task, since a
            # document is parsed whole and may be large or remote (#575).
            self._open_document(entry)
            return
        else:
            show_text_viewer(self.panel, entry, state_manager=self.state_manager,
                             on_edit=lambda path: self._edit_entries([path]))
        self.panel.render()

    def _open_document(self, entry) -> None:
        """Extract ``entry``'s text (:mod:`xefm.document_text`) on a task —
        the progress dialog shows, Esc stops it — then open the text viewer on
        it: raw mode its plain text, rich mode its structure."""
        task = Task(f"Reading {entry.name}…", config=self.config, kind="document",
                    busy_label="Reading…")

        def run(t: Task) -> dict:
            extracted = document_text.extract(entry)
            return {"document": extracted, "cancelled": t.cancelled()}

        def on_done(res: dict) -> None:
            doc = res.get("document")
            if res.get("cancelled") or doc is None:
                self.log_info(f"{entry.name}: not opened")
            else:
                if doc.problem:
                    key = keys_label_for_action("open_with_os")
                    hint = f" — {key} opens it in its application" if key else ""
                    self.log_info(f"{entry.name}: {doc.problem}{hint}")
                show_text_viewer(self.panel, entry, state_manager=self.state_manager,
                                 on_edit=lambda path: self._edit_entries([path]),
                                 document=doc)
            self.panel.render()

        self.tasks.submit(task, self.panel, run=run, on_done=on_done)

    def _restore_post_effect(self) -> None:
        """Re-apply the active theme's post-effect and repaint — the close hook
        for the image viewer, which suspends it for a faithful picture."""
        self._apply_post_effect(self.themes[self._theme_index][1])
        self.panel.render()

    @staticmethod
    def _follow_viewer_cursor(pane: dict, path) -> None:
        """The image viewer stepped to another file: land ``pane``'s cursor on
        it. Matched by full path — a virtual (search-results) pane lists hits
        from many directories, where names alone can collide. A file the pane no
        longer lists (a refresh happened under the viewer) is a no-op; the pane
        widget auto-scrolls to a moved cursor on the next draw."""
        for i, f in enumerate(pane["files"]):
            if str(f) == str(path):
                pane["focused_index"] = i
                return

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
        if command and self._launch_associated([entry], command):
            self.log_info(f"Viewing {entry.name} with {command[0]}")
            return
        self._ensure_archive_password(entry, lambda: self._open_viewer(entry, pane))

    def diff_files(self) -> None:
        """Compare exactly two selected files side by side. Files may be selected
        across both panes."""
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
        self.open_diff(files[0], files[1])

    def open_diff(self, left, right, titles: tuple[str | None, str | None] = (None, None)) -> None:
        """Compare two files: side by side when both are text, byte for byte
        when either is binary. ``diff_files`` and ``ctx.diff`` (#824) both end
        here, so the two cannot drift."""
        if looks_binary(left) or looks_binary(right):
            # A text diff of two placeholders answers nothing; say whether the
            # bytes match instead (#631).
            show_byte_comparison(self.panel, self.tasks, left, right,
                                 config=self.config)
            return
        show_diff_viewer(self.panel, left, right, titles=titles)
        self.panel.render()

    def diff_directories(self) -> None:
        """Recursively compare the two panes' current directories side by side."""
        left = self.pane("left")["path"]
        right = self.pane("right")["path"]
        show_directory_diff_viewer(self.panel, left, right,
                                   show_hidden=self.flm.show_hidden, config=self.config,
                                   monitor=self.file_monitor)
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
        name when nothing is selected — to the system clipboard, one per line.
        In terminal mode the copy rides OSC 52, so it reaches the user's own
        clipboard on terminals that honor it (and stays process-local on the
        ones that don't, e.g. Terminal.app); either way the copy succeeds.

        The name copied is the one the pane *shows*: on a virtual (search-results)
        pane that is the path relative to the search root — ``sub/dir/a.txt``,
        not a bare, location-less ``a.txt`` that says nothing about which of
        several hits it was (issue #433). Verbatim, though, not the NFC form the
        name column renders: a copied name gets pasted into a shell or an editor,
        where it has to address the file that is actually on disk (see
        :mod:`xefm.name_key`)."""
        virtual = self.active_pane().get("virtual")
        root = virtual["root"] if virtual else None
        self._copy_to_clipboard(lambda f: name_key.rel_name(f, root), "name")

    # --- the file clipboard (#577) ------------------------------------------------

    def clipboard_put(self, *, cut: bool) -> None:
        """Copy (or cut) the selection — or the cursor item — to the file
        clipboard. Nothing on disk changes: the files are copied or moved when
        they are pasted, wherever the user is standing then.

        With text selected in the log pane, the copy chord copies that text
        instead — the highlight is on screen, so the chord acts on what can
        be seen, as it did before the file clipboard existed."""
        if not cut and self.log.selection_text():
            self.copy_log_selection()
            return
        pane = self.active_pane()
        targets = self._selected_or_focused(pane)
        if not targets:
            self.log_info("Nothing to copy" if not cut else "Nothing to cut")
            return
        local = [str(t) for t in targets if self._is_local(t)]
        to_os = self.clipboard.put(targets, cut=cut, local_paths=local)
        n = len(targets)
        what = f"{n} item{'' if n == 1 else 's'}"
        paste = self._keys_label("clipboard_paste")
        verb = "Cut" if cut else "Copied"
        then = "they move when you paste" if cut else "paste puts copies"
        note = " (also on the system clipboard)" if to_os else ""
        self.log_info(f"{verb} {what} to the clipboard{note} — {then} "
                      f"into the folder you are in ({paste})")
        self._clipboard_changed()

    #: Paths the clipboard dialog lists before "and N more".
    _CLIPBOARD_SHOW_MAX = 20

    def clipboard_clear(self) -> None:
        self.clipboard.clear()
        self.log_info("Clipboard cleared")
        self._clipboard_changed()

    def clipboard_paste(self) -> None:
        """Paste the clipboard into the active pane's folder: copy what was
        copied, move what was cut, through the shared engine (confirmation
        and conflict dialog as for C / M). Files another application put on
        the system clipboard after XeFM's last copy are what is pasted then,
        and the log says so."""
        contents = self.clipboard.contents()
        if contents is None:
            self.log_info("The clipboard is empty")
            return
        pane = self.active_pane()
        if pane.get("virtual"):
            self.log_info("Cannot paste here: this pane is a list of results, "
                          "not a folder")
            return
        if self._is_archive(pane["path"]):
            self.log_info("Cannot paste here: this is a read-only archive")
            return
        dest = pane["path"]
        sources = list(contents.paths)
        if contents.cut:
            # A cut pasted where it already is moves nothing.
            sources = [p for p in sources if str(p.parent) != str(dest)]
            if not sources:
                self.log_info("Nothing to move: the cut items are already here")
                return
        origin = " from another app" if contents.from_other_app else ""
        kind = "move" if contents.cut else "copy"

        def on_complete(result: dict) -> None:
            self._relist(self.pm.left_pane)
            self._relist(self.pm.right_pane)
            self.log_info(format_op_summary(kind.capitalize(), result) + origin)
            self._report_op_failures(kind.capitalize(), result)
            if not result.get("cancelled"):
                if contents.from_other_app:
                    if contents.cut:
                        self.clipboard.take_os()
                else:
                    self.clipboard.consume()
            self._clipboard_changed()
            self._clipboard_ramp_hint()
            self.panel.render()

        op = self._fileops.move if contents.cut else self._fileops.copy
        op(self.panel, sources, dest, on_complete=on_complete, log=self.log_info)
        self.panel.render()

    _clipboard_ramp_shown = False

    def _clipboard_ramp_hint(self) -> None:
        """Once per session, after a paste: the two-pane way is one key. The
        clipboard is a ramp, not a destination (#342)."""
        if self._clipboard_ramp_shown:
            return
        self._clipboard_ramp_shown = True
        c, m = self._keys_label("copy_files"), self._keys_label("move_files")
        if c and m:
            self.log_info(f"Tip: {c} / {m} copy or move the selection straight to "
                          f"the other pane, in one step")

    def _clipboard_changed(self) -> None:
        """Re-mark the rows on the clipboard in both panes."""
        marks = self.clipboard.marks()
        for view in (self.left_view, self.right_view):
            view.clipboard_source = self.clipboard
            view.clipboard_marks = marks
            view.clipboard_cut = self.clipboard.cut
        self.status.invalidate()

    def _set_text_clipboard(self, text: str) -> None:
        """Put ``text`` on the clipboard. It is one clipboard: a text copy
        replaces the files XeFM was holding, here as on the OS clipboard —
        explicitly, so it holds where there is no OS bridge (Linux) too."""
        self.panel.set_clipboard(text)
        if self.clipboard.paths:
            self.clipboard.clear()
            self._clipboard_changed()

    def clipboard_show(self) -> None:
        """What the clipboard holds, with Paste Here and Clear — also what a
        click on the status bar's ``[COPY n]`` opens."""
        contents = self.clipboard.contents()
        if contents is None:
            self.log_info("The clipboard is empty")
            self.panel.render()
            return
        verb = "Cut" if contents.cut else "Copied"
        where = " (from another application)" if contents.from_other_app else ""
        shown = [str(p) for p in contents.paths[:self._CLIPBOARD_SHOW_MAX]]
        more = len(contents.paths) - len(shown)
        lines = shown + ([f"… and {more} more"] if more else [])

        def answered(label: str) -> None:
            if label == "Paste Here":
                self.clipboard_paste()
            elif label == "Clear":
                self.clipboard_clear()
            self.panel.render()

        show_message_box(
            self.panel, "\n".join(lines),
            title=f"{verb}: {len(contents.paths)} item(s){where}",
            icon="info", buttons=("Paste Here", "Clear", "Close"),
            default=0, cancel=2, on_result=answered)
        self.panel.render()

    def _paste_preview(self, pane: dict) -> str:
        """The pane footer's "paste: 2 conflicts" — from the names the pane
        already lists, cached until the clipboard or the listing changes."""
        if pane.get("virtual"):
            return ""
        contents = self.clipboard.contents()
        if contents is None:
            return ""
        key = (id(pane["files"]), len(pane["files"]), str(pane["path"]),
               self.clipboard.version, contents.paths)
        cache = pane.get("_paste_preview")
        if cache is not None and cache[0] == key:
            return cache[1]
        n = clipboard_conflicts(contents, pane["path"], (f.name for f in pane["files"]))
        text = f"paste: {n} conflict{'' if n == 1 else 's'}" if n else ""
        pane["_paste_preview"] = (key, text)
        return text

    def copy_paths_to_clipboard(self) -> None:
        """Copy the active pane's selected full path(s) — or the cursor entry's
        path when nothing is selected — to the system clipboard, one per
        line."""
        self._copy_to_clipboard(lambda f: str(_real_entry(f) or f), "path")

    def open_list_from_clipboard(self) -> None:
        """Show the paths on the clipboard, one per line, as the active pane's
        listing — the inverse of ``copy_paths`` (#453).

        The list comes from anywhere that can put text on a clipboard: a
        search tool's "copy full paths", ``find … | pbcopy``, a column out of a
        spreadsheet, a list pasted in chat. Nothing is touched on disk — this
        changes what the pane *shows*, and ⌫ goes back to the directory. That is
        the line between this and a paste: "show me these files", not "put
        these files here".

        A relative line resolves against the directory the pane is showing,
        because the clipboard carries no anchor of its own."""
        lines = path_list.parse(self.panel.get_clipboard())
        if not lines:
            self.log_info("The clipboard holds no paths to import")
            return
        self.open_path_list(self.pm.active_pane, lines,
                            title="Clipboard")

    #: State key for the commands ``open_list_from_command`` has run, most
    #: recent first — the commonest next command is one already run.
    _LIST_COMMAND_STATE = "list_command.history"
    _LIST_COMMAND_HISTORY_MAX = 100

    def open_list_from_command(self) -> None:
        """Run a command and show the paths it prints, one per line, as the
        active pane's listing — Midnight Commander's *External panelize*
        (#453 ③).

        ``rg -l TODO``, ``git ls-files -m``, ``fd -e py``, ``es.exe <query>``:
        any tool that prints paths becomes a search XeFM can show, with no
        clipboard in between. The command runs through the shell in the
        pane's directory, with the same ``XEFM_*`` environment a ``PROGRAMS``
        entry gets, and relative lines resolve against that same directory.
        The dialog is a command field over the command history, most recent
        first (:mod:`xefm.history_input_dialog`): typing narrows the history,
        ↓ copies a command into the field to run or change, and Enter runs
        whatever the field holds — never a row the typing merely matched.
        Shift-Delete forgets a command while browsing."""
        pane = self.active_pane()
        _env, cwd = self._program_env(pane)
        if path_schemes.is_uri(cwd):
            self.log_info(f"Commands run in a local directory; this pane is "
                          f"showing {cwd}")
            return

        def run(text: str) -> None:
            command = text.strip()
            if command:
                self._run_list_command(self.pm.active_pane, command)
            self.panel.render()

        show_history_input(
            self.panel, self._list_command_history(),
            title="Open List from Command", prompt="Command:",
            accept_label="run", on_accept=run,
            on_remove=self._forget_list_command, on_cancel=self.panel.render,
            region=self._active_pane_region())
        self.panel.render()

    # --- the OS search index (#579) ----------------------------------------------

    _INDEX_STATE = "index_search.history"

    def index_search(self) -> None:
        """Search the index the OS keeps — Spotlight on macOS, Windows Search
        on Windows — under the active pane's folder (#579): the search dialog
        in its index mode (#609), results streaming in as the query is typed,
        Enter feeding them to the pane. The query is the engine's own language
        — Spotlight reads it as its search field does (words, ``kind:pdf``,
        metadata predicates); Windows Search matches words against names and
        contents, or takes ``where …`` as raw SQL — and the filter chips need
        none of it."""
        why = self._index_scope(self.active_pane())
        if why:
            self.log_info(why)
            self.panel.render()
            return
        self._open_search("index")

    def _query_history(self, key: str) -> list:
        """The queries stored under state ``key``, most recent first. Not
        ``_history``: that is the directory history list, set per instance,
        which shadowed this method and broke the index search (#607)."""
        history = self.state_manager.get_state(key, [])
        return [c for c in history if isinstance(c, str)] if isinstance(history, list) else []

    def _record_history(self, key: str, entry: str) -> None:
        history = [c for c in self._query_history(key) if c != entry]
        history.insert(0, entry)
        self.state_manager.set_state(key, history[:self._LIST_COMMAND_HISTORY_MAX])

    def _forget_history(self, key: str, entry: str) -> bool:
        history = self._query_history(key)
        if entry not in history:
            return False
        history.remove(entry)
        self.state_manager.set_state(key, history)
        return True

    def _run_index_search(self, pane_name: str, query: str, scope: str, *,
                          title: str | None = None, run_search=None) -> None:
        """Query the OS index on a task — the progress dialog counts matches,
        Esc stops it — and open what it found as ``pane_name``'s list."""
        engine = os_index.engine() or "Index"
        title = title or f"{engine}: {query}"
        task = Task(title, config=self.config, kind="index_search", busy_label="Searching…")
        search = run_search or (lambda t: os_index.search(
            query, scope, cancelled=t.cancelled,
            on_count=lambda n: setattr(t, "counted", n)))

        def run(t: Task) -> dict:
            return {"result": search(t), "cancelled": t.cancelled()}

        def on_done(res: dict) -> None:
            result = res.get("result")
            if res.get("cancelled") or result is None or result.cancelled:
                self.log_info(f"{title}: stopped")
            elif result.error:
                self.log_info(f"{title}: {result.error}")
            elif not result.paths:
                self.log_info(f"{title}: nothing found")
            else:
                self.open_path_list(pane_name, result.paths, title=title, base=scope)
            self.panel.render()

        self.tasks.submit(task, self.panel, run=run, on_done=on_done)

    def _open_saved_search(self, pane: dict, entry) -> None:
        """``Enter`` on a Finder saved search (a Smart Folder's
        ``.savedSearch``): run its query in its scopes and show the matches as
        a list, titled with its name."""
        try:
            query, scopes = os_index.read_saved_search(entry.read_bytes())
        except (OSError, ValueError) as e:
            self.log_info(f"{entry.name}: {e}")
            return
        self._run_index_search(
            self._pane_name_of(pane), query, str(pane["path"]), title=entry.stem,
            run_search=lambda t: os_index.search_saved(
                query, scopes, cancelled=t.cancelled,
                on_count=lambda n: setattr(t, "counted", n)))

    def _list_command_history(self) -> list:
        """The commands run so far, most recent first."""
        history = self.state_manager.get_state(self._LIST_COMMAND_STATE, [])
        return [c for c in history if isinstance(c, str)] \
            if isinstance(history, list) else []

    def _record_list_command(self, command: str) -> None:
        """Put ``command`` at the head of the history, once."""
        history = [c for c in self._list_command_history() if c != command]
        history.insert(0, command)
        self.state_manager.set_state(self._LIST_COMMAND_STATE,
                                     history[:self._LIST_COMMAND_HISTORY_MAX])

    def _forget_list_command(self, command: str) -> bool:
        """Drop ``command`` from the history (the picker's remove key)."""
        history = self._list_command_history()
        if command not in history:
            return False
        history.remove(command)
        self.state_manager.set_state(self._LIST_COMMAND_STATE, history)
        return True

    def _run_list_command(self, pane_name: str, command: str) -> None:
        """Run ``command`` for :meth:`open_list_from_command` on a task, with
        the progress dialog counting the lines it prints and Esc stopping it —
        the whole process tree, not only the shell — then hand its output to
        :meth:`open_path_list`.

        The command runs once. A refresh after a file operation drops the rows
        that are gone, as for any list; it does not run the command again,
        which after every delete would be slow and would reorder the rows
        under the cursor."""
        pane = self.pane(pane_name)
        env, cwd = self._program_env(pane)
        self._record_list_command(command)
        task = Task(command, config=self.config, kind="list_command",
                    busy_label="Running…")

        def run(t: Task) -> dict:
            output = command_list.run(
                command, cwd=cwd, env=env, cancelled=t.cancelled,
                on_count=lambda n: setattr(t, "counted", n))
            return {"output": output, "cancelled": output.cancelled}

        def on_done(res: dict) -> None:
            output = res.get("output")
            if output is None or output.cancelled:
                self.log_info(f"{command}: cancelled")
            elif output.code is None:
                self.log_info(f"{command}: could not run: {output.error}")
            else:
                self._open_command_output(pane_name, command, cwd, output)
            self.panel.render()

        self.tasks.submit(task, self.panel, run=run, on_done=on_done)

    def _open_command_output(self, pane_name: str, command: str, cwd: str,
                             output) -> None:
        """Show what ``command`` printed, or say why there is nothing to show.

        A nonzero exit is not by itself a failure: ``grep`` and ``rg`` exit 1
        for "no match", and a ``find`` that met one unreadable directory exits
        1 having printed everything else. So paths that arrived are shown
        whatever the code, and the code is only reported when nothing did —
        together with the command's last words on stderr, which is where it
        says why."""
        for line in output.stderr_tail:
            self._log_queue.put(("STDERR", line))
        self._wake_pump()
        lines = path_list.parse(output.stdout)
        if not lines:
            code = f" (exit code {output.code})" if output.code else ""
            self.log_info(f"{command}: printed no paths{code}")
            return
        self.open_path_list(pane_name, lines, title=command, base=cwd)

    def open_path_list(self, pane_name: str, paths, *, title: str,
                       base=None) -> None:
        """Open ``paths`` in pane ``pane_name`` as a virtual listing headed
        ``title`` — the one door every file-list source comes through: the
        clipboard import, and ``PaneApi.open_list`` for a config's own.

        ``paths`` are strings or ``Path`` objects. A relative one resolves
        against ``base`` (the pane's directory when not given); absolute paths
        and URIs stand as they are, so one list can span drives, hosts and
        schemes. Which of them exist is found on a worker thread, and the pane
        changes only once that answer lands — to the ones that do, or not at
        all if none do. The status line says how many were left out, and how
        many were resolved relatively, since a relative path resolved against
        the wrong directory finds a real file that is not the one meant."""
        pane = self.pane(pane_name)
        if base is None:
            base = pane["path"]
        lines = [str(p) for p in paths]
        self._open_list(pane_name, title=title,
                        load=lambda: path_list.resolve(lines, base),
                        relative_to=str(base))

    def _open_list(self, pane_name: str, *, title: str, load,
                   relative_to: str) -> None:
        """Open the set ``load()`` resolves as pane ``pane_name``'s listing,
        headed ``title``, and report it — the tail every file-list source
        shares. ``load`` runs on the worker (:meth:`_list_virtual`), so a source
        may do its reading there. ``relative_to`` names what relative lines
        were resolved against, for the report."""
        pane = self.pane(pane_name)
        # The row go_parent lands back on, by name in pane["path"]'s listing:
        # the one the list was opened from, or — opened over another list —
        # wherever that one would have returned.
        previous = pane.get("virtual")
        if previous:
            return_to = previous.get("return_to")
        else:
            files = pane["files"]
            return_to = files[pane["focused_index"]].name if files else None
        virtual = {"kind": "list", "title": title, "root": None,
                   "results": [], "meta": {}, "return_to": return_to}
        report = {}

        def details() -> str:
            parts = []
            if report.get("missing"):
                parts.append(f'{report["missing"]} not found')
            if report.get("unreachable"):
                parts.append(f'{report["unreachable"]} unreachable')
            if report.get("relative"):
                parts.append(f'{report["relative"]} resolved relative to '
                             f'{relative_to}')
            parts.extend(f"could not read {p}" for p in report.get("problems", ()))
            return f" ({', '.join(parts)})" if parts else ""

        def counted(result: dict) -> None:
            report.update({k: result.get(k) for k in
                           ("missing", "unreachable", "relative", "problems",
                            "total")})

        def landed(p: dict) -> None:
            n = len(virtual["results"])
            self.log_info(f"{title}: {n} item{'' if n == 1 else 's'}"
                          f"{details()}  — {self._virtual_keys_hint()}")

        def empty(result: dict) -> None:
            counted(result)
            total = report.get("total") or 0
            if not total:
                self.log_info(f"{title}: no paths to show{details()}")
                return
            self.log_info(f"{title}: none of the {total} "
                          f"path{'' if total == 1 else 's'} could be shown"
                          f"{details()}")

        self.log_info(f"{title}: reading…")
        self._list_virtual(pane, virtual, on_ready=landed, on_empty=empty,
                           on_result=counted, load=load)
        self.panel.render()

    def open_list_from_file(self) -> None:
        """Open the list file under the cursor — or every selected one, as one
        list — as the active pane's listing: one path per line (#453 ②).

        A relative line resolves against the directory its own list file is
        in, the convention of M3U playlists and ``.gitignore``: a list kept
        beside the files it names keeps working wherever the folder goes, and
        reads the same from whichever pane it is opened. The file is read on
        the listing worker, so a list on a remote host does not hold the UI.
        Directories among the selection are skipped."""
        pane = self.active_pane()
        info = pane.get("file_info") or {}
        files = [f for f in self._selected_or_focused(pane)
                 if not (info.get(str(f)) or {}).get("is_dir")]
        if not files:
            self.log_info("Open List from File: put the cursor on a text file "
                          "that lists paths, one per line")
            return
        self._open_list_files(self.pm.active_pane, files)

    def _open_list_files(self, pane_name: str, files) -> None:
        """Open the list files ``files`` as one list in pane ``pane_name`` —
        behind both Open List from File and an ``'enter': 'list'`` rule."""
        title = files[0].name if len(files) == 1 else \
            f"{files[0].name} +{len(files) - 1}"
        relative_to = (str(files[0].parent) if len(files) == 1
                       else "each list's folder")
        self._open_list(pane_name, title=title,
                        load=lambda: path_list.read_lists(files),
                        relative_to=relative_to)

    def flat_view(self) -> None:
        """Show every file below the active pane's directory as one flat list —
        flat view (#547) — or, on a pane already showing one, go back.

        Everything that works on a list works here: sort by size to find what
        takes the space, by date to see what changed across the tree, filter by
        ``*.jpg`` and copy the matches into one folder. Rows are named relative
        to the directory, as search results are.

        With a selection, only that is flattened: each selected directory's
        files, and each selected file as itself — the narrower view, without a
        second key. Files only: a directory has no row of its own, since every
        file below it is already there.

        The walk is :func:`xefm.tree_walk.walk`, on a task with the progress
        dialog counting what it found and Esc stopping it, so a large or remote
        tree never holds the window. Hidden entries follow the pane: what it
        does not show is neither listed nor descended. Symbolic links to
        directories are not descended, so a link back up the tree cannot make
        the walk endless. The list is a snapshot — leave it and come back to
        see what has changed since."""
        pane = self.active_pane()
        virtual = pane.get("virtual")
        if virtual and virtual.get("kind") == "flat":
            self._go_parent(pane)
            return
        if virtual:
            self.log_info("Flat view lists a directory's files; this pane is "
                          "showing a list")
            return
        info = pane.get("file_info") or {}
        selected = [f for f in pane["files"] if str(f) in pane["selected_files"]]
        roots = [f for f in selected if (info.get(str(f)) or {}).get("is_dir")]
        picked = [f for f in selected if f not in roots]
        if not selected:
            roots = [pane["path"]]
        self._run_flat_walk(self.pm.active_pane, roots, picked)

    def _run_flat_walk(self, pane_name: str, roots: list, picked: list) -> None:
        """Walk ``roots`` for :meth:`flat_view` on a task and open what it
        finds, together with the files ``picked`` from the selection, as pane
        ``pane_name``'s flat list. Esc stops the walk and leaves the pane as
        it was: a part of a tree, in whatever order the storage answered,
        would look complete and not be."""
        pane = self.pane(pane_name)
        root = pane["path"]
        show_hidden = self.flm.show_hidden
        # The selected files' records from the listing the pane already has —
        # copied without the compared name, which was made for a directory pane
        # and is recomputed relative to the listing's root.
        records = {str(p): a for p, a in (pane.get("_listing_entries") or ())}
        picked_entries = [(f, {k: v for k, v in records[str(f)].items()
                               if k != "cmp_name"})
                          for f in picked if str(f) in records]
        task = Task(f"Flat view: {root}", config=self.config,
                    kind="flat_view", busy_label="Reading…")

        def run(t: Task) -> dict:
            flag = types.SimpleNamespace(is_set=t.cancelled)
            found = list(picked_entries)
            for r in roots:
                for entry, attrs in _flat_files(r, flag, show_hidden):
                    found.append((entry, attrs))
                    t.counted = len(found)
            return {"entries": found, "cancelled": t.cancelled()}

        def on_done(res: dict) -> None:
            if res.get("cancelled") or "entries" not in res:
                self.log_info("Flat view: cancelled")
            else:
                self._open_flat(pane_name, root, res["entries"])
            self.panel.render()

        self.tasks.submit(task, self.panel, run=run, on_done=on_done)

    def _open_flat(self, pane_name: str, root, entries: list) -> None:
        """Install ``entries`` — the walk's ``(Path, attrs)`` — as pane
        ``pane_name``'s flat list, named relative to ``root``. Go to parent,
        or the flat view key again, lands back on the row the cursor was on."""
        pane = self.pane(pane_name)
        if not entries:
            self.log_info(f"Flat view: no files below {root}")
            return
        files = pane["files"]
        idx = pane["focused_index"]
        return_to = files[idx].name if files and 0 <= idx < len(files) else None
        virtual = {"kind": "flat", "title": "Flat view", "root": root,
                   "results": [p for p, _ in entries], "meta": {},
                   "return_to": return_to}

        def landed(p: dict) -> None:
            n = len(virtual["results"])
            self.log_info(f"Flat view: {n} file{'' if n == 1 else 's'} below "
                          f"{root}  — {self._keys_label('flat_view')} or "
                          f"{self._keys_label('go_parent')} back")

        self._list_virtual(pane, virtual, on_ready=landed, entries=entries)
        self.panel.render()

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
        self._set_text_clipboard(text)
        count = len(targets)
        self.log_info(f"Copied {count} {label}{'s' if count != 1 else ''} to clipboard")

    def copy_log_selection(self) -> None:
        """Copy the log pane's selected text — dragged out with the mouse — to
        the clipboard, then drop the highlight.

        Focus-independent, like every other action that reaches into the log
        (``scroll_log_up`` and friends drive the pane from the file list): the
        highlight is on screen, so the chord acts on what the user can see
        rather than on wherever focus happens to sit. A no-op when nothing is
        selected, which is what keeps the chord from meaning anything at all in
        the common case."""
        text = self.log.selection_text()
        if not text:
            return
        self._set_text_clipboard(text)
        self.log.clear_selection()

    def copy_log_all(self) -> None:
        """Copy the whole log — every line still in the pane's buffer, not only
        the ones on screen — to the clipboard (issue #360).

        Selecting log text is mouse-only, so this is the one a keyboard user can
        reach, and it is what "paste your log into the issue" actually wants."""
        lines = [text for text, _style in self.log.lines]
        if not lines:
            self.log_info("Log is empty")
            return
        self._set_text_clipboard("\n".join(lines))
        count = len(lines)
        self.log_info(f"Copied {count} log line{'s' if count != 1 else ''} to clipboard")

    def copy_files(self) -> bool:
        """Copy the active pane's selection (or cursor entry) into the other
        pane's directory (the 'C' key).
        Returns True when a guard bailed out synchronously (see ``_transfer``)."""
        return self._transfer("copy")

    def move_files(self) -> bool:
        """Move the active pane's selection (or cursor entry) into the other
        pane's directory (the 'M' key, when a selection exists).
        Returns True when a guard bailed out synchronously (see ``_transfer``)."""
        return self._transfer("move")

    def copy_files_to(self) -> bool:
        """Copy the active pane's selection (or cursor entry) into a directory
        typed in a prompt (the 'Shift-C' key) — cfiler's CopyInput.
        Returns True when a guard bailed out synchronously (see ``_transfer``)."""
        return self._transfer_to_path("copy")

    def move_files_to(self) -> bool:
        """Move the active pane's selection (or cursor entry) into a directory
        typed in a prompt (the 'Shift-M' key) — cfiler's MoveInput.
        Returns True when a guard bailed out synchronously (see ``_transfer``)."""
        return self._transfer_to_path("move")

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
            self._relist(pane, on_ready=on_ready)
            self._relist_others_showing({str(pane["path"])}, besides=pane)
            self.log_info(format_op_summary("Duplicate", result))
            self._report_op_failures("Duplicate", result)
            self.panel.render()

        self._fileops.duplicate(self.panel, targets, pane["path"],
                                on_complete=on_complete, log=self.log_info)
        return False

    def _relist_others_showing(self, dirs: set, besides: dict | None) -> None:
        """Re-list every pane but ``besides`` that shows one of ``dirs`` (as
        strings) — the completion rule every file operation shares. An
        operation silences the watchers of the directories it changes and drops
        their events (#243), so the other pane, when it is on one of them, is
        brought up to date only here.

        A virtual pane (search results, an imported list, a flat view) is never
        re-listed from here: it is a snapshot, updated by what is done *in* it
        and by Reread, not by an operation in the other pane."""
        for pane in (self.pm.left_pane, self.pm.right_pane):
            if (pane is not besides and not pane.get("virtual")
                    and str(pane["path"]) in dirs):
                self._relist(pane)

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
            # nowhere to write. Reveal a real destination first (the pane-sync
            # actions).
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
        targets = self._selected_or_focused(src_pane)
        if not targets:
            self.log_info(f"No file to {kind}")
            return True
        return self._run_transfer(kind, src_pane, targets, dst_pane["path"])

    def _run_transfer(self, kind: str, src_pane: dict, targets: list, dest_dir) -> bool:
        """Copy or move ``targets`` from ``src_pane`` into ``dest_dir`` — the other
        pane's directory for C / M, a typed one for Shift-C / Shift-M. Callers
        have already cleared the destination as a writable directory. On
        completion, every pane showing ``dest_dir`` is re-listed, and on a move
        the source pane and every pane showing a source directory too
        (:meth:`_relist_others_showing`). Same return contract as
        ``_transfer``."""
        verb = "Copy" if kind == "copy" else "Move"
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
            changed = {str(dest_dir)}
            if kind == "move":
                # The source directories lost entries too: the other pane may
                # show one of them when the destination was typed (Shift-M).
                changed |= {str(t.parent) for t in targets}
                self._relist(src_pane)
            self._relist_others_showing(changed, besides=src_pane if kind == "move" else None)
            src_pane["selected_files"].clear()
            self.log_info(format_op_summary(verb, result))
            self._report_op_failures(verb, result)
            self.panel.render()

        op = self._fileops.copy if kind == "copy" else self._fileops.move
        op(self.panel, targets, dest_dir, on_complete=on_complete, log=self.log_info)
        return False

    def _transfer_for_api(self, kind: str, targets: list, dest_dir,
                          on_complete: "Callable[[dict], None]",
                          on_declined: "Callable[[], None]") -> None:
        """``ctx.copy`` / ``ctx.move`` (#716): the same operation C / M start —
        confirmation, conflict dialog, job queue, progress — on targets and a
        destination the caller chose, then the same completion: every pane
        showing the destination or a moved item's directory is re-listed, the
        summary logged and failures reported. ``on_complete(result)`` follows
        with the service's result; ``on_declined()`` instead when the user
        cancels at the confirmation. The caller has already checked the
        arguments."""
        verb = "Copy" if kind == "copy" else "Move"

        def done(result: dict) -> None:
            changed = {str(dest_dir)}
            if kind == "move":
                changed |= {str(t.parent) for t in targets}
            self._relist_others_showing(changed, besides=None)
            self.log_info(format_op_summary(verb, result))
            self._report_op_failures(verb, result)
            on_complete(result)
            self.panel.render()

        op = self._fileops.copy if kind == "copy" else self._fileops.move
        op(self.panel, targets, dest_dir, on_complete=done, log=self.log_info,
           on_declined=on_declined)

    def _transfer_to_path(self, kind: str) -> bool:
        """Prompt for a destination directory, then copy / move the active pane's
        targets there (#528). The prompt is Jump to Path's: prefilled with the
        other pane's directory, TAB-completing directories, and resolving a
        relative path — ``.`` included — against the *active* pane, so ``.``
        means "here" and ``..`` its parent. Same return contract as
        ``_transfer``; the source-side guards are its, the destination ones run
        as the prompt's validation."""
        verb = "Copy" if kind == "copy" else "Move"
        src_pane = self.active_pane()
        if kind == "move" and self._is_archive(src_pane["path"]):
            self.log_info("Cannot move out of an archive — use copy instead")
            return True
        targets = self._selected_or_focused(src_pane)
        if not targets:
            self.log_info(f"No file to {kind}")
            return True
        current = str(src_pane["path"])

        def resolve(text: str) -> Path:
            return self._resolve_jump_target(text, current)

        def validate(text: str) -> str | None:
            if not text.strip():
                return "Path cannot be empty"
            target = resolve(text)
            if self._is_archive(target):
                return f"Cannot {kind} into a read-only archive"
            try:
                is_dir = target.is_dir()
            except Exception as exc:
                # A hand-written PATH_SCHEMES backend can raise anything; left
                # unguarded it escapes the dialog's key handler (see jump_to_path).
                report_user_failure(f"{verb} to {text!r}", exc)
                return f"{exc.__class__.__name__}: {exc}"
            if not is_dir:
                return f"Not a directory: {target}"
            return None

        def accept(text: str) -> None:
            self._run_transfer(kind, src_pane, targets, resolve(text))
            self.panel.render()

        # Prefill with the other pane's directory — C / M's destination, ready to
        # edit — unless that pane is a search-results feed with none of its own.
        dst_pane = self.pm.get_inactive_pane()
        start = current if dst_pane.get("virtual") else str(dst_pane["path"])
        sep = os.sep if self._is_local(start) else "/"
        initial = start if start.endswith(sep) else start + sep
        show_input(self.panel, title=f"{verb} to Path", prompt=f"{verb} to:", text=initial,
                   on_accept=accept, validate=validate, select_all=False,
                   completer=FilepathCompleter(base_directory=current, directories_only=True,
                                               show_hidden=self.flm.show_hidden),
                   region=self._active_pane_region())
        self.panel.render()
        return False

    def delete_files(self) -> bool:
        """K / Delete: send the selection (or cursor entry) to the system's
        trash (#591) where every item has one, else delete for good — after a
        confirmation that says there is no trash here. ``DELETE_TO_TRASH =
        False`` makes it :meth:`delete_permanently`."""
        config = getattr(self, "config", None)
        return self._delete(permanent=not getattr(config, "DELETE_TO_TRASH", True))

    def delete_permanently(self) -> bool:
        """Shift-K / Shift-Delete: delete the selection for good, skipping the
        trash, via the shared :class:`~xefm.file_operations.FileOperationService`
        (confirm honouring ``CONFIRM_DELETE``, directories removed
        recursively); refresh the pane and log the summary on completion.

        Returns True when a guard bailed out synchronously (see ``_transfer`` for
        why the caller then needs to redraw)."""
        return self._delete(permanent=True)

    def _delete(self, permanent: bool) -> bool:
        pane = self.active_pane()
        targets = self._selected_or_focused(pane)
        if not targets:
            self.log_info("No file to delete")
            return True
        if any(self._is_archive(t) for t in targets):
            self.log_info("Cannot delete inside a read-only archive")
            return True

        to_trash = not permanent and all(trash.available(t) for t in targets)
        verb = "Trash" if to_trash else "Delete"

        def on_complete(result: dict, verb: str = verb) -> None:
            pane["selected_files"].clear()
            # _relist, not _refresh: nothing navigated, so the cursor stays on
            # what it was on — or, when that was one of the files just deleted,
            # on the entry that took its place (#414).
            self._relist(pane)
            self._relist_others_showing({str(t.parent) for t in targets}, besides=pane)
            self.log_info(format_op_summary(verb, result))
            # What turned out to have no trash (#765) is offered a permanent
            # delete below, so it is not also reported as a failure.
            no_trash = result.get("no_trash") or []
            names = {str(t) for t in no_trash}
            self._report_op_failures(verb, {**result, "errors": [
                e for e in result.get("errors", []) if e[0] not in names]})
            if no_trash:
                self._fileops.delete(
                    self.panel, no_trash, log=self.log_info,
                    on_complete=lambda r: on_complete(r, "Delete"),
                    note=(f"These are online-only files in cloud storage, which "
                          f"the {trash.NAME} does not take. Download them first "
                          "to keep them recoverable."))
            self.panel.render()

        if to_trash:
            self._fileops.trash(self.panel, targets, on_complete=on_complete,
                                log=self.log_info)
            return False
        note = None
        if not permanent:
            # K was pressed expecting the trash; say plainly that there is none.
            note = (f"There is no {trash.NAME} here, so these are deleted for "
                    "good.")
        self._fileops.delete(self.panel, targets, on_complete=on_complete,
                             log=self.log_info, note=note)
        return False

    # --- archives (create / extract) -----------------------------------------

    # Creation has two implementations, so "what can P create" has two sources.
    # zip and tar are written right here through zipfile / tarfile — that is
    # where the byte-counting subclasses in xefm.archive_progress attach and
    # where this code has always lived — and the table below is theirs. Anything
    # else is written by the engine that reads it and registers a writer with its
    # format, so whether .7z can be created depends on the libarchive that
    # loaded, exactly as reading it does. ``_writable_formats`` is the union, and
    # the reason it is computed rather than written down.

    #: Archive extensions zipfile / tarfile can create → format label. The
    #: Zstandard rows appear only on a Python whose tarfile has it (3.14+), the
    #: same condition the readable table applies — see
    #: :func:`xefm.archive.tar_zstd_supported`.
    _ARCHIVE_EXTS = (
        (".tar.gz", "tar.gz"), (".tgz", "tar.gz"),
        (".tar.bz2", "tar.bz2"), (".tbz2", "tar.bz2"),
        (".tar.xz", "tar.xz"), (".txz", "tar.xz"),
        (".zip", "zip"), (".tar", "tar"),
        *(((".tar.zst", "tar.zst"), (".tzst", "tar.zst"))
          if tar_zstd_supported() else ()),
    )
    #: tarfile write modes per format label (zip is handled separately).
    _TAR_MODES = {
        "tar": "w", "tar.gz": "w:gz", "tar.bz2": "w:bz2", "tar.xz": "w:xz",
        **({"tar.zst": "w:zst"} if tar_zstd_supported() else {}),
    }

    @classmethod
    def _writable_formats(cls) -> list:
        """``(suffix, label)`` for every format P can create, longest suffix
        first — the stdlib table plus whatever the registry's writers add.

        Sorted rather than concatenated in a fixed order for the same reason the
        read registry sorts: ``.tar.gz`` has to beat ``.tar`` whichever list each
        came from, and a future format is exactly the thing that would otherwise
        find the wrong one."""
        rows = list(cls._ARCHIVE_EXTS)
        rows += [(suffix, fmt.label) for fmt in archive_writable_formats()
                 for suffix in fmt.suffixes]
        rows.sort(key=lambda row: -len(row[0]))
        return rows

    @classmethod
    def _archive_format(cls, name: str) -> str | None:
        """The format label XeFM can *create* ``name`` as, or None. The write
        side — see :meth:`_readable_archive_format` for the other one."""
        low = name.lower()
        return next((label for suffix, label in cls._writable_formats()
                     if low.endswith(suffix)), None)

    @staticmethod
    def _readable_archive_format(name: str) -> str | None:
        """The format label XeFM can *read* ``name`` as, or None — what Enter
        browses and what U extracts. Comes from the registry rather than a table
        here, because which formats are readable depends on the libarchive that
        loaded at startup."""
        return archive_format_label(name)

    @staticmethod
    def _archive_basename(name: str) -> str:
        """``name`` with its recognised archive extension stripped (the default
        extraction subdirectory), or unchanged if none matches. Strips by the
        readable table, since extraction is what asks."""
        return archive_strip_suffix(name)

    @staticmethod
    def _entry_size(path) -> int:
        """``path``'s size in bytes for the byte bar, or 0 if it can't be read —
        the archive writer is what reports a genuinely unreadable file."""
        try:
            return int(path.stat().st_size)
        except Exception:  # noqa: BLE001 — a missing size just hides the bar
            return 0

    @staticmethod
    def _add_to_zip(zf, path, arcname: str, *, task=None, prog=None,
                    bytes_=None, log=None, archive_path=None) -> int:
        """Add ``path`` to an open ZipFile under ``arcname``, recursing into
        directories (tarfile recurses on its own; zipfile does not). Returns the
        number of files written.

        ``task`` / ``prog`` make each file a cancellation checkpoint and a
        progress update, and ``bytes_`` (a
        :class:`~xefm.archive_progress.ByteProgress`) opens each file's byte bar;
        all three default to None, which writes exactly as before."""
        if path.is_dir() and not path.is_symlink():
            count = 0
            for child in path.iterdir():
                count += XeFMApp._add_to_zip(zf, child, f"{arcname}/{child.name}",
                                             task=task, prog=prog, bytes_=bytes_,
                                             log=log, archive_path=archive_path)
            return count
        if task is not None:
            task.checkpoint()
        if bytes_ is not None:
            bytes_.begin(arcname, XeFMApp._entry_size(path))
        zf.write(str(path), arcname)
        if log is not None:
            log(XeFMApp._added_line(arcname, archive_path))
        return 1

    def _write_archive(self, sources: list, archive_path, fmt: str, *,
                       task=None, prog=None, log=None) -> int:
        """Write ``sources`` into a new archive at ``archive_path`` in ``fmt``.
        Local filesystem paths (this phase); returns the number of files added.

        ``task`` (a :class:`~xefm.task.Task`) and ``prog`` (its
        :class:`~xefm.progress_manager.ProgressManager`) make the write
        cancellable and progress-reporting, entry by entry — and, through the
        :mod:`xefm.archive_progress` file subclasses, byte by byte within an
        entry, so a single huge member still moves something. ``Cancelled``
        unwinds out of here mid-archive, leaving the caller to drop the partial
        file. Both default to None, which writes exactly as before.

        ``log``, when given, gets one line per file added, the same grain the
        copy engine logs at. tar and 7z hand out a seam only at the start of a
        member, so those lines are held one step behind (:class:`_StepBehindLog`)
        and a member that fails is never claimed as added."""
        import zipfile
        from xefm.archive_progress import ByteProgress, ProgressTarFile, ProgressZipFile
        bytes_ = ByteProgress(prog) if prog is not None else None
        if fmt != "zip" and fmt not in self._TAR_MODES:
            return self._write_via_handler(sources, archive_path, task=task,
                                           prog=prog, bytes_=bytes_, log=log)
        if fmt == "zip":
            with ProgressZipFile(str(archive_path), "w", zipfile.ZIP_DEFLATED) as zf:
                zf.byte_progress = bytes_
                count = sum(self._add_to_zip(zf, s, s.name, task=task, prog=prog,
                                             bytes_=bytes_, log=log,
                                             archive_path=archive_path)
                            for s in sources)
                self._writing_out(task, bytes_, archive_path)
            return count
        added = 0

        def report(tarinfo):
            # tarfile.add()'s own per-member filter hook, called as it recurses —
            # the one seam it offers for progress and cancellation, since (unlike
            # zipfile) it walks directories itself. Never skips a member, so the
            # count matches the getmembers() this replaces.
            nonlocal added
            if task is not None:
                task.checkpoint()
            added += 1
            if bytes_ is not None:
                bytes_.begin(tarinfo.name, tarinfo.size)
            if tarinfo.isreg():
                unit.announce(self._added_line(tarinfo.name, archive_path))
            return tarinfo

        unit = _StepBehindLog(log)
        with ProgressTarFile.open(str(archive_path), self._TAR_MODES[fmt]) as tf:
            tf.byte_progress = bytes_
            for s in sources:
                tf.add(str(s), arcname=s.name, filter=report)  # recurses into dirs
            self._writing_out(task, bytes_, archive_path)
        unit.flush()
        return added

    def _write_via_handler(self, sources: list, archive_path, *, task=None,
                           prog=None, bytes_=None, log=None) -> int:
        """Create a format neither zipfile nor tarfile can write — 7z — through
        the writer its registry entry brought with it.

        The writer takes two callbacks instead of being driven as a loop from
        here, because it holds the output archive open for its whole run; what
        this method supplies is the same per-entry bookkeeping ``report`` does for
        tar, and ``bytes_.advance`` for the payload. ``task.checkpoint()`` inside
        ``on_entry`` is what makes the create cancellable: ``Cancelled`` unwinds
        through the writer, which closes the partial file on the way out for
        ``create_archive`` to remove."""
        fmt = archive_format_for_name(archive_path.name)
        if fmt is None or fmt.writer is None:  # guarded by the caller
            raise ArchiveFormatError(
                f"Cannot create archive format: {archive_path.name}")
        written = 0

        def on_entry(arcname: str, size: int, is_dir: bool = False) -> None:
            nonlocal written
            if task is not None:
                task.checkpoint()
            written += 1
            if bytes_ is not None:
                bytes_.begin(arcname, size)
            if not is_dir:
                unit.announce(self._added_line(arcname, archive_path))

        unit = _StepBehindLog(log)
        count = fmt.writer(
            archive_path, sources, on_entry=on_entry,
            on_bytes=bytes_.advance if bytes_ is not None else None,
            on_finish=lambda: self._writing_out(task, bytes_, archive_path))
        unit.flush()
        return count

    @classmethod
    def _count_archive_entries(cls, sources: list, *, include_dirs: bool,
                               task=None) -> int:
        """Recursively count the entries writing ``sources`` will produce, so the
        progress bar is determinate rather than a spinner.

        ``include_dirs`` follows the format: zip writes leaf files only (see
        ``_add_to_zip``), tar adds a member per directory too. A directory that
        cannot be listed is counted as itself and not descended — the write is
        what surfaces the error, not the count."""
        total = 0

        def walk(path) -> None:
            nonlocal total
            if task is not None:
                task.checkpoint()
            is_dir = path.is_dir() and not path.is_symlink()
            if include_dirs or not is_dir:
                total += 1
                if task is not None:
                    task.counted = total
            if not is_dir:
                return
            try:
                children = list(path.iterdir())
            except Exception:  # noqa: BLE001 — the write reports the real error
                return
            for child in children:
                walk(child)

        for s in sources:
            walk(s)
        return total

    @staticmethod
    def _member_label(archive_name: str, internal_path: str) -> str:
        """How a member names itself while it is being extracted:
        ``photos.7z › 2019/summer/beach.jpg``.

        Both halves are wanted. The archive alone cannot say what the operation
        is doing right now — a big archive would sit on one unchanging line for
        minutes — and the member alone cannot say which archive it came out of,
        which a batch needs and even a single extraction has to be read out of
        the dialog's title to know. The dialog abbreviates a row that will not
        fit by cutting the middle, so a long label keeps the archive at one end
        and the member's own name at the other."""
        return f"{archive_name} \u203a {internal_path}" if archive_name else internal_path

    @staticmethod
    def _writing_out(task, bytes_, archive_path) -> None:
        """Every member is in; the archive itself is now being written.

        On a mounted volume that holds a file until it is closed, this is one
        transfer of the whole archive and the only part of the run with no
        member left to report — the bars have nothing more to say, so the title
        does. Closes the last member's row first, so its item is counted before
        the wait rather than after it."""
        if bytes_ is not None:
            bytes_.finish()
        if task is not None:
            task.title = f"Writing {archive_path.name}…"

    @staticmethod
    def _extracted_line(internal_path: str, archive_path, dest_dir) -> str:
        """One extracted member, in the shape the copy engine logs a file in:
        the thing once in quotes, then where it came from and where it went."""
        return f"Extracted '{internal_path}': {archive_path.name} → {dest_dir}"

    @staticmethod
    def _added_line(arcname: str, archive_path) -> str:
        """One member added to a new archive. No source directory: unlike a copy,
        every member comes from the one pane the selection was made in, and the
        arcname already carries its place in that tree."""
        return f"Added '{arcname}' → {archive_path.name}"

    @staticmethod
    def _reporting_members(members, describe, task, prog, bytes_=None, unit=None):
        """Yield ``members`` one at a time, checkpointing and reporting each —
        ``describe(member)`` gives its ``(name, size, log line)``, the last None
        for a member that should not be logged (a directory, which the copy
        engine does not log either).

        ``unit`` is a :class:`_StepBehindLog`: extractall hands out no seam after
        a member, so each line waits for the next member to start and the caller
        flushes the last one when extractall returns.

        Handed to ``extractall(members=…)`` so extraction gets per-entry progress
        and cancellation *without* reimplementing its loop: tar's deferred
        directory-permission fixup is subtle enough (permissions on a directory
        would otherwise block writing into it) that a hand-rolled per-member
        ``extract()`` would be a regression. The member's bytes are counted by the
        :mod:`xefm.archive_progress` subclass doing the reading; this only opens
        the bar, after ``update_progress`` has cleared the previous member's."""
        for member in members:
            if task is not None:
                task.checkpoint()
            name, size, logged = describe(member)
            if bytes_ is not None:
                bytes_.begin(name, size)
            if unit is not None and logged is not None:
                unit.announce(logged)
            yield member

    def _extract_archive(self, archive_path, dest_dir, fmt: str, pwd: bytes | None = None,
                         *, task=None, prog=None, owns_total: bool = True,
                         log=None, pool=None, key=0) -> int:
        """Extract ``archive_path`` into ``dest_dir`` (created if absent). Returns
        the number of entries. Tar extraction uses the ``data`` filter where
        available (Python 3.12+) to reject unsafe member paths.

        ``pwd`` (bytes) is the password for an encrypted archive; it is verified
        up front — by :func:`xefm.archive.verify_zip_password` for a zip, by the
        handler's own ``verify_password`` otherwise — so a missing/wrong password
        raises *before* any file is written, rather than leaving a half-extracted
        directory behind. A missing/wrong password raises ``RuntimeError``;
        encryption XeFM cannot decrypt at all raises ``NotImplementedError``.
        ``on_done`` dispatches on exactly those two types.

        ``task`` / ``prog``, when given, report each member and make it a
        cancellation point (see ``_reporting_members``); both default to None,
        which extracts exactly as before.

        ``owns_total`` says whether this call may publish the operation's totals.
        A batch counts every archive up front and publishes one total for the lot
        (:meth:`_survey_archives`), which each archive must then not overwrite
        with its own; a lone call keeps the default and scales the bar itself.

        ``log``, when given, gets one line per file member as it lands — the same
        grain the copy engine logs at, and for the same reason: a run's record
        should say what it actually wrote, not only how many things it wrote.
        Directory members are not logged, again matching copy."""
        from xefm.archive import open_zip, verify_zip_password
        from xefm.archive_progress import ByteProgress, ProgressTarFile, ProgressZipFile
        bytes_ = ByteProgress(prog) if prog is not None else None
        dest_dir.mkdir(parents=True, exist_ok=True)
        unit = _StepBehindLog(log)
        if fmt != "zip" and fmt not in self._TAR_MODES:
            return self._extract_via_handler(archive_path, dest_dir, pwd,
                                             task=task, prog=prog, bytes_=bytes_,
                                             owns_total=owns_total, log=log,
                                             pool=pool, key=key)
        if fmt == "zip":
            with open_zip(str(archive_path), ProgressZipFile) as zf:
                verify_zip_password(zf, pwd)  # no-op unless the zip is encrypted
                zf.byte_progress = bytes_     # after the probe, which reads a little
                members = zf.infolist()
                if prog is not None and owns_total:
                    prog.update_operation_total(
                        len(members),
                        total_bytes=sum(m.file_size for m in members))
                zf.extractall(
                    str(dest_dir), pwd=pwd,
                    members=self._reporting_members(
                        members,
                        lambda m: (self._member_label(archive_path.name, m.filename),
                                   m.file_size,
                                   None if m.is_dir() else self._extracted_line(
                                       m.filename, archive_path, dest_dir)),
                        task, prog, bytes_, unit))
                unit.flush()
                if bytes_ is not None:
                    bytes_.finish()
                return len(members)
        with ProgressTarFile.open(str(archive_path)) as tf:
            tf.byte_progress = bytes_
            # getmembers() reads the whole (compressed) archive to build the list;
            # that is the operation's counting phase, and why it runs on the worker.
            members = tf.getmembers()
            if prog is not None and owns_total:
                # Only regular files report bytes on the way past, so only they
                # may promise any — a directory member's size would never be paid.
                prog.update_operation_total(
                    len(members),
                    total_bytes=sum(m.size for m in members if m.isreg()))

            def reported():
                return self._reporting_members(
                    members,
                    lambda m: (self._member_label(archive_path.name, m.name), m.size,
                               self._extracted_line(m.name, archive_path, dest_dir)
                               if m.isreg() else None),
                    task, prog, bytes_, unit)

            try:
                tf.extractall(str(dest_dir), filter="data", members=reported())
            except TypeError:  # older Python without the extraction filter
                # Raised on the call itself (unknown keyword), before the members
                # generator is touched, so a fresh one is the whole retry.
                tf.extractall(str(dest_dir), members=reported())
            unit.flush()
            if bytes_ is not None:
                bytes_.finish()
            return len(members)

    def _extract_via_handler(self, archive_path, dest_dir, pwd: bytes | None,
                             *, task=None, prog=None, bytes_=None,
                             owns_total: bool = True, log=None,
                             pool=None, key=0) -> int:
        """Extract a format neither zipfile nor tarfile reads — 7z, and whatever
        else the loaded libarchive contributes — through its registered handler.

        These formats have no random access, so the archive is read in a single
        forward pass rather than one entry at a time: a per-entry loop would
        rescan from the beginning for every member. Members are taken off that
        pass by :meth:`_extract_members`' workers, each of which then carries its
        own member to a closed file; the gate below runs first because nothing
        should be written before it is known whether the archive can be read at
        all."""
        fmt = archive_format_for_name(archive_path.name)
        if fmt is None:  # guarded by the caller; a table change could still get here
            raise ArchiveFormatError(f"Unsupported archive format: {archive_path.name}")
        handler = fmt.factory(archive_path)
        try:
            handler.open()
            # Same up-front verification the zip path does, and reported the same
            # way so on_done's dispatch does not need to know the format.
            status = handler.encryption_status()
            if status == "unsupported":
                raise NotImplementedError(
                    f"{archive_path.name}: encryption XeFM cannot decrypt")
            if status == "password" and (pwd is None or not handler.verify_password(pwd)):
                raise RuntimeError(f"{archive_path.name}: password required")

            if prog is not None and owns_total:
                items, size = handler.extraction_totals()
                prog.update_operation_total(items, total_bytes=size)
            if getattr(handler, "extraction_pass", None) is None:
                # A handler that offers no claimable pass — none XeFM registers
                # today — keeps the one-member-at-a-time contract instead.
                count = 0
                for entry in handler.iter_extract(
                        dest_dir, password=pwd,
                        on_bytes=bytes_.advance if bytes_ is not None else None):
                    if task is not None:
                        task.checkpoint()
                    if bytes_ is not None:
                        bytes_.begin(entry.internal_path,
                                     0 if entry.is_dir else entry.size)
                    count += 1
                if bytes_ is not None:
                    bytes_.finish()
                return count
            return self._extract_members(handler, dest_dir, pwd,
                                         task=task, prog=prog, log=log,
                                         archive_path=archive_path,
                                         pool=pool, key=key)
        finally:
            handler.close()

    def _extract_workers(self, dest_dir=None) -> int:
        """How many members an extraction may have in flight.

        The destination's write ceiling, through the same rule a copy uses
        (:func:`~xefm.file_operations.transfer_workers`) — the archive's own end
        is not in it, because the reader is serialised by the handler's claim
        whatever this returns, so the only thing a worker count can overlap here
        is the writing. No destination is a local one."""
        dest = dest_dir if dest_dir is not None else Path(".")
        return transfer_workers(getattr(self, "config", None), (), dest)

    def _close_gate(self) -> CloseGate:
        """This extraction's gate on closing files — the copy engine's, because
        the constraint belongs to the destination rather than to the operation
        writing it."""
        return CloseGate()

    def _extract_members(self, handler, dest_dir, pwd: bytes | None,
                         *, task=None, prog=None, log=None, archive_path=None,
                         pool=None, key=0) -> int:
        """Extract every member of ``handler``'s archive with symmetric workers.

        Each worker carries one member from claim to closed file, so a member's
        whole life — and its file handle's — stays on one thread. The archive is
        claimed one member at a time because libarchive's reader is a cursor, but
        that lock lives with the cursor, inside the handler
        (``LibarchiveHandler.extraction_pass``): nothing here knows why claims
        serialise, which is what lets the worker count be chosen for the
        destination rather than for the archive.

        What overlaps is therefore everything *after* the claim. On a filesystem
        that holds a file in a local cache until it is closed — WebDAV, NFS's
        close-to-open flush — that is the whole transfer, and two workers were
        measured to halve a batch's wall clock. On one that does not, the workers
        queue on the claim and the run is what it always was; the design does not
        have to know which it is dealing with.

        Progress goes through the copy engine's transfer slots rather than the
        single current-item fields: several members are in flight, so there is no
        one current member to name. The item is counted at ``file_end``, after
        the file is closed, so a member counts when it has actually landed — and
        ``log`` gets its line there too, for the same reason. ``log`` must
        already be serialised (:func:`~xefm.file_operations.serialized_log`).

        ``pool``, when a batch supplies one, is workers already running over its
        other archives. This then returns once the archive has been *read*, its
        files still landing, and the count and any failure are the pool's to
        report when it closes — hence the 0 here. Without one, a pool is made for
        this archive alone and joined before returning: the same code path with
        the batch's overlap left out."""
        root = handler.extraction_root(dest_dir)
        if pool is not None:
            with handler.extraction_pass(dest_dir, password=pwd) as pass_:
                pool.run_archive(key, pass_, root, archive_path, dest_dir)
            return 0
        own = _ExtractionPool(self._extract_workers(dest_dir), task=task,
                              prog=prog, log=log, close_gate=self._close_gate())
        try:
            with handler.extraction_pass(dest_dir, password=pwd) as pass_:
                own.run_archive(key, pass_, root, archive_path, dest_dir)
        finally:
            results = own.close()
        count, error = results.get(key, (0, None))
        if error is not None:
            raise error
        return count

    def _survey_archives(self, plan, task=None) -> list[tuple]:
        """Open every archive in the batch once, up front, and report what
        extracting it will cost: ``(encryption status, members, bytes)`` each.

        One open per archive, not two. The encryption gate already had to open
        each of them — ``archive_encryption_status_path`` did it inside the loop,
        one archive at a time, just before extracting that one — and the same
        open knows how many members it stores and how many bytes they hold. So
        the batch's totals cost nothing beyond a probe that was happening
        anyway, which is what lets the progress bar span the whole batch instead
        of restarting at zero for each archive, and be weighted by bytes rather
        than by member count alone.

        An archive that will not open contributes nothing and is *not* recorded
        as a failure: the extraction that follows opens it again and reports what
        is wrong with it, in the place that can attribute the error to it. The
        bar is then short by that archive's share, which is the right way round —
        a bar that promised bytes nothing will deliver would end up stuck.

        Runs on the task worker: for a compressed tar this is a full read of the
        file, and even where it is only a header pass it is still I/O — and it is
        a cancellation point per archive, so a batch aimed at the wrong pane can
        be stopped before it opens all of them."""
        from xefm.archive import archive_extraction_survey
        surveys: list[tuple] = []
        for entry, _target, _fmt in plan:
            if task is not None:
                task.checkpoint()
            survey = archive_extraction_survey(str(entry))
            surveys.append(survey)
            if task is not None:
                # What the progress dialog's "Preparing… (n items)" line reads.
                task.counted += survey[1]
        return surveys

    @staticmethod
    def _unlink_quietly(path) -> bool:
        """Remove ``path``, returning whether it went. Cleanup after a cancelled
        write, where the cancel is the news and a failed tidy-up is not — but the
        caller still says which of the two happened."""
        try:
            path.unlink()
            return True
        except Exception:  # noqa: BLE001 — best effort
            return False

    def _submit_archive_task(self, task: Task, run, on_done, dest_dir) -> None:
        """Run an archive operation on the task worker, silencing ``dest_dir``'s
        filesystem watcher for its duration.

        The operation writes into the directory the other pane is showing, and its
        own writes would otherwise re-list that pane for the whole run, competing
        with it for I/O; ``on_done``'s refresh is the reconciliation (the same
        bracket :class:`~xefm.file_operations.FileOperationService` puts around
        copy / move / delete — issue #243)."""
        monitor = getattr(self, "file_monitor", None)

        def run_bracketed(t: Task) -> dict:
            # Suppression is taken on the worker (it is refcounted and lock-guarded,
            # so any thread may) rather than before submit, so it cannot be leaked
            # by a task that never starts.
            if monitor is not None:
                monitor.suppress_path(dest_dir)
            try:
                return run(t)
            finally:
                if monitor is not None:
                    monitor.release_path(dest_dir)

        self.tasks.submit(task, self.panel, run=run_bracketed, on_done=on_done)

    def create_archive(self) -> bool:
        """Create an archive from the active pane's selection (or cursor entry)
        in the other pane's directory (the 'P' key). Prompts for a filename whose
        extension picks the format; an unrecognised extension defaults to
        ``.tar.gz``. An extension the registry reads but brought no writer for is
        refused with a message rather than silently becoming a ``.tar.gz``.

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
            if fmt is None:
                readable = self._readable_archive_format(name)
                if readable is not None:
                    # A format the registry reads but brought no writer for: a
                    # read-only format like rar, or a libarchive whose 7z writer
                    # is missing. Better to say so than to append ".tar.gz" to a
                    # name the user clearly meant as something else.
                    self.log_info(f"Cannot create {readable} archives — "
                                  f"XeFM reads that format but cannot write it")
                    self.panel.render()
                    return
                name += ".tar.gz"  # no recognised extension → default to .tar.gz
                fmt = "tar.gz"
            archive_path = dest_dir / name

            def go() -> None:
                # Compression is slow enough on a large tree (and .tar.xz slow
                # enough on a small one) that doing it here would freeze the UI for
                # its whole duration, so it runs as a task: worker thread, progress
                # dialog, Esc to cancel.
                task = Task("Creating archive…", config=self.config,
                            kind="archive_create")
                task.progress.start_operation(OperationType.ARCHIVE_CREATE, 0,
                                              description=name)

                def run(t: Task) -> dict:
                    prog = t.progress
                    try:
                        prog.update_operation_total(self._count_archive_entries(
                            sources, include_dirs=(fmt != "zip"), task=t))
                        added = self._write_archive(sources, archive_path, fmt,
                                                    log=self.log_info,
                                                    task=t, prog=prog)
                    except Cancelled:
                        # A half-written archive is not a usable one, and the file
                        # did not exist before (an overwrite truncated whatever was
                        # there the moment it opened): drop it rather than leave
                        # rubble behind. Cancelling during the count precedes the
                        # file, hence "removed" rather than an unconditional claim.
                        return {"cancelled": True,
                                "removed": self._unlink_quietly(archive_path)}
                    except Exception as exc:  # noqa: BLE001 — reported on the main thread
                        return {"error": exc}
                    finally:
                        prog.finish_operation()
                    return {"added": added}

                def on_done(res: dict) -> None:
                    if res.get("cancelled"):
                        tail = f" — {name} removed" if res.get("removed") else ""
                        self.log_info(f"Archive creation cancelled{tail}")
                    elif res.get("error") is not None:
                        self.log_info(f"Archive creation failed: {res['error']}")
                    else:
                        self.log_info(
                            f"Created {name} ({res.get('added', 0)} file(s)) in {dest_dir}")
                    self._relist(self.pm.get_inactive_pane())
                    self.panel.render()

                self._submit_archive_task(task, run, on_done, dest_dir)

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
                   completer=FilepathCompleter(base_directory=str(dest_dir),
                                               show_hidden=self.flm.show_hidden),
                   region=self._active_pane_region())
        self.panel.render()
        return False

    def extract_archive(self) -> bool:
        """Extract the active pane's selected archives — or, with nothing
        selected, the one under the cursor — each into a subdirectory named after
        it in the other pane's directory (the 'U' key). Confirms when
        ``CONFIRM_EXTRACT_ARCHIVE`` is set or a destination already exists.

        The selection is what every other file operation acts on, and U ignoring
        it was #408. Selected entries that are not readable archives are skipped
        and reported rather than sinking the whole batch, and the batch runs as
        *one* task: one progress dialog, one Cancel, one summary. Each archive's
        password (when it needs one) is asked for from the worker through the
        task's UI bridge, which is also what moves the encryption probe — a full
        open of the file — off the main thread.

        Returns True when a guard bailed out synchronously (see ``_transfer`` for
        why the caller then needs to redraw)."""
        targets = self._selected_or_focused(self.active_pane())
        if not targets:
            self.log_info("No file to extract")
            return True
        if any(self._is_archive(t) for t in targets):
            self.log_info("Cannot extract an archive nested inside another archive")
            return True
        dest_dir = self.pm.get_inactive_pane()["path"]
        if self._is_archive(dest_dir):
            self.log_info("Cannot extract into a read-only archive")
            return True

        plan: list[tuple] = []    # (entry, target, fmt) — what will be extracted
        skipped: list[tuple] = []  # (entry, reason) — what the selection swept up
        for entry in targets:
            try:
                is_file = entry.is_file()
            except Exception:  # noqa: BLE001 — an unreadable stat is not a verdict
                is_file = True
            if not is_file:
                skipped.append((entry, f"{entry.name} is not a file"))
                continue
            fmt = self._readable_archive_format(entry.name)
            if fmt is None:
                skipped.append((entry, f"'{entry.name}' is not a supported archive"))
                continue
            plan.append((entry, dest_dir / self._archive_basename(entry.name), fmt))
        if not plan:
            # A single target keeps its own diagnosis — it says *why* that file
            # cannot be extracted, which a count would throw away.
            self.log_info(skipped[0][1] if len(skipped) == 1 else
                          f"None of the {len(skipped)} selected items is an archive")
            return True
        if skipped:
            self.log_info(f"Skipping {len(skipped)} selected item(s) "
                          f"that are not archives")
        single = len(plan) == 1

        def password_prompt(entry, error: str | None):
            """A ``show_fn(panel, deliver)`` for :meth:`Task.ask`: the masked
            password field for ``entry``, stacked above the progress dialog (the
            same ``z + 5`` the conflict dialog uses). Cancelling delivers None."""
            def show(panel, deliver) -> None:
                show_input(
                    panel, title="Extract Archive",
                    prompt=error or f"Password for {entry.name}:", password=True,
                    on_accept=deliver, on_cancel=lambda: deliver(None),
                    select_all=False, region=self._active_pane_region(), z=75)
                panel.render()
            return show

        def go() -> None:
            """Run the whole batch on the task worker — decompressing a large
            archive would otherwise freeze the UI for its whole duration, and
            building a compressed tar's member list (the counting phase) is itself
            a full read of the file."""
            task = Task("Extracting archive…", config=self.config,
                        kind="archive_extract")
            task.progress.start_operation(OperationType.ARCHIVE_EXTRACT, 0,
                                          description=plan[0][0].name)

            def run(t: Task) -> dict:
                prog = t.progress
                # Workers write into the same log sink, which copes with one
                # background writer and not several — the copy engine takes the
                # same wrapper for the same reason.
                log = serialized_log(self.log_info)
                # The archive being *read* when a cancel lands, for the cancel
                # message: what landed stays (the destination may be a directory
                # the user already had files in — the confirm box says as much —
                # so removing it wholesale could take those with it). A hint
                # rather than an inventory, and slightly more so now that the pool
                # spans archives: the one before this may still have had files in
                # flight. Naming the archive the cancel interrupted is the useful
                # half.
                partial = None

                def extract_one(entry, target, fmt, status, key) -> int:
                    """One archive, asking for its password if it needs one.

                    A wrong password re-asks *here*, in place, rather than
                    unwinding the task and resubmitting it: nothing is written
                    until the password verifies (see ``_extract_archive``), so the
                    retry costs only the prompt.

                    ``status`` is the survey's verdict on this archive's
                    encryption — which of "needs a password" and "XeFM cannot
                    decrypt this at all" applies is the format's own handler's
                    answer, taken during the counting pass because that opened
                    every archive anyway."""
                    nonlocal partial
                    from xefm.archive import set_archive_password
                    if status == "unsupported":
                        raise NotImplementedError(
                            f"{entry.name}: encryption XeFM cannot decrypt")
                    pwd = None
                    error = None
                    while True:
                        if status == "password":
                            answer = t.ask(password_prompt(entry, error),
                                           headless=None)
                            if not answer:  # Esc, or an empty password
                                raise Cancelled()
                            pwd = answer.encode("utf-8")
                        partial = target
                        try:
                            count = self._extract_archive(entry, target, fmt,
                                                          pwd=pwd, task=t, prog=prog,
                                                          owns_total=False, log=log,
                                                          pool=pool, key=key)
                        except NotImplementedError:
                            # Defensive: the probe above already refused these, and
                            # NotImplementedError *is* a RuntimeError, so it must
                            # not fall into the wrong-password branch below.
                            raise
                        except RuntimeError:
                            if status != "password":
                                raise
                            error = "Incorrect password — try again:"
                            partial = None  # verified before anything was written
                            continue
                        partial = None
                        if pwd is not None:
                            # Remember the working password so browsing this same
                            # archive later doesn't prompt again this session.
                            set_archive_password(entry, pwd)
                        return count

                # One pool for the batch. Started here rather than per
                # archive so no archive's tail is waited on before the next one
                # is opened: on a destination that uploads at close, the last
                # members of an archive were landing while every other worker sat
                # idle and the next archive could not begin reading.
                pool = _ExtractionPool(
                    self._extract_workers(dest_dir), task=t, prog=prog, log=log,
                    close_gate=self._close_gate())
                entries = 0
                failures: list[tuple] = []
                started: list[tuple] = []
                cancelled = False
                try:
                    # Count the whole batch before writing any of it, and publish
                    # it as one total. The operation started with the task and is
                    # never restarted, so the bar runs once from end to end — it
                    # used to be started afresh per archive and rewind to zero
                    # each time — and it is weighted by bytes as well as members,
                    # so a 4 GiB member no longer goes past at the same speed as
                    # a 4 KiB one.
                    surveys = self._survey_archives(plan, task=t)
                    prog.update_operation_total(
                        sum(items for _st, items, _by in surveys),
                        total_bytes=sum(by for _st, _it, by in surveys))
                    for index, ((entry, target, fmt), (status, _i, _b)) in enumerate(
                            zip(plan, surveys), 1):
                        t.checkpoint()
                        if not single:
                            # Read live by the progress dialog each frame.
                            t.title = f"Extracting archive {index} of {len(plan)}…"
                        try:
                            entries += extract_one(entry, target, fmt, status,
                                                   index)
                        except Cancelled:
                            raise  # Cancel is the batch's, not this archive's
                        except Exception as exc:  # noqa: BLE001 — on the main thread
                            # One bad archive does not sink the rest of the batch;
                            # every failure is reported when the task lands.
                            failures.append((entry, exc))
                            continue
                        started.append((index, entry))
                except Cancelled:
                    cancelled = True
                finally:
                    # Draining the pool is what makes the tallies knowable: an
                    # archive's last files land after its reading ended, so
                    # neither its count nor its failure existed when the loop
                    # moved on from it.
                    results = pool.close()
                    prog.finish_operation()
                done = 0
                for index, entry in started:
                    count, error = results.get(index, (0, None))
                    entries += count
                    if error is not None:
                        failures.append((entry, error))
                    else:
                        done += 1
                if cancelled:
                    return {"cancelled": True, "done": done, "entries": entries,
                            "failures": failures, "partial": partial}
                return {"done": done, "entries": entries, "failures": failures}

            def on_done(res: dict) -> None:
                for entry, exc in res.get("failures") or []:
                    if isinstance(exc, NotImplementedError):
                        self.log_info(f"Cannot extract {entry.name}: "
                                      f"its encryption is not supported")
                    elif single:
                        self.log_info(f"Extraction failed: {exc}")
                    else:
                        self.log_info(f"Extraction failed for {entry.name}: {exc}")
                done = res.get("done", 0)
                entries = res.get("entries", 0)
                if res.get("cancelled"):
                    partial = res.get("partial")
                    detail = []
                    if not single:
                        detail.append(f"{done} of {len(plan)} archive(s) extracted")
                    if partial is not None:
                        detail.append(f"{partial.name}/ is partly written")
                    self.log_info("Extraction cancelled" +
                                  (" — " + ", ".join(detail) if detail else ""))
                elif done and single:
                    entry, target, _ = plan[0]
                    self.log_info(
                        f"Extracted {entry.name} → {target.name}/ ({entries} entries)")
                elif done:
                    self.log_info(f"Extracted {done} archive(s) → {dest_dir} "
                                  f"({entries} entries)")
                self._relist(self.pm.get_inactive_pane())
                self.panel.render()

            self._submit_archive_task(task, run, on_done, dest_dir)

        existing = [target for _, target, _ in plan if target.exists()]
        if existing or getattr(self.config, "CONFIRM_EXTRACT_ARCHIVE", True):
            # Markdown message: the archive name and destination render as `code`
            # chips (backticks also shield a path's _ / * from markdown). A blank
            # line makes the warning a separate paragraph, not a folded-in clause.
            if single:
                message = f"Extract `{plan[0][0].name}` to `{plan[0][1]}`?"
                if existing:
                    message += "\n\nThe destination exists; files may be overwritten."
            else:
                message = f"Extract {len(plan)} archives to `{dest_dir}`?"
                if existing:
                    message += (f"\n\n{len(existing)} destination(s) exist; "
                                f"files may be overwritten.")
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

    #: First row of the Filter picker — selecting it clears the filter. ``*`` is
    #: the pattern that would show everything anyway, so the row reads as the
    #: thing it does rather than as a glyph too small to identify (#385); the
    #: label around it is what keeps a real glob from colliding with the row.
    _FILTER_CLEAR = "*  (clear filter)"

    def enter_filter(self) -> None:
        """Filter picker for the active pane (the ';' key).

        A pattern field over a list of three bands, in this order: the "clear
        filter" row, the filters the config defines (``FILTERS``,
        :mod:`xefm.filters`), and the patterns applied here before. The middle
        band is *fixed* — a defined filter sits in the same place every time
        rather than ageing down a history it was never part of.

        ``Enter`` applies what the field holds (:mod:`xefm.history_input_dialog`):
        typed text narrows the list, and ``↓`` copies a row into the field — a
        defined filter as its name, the clear row as nothing — to apply as it
        is or change first. So a new pattern is applied as typed even where it
        matches an old one. Directories are always shown; an applied *pattern*
        is (re)recorded most-recent-first, a defined filter is not (it already
        has a row of its own)."""
        pane = self.active_pane()

        def apply(pattern: str) -> None:
            pattern = pattern.strip()
            if pattern:
                self._record_filter_pattern(pattern)
                name = filters.label(pattern)
                # The item count only exists once the (async) listing lands, so
                # the summary is logged from there — and redrawn by the same pump.
                self._apply_filter(pane, pattern, on_count=lambda count:
                                   self.log_info(f"Filter '{name}': {count} item(s)"))
            else:
                self._apply_filter(pane, pattern)
                self.log_info("Filter cleared")
            self.panel.render()

        def text_of(value) -> str:
            # The text a row stands for: a defined filter by its name (which is
            # what applying it types), the clear row as nothing at all.
            if isinstance(value, filters.Row):
                return value.name
            return "" if value == self._FILTER_CLEAR else value

        items = [self._FILTER_CLEAR, *filters.rows(), *self._filter_history()]
        show_history_input(
            self.panel, items, title="Filter", prompt="Pattern:",
            heading="Filters and history", accept_label="apply",
            to_label=lambda v: v.label if isinstance(v, filters.Row) else v,
            to_text=text_of, on_accept=apply,
            on_remove=self._forget_filter_pattern, on_cancel=self.panel.render,
            region=self._active_pane_region())
        self.panel.render()

    def enter_isearch(self, quick: bool = False) -> None:
        """Incremental search over the active pane (the 'F' key).

        The prompt is not a centered modal: an ``ISearchBar`` overlay is pinned to
        the active pane's footer bar (same slot, same size), so the list above
        stays visible and its cursor keeps moving as you type.

        Type a case-insensitive *contains* pattern (space-separated tokens all
        match); every hit is highlighted and the cursor jumps to the nearest match
        at/after its current position. ``isearch.prev_match`` /
        ``isearch.next_match`` walk the matches; ``isearch.toggle_select_up`` /
        ``isearch.toggle_select_down`` mark the current item on the way (the file
        list's own toggle key cannot: a printable key here separates the
        pattern's tokens — issue #347) and ``isearch.select_matches`` marks every
        match at once; ``isearch.accept`` stops at the current match;
        ``isearch.cancel`` restores the pre-search cursor. Reuses
        ``FileListManager.find_matches`` for the hits.

        ``quick`` is the Orthodox keymap's type-ahead. It matches as above, and
        closes the way the function-key file managers' quick search does: Esc
        leaves the cursor on the match, and any other key that is not typing —
        Enter, F5, an arrow sideways — closes the search and acts on the file
        list, so Enter opens the match and F5 copies it. Up / Down still walk
        the matches."""
        if self._isearch_active or not self.active_pane()["files"]:
            return
        footer = self._footers.get(self.pm.active_pane)
        if footer is None or footer.rect is None:
            return  # footer not drawn yet — nothing to anchor to
        x, y, w, h = footer.rect
        self._isearch_active = True
        self._isearch_quick = quick
        self._isearch_origin = self.active_pane()["focused_index"]
        self._isearch_matches = []
        # Migemo only ever matches a *non-ASCII* name (migemo_search.has_hit),
        # so a listing without one leaves no romaji token undecided — which is
        # what lets _isearch_recompute refuse a miss on the first character
        # there rather than at the third. Read once: the listing does not
        # change under an open search.
        self._isearch_migemo = any(
            not f.name.isascii() for f in self.active_pane()["files"])
        self._active_view().search_matches = set()
        if quick:
            self._isearch_bar = ISearchBar(
                on_change=self._isearch_recompute,
                on_navigate=self._isearch_step,
                on_cancel=self._isearch_stop,
                get_status=self._isearch_status,
                on_passthrough=self._isearch_passthrough,
            )
        else:
            self._isearch_bar = ISearchBar(
                on_change=self._isearch_recompute,
                on_navigate=self._isearch_step,
                on_select=self._isearch_toggle_select,
                on_select_all=self._isearch_select_matches,
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
        matches).

        A typed character that would leave the search with no candidate at all
        is refused instead (issue #370): the bar rolls the pattern back to the
        last one that had matches, so the search stays on its hit rather than
        running on past it while the counter reads 0. Backspace always gets you
        out again — only an edit that *added* text is rolled back — and a
        pattern Migemo has yet to reach is never called a dead end
        (``search_match.dead_end``), because two characters of romaji find
        Japanese only once they are three — in a listing that holds Japanese at
        all."""
        pane = self.active_pane()
        matches = self.flm.find_matches(
            pane, pattern, match_all=True, return_indices_only=True)
        if (not matches and search_match.dead_end(pattern,
                                                  migemo=self._isearch_migemo)
                and self._isearch_bar is not None
                and self._isearch_bar.reject_edit()):
            return  # pattern, matches, highlights and cursor all stay put
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

    def _isearch_toggle_select(self, delta: int) -> None:
        """Toggle the focused item's selection, then walk to the previous
        (``delta<0``) / next (``delta>0``) match — the file list's
        ``toggle_select_down`` / ``toggle_select_up``, whose "move" is one row
        where this one is one match.

        The pattern field owns SPACE itself (it separates the pattern's tokens),
        which is what left marking unreachable during a search until now."""
        self._log_result(self.flm.toggle_selection(
            self.active_pane(), move_cursor=False))
        if self._isearch_matches:
            self._isearch_step(delta)   # renders
        else:
            self.panel.render()

    def _isearch_select_matches(self) -> None:
        """``isearch.select_matches``: mark every match found — the counter's whole
        "n" in one key — or clear them when they are all marked already.

        The bulk answer to the same need the mark-and-move keys cover one file
        at a time:
        the search has already worked out which files you mean. Items outside the
        match set are left alone, so a second search adds to the marks rather
        than replacing them, and the bar stays open to make that the obvious
        move."""
        self._log_result(self.flm.toggle_matches_selection(
            self.active_pane(), self._isearch_matches))
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
        if self._isearch_bar is not None and self._isearch_bar.pattern:
            # What search_next / search_prev (Vim's n / N) search for again.
            self._last_isearch_pattern = self._isearch_bar.pattern
        self._isearch_active = False
        self._isearch_quick = False
        self._isearch_matches = []
        self._active_view().search_matches = set()
        if (self.panel.has_layers
                and self.panel._layers[-1].widget is self._isearch_bar):
            self.panel.pop_layer()
        self._isearch_bar = None

    def _isearch_stop(self) -> None:
        """Enter in the field: keep the current match and close.

        The pattern is deliberately *not* added to the ';' filter history (#385).
        The two are different languages — isearch's space-separated tokens are an
        order-free AND and its romaji reaches Japanese through Migemo, neither of
        which has an ``fnmatch`` spelling — so a translated entry would recall
        something the search never matched. And isearch is a *navigation* key,
        optimized for typing fast: every Enter on the way to a file would push a
        real, deliberately composed filter out of the history.
        """
        self._isearch_close()
        self.panel.render()

    def _isearch_passthrough(self, event) -> None:
        """Quick search: a key the bar does not own ends the search at the
        current match and then does what it does in the file list."""
        self._isearch_close()
        self.on_event(event)
        self.panel.render()

    def _isearch_cancel(self) -> None:
        """Esc / outside click: restore the pre-search cursor and close."""
        self.active_pane()["focused_index"] = self._isearch_origin
        self._isearch_close()
        self.panel.render()

    def select_by_pattern(self, select: bool = True) -> None:
        """Select (or, with ``select`` false, unselect) the active pane's files
        matching a typed pattern (issue #544).

        The pattern language is the ';' filter's, so the prompt is the Filter
        picker's too, less its "clear filter" row: the filters a config defines,
        then the shared pattern history. A pattern applied here is recorded in
        that same history — what you typed to filter a pane is what you will
        want to select by, and the other way round. Matching goes through
        :meth:`FileListManager.select_by_pattern`, i.e. through the filter's own
        comparison."""
        pane = self.active_pane()

        def apply(pattern: str) -> None:
            pattern = pattern.strip()
            if pattern:
                self._record_filter_pattern(pattern)
                self._log_result(self.flm.select_by_pattern(pane, pattern, select))
            self.panel.render()

        show_history_input(
            self.panel, [*filters.rows(), *self._filter_history()],
            title="Select by Pattern" if select else "Unselect by Pattern",
            prompt="Pattern:", heading="Filters and history",
            accept_label="select" if select else "unselect",
            to_label=lambda v: v.label if isinstance(v, filters.Row) else v,
            to_text=lambda v: v.name if isinstance(v, filters.Row) else v,
            on_accept=apply, on_remove=self._forget_filter_pattern,
            on_cancel=self.panel.render, region=self._active_pane_region())
        self.panel.render()

    def _record_filter_pattern(self, pattern: str) -> None:
        """Add ``pattern`` to the most-recent-first filter history (persisted via
        the state manager, capped), so the ';' Filter prompt can recall it. Silent
        and best-effort — a history write must never break the filter.

        The name of a filter the config defines is not a pattern and is not
        recorded: the picker pins it a row of its own, and recording it would
        show it twice and push a typed pattern out of the history to do it."""
        pattern = pattern.strip()
        if not pattern or filters.is_known(pattern):
            return          # a defined filter has a fixed row; it never ages
        try:
            hist = [p for p in self.state_manager.get_state(_FILTER_HISTORY_KEY, [])
                    if p != pattern]
            hist.insert(0, pattern)
            self.state_manager.set_state(_FILTER_HISTORY_KEY, hist[:_FILTER_HISTORY_MAX])
        except Exception:
            pass

    def _forget_filter_pattern(self, pattern: str) -> bool:
        """Drop ``pattern`` from the saved filter history (the Filter picker's
        remove key, #271). Returns whether anything went — which is also how the
        picker's "clear filter" row survives the key: it is not a saved pattern,
        so nothing matches it and the row stays."""
        try:
            hist = self._filter_history()
            kept = [p for p in hist if p != pattern]
            if len(kept) == len(hist):
                return False
            self.state_manager.set_state(_FILTER_HISTORY_KEY, kept)
        except Exception as e:
            self.log_info(f"Could not update filter history: {e}")
            return False
        self.log_info(f"Removed from filter history: {pattern}")
        return True

    def _filter_history(self) -> list[str]:
        """The saved filter patterns, most-recent first (best-effort)."""
        try:
            hist = self.state_manager.get_state(_FILTER_HISTORY_KEY, [])
            return [p for p in hist if isinstance(p, str)]
        except Exception:
            return []

    @classmethod
    def _resolve_jump_target(cls, text: str, current: str) -> Path:
        """Resolve the Jump-to-Path dialog's input against the pane's current
        directory ``current``. Accepts ``~``, relative (to ``current``) and
        absolute local paths, plus full remote URIs (``s3://…``, ``ssh://…``):
        a remote URI is taken as-is, and any remote result skips
        ``os.path.normpath``, which would collapse its ``scheme://`` separator
        to ``scheme:/`` (#318)."""
        text = text.strip()
        if path_schemes.is_uri(text):
            return Path(text)
        if text.startswith("~"):
            # os.sep too: "~\Documents" left as "\Documents" is rooted on
            # Windows, and joining it to home gave C:\Documents.
            target = Path.home() / text[1:].lstrip("/" + os.sep)
        elif not (os.path.isabs(text) or text.startswith(("/", os.sep))):
            # A rooted "\usr\lib" counts as absolute here: Python 3.13 stopped
            # calling a path with no drive absolute on Windows, and joining it
            # to an S3 pane gave s3://bucket/dir//usr/lib.
            target = Path(current) / text
        else:
            target = Path(text)
        if not cls._is_local(target):
            return target
        return Path(os.path.normpath(str(target)))

    def jump_to_path(self) -> None:
        """Prompt for a path and navigate the active pane there.
        Accepts ``~``, relative (to the current path), and absolute paths,
        plus remote URIs (``s3://…``, ``ssh://…``) in
        the jump-to-path dialog. TAB completes names via
        :class:`xefm.completion.FilepathCompleter`.

        A **file** path is accepted too (#351): the pane goes to the file's
        directory and the cursor lands on the file, which is what pasting a full
        path from somewhere else is nearly always meant to do. Completion
        therefore offers files as well as directories."""
        pane = self.active_pane()
        current = str(pane["path"])

        def resolve(text: str) -> Path:
            return self._resolve_jump_target(text, current)

        def probe(text: str, question):
            """Ask a path one question, reporting a backend that cannot answer.

            A scheme from ``PATH_SCHEMES`` is code someone wrote by hand, and
            this prompt is the first place a typed URI reaches it. Left
            unguarded, whatever it raises leaves through the dialog's key
            handler: Enter does nothing, and nothing says why. Returns
            ``(ok, answer)``."""
            try:
                return True, question(resolve(text))
            except Exception as exc:
                report_user_failure(f"Jump to Path {text!r}", exc)
                return False, f"{exc.__class__.__name__}: {exc}"

        def validate(text: str) -> str | None:
            if not text.strip():
                return "Path cannot be empty"
            ok, exists = probe(text, lambda target: target.exists())
            if not ok:
                return exists            # the message, not an answer
            if not exists:
                return f"Path does not exist: {resolve(text)}"
            return None

        def accept(text: str) -> None:
            # A file names where to *go* and what to land on; a directory only
            # the former. is_dir() is the one filesystem call either way.
            ok, is_dir = probe(text, lambda target: target.is_dir())
            if not ok:
                return                   # already reported, with its traceback
            target = resolve(text)
            if is_dir:
                target_dir, target_name = target, None
            else:
                target_dir, target_name = target.parent, target.name
            self.log_info(f"Jumped to: {target}")
            self._go_to_dir(pane, target_dir, target_name)  # renders

        # Prefill with the current path plus a trailing separator, ready to type
        # a child name. Remote URIs always use ``/``, whatever os.sep is.
        sep = os.sep if self._is_local(current) else "/"
        initial = current if current.endswith(sep) else current + sep
        show_input(self.panel, title="Jump to Path", prompt="Path:", text=initial,
                   on_accept=accept, validate=validate, select_all=False,
                   completer=FilepathCompleter(base_directory=current, directories_only=False,
                                               show_hidden=self.flm.show_hidden),
                   region=self._active_pane_region())
        self.panel.render()

    def compare_selection(self) -> None:
        """W: open the Compare & Select dialog, then mark items in the active pane
        by comparing each with the same-named item in the other pane.

        Either side may be a virtual (search-results) pane: its rows are real
        ``Path``s, so the engine's name join applies to them exactly as it does to
        a directory listing — the compared feed is the pane's *displayed* listing
        (sorted + filtered) on both sides. A result set spans directories, so the
        other side may hold several same-named candidates; the engine selects an
        entry when any of them matches.

        With a virtual pane on either side the dialog grows a "Match the whole
        path shown" row (#383): a result set can hold a dozen files called
        ``index.html``, which all collapse onto one another under the default
        name join, and only the path below the search root separates them. Two
        directory panes never see the row — their entries are direct children,
        whose path below the pane is the basename already.

        Both sides' attributes come from the snapshot each pane's listing left
        behind, so a compare reads nothing but file *contents* — see
        :meth:`_pane_attrs`."""
        pane = self.active_pane()
        other = self.pm.get_inactive_pane()
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
                    pane["files"], other["files"], criteria,
                    current_attrs=self._pane_attrs(pane),
                    other_attrs=self._pane_attrs(other),
                    current_root=self._pane_root(pane),
                    other_root=self._pane_root(other))
                self._apply_compare_result(pane, criteria, result)
            self.panel.render()

        show_compare_select(self.panel, region=self._active_pane_region(),
                            on_result=on_result,
                            allow_path_match=bool(pane.get("virtual")
                                                  or other.get("virtual")))
        self.panel.render()

    @staticmethod
    def _pane_root(pane: dict):
        """The directory a pane's rows are named relative to: the search root on a
        virtual pane, the pane's own directory otherwise.

        Only the compare's path-match option reads this, and each side brings its
        own — which is what makes the option mean what it looks like it means. A
        directory listing of ``/a`` and a search rooted at ``/a`` then agree on
        ``x.txt`` for a hit sitting in ``/a``, and disagree on ``sub/x.txt`` for
        one a level down, exactly as the two panes show them."""
        virtual = pane.get("virtual")
        return virtual["root"] if virtual else pane.get("path")

    @staticmethod
    def _pane_attrs(pane: dict) -> dict:
        """``{str(path): attrs}`` for everything a pane last listed — the
        :mod:`xefm.dir_scan` records ``apply_listing`` kept, handed to the compare
        engine so it answers is_dir/size/mtime without touching the filesystem.

        The snapshot is taken before the filename filter, so it covers every
        displayed row and then some. Empty when the pane has no snapshot (nothing
        listed yet, or the listing failed); the engine then reads per file, which
        is what it always did.

        These are the same attributes the pane's own size and date columns are
        drawn from, so a comparison now agrees with what the user is looking at —
        and carries that display's staleness, which the file monitor and every
        re-listing already exist to clear."""
        entries = pane.get("_listing_entries")
        if not entries:
            return {}
        return {str(p): a for p, a in entries}

    def _compare_with_content(self, pane: dict, other: dict, criteria) -> None:
        """Content-comparison path: reads files, so it runs on the task worker with
        a cancellable progress dialog. Snapshots the pane feeds and their attributes
        up front (the worker must not touch the panel) and applies the result on the
        main thread."""
        current_files = list(pane["files"])
        other_files = list(other["files"])
        current_attrs = self._pane_attrs(pane)
        other_attrs = self._pane_attrs(other)
        current_root = self._pane_root(pane)
        other_root = self._pane_root(other)
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
                current_attrs=current_attrs, other_attrs=other_attrs,
                current_root=current_root, other_root=other_root,
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
            ("cursor_top", "Move cursor to the first item"),
            ("cursor_bottom", "Move cursor to the last item"),
            ("open_item", "Open: enter a directory/archive, or view a file"),
            ("go_parent", "Go to parent directory"),
            ("go_root", "Go to the root of the current drive or location"),
            ("switch_pane", "Switch active pane"),
            ("quick_view", "Preview the item under the cursor in the other pane"),
            ("jobs", "List background jobs; bring one forward or drop it from the queue"),
            ("find_similar", "Find identical files, or similar images, videos or audio (Tools menu)"),
            ("new_tab", "Open a new tab in this pane, at the same place"),
            ("open_in_new_tab", "Open the directory under the cursor in a new tab"),
            ("close_tab", "Close this pane's current tab"),
            ("next_tab", "Show this pane's next tab"),
            ("prev_tab", "Show this pane's previous tab"),
            ("nav_left", "Focus left pane / go to parent"),
            ("nav_right", "Focus right pane / go to parent"),
            ("favorites", "Go to a favorite, or find files by tag"),
            ("add_favorite", "Add a favorite, or tag the selection"),
            ("context_menu", "Open the context menu for the item under the cursor"),
            ("context_menu_dir", "Open the context menu for the current directory"),
            ("jump_to_path", "Jump to a typed path"),
            ("drives", "Open the drives / locations picker"),
            ("history", "Go to a recently-visited directory"),
            ("go_back", "Back to the directory shown before"),
            ("go_forward", "Forward again after going back"),
            ("flat_view", "Show every file below this directory as one list"),
            ("open_list_from_clipboard",
             "Open the paths on the clipboard as a list (Go menu)"),
            ("open_list_from_command",
             "Open the paths a command prints as a list (Go menu)"),
            ("open_list_from_file",
             "Open the list file under the cursor as a list (Go menu)"),
            ("sync_current_to_other", "Go to the other pane's directory"),
            ("sync_other_to_current", "Send this directory to the other pane"),
        )),
        # 'toggle_select_up' and 'isearch.toggle_select_up' — mark and move
        # *backwards* — are deliberately absent: both gave up their default key
        # (Shift-SPACE went to 'select_range', Shift-UP to the log pane it always
        # read as), and a row with no key and no menu route would advertise a
        # feature while withholding the one way to reach it. Both are still
        # registered actions, listed for rebinding in the File Selection and
        # incremental-search blocks of _config.py.
        ("Selection", (
            ("toggle_select_down", "Toggle selection, move down"),
            ("select_range", "Select from the nearest selected item to the cursor"),
            ("toggle_select_files", "Toggle all files"),
            ("toggle_select_items", "Toggle all items"),
            ("select_all", "Select every item"),
            ("unselect_all", "Clear selection"),
            ("select_by_pattern", "Select the files matching a pattern"),
            ("unselect_by_pattern", "Unselect the files matching a pattern"),
            ("select_same_extension", "Select every file with the cursor file's extension (Select menu)"),
            ("cursor_next_selected", "Move cursor to the next selected item"),
            ("cursor_prev_selected", "Move cursor to the previous selected item"),
            ("compare_selection", "Compare & select vs. other pane"),
        )),
        ("File Operations", (
            ("create_directory", "Create new directory"),
            ("create_file", "Create new file"),
            ("rename", "Rename file/directory"),
            ("rename_in_editor", "Rename the selection in the TEXT_EDITOR"),
            ("copy_files", "Copy selection to the other pane"),
            ("clipboard_copy", "Copy files to the clipboard (or the log's selected text)"),
            ("clipboard_cut", "Cut files to the clipboard: they move when pasted"),
            ("clipboard_paste", "Paste the clipboard into this folder"),
            ("clipboard_show", "Show what the file clipboard holds (Edit menu)"),
            ("clipboard_clear", "Empty the file clipboard (Edit menu)"),
            ("copy_names", "Copy selection's name(s) to the clipboard"),
            ("copy_paths", "Copy selection's full path(s) to the clipboard"),
            ("move_files", "Move selection to the other pane"),
            ("copy_files_to", "Copy selection to a typed directory"),
            ("move_files_to", "Move selection to a typed directory"),
            ("delete_files", f"Move selection to the {trash.NAME}"),
            ("delete_permanently", "Delete selection for good"),
            ("create_archive", "Create archive from selection"),
            ("extract_archive", "Extract the selected archive(s)"),
            ("file_details", "Show file details"),
            ("edit_file", "Edit the selected file(s) in the configured TEXT_EDITOR"),
            ("subshell", "Open a shell in the current directory"),
            ("open_with_os", "Open with the default app"),
            ("open_with", "Choose the app that opens the selection (File menu)"),
            ("reveal_in_os", "Reveal in the OS file manager"),
            ("programs", "Run an external program on the selection"),
        )),
        ("Search", (
            ("isearch", "Incremental search (jump to match)"),
            ("filter", "Filter list by filename pattern"),
            ("clear_filter", "Clear the filename filter"),
            ("find_files", "Recursive filename search"),
            ("find_in_files", "Recursive content (grep) search"),
            ("index_search", "Search the OS index (Spotlight / Windows Search) under this folder"),
            ("options", "In the search dialog: case, pattern, subfolders"),
        )),
        # The only non-file-list surface here, and deliberately: the search bar
        # sits on the pane rather than replacing it, so its keys are the ones a
        # user reaches for mid-task and looks up in the same place as the rest.
        # (The viewers keep their own footers.)
        ("Incremental Search (while the search bar is open)", (
            ("isearch.next_match", "Move to the next match"),
            ("isearch.prev_match", "Move to the previous match"),
            ("isearch.toggle_select_down", "Select, then move to the next match"),
            ("isearch.select_matches", "Select every match (again: clear them)"),
            ("isearch.accept", "Stop at the current match"),
            ("isearch.cancel", "Cancel and restore the cursor"),
        )),
        ("View", (
            ("view_file", "View file (text viewer)"),
            ("diff_files", "Compare two selected files"),
            ("toggle_hidden", "Toggle hidden files"),
            ("toggle_color_scheme", "Cycle color theme (View menu)"),
            ("sort", "Sort dialog (key F/E/S/T + order)"),
            ("quick_sort_name", "Quick-sort by name (repeat: reverse)"),
            ("quick_sort_size", "Quick-sort by size (repeat: reverse)"),
            ("quick_sort_date", "Quick-sort by date (repeat: reverse)"),
            ("quick_sort_ext", "Quick-sort by extension (repeat: reverse)"),
        )),
        ("Log Pane", (
            ("scroll_log_up", "Scroll the log up one line"),
            ("scroll_log_down", "Scroll the log down one line"),
            ("scroll_log_page_up", "Scroll the log up one page"),
            ("scroll_log_page_down", "Scroll the log down one page"),
            ("adjust_log_up", "Make the log pane larger"),
            ("adjust_log_down", "Make the log pane smaller"),
            ("reset_log_height", "Reset the log pane height"),
            ("copy_log_selection", "Copy the log's selected text — the copy key does it too (Edit menu)"),
            # These three carry their menu: nothing binds them out of the box,
            # so a row saying only "—" would name a feature and then withhold
            # the one way to reach it. The menu is stated rather than "unbound
            # by default", which stops being true the moment a config binds it.
            ("copy_log_all", "Copy the whole log (Edit menu)"),
        )),
        ("Other", (
            ("menu", "Open the menu bar (←/→ walk it, Esc closes)"),
            ("command_palette", "Search every action by name and run it"),
            ("edit_config", "Edit ~/.xefm/config.py, then reload (Tools menu)"),
            ("reload_config", "Reload ~/.xefm/config.py (Tools menu)"),
            ("install_extension", "Install an extension package: the one under the cursor, a .zip, a URL or github:owner/repo (Tools ▸ Advanced menu)"),
            ("extensions", "List extension packages (Tools ▸ Advanced menu)"),
            ("check_extension_updates", "Look for newer versions of extension packages (Tools ▸ Advanced menu)"),
            ("sync_python_packages", "Install what ~/.xefm/requirements.txt lists (Tools ▸ Advanced menu)"),
            ("help", "Show this help"),
            ("quit", "Quit XeFM"),
        )),
    )

    #: Rows of :data:`_HELP_SECTIONS` that only some frontends can honor, each
    #: mapped to the test for "this one can". The help is one table for two
    #: frontends, and an action the running one refuses is worse than a missing
    #: row: ``menu`` answers nothing once an OS menu bar has taken the menu
    #: over. It stays in the sections above — it is a real action, and the
    #: *other* frontend lists it — so the filter lives here rather than as a
    #: branch in the table. (``subshell`` used to be gated too, until desktop
    #: mode learned to open it in an external terminal — #472.)
    #:
    #: The menu bar is asked about itself, not the backend about its
    #: capabilities: which menus a platform has is PuiKit's business, and XeFM
    #: only wants to know whether the key it would print does anything.
    _BACKEND_GATED = {
        "menu": lambda self: self.menu_bar.takes_activation_key,
    }

    def _help_entries(self, entries):
        """``entries`` minus the rows this backend cannot perform."""
        return [(action, desc) for action, desc in entries
                if action not in self._BACKEND_GATED
                or self._BACKEND_GATED[action](self)]

    def _keys_label(self, action: str) -> str:
        """Comma-joined, display-formatted key(s) bound to ``action`` ("—" if
        unbound), for the help dialog and the tips.

        The ``filer`` context answers first, so a name the file list also owns
        shows what the file list will do with the key. Falling through to the
        other contexts is what lets a surface-qualified name resolve at all —
        the help's isearch section (``isearch.select_matches``) and the tips,
        which talk about the viewers too (``{key:image_viewer.next}``), would
        otherwise render every one of those as "—"."""
        for context in (_ctx.FILER,) + _ctx.CONTEXTS:
            keys, _ = self.keys.get_keys_for_action(action, context)
            if keys:
                return ", ".join(self.keys.format_key_for_display(k) for k in keys)
        return UNBOUND_KEYS

    def show_help(self) -> None:
        """A scrollable key-binding reference, built live from the port's keymap.

        A row whose action has details links to its page
        (:meth:`_action_link`): click it, or Tab to it and press Enter, and the
        page opens over the help; Esc returns to the help where it was."""
        show_markdown(self.panel, self._help_markdown(), title="Help",
                      on_link=self._follow_action_link)
        self.panel.render()

    def _action_link(self, name: str, text: str) -> str:
        """``text`` as a link to action ``name``'s page, when there is a page
        worth opening — the action has details beyond the line already in the
        row; otherwise ``text`` unchanged. Only the file list's actions (and the
        shared ones) carry details, so a viewer's row stays plain."""
        action = _action_registry.resolve(_ctx.FILER, name)
        if action is None or not action.details:
            return text
        label = text.replace("[", "\\[").replace("]", "\\]")
        return f"[{label}]({_ACTION_LINK}{quote(name, safe='')})"

    def _follow_action_link(self, url: str) -> bool:
        """The Help dialog's link handler: an ``xefm-action:`` link opens that
        action's page over the help; any other link is declined, so PuiKit opens
        it the usual way (a browser, or the clipboard in a terminal)."""
        if not url.startswith(_ACTION_LINK):
            return False
        name = unquote(url[len(_ACTION_LINK):])
        action = _action_registry.resolve(_ctx.FILER, name)
        if action is None:
            self.log_info(f"No action named '{name}'")
        else:
            # Over the dialog the link is in — the topmost layer, since only it
            # takes events — so the page is inset and dims the help behind it.
            help_dialog = self.panel._layers[-1].widget if self.panel.has_layers else None
            show_markdown(self.panel, self._action_page(action), title=name,
                          over=help_dialog)
        self.panel.render()
        return True

    # --- command palette (#550) ---------------------------------------------

    def show_command_palette(self) -> None:
        """Every file-list action in a searchable picker, run on Enter.

        Built on the shared ``FilterListDialog`` so it matches the way every
        other picker does (tokens ANDed, Migemo), with three of its opt-in
        hooks: the key each action is bound to as a right-hand column, its
        one-line description under the list, and a help page on F1
        (``describe_list_item``). The rows are the actions this surface can
        actually run — the ``filer`` context's own, the inherited ``common``
        ones, and the config's ``ACTIONS`` — so a viewer's actions, which only
        mean something inside that viewer, are not offered here."""
        show_filter_list(
            self.panel, self._palette_actions(), title="Command Palette",
            to_label=lambda a: a.name,
            to_right=self._palette_keys,
            to_detail=lambda a: a.description,
            to_help=self._action_page,
            on_accept=lambda a: self._menu(a.name))
        self.panel.render()

    def _palette_actions(self) -> list:
        """The rows the palette offers, in registry order (which is the order
        the help dialog reads in, grouped by what the actions do).

        A built-in needs a handler in this app to be runnable, and an action
        the running frontend refuses (``_BACKEND_GATED``) is left out for the
        same reason the help leaves it out. The palette itself is left out
        too — opening it from inside it would only stack a second one."""
        handlers = self._filer_handlers()
        rows = []
        for action in _action_registry.actions(_ctx.FILER):
            name = action.name
            if name == "command_palette":
                continue
            if not action.is_user and name not in handlers:
                continue
            gate = self._BACKEND_GATED.get(name)
            if gate is not None and not gate(self):
                continue
            rows.append(action)
        return rows

    def _palette_keys(self, action) -> str:
        """The palette's right-hand column: the key(s) bound to ``action`` in the
        file list, or nothing — an empty column reads as "no key" at a glance,
        where a dash on half the rows would be noise."""
        keys, _ = self.keys.get_keys_for_action(action.name, _ctx.FILER)
        return ", ".join(self.keys.format_key_for_display(k) for k in keys)

    def _action_page(self, action) -> str:
        """One action's help page: what it does, its keys, what it needs, and
        the details where the action has some (a built-in's ``Action.details``,
        the body of a user action's docstring).

        Shared by the two surfaces that explain an action — the command
        palette (F1 on a row) and the Help dialog (a row's link) — and owned
        by neither: the page is the action's, built from the registry."""
        paragraphs = [action.description or action.name]
        if action.details:
            paragraphs.append(action.details)
        # The facts as labelled lines in one paragraph, joined by hard breaks:
        # a list would hang a lone bullet off the common case, which has only
        # the keys to state. The name is not repeated — it is the title.
        keys = self._palette_keys(action)
        facts = [f"**Keys:** `{keys}`" if keys else
                 "**Keys:** none — bind one under `KEY_BINDINGS` in config.py"]
        if action.resolved_selection() == "required":
            facts.append("**Needs a selection:** its key does nothing until "
                         "an item is marked")
        elif action.resolved_selection() == "none":
            facts.append("**Only without a selection:** its key is ignored "
                         "while items are marked")
        if action.is_user:
            facts.append(f"**Defined in:** {self._action_origin(action)}")
        if action.aliases:
            old = ", ".join(f"`{a}`" for a in action.aliases)
            facts.append(f"**Formerly:** {old}")
        paragraphs.append("\\\n".join(facts))
        return "\n\n".join(paragraphs)

    def _action_origin(self, action) -> str:
        """Where a user action came from, for its help page: the extension
        package that placed it in ``ACTIONS``, or config.py. Both register
        with ``source == "user"``; the extension loader's report is what tells
        them apart (#709) — and it is the user's first clue which package to
        update or disable when the action misbehaves."""
        report = getattr(config_manager, "extension_report", None)
        owner = report.owners.get(("ACTIONS", action.name)) if report else None
        if owner is None:
            return "your config.py (`ACTIONS`)"
        manifest = next((m for m in report.loaded if m.id == owner), None)
        if manifest is None:
            return f"the extension `{owner}`"
        return f"the *{manifest.name}* extension (`{owner}` {manifest.version})"

    def _help_markdown(self) -> str:
        """The help dialog's whole body.

        Each section renders as a Markdown heading over a two-column table
        (Key(s) / Action), so bindings align in a real column and the section
        titles stand out. Each action ends with its own name (``cursor_up``) —
        what ``KEY_BINDINGS`` and ``ctx.invoke`` take, so a key can be rebound
        without looking the name up elsewhere.

        Split from :meth:`show_help` so the content can be built — and checked —
        without a panel to push it onto."""
        from xefm.const import VERSION
        lines = ["# XeFM", f"Version {VERSION}", ""]
        lines += self._help_markers_section()
        for title, entries in self._HELP_SECTIONS + self._user_help_sections():
            rows = self._help_entries(entries)
            if not rows:
                continue
            lines += [f"## {title}", "", "| Key(s) | Action |", "| --- | --- |"]
            for action, desc in rows:
                label = self._keys_label(action)
                # Only a real binding is set as code. An unbound action's "—" in
                # the same code style reads as a key you could press — and next
                # to reset_log_height, whose binding *is* an underscore, the two
                # are a glyph apart.
                keys = UNBOUND_KEYS if label == UNBOUND_KEYS else \
                    "`" + label.replace("|", "\\|") + "`"
                # The name rides in the action's cell rather than a column of
                # its own: at 80 columns a third column breaks
                # toggle_select_in_place mid-word, while here the whole name
                # moves down a line.
                lines.append(f"| {keys} | {self._action_link(action, desc)} "
                             f"· `{action}` |")
            lines.append("")
        lines.append(self._archive_help_section())
        return "\n".join(lines)

    def _help_markers_section(self) -> list[str]:
        """The legend (#789): what the marks and extra columns in the active
        pane mean, first in Help because they are what is on screen. Only the
        extras active in this tab; nothing at all when there are none.

        Each mark is the extra's own format run on each value it declares, so
        the legend shows what the pane draws. Help is Markdown, which has no
        color, so a mark's color is named beside it."""
        from xefm.user_api import EntryInfo   # imported here: user_api imports us
        sample = lambda: EntryInfo(Path("."))   # noqa: E731
        if getattr(self, "pm", None) is None:
            return []                       # built without panes (tests)
        out = []
        for extra in layouts.active_extras(self.active_pane()):
            rows = layouts.glyphs(extra, sample)
            columns = [attributes.get(c.column.attr) for c in extra.columns]
            columns = [a.label for a in columns if a is not None]
            if not rows and not columns:
                continue
            place = ", ".join(
                f"{m.marker.side} the {'name' if m.on == 'name' else m.on}"
                for m in extra.markers)
            out.append(f"**{extra.label}**" + (f" — marks {place}" if place else ""))
            out.append("")
            # A list, not a table: kept short, so the key list's links are
            # still on the first screen, where Tab and Shift-Tab start.
            for cells, meaning in rows:
                mark = "".join(c.text for c in cells)
                colors = {c.color for c in cells if c.color is not None}
                color = f" {', '.join(sorted(map(str, colors)))}" if colors else ""
                out.append(f"- `{mark}`{color} — {meaning}")
            if rows:
                out.append("")
            if columns:
                out += [f"Column: {', '.join(columns)}", ""]
        if not out:
            return []
        return ["## Markers in this pane", ""] + out

    def _archive_help_section(self) -> str:
        """The archive formats *this run* supports, as a closing help section.

        Generated rather than written down, because neither list is fixed: what
        libarchive contributes depends on the library that loaded, and
        ``.tar.zst`` on the Python version. A list kept anywhere else would drift
        the moment either changed.

        This is also where the loaded library is named. A bug report needs that
        and it used to be an info line at every startup, which was more than the
        normal case deserved — here it is one dialog away instead, and only when
        someone goes looking."""
        creatable = {label for _sfx, label in self._writable_formats()}
        lines = ["## Archive Formats", "",
                 "| Format | Extensions | Create |", "| --- | --- | --- |"]
        for fmt in archive_readable_formats():
            extensions = " ".join(f"`{sfx}`" for sfx in fmt.suffixes)
            lines.append(f"| {fmt.description or fmt.label} | {extensions} | "
                         f"{'yes' if fmt.label in creatable else '—'} |")
        lines += ["", self._libarchive_help_line(), ""]
        return "\n".join(lines)

    @staticmethod
    def _libarchive_help_line() -> str:
        """One sentence naming the libarchive behind the formats above, or saying
        why there is none. The formats it would add are named in the negative
        case so the sentence is useful to someone who does not know what
        libarchive is for."""
        missing = ("7z, RAR, ISO, CAB, cpio and RPM come from **libarchive**, "
                   "which is not available here")
        try:
            from xefm.archive_libarchive import libarchive_info
            info = libarchive_info()
        except Exception as exc:  # noqa: BLE001 — the binding is optional
            return f"{missing} ({exc})."
        if not info.available:
            return f"{missing} ({info.error})."
        return f"Using {info.details} — `{info.library_path}`."

    def _user_help_sections(self) -> tuple:
        """The config's own actions as a final help section, or nothing when it
        defines none. A user who binds a key deserves to find it in the same
        place as every built-in one; the description is the action's docstring
        summary (or an explicit ``description`` entry)."""
        user = _action_registry.user_actions(_ctx.FILER)
        if not user:
            return ()
        return (("Your Actions (config.py)",
                 tuple((a.name, a.description) for a in user)),)

    @staticmethod
    def _about_text() -> str:
        """The About box body: name, version, and project URL (mirrors the legacy
        About dialog's content; its cosmetic Matrix-rain background is answered
        now by the theme's arriving-text effect, not a background animation).

        Written as Markdown: the trailing backslash is a hard line break keeping
        name and version on their own rows, and the URL sits in its own paragraph
        so it renders as a real clickable link on every backend — the desktop
        About showed it as inert text while the terminal auto-linked it (#307)."""
        from xefm.const import VERSION, GITHUB_URL
        return (f"XeFM — a dual-pane file manager for desktop and terminal\\\n"
                f"Version {VERSION}\n\n"
                f"{GITHUB_URL}")

    def show_about(self) -> None:
        """The About box.

        Deliberately a plain call: under a theme carrying a ``text_effect``
        (Sci-Fi) the body decodes into place because the box *appeared*, and
        under every other theme it opens plainly. That is the whole point of the
        text-animation system — the effect is theme data, so no call site in XeFM
        asks for it or knows it exists.

        ``markdown=True`` so the project URL is a real link — clickable on the
        desktop backends, not just auto-detected by the terminal (#307).
        """
        show_message_box(self.panel, self._about_text(),
                         title="About XeFM", icon="info", buttons=("OK",),
                         markdown=True)
        self.panel.render()

    def show_tips(self) -> None:
        """The Tip of the Day dialog (Help menu, and once a day at startup),
        opened at the next unseen tip in the persisted rotation. The dialog's
        "Don't show tips at startup" checkbox arrives reflecting the current
        setting, so opening from the menu and unchecking it re-enables the
        startup tips."""
        try:
            index = int(self.state_manager.get_state(_TIPS_INDEX_KEY, 0))
        except Exception:
            index = 0
        try:
            dont_show = not self.state_manager.get_state(_TIPS_ENABLED_KEY, True)
        except Exception:
            dont_show = False
        show_tips_dialog(self.panel, index=index, dont_show=dont_show,
                         resolve=self._keys_label, on_result=self._tips_closed)
        self.panel.render()

    def _tips_closed(self, index: int, dont_show: bool) -> None:
        """Persist the tips rotation as the dialog closes: the rotation resumes
        after the last tip *viewed* (browsing with ←/→ advances it), and the
        checkbox decides the startup dialog. Silent and best-effort — a state
        write must never break closing a dialog."""
        try:
            self.state_manager.set_state(_TIPS_INDEX_KEY, (index + 1) % tip_count())
            self.state_manager.set_state(_TIPS_ENABLED_KEY, not dont_show)
        except Exception:
            pass

    def _maybe_show_startup_tip(self) -> None:
        """Show the Tip of the Day on the first launch of the day, unless the
        user opted out. The shown-today marker is written before the dialog
        opens, so a same-day relaunch stays quiet either way."""
        from datetime import date
        try:
            if not self.state_manager.get_state(_TIPS_ENABLED_KEY, True):
                return
            today = date.today().isoformat()
            if self.state_manager.get_state(_TIPS_LAST_SHOWN_KEY) == today:
                return
            self.state_manager.set_state(_TIPS_LAST_SHOWN_KEY, today)
        except Exception:
            return
        self.show_tips()

    def _show_context_menu(self, pane_name: str, index: int, x: float, y: float) -> None:
        """Right-click in a pane: activate it, then pop a context menu at the
        pointer (native on macOS, a widget popup in the terminal). On a row,
        that row becomes the cursor and gets the item menu; below the last row
        (``index`` -1) the click is on the directory, and gets its menu."""
        self.pm.active_pane = pane_name
        self._sync_active()
        pane = self.active_pane()
        if 0 <= index < len(pane["files"]):
            pane["focused_index"] = index
            menu = self._item_context_menu(pane)
        else:
            menu = self._dir_context_menu(pane)
        # Render *before* the menu opens: a native menu holds the UI thread
        # until it closes, so a render after it showed the cursor on the
        # clicked row only once the menu was gone — while it was open nothing
        # said which row it was for.
        self.panel.render()
        self.panel.popup_menu(menu, x, y)
        self.panel.render()

    def _active_view(self):
        return self.left_view if self.pm.active_pane == "left" else self.right_view

    def context_menu(self) -> None:
        """The item context menu from the keyboard ('/', the Menu key), opened
        just under the cursor row — what a right-click on that row opens. An
        empty pane has no row to talk about, so it gets the directory's menu."""
        pane = self.active_pane()
        if not pane["files"]:
            self.context_menu_dir()
            return
        x, y = self._active_view().menu_anchor(pane["focused_index"])
        self.panel.popup_menu(self._item_context_menu(pane), x, y)
        self.panel.render()

    def context_menu_dir(self) -> None:
        """The directory context menu from the keyboard ('?', Shift + the Menu
        key), hanging from the pane's path bar — what a right-click below the
        last row opens."""
        x, y = self._headers[self.pm.active_pane].menu_anchor()
        self.panel.popup_menu(self._dir_context_menu(self.active_pane()), x, y)
        self.panel.render()

    def _item_context_menu(self, pane: dict) -> Menu:
        """The menu for the row under the cursor (and the selection, for the
        operations that take one)."""
        entry = self._focused_entry()
        selected = entry is not None and str(entry) in pane["selected_files"]
        return Menu(
            MenuItem("Open", on_select=lambda: self._menu("open_item")),
            MenuItem("View File", on_select=self.view_file, enabled=entry is not None),
            MenuItem("Open With…", on_select=self.open_with, enabled=entry is not None),
            MenuItem("Deselect" if selected else "Select",
                     on_select=self._toggle_select_in_place),
            SEPARATOR,
            MenuItem("Rename…", on_select=self.rename, enabled=entry is not None),
            MenuItem("Duplicate", on_select=self.duplicate_files, enabled=entry is not None),
            SEPARATOR,
            MenuItem("Copy to Other Pane", on_select=self.copy_files, enabled=entry is not None),
            MenuItem("Move to Other Pane", on_select=self.move_files, enabled=entry is not None),
            MenuItem("Copy to…", on_select=self.copy_files_to, enabled=entry is not None),
            MenuItem("Move to…", on_select=self.move_files_to, enabled=entry is not None),
            MenuItem(f"Move to {trash.NAME}", on_select=self.delete_files,
                     enabled=entry is not None),
            MenuItem("Delete Permanently", on_select=self.delete_permanently,
                     enabled=entry is not None),
            SEPARATOR,
            MenuItem("Copy Name(s)", on_select=self.copy_names_to_clipboard,
                     enabled=entry is not None),
            MenuItem("Copy Full Path(s)", on_select=self.copy_paths_to_clipboard,
                     enabled=entry is not None),
            MenuItem("Open as List", on_select=lambda: self._menu("open_list_from_file"),
                     enabled=entry is not None),
            *self._user_menu_items("context"),
            SEPARATOR,
            MenuItem("Add to Favorites…", on_select=self._add_cursor_favorite,
                     enabled=entry is not None),
            SEPARATOR,
            MenuItem("Show Hidden Files", on_select=lambda: self._menu("toggle_hidden"),
                     checked=lambda: self.flm.show_hidden),
        )

    def _dir_context_menu(self, pane: dict) -> Menu:
        """The menu for the directory the pane is showing. A search-results
        pane has no directory of its own, so the items about one are disabled
        there; what is left (sorting, hidden files) still applies to its rows."""
        has_dir = not pane.get("virtual")
        local = has_dir and self._is_local(pane["path"])
        return Menu(
            MenuItem("New Directory…", on_select=self.create_directory, enabled=has_dir),
            MenuItem("New File…", on_select=self.create_file, enabled=has_dir),
            SEPARATOR,
            MenuItem("Add to Favorites…",
                     on_select=lambda: self._name_favorite(pane["path"], False),
                     enabled=has_dir),
            MenuItem("Copy Full Path", on_select=lambda: self._copy_dir_path(pane),
                     enabled=has_dir),
            MenuItem(_FILE_MANAGER_OPEN_LABEL,
                     on_select=lambda: self._open_dir_in_os(pane), enabled=local),
            MenuItem("Subshell Here", on_select=self.subshell, enabled=local),
            SEPARATOR,
            MenuItem("Sort…", on_select=self.show_sort_menu),
            MenuItem("Show Hidden Files", on_select=lambda: self._menu("toggle_hidden"),
                     checked=lambda: self.flm.show_hidden),
        )

    def _copy_dir_path(self, pane: dict) -> None:
        self._set_text_clipboard(str(pane["path"]))
        self.log_info(f"Copied path to clipboard: {pane['path']}")

    def _open_dir_in_os(self, pane: dict) -> None:
        """Open the pane's directory in the OS file manager (Finder / Explorer
        / the desktop's own)."""
        path = str(pane["path"])
        system = platform.system()
        try:
            if system == "Darwin":
                subprocess.run(["open", path], check=True)
            elif system == "Windows":
                os.startfile(path)
            else:
                subprocess.run(["xdg-open", path], check=True)
        except Exception as exc:
            self.log_info(f"Failed to open {path}: {exc}")
        else:
            self.log_info(f"Opened {path} in the file manager")

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
            paths, event=event, operations=("copy", "move"),
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
            if operation == "move":
                # The receiver moved them (Finder does the move itself), so the
                # source listing is stale.
                self._relist(self.pm.left_pane)
                self._relist(self.pm.right_pane)

    def _on_drop(self, pane_name: str, index: int, paths: list,
                 operation: str | None = None) -> None:
        """Files were dropped onto a pane — from another app (Finder, an
        editor) or from the other pane: copy or move them into the drop target.

        ``operation`` is what the platform's drag modifiers asked for
        (:mod:`puikit` reports it: Command/Shift moves, Option/Ctrl copies).
        With none held, the platform default applies: a move when the files
        are on the same volume as the target, a copy otherwise — Finder's and
        Explorer's rule (#589). A link request is refused; XeFM does not make
        aliases. The target is the directory *row* under
        the drop when it is a folder (like Finder), otherwise the pane's own
        directory. Refuses read-only destinations (a browsed archive) and a
        search-results (virtual) pane, and skips any source already sitting in the
        destination so a drop back onto its own folder is a no-op, not a conflict
        prompt. Reuses the shared copy engine (confirm + conflict resolution +
        threaded progress)."""
        plan = self._drop_plan(pane_name, index, paths, operation)
        if plan["kind"] == "in_place":
            # Released back onto the pane the drag started from, over its own
            # directory: the files are already here, so cancel the drag
            # silently rather than reporting a no-op copy (#230). Flag it so
            # _on_drag_complete also drops its "Dragged … out" log.
            self._drag_cancelled_in_place = True
            return
        if plan["kind"] == "refuse":
            self.log_info(plan["message"])
            return
        targets, dest_dir, operation = plan["targets"], plan["dest"], plan["operation"]
        verb = "Move" if operation == "move" else "Copy"

        def on_complete(result: dict) -> None:
            self._relist(self.pm.left_pane)
            self._relist(self.pm.right_pane)
            self.log_info(format_op_summary(verb, result))
            self._report_op_failures(verb, result)
            self.panel.render()

        run = self._fileops.move if operation == "move" else self._fileops.copy
        run(self.panel, targets, dest_dir, on_complete=on_complete, log=self.log_info)
        self.panel.render()

    # --- run -----------------------------------------------------------------

    def _drop_plan(self, pane_name: str, index: int, paths: list,
                   operation: str | None) -> dict:
        """What dropping ``paths`` at row ``index`` of a pane does — shared by
        the drop itself and the hover query that sets the cursor's badge, so
        the badge cannot promise one thing and the drop do another.

        ``{"kind": "do", "operation", "targets", "dest"}``, or
        ``{"kind": "refuse", "message"}``, or ``{"kind": "in_place"}`` for a
        drag released over the folder it came from."""
        pane = self.pane(pane_name)
        if pane.get("virtual"):
            return {"kind": "refuse",
                    "message": "Cannot drop here: this pane is a search-results view"}
        if self._is_archive(pane["path"]):
            return {"kind": "refuse",
                    "message": "Cannot drop here: this is a read-only archive"}
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
        targets = [Path(p) for p in paths if str(Path(p).parent) != str(dest_dir)]
        if not targets:
            if pane_name == self._drag_source_pane:
                return {"kind": "in_place"}
            return {"kind": "refuse",
                    "message": "Nothing to copy (already in this folder)"}
        if operation == "link":
            return {"kind": "refuse",
                    "message": "Dropping as a link is not supported; drop "
                               "without the link keys to copy or move"}
        if operation is None:
            operation = "move" if self._same_volume_cached(targets, dest_dir) else "copy"
        return {"kind": "do", "operation": operation, "targets": targets,
                "dest": dest_dir}

    def _same_volume_cached(self, targets: list, dest_dir) -> bool:
        """:func:`_same_volume`, remembered for the last question: the hover
        query asks it on every pointer move of a drag, with the same files."""
        key = (tuple(str(t) for t in targets), str(dest_dir))
        cached = getattr(self, "_same_volume_memo", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        answer = _same_volume(targets, dest_dir)
        self._same_volume_memo = (key, answer)
        return answer

    def _drop_effect(self, pane_name: str, index: int, paths: list,
                     operation: str | None) -> str:
        """The hover answer for the cursor's badge: what :meth:`_on_drop` would
        do here — "move", "copy", or "none" where it would refuse."""
        plan = self._drop_plan(pane_name, index, paths, operation)
        return plan["operation"] if plan["kind"] == "do" else "none"

    #: Positioned events routed to the widget under the pointer (the FilePanes own
    #: click + wheel/trackpad scroll and accept an OS FILE_DROP); keyboard uses
    #: XeFM's global keymap.
    _MOUSE = frozenset({
        EventType.MOUSE_DOWN, EventType.MOUSE_UP, EventType.MOUSE_CLICK,
        EventType.MOUSE_DRAG, EventType.MOUSE_SCROLL, EventType.FILE_DROP,
        EventType.FILE_DRAG_OVER,
    })

    def _menu_mnemonic(self, event) -> bool:
        """Alt+letter opens the menu whose title starts with that letter
        (Alt+F → File, Alt+G → Go) — the desktop accelerator convention,
        brought to the terminal menu (#304). Tried only after the keymap had
        no binding for the chord, so a user's own Alt-<letter> bindings keep
        winning; a no-op on native-menu backends, where the OS bar owns Alt.
        With a menu already open, the modal popup handles Alt+letter itself
        (the layer branch above), jumping between the bar's menus."""
        key = event.key
        if (frozenset(event.modifiers or ()) == frozenset({"alt"})
                and isinstance(key, str) and len(key) == 1 and key.isalpha()):
            return self.menu_bar.open_menu_mnemonic(key)
        return False

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
        # quit_app (Cmd-Q, Alt-F4) is the window's close button as a key: it
        # works over a dialog or a viewer too, so it is answered before any
        # layer sees the key.
        if (event.type is EventType.KEY
                and self.keys.is_action_for_event(event, "quit_app", context=_ctx.FILER)):
            self.key_sequence.cancel()
            self._on_quit_request()
            return
        # A modal layer (message box, menu popup) owns events while open: route
        # everything to it and let XeFM's global keymap stand down.
        if self.panel.has_layers:
            self.key_sequence.cancel()
            if self.panel.dispatch_event(event):
                self.panel.render()
            return
        if event.type is EventType.KEY:
            has_sel = bool(self.active_pane()["selected_files"])
            outcome, sequence_action = self.key_sequence.feed(event, has_sel)
            if outcome == key_sequence.WAIT:
                return
            if outcome == key_sequence.ACT:
                if self.dispatch(sequence_action):
                    self.panel.render()
                self._quick_view_follow()
                return
            if sequence_action is not None and self.dispatch(sequence_action):
                self.panel.render()
            action = self.keys.find_action_for_event(event, has_sel, _ctx.FILER)
            if self.dispatch(action):
                self.panel.render()
            elif action is None and self._menu_mnemonic(event):
                self.panel.render()
            elif (action is None and event.key == "escape"
                    and self._quick_view is not None):
                self._close_quick_view()
                self.log_info("Quick view closed")
                self.panel.render()
            elif action is None and self._type_ahead(event):
                self.panel.render()
            self._quick_view_follow()
            return
        if event.type in self._MOUSE:
            if self.panel.dispatch_event(event):
                self.panel.render()
            self._quick_view_follow()

    def _sequence_timed_out(self, action: str) -> None:
        """A key that is also the start of a longer sequence ran on its own,
        once KEY_SEQUENCE_TIMEOUT passed with nothing following."""
        if self.dispatch(action):
            self.panel.render()
        self._quick_view_follow()

    def run(self) -> None:
        self.panel.render()
        # 'startup' fires against a fully live app — panes listed, panel drawn —
        # which is the whole reason the event exists: a config's module body runs
        # long before any of that is true.
        _hooks.fire("startup", self._user_ctx)
        # After the first full render, so the dialog opens over a live UI.
        # Here rather than __init__: tests construct the app without run().
        # The first launch's keymap question comes before any tip of the day.
        if self._keymap_preset is None:
            self._ask_keymap_preset()
        else:
            self._maybe_show_startup_tip()
        self._layout_refresh_tick(first=True)
        try:
            self.backend.run_event_loop(self.on_event)
        finally:
            self._restore_streams()

    def _layout_refresh_tick(self, first: bool = False) -> None:
        """Repaint while a pane draws a column that goes stale on its own — a
        relative time ("5 min ago") — at the shortest interval one asked for;
        otherwise just look again later."""
        due = [v.refresh_interval for v in (self.left_view, self.right_view)
               if v.refresh_interval]
        if due and not first:
            self.panel.render()
        self.panel.call_later(min(due) if due else 30.0, self._layout_refresh_tick)

    def _restore_streams(self) -> None:
        """Put the real stdout/stderr back so anything printed after the event
        loop (a shutdown traceback, teardown warnings) reaches the terminal
        again. Idempotent: safe if the streams were already restored."""
        # Loggers go back to buffering too: the pane is no longer being drawn, so
        # a teardown warning belongs on the restored stderr, not on a dead queue.
        clear_log_sink()
        for stream in (sys.stdout, sys.stderr):
            if isinstance(stream, _StreamToLog):
                stream.drain_partial()
        if isinstance(sys.stdout, _StreamToLog):
            sys.stdout = self._orig_stdout
        if isinstance(sys.stderr, _StreamToLog):
            sys.stderr = self._orig_stderr


# XeFM-friendly spellings -> PuiKit backend names. Anything absent passes
# through verbatim, which is how the concrete names stay reachable — notably
# "curses", the escape hatch now that "tui" resolves to the VT backend
# everywhere (mapping it to "tui" here would silently take that hatch away).
_BACKENDS = {"tui": "tui", "gui": "gui", "macos": "gui",
             "web": "web", "webbrowser": "web", "browser": "web"}


#: ``--help`` blurb. Deliberately *not* ``__doc__``: the module docstring is
#: written for readers of the source (RST markup, architecture notes), and
#: argparse would reflow the whole thing into an unreadable wall of text.
_CLI_DESCRIPTION = """\
XeFM — a dual-pane file manager for the desktop and the terminal.

The same app runs as a native desktop window on Windows and macOS, as a TUI on
Windows, macOS and Linux, or in a browser tab. Choose with --backend.
"""

_CLI_EPILOG = """\
examples:
  xefm                            terminal — the default
  xefm --backend gui              native desktop window (Windows/macOS)
  xefm --backend web              browser tab
  xefm --left ~/projects --right ~/downloads
  xefm ext --help                 manage extension packages
  xefm skill --help               the skill that teaches AI agents XeFM
  xefm try --help                 XeFM in a throwaway home — to try, test or record a demo

Project home: https://github.com/crftwr/xefm
"""


def create_parser() -> argparse.ArgumentParser:
    """Build the command-line parser. Factored out of ``main`` so the entry
    point's argument contract (``--version``, ``--help``, the pane flags) can be
    unit-tested without launching the app."""
    parser = argparse.ArgumentParser(
        prog="xefm",
        description=_CLI_DESCRIPTION,
        epilog=_CLI_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-v", "--version", action="version",
                        version=f"XeFM {_VERSION}")
    parser.add_argument("--backend", default="tui",
                        help="tui (terminal, the default) | gui (native desktop, Windows/macOS) | web (browser tab)")
    # A developer diagnostic, not a preference: it belongs on the command line
    # of the run being investigated rather than in the config file.
    parser.add_argument("--ui-watchdog", nargs="?", const="1", default=None, metavar="MS",
                        help="log a stack trace whenever the UI thread stalls, with an "
                             "optional threshold in milliseconds (default 250)")
    # ``default=None`` lets us tell an explicit ``--left .`` from no flag: an
    # explicitly given directory wins over the one saved from the last session.
    parser.add_argument("--left", default=None, help="left pane startup directory")
    parser.add_argument("--right", default=None, help="right pane startup directory")
    return parser


def _web_access_message(url: str) -> str:
    """The startup notice for ``--backend web``: where the UI is being served,
    and how to reach it from another machine. PuiKit's web server binds
    127.0.0.1 only, so a remote browser needs an SSH tunnel to this host — the
    command below is ready to paste, carrying this run's actual (ephemeral)
    port. The user/host part is a best guess (``getpass`` / ``gethostname``);
    a user whose ssh address differs substitutes their own."""
    port = urlsplit(url).port
    try:
        user_host = f"{getpass.getuser()}@{socket.gethostname()}"
    except Exception:
        # getuser() has no username to report (stripped container / odd env) —
        # a placeholder keeps the hint useful rather than failing startup.
        user_host = "USER@HOST"
    return (
        f"XeFM web UI: {url} — reachable from this machine only.\n"
        f"To use it from another machine, start a tunnel there:\n"
        f"\n"
        f"    ssh -N -L {port}:127.0.0.1:{port} {user_host}\n"
        f"\n"
        f"then open {url} in that machine's browser."
    )


def main() -> None:
    # Before anything can open a connection: HTTPS is verified by the OS on
    # macOS and Windows, every channel alike (#676, xefm/tls.py).
    from xefm.tls import use_os_trust_store
    use_os_trust_store()
    # XeFM.app started from Finder/Dock runs with launchd's bare PATH, not the
    # login shell's, so Homebrew's ffmpeg/fpcalc were invisible to anything that
    # searches *our* PATH: similar-files, an extension's required-program check
    # (#627). Extending the child-process env alone was not enough - extend our
    # own, once, before anything looks a program up.
    from xefm.external_programs import ensure_common_paths_in_env
    ensure_common_paths_in_env(os.environ)
    # `xefm ext …` manages extension packages and never opens a window, so it
    # is dispatched before the UI's own arguments are parsed.
    if len(sys.argv) > 1 and sys.argv[1] == "ext":
        from xefm.extension_cli import main as ext_main
        sys.exit(ext_main(sys.argv[2:]))
    # `xefm skill` writes or installs the AI-agent skill — no window either.
    if len(sys.argv) > 1 and sys.argv[1] == "skill":
        from xefm.extension_cli import skill_main
        sys.exit(skill_main(sys.argv[2:]))
    # `xefm try` runs XeFM itself, but in a throwaway home and, with --keys, in
    # a pseudo-terminal of its own — never in this process's window.
    if len(sys.argv) > 1 and sys.argv[1] == "try":
        from xefm.try_cli import main as try_main
        sys.exit(try_main(sys.argv[2:]))
    # `xefm keys` reads the config and prints what each key does — no window.
    if len(sys.argv) > 1 and sys.argv[1] == "keys":
        from xefm.keys_cli import main as keys_main
        sys.exit(keys_main(sys.argv[2:]))
    # `xefm deps sync|status` — the packages ~/.xefm/requirements.txt declares.
    if len(sys.argv) > 1 and sys.argv[1] == "deps":
        from xefm.deps_cli import main as deps_main
        sys.exit(deps_main(sys.argv[2:]))
    args = create_parser().parse_args()

    backend_name = _BACKENDS.get(args.backend, args.backend)
    # Publish the resolved backend so is_desktop_mode() (used by the config,
    # e.g. TEXT_EDITOR = 'code' in GUI vs 'vim' in terminal) reads it directly
    # rather than re-sniffing sys.argv. Set before get_config()/XeFMApp load the
    # config below.
    os.environ["XEFM_BACKEND"] = backend_name
    # PuiKit's UI-thread stall detector reports work that blocks the event loop
    # (see doc/dev/UI_WATCHDOG_SYSTEM.md). Off unless asked for, and set here
    # because PuiKit reads the variable when the backend opens, below.
    if args.ui_watchdog is not None:
        os.environ["PUIKIT_UI_WATCHDOG"] = args.ui_watchdog
        if importlib.util.find_spec("puikit._watchdog") is None:
            # An older PuiKit ignores the variable, and a switch that silently
            # does nothing is worse than no switch at all when the thing being
            # investigated is "why did nothing get reported?".
            getLogger("Main").warning(
                "--ui-watchdog needs a PuiKit with the UI-thread stall detector; "
                "the installed one ignores it")
    # Those reports - and PuiKit's own warnings - are logged under "puikit",
    # which is not one of XeFM's loggers and so has no route into the log pane
    # until it is given one.
    route_library_logger("puikit")
    backend_kwargs = {}
    if backend_name == "gui":
        # Both kwargs are the native window's business, which is why they are
        # only passed here: the terminal has no window to speak of and the web
        # backend's is a browser tab (WebBackend takes neither).
        #
        # Position and size persist and are restored across runs, via the
        # NSWindow frame-autosave feature.
        backend_kwargs["frame_autosave_name"] = "XeFMMainWindow"
        # Take the click that brings XeFM forward, rather than letting the window
        # system spend it on activation alone. A drag starts on the press, so a
        # swallowed press started nothing: the first drag out of a background XeFM
        # did nothing at all, and the user had to click the window forward and
        # begin again (issue #431). Finder's bargain, and Finder's cost — that
        # click now also lands on the row it is over.
        backend_kwargs["style"] = WindowStyle(takes_first_click=True)
    # Ground the pixel backends' base (grid) font in the user's config: the base
    # unit — hence the on-screen text size — is derived from this font's glyph
    # box, so MONO_FONT_NAME and FONT_SIZE take effect here. The base font must be
    # monospaced; MONO_FONT_NAME=None falls back to PuiKit's bundled Noto Sans
    # Mono. Both the native GUI and the browser backend read it; the TUI has one
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
        if backend_name == "web":
            # A deliberate console print, not the unified logger: the notice
            # must reach the terminal the user launched from (over SSH that
            # terminal is all they have), and the log pipeline that print()
            # is normally routed into — XeFMApp redirects the streams in
            # __init__ — doesn't exist yet. The port is only known here, after
            # open() has bound the server.
            print(_web_access_message(backend.url), flush=True)
        XeFMApp(
            backend,
            args.left if args.left is not None else ".",
            args.right if args.right is not None else ".",
            left_provided=args.left is not None,
            right_provided=args.right is not None,
        ).run()


if __name__ == "__main__":
    main()

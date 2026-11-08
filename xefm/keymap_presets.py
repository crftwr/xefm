"""Keymap presets (#565, #597): the whole keymap, chosen as one.

A preset is a complete keymap. The presets are peers: none is the default
the others are laid over, and a launch with none chosen — a new install or
an upgrade from before presets alike — asks which one to use.

- **AFX** (:mod:`xefm.keymap_afx`) — one letter runs one command.
- **Orthodox** — function keys, and typing a letter searches.
- **OS native** — Finder's keys on macOS, Explorer's elsewhere (#587).
- **Vim style** — Vim-style keys: ``hjkl``, ``gg`` / ``G``, ``yy`` / ``dd``
  / ``p``, ``/`` and ``n`` (#587).

A preset is **a key table plus a behavior flag**:

- ``bindings`` — action name → keys, or a function returning that table
  when it depends on the platform and backend (AFX, OS native);
- ``type_ahead`` — an unbound printable key in the file list starts
  incremental search with that character, the way typing in a file list does
  almost everywhere else.

Every preset is laid over :mod:`xefm.keymap_common`: the viewers', dialogs'
and search bars' keys (they take typed text or have no file list, so they are
the same under every preset), the file list's keys that are not letters or
digits, and the desktop app's platform keys. That table binds no bare letter
or digit in the file list, so a preset that binds none (Orthodox, OS native)
leaves typing to type-ahead. A preset's entry replaces the action's entry
there; an action it does not name keeps the common keys.

``config.py``'s ``KEY_BINDINGS`` is laid over the preset in force, action by
action, **always**: an entry there replaces that action's keys whatever the
preset says, and the keys it binds leave the preset actions that had them
(:func:`_release_claimed_keys`, #662). It ships with examples only.

:func:`apply` writes the result into ``config.KEY_BINDINGS`` itself, so every
reader — the app's keymap, the help dialog, the menus, the directory diff
viewer — sees one table. The table ``config.py`` was loaded with is kept on
the config (``_KEY_BINDINGS_BASE``), so presets can be switched back and
forth at runtime without compounding.
"""

from __future__ import annotations

import copy
import sys
from dataclasses import dataclass, field
from typing import Callable, Optional, Union

from xefm.log_manager import getLogger

logger = getLogger("Keymap")

#: XeFM's own letter layout, named for its lineage: the single-key Japanese
#: filers — the X68000 ones, then AFX (あふ), then cfiler — rather than for
#: being the default, which says nothing about what it is. Not a replica of
#: AFX's table; the direction, not the details.
AFX = "afx"
ORTHODOX = "orthodox"
NATIVE = "native"
VIM = "vim"
#: The table in force for the moment a launch with no preset chosen spends
#: before its question is answered. Not a default: nothing is stored.
FALLBACK = AFX
#: Earlier spellings still accepted, so a config or a saved menu choice that
#: says ``'default'`` keeps meaning what it meant.
ALIASES = {"default": AFX}


def canonical(name: Optional[str]) -> Optional[str]:
    """``name`` with an old spelling (``'default'``) replaced by its preset."""
    return ALIASES.get(name, name) if name else name


@dataclass(frozen=True)
class Preset:
    name: str
    label: str
    description: str
    bindings: Union[dict, Callable[[], dict]] = field(default_factory=dict)
    type_ahead: bool = False


#: The function-key layout shared by the "orthodox" two-pane file managers —
#: F3 view, F5 copy, F8 delete — and nothing on a bare letter.
_ORTHODOX = Preset(
    name=ORTHODOX,
    label="Orthodox",
    description=("F3 view, F4 edit, F5 copy, F6 move, F7 new folder, F8 "
                 "delete; typing a letter searches."),
    type_ahead=True,
    # Total Commander's default keys wherever XeFM has the action (its
    # keyboard map: Configuration > Keyboard, KEYBOARD.TXT). Where TC's key
    # does something XeFM has no action for, the key is simply not bound;
    # where XeFM has an action TC has no key for, the action keeps no key
    # here and is reached from the menus and the command palette. Actions
    # from features not merged yet are listed too: ``apply`` skips any the
    # running XeFM does not have.
    bindings={
        # Application
        "help": ["F1"],
        "reread": ["F2", "Ctrl-R"],
        "menu": ["F9", "F10", "ALT"],
        "quit": ["Alt-F4"],
        "redraw": [],
        "programs": [],
        "context_menu": ["Shift-F10", "APPS"],
        "command_palette": ["Ctrl-Shift-P"],   # TC has none; Ctrl-T is tabs
        # Files
        "view_file": ["F3"],
        "edit_file": ["F4"],
        "create_file": ["Shift-F4"],
        "copy_files": ["F5"],
        "duplicate_files": ["Shift-F5"],        # TC: copy with rename, same dir
        "move_files": ["F6"],
        "rename": ["Shift-F6", "Ctrl-M"],       # Ctrl-M: multi-rename
        "create_directory": ["F7"],
        "delete_files": ["F8", "DELETE"],
        "delete_permanently": ["Shift-F8", "Shift-DELETE"],
        "copy_files_to": [],
        "move_files_to": [],
        "file_details": ["Alt-ENTER"],          # TC: properties
        "create_archive": ["Alt-F5"],
        "extract_archive": ["Alt-F9", "Alt-F6"],
        "clipboard_copy": ["Ctrl-C"],
        "clipboard_cut": ["Ctrl-X"],
        "clipboard_paste": ["Ctrl-V"],
        "copy_names": [],
        "copy_paths": ["Ctrl-P"],
        # Search and filter
        "find_files": ["Alt-F7"],
        "find_in_files": [],
        "filter": ["Ctrl-S"],                   # TC: quick filter
        "clear_filter": ["Ctrl-F10"],           # TC: show all files
        "isearch": [],                          # typing a letter searches
        "index_search": [],
        "find_by_tag": [],
        # Places
        "open_item": ["ENTER", "Ctrl-PAGE_DOWN"],
        "go_parent": ["BACKSPACE", "Ctrl-PAGE_UP"],
        "go_root": ["Ctrl-BACKSLASH"],
        "drives": ["Alt-F1", "Alt-F2"],          # TC: left / right drive
        "history": ["Alt-DOWN"],
        "go_back": ["Alt-LEFT"],
        "go_forward": ["Alt-RIGHT"],
        "favorites": ["Ctrl-D"],                # TC: directory hotlist
        "connect_server": ["Ctrl-F", "Ctrl-N"],  # TC: FTP connect / new URL
        "compare_selection": ["Shift-F2"],      # TC: compare file lists
        "diff_directories": [],
        "flat_view": ["Ctrl-B"],                # TC: branch view
        "quick_view": ["Ctrl-Q"],
        # Tabs
        "new_tab": ["Ctrl-T"],
        "open_in_new_tab": ["Ctrl-UP"],
        "close_tab": ["Ctrl-W"],
        "next_tab": ["Ctrl-TAB"],
        "prev_tab": ["Ctrl-Shift-TAB"],
        # Selection and cursor
        "toggle_select_down": ["INSERT", "SPACE"],
        "select_by_pattern": ["+"],             # TC: Num +
        "unselect_by_pattern": ["-"],           # TC: Num -
        "toggle_select_files": ["*"],           # TC: Num * (invert)
        "select_all": ["Ctrl-A"],
        "unselect_all": ["Ctrl-MINUS"],         # TC: Ctrl-Num -
        "select_same_extension": ["Alt-+"],     # TC: Alt-Num +
        "cursor_top": ["HOME", "Ctrl-HOME"],
        "cursor_bottom": ["END", "Ctrl-END"],
        "cursor_next_selected": [],             # Ctrl-Up opens a tab here
        "cursor_prev_selected": [],
        "reveal_in_os": [],                     # Ctrl-R rereads here
        "reset_pane_boundary": [],              # '-' unselects here
        "reset_log_height": [],                 # '_' starts names (__init__.py)
        # Sorting
        "quick_sort_name": ["Ctrl-F3"],
        "quick_sort_ext": ["Ctrl-F4"],
        "quick_sort_date": ["Ctrl-F5"],
        "quick_sort_size": ["Ctrl-F6"],
        # The viewers, as Lister: F7 searches, F3 / Shift-F3 find again —
        # scoped, since F7 and F3 are the file list's new folder and view
        # (#737). The isearch bar takes F3 / Shift-F3 from these too.
        "text_viewer.isearch": ["F7"],
        "text_viewer.search_next": ["F3"],
        "text_viewer.search_prev": ["Shift-F3"],
        "file_diff.isearch": ["F7"],
        "file_diff.search_next": ["F3"],
        "file_diff.search_prev": ["Shift-F3"],
    },
)

def _native_bindings() -> dict:
    """The OS native table for the case XeFM is running in (#587).

    Finder's keys in the macOS desktop app, Explorer's in the Windows one, and
    in a terminal on any OS the same layout with every chord a terminal can
    actually send — the "three cases" note at the foot of
    :mod:`xefm.keymap_common` says which those are. The preset is chosen once for
    both apps (``~/.xefm``), so the terminal case has to stand on its own: the
    desktop tables are it with the platform chord in front, never a different
    layout.

    The two-pane operations have no OS convention, so they take the function
    keys every two-pane manager uses (F5 copy, F6 move to the other pane), as
    Orthodox does. Enter opens, on macOS too: Finder's Enter-renames would
    leave no key to open a folder that every other preset opens with Enter.
    """
    keys = {
        # Opening and moving around
        "open_item": ["ENTER"],
        "go_parent": ["BACKSPACE", "Alt-UP"],
        "go_back": ["Alt-LEFT"],
        "go_forward": ["Alt-RIGHT"],
        "cursor_top": ["HOME", "Ctrl-HOME"],
        "cursor_bottom": ["END", "Ctrl-END"],
        "jump_to_path": ["Ctrl-L", "Alt-D"],
        "history": ["Alt-DOWN"],
        "new_tab": ["Ctrl-T"],
        # Files
        "rename": ["F2"],
        "view_file": ["F3"],
        "edit_file": ["F4"],
        "copy_files": ["F5"],
        "move_files": ["F6"],
        "create_directory": ["F7"],
        "delete_files": ["DELETE", "F8"],
        "delete_permanently": ["Shift-DELETE", "Shift-F8"],
        "clipboard_copy": ["Ctrl-C"],
        "clipboard_cut": ["Ctrl-X"],
        "clipboard_paste": ["Ctrl-V"],
        "file_details": ["Alt-I"],
        "quick_view": ["Alt-P"],                # Explorer's preview pane
        "context_menu": ["Shift-F10", "APPS"],
        # Selection: Space marks, as in Explorer; typing a letter selects by name
        "toggle_select_down": ["SPACE", "INSERT"],
        "select_all": ["Ctrl-A"],
        "unselect_all": [],
        # Search
        "find_files": ["Ctrl-F"],
        "index_search": [],
        "isearch": [],                          # typing a letter searches
        # Application
        "help": ["F1"],
        "reread": ["Ctrl-R"],
        "reveal_in_os": [],                     # Ctrl-R rereads here
        "redraw": [],                           # F5 copies here
        "command_palette": ["Ctrl-K"],
        # Ctrl-Q always asks. Cmd-Q / Alt-F4 (quit_app) come with the AFX
        # table's desktop keys, which every preset starts from.
        "quit": ["Ctrl-Q"],
        # The viewers find as Windows' own viewers do (#737): scoped, since
        # Ctrl-F is the file list's find_files.
        "text_viewer.isearch": ["Ctrl-F"],
        "text_viewer.search_next": ["F3"],
        "text_viewer.search_prev": ["Shift-F3"],
        "file_diff.isearch": ["Ctrl-F"],
        "file_diff.search_next": ["F3"],
        "file_diff.search_prev": ["Shift-F3"],
    }
    from xefm.backend_detector import is_desktop_mode
    if not is_desktop_mode():
        return keys
    if sys.platform == "darwin":
        # Finder. A Command chord goes first, since a menu shows keys[0].
        keys.update({
            "open_item": ["ENTER", "Command-DOWN"],
            "go_parent": ["Command-UP", "BACKSPACE", "Alt-UP"],
            "go_back": ["Command-LEFT_BRACKET", "Alt-LEFT"],
            "go_forward": ["Command-RIGHT_BRACKET", "Alt-RIGHT"],
            "jump_to_path": ["Command-Shift-G", "Ctrl-L"],
            "new_tab": ["Command-T", "Ctrl-T"],
            "close_tab": ["Command-W", "Ctrl-W"],
            "delete_files": ["Command-BACKSPACE", "DELETE", "F8"],
            "delete_permanently": ["Command-Alt-BACKSPACE", "Shift-DELETE", "Shift-F8"],
            "create_directory": ["Command-Shift-N", "F7"],
            "clipboard_copy": ["Command-C", "Ctrl-C"],
            "clipboard_cut": ["Command-X", "Ctrl-X"],
            "clipboard_paste": ["Command-V", "Ctrl-V"],
            "copy_paths": ["Command-Alt-C", "Ctrl-P"],
            "file_details": ["Command-I", "Alt-I"],
            # Quick Look is Space; marking moves to Ctrl-Space, which every
            # backend delivers.
            "quick_view": ["SPACE", "Alt-P"],
            "toggle_select_down": ["Ctrl-SPACE", "INSERT"],
            "select_all": ["Command-A", "Ctrl-A"],
            "find_files": ["Command-F", "Ctrl-F"],
            "toggle_hidden": ["Command-Shift-.", "."],
            "command_palette": ["Command-Shift-P", "Ctrl-K"],
            # The standard macOS find keys in the viewers.
            "text_viewer.isearch": ["Command-F", "Ctrl-F"],
            "text_viewer.search_next": ["Command-G", "F3"],
            "text_viewer.search_prev": ["Command-Shift-G", "Shift-F3"],
            "file_diff.isearch": ["Command-F", "Ctrl-F"],
            "file_diff.search_next": ["Command-G", "F3"],
            "file_diff.search_prev": ["Command-Shift-G", "Shift-F3"],
        })
    elif sys.platform == "win32":
        keys.update({
            "create_directory": ["Ctrl-Shift-N", "F7"],
            "copy_paths": ["Ctrl-Shift-C", "Ctrl-P"],
            "file_details": ["Alt-ENTER", "Alt-I"],
            "command_palette": ["Ctrl-Shift-P", "Ctrl-K"],
        })
    return keys


#: Finder's and Explorer's keys, with the two-pane operations on F5 / F6.
_NATIVE = Preset(
    name=NATIVE,
    label="OS native",
    description=("Finder's keys on macOS, Explorer's elsewhere, for copy, "
                 "paste, rename and delete; F5 copies and F6 moves to the "
                 "other pane; typing a letter selects by name."),
    bindings=_native_bindings,
    type_ahead=True,
)

#: vifm's normal-mode keys (vifm 0.15 manual, and the sample vifmrc a new
#: install gets: F3-F8, w, s, S), wherever XeFM has the action. Like AFX it
#: is a letter layout, laid over the common table (which binds no letter), and
#: nothing is typed ahead: search is '/', as in Vim. Sequences ('g g', 'y y') are
#: KEY_BINDINGS key sequences, waiting KEY_SEQUENCE_TIMEOUT where a prefix is
#: also a key of its own.
_VIM_BINDINGS = {
    # Moving: h is the parent directory and l opens, as in vifm, not a column
    # step; the arrows keep AFX's meaning.
    "cursor_down": ["j", "DOWN"],
    "cursor_up": ["k", "UP"],
    "go_parent": ["h", "g h", "BACKSPACE"],
    "open_item": ["l", "g l", "ENTER"],
    "cursor_top": ["g g", "HOME", "Ctrl-HOME"],
    "cursor_bottom": ["Shift-G", "END", "Ctrl-END"],
    "page_down": ["Ctrl-F", "PAGE_DOWN"],
    "page_up": ["Ctrl-B", "PAGE_UP"],
    "half_page_down": ["Ctrl-D"],
    "half_page_up": ["Ctrl-U"],
    "switch_pane": ["TAB", "SPACE"],
    "go_back": ["Ctrl-O", "Alt-LEFT"],
    "go_forward": ["Alt-RIGHT"],               # vifm's Ctrl-I is Tab here
    "jump_to_path": ["g p"],
    "favorites": ["'"],                        # vifm's marks
    # Selecting. vifm's v starts a visual block; here it fills from the
    # nearest mark to the cursor, which is what a block ends as.
    "toggle_select_in_place": ["t"],
    "toggle_select_down": ["INSERT"],
    "select_range": ["v", "Shift-SPACE"],
    "select_all": [],
    "unselect_all": ["ESCAPE"],                # vifm: Esc clears the selection
    "select_by_pattern": [],                   # ' is marks here
    # Files: yank / delete / put. dd goes to the Trash and DD past it, as in
    # vifm; p pastes what yy yanked, and x cuts (vifm's P moves a yank; here a
    # cut and a paste do).
    "clipboard_copy": ["y y", "Ctrl-C"],
    "clipboard_cut": ["x", "Ctrl-X"],
    "clipboard_paste": ["p", "Ctrl-V"],
    "delete_files": ["d d", "DELETE", "F8"],
    "delete_permanently": ["Shift-D Shift-D", "Shift-DELETE", "Shift-F8"],
    "rename": ["c w"],
    "view_file": ["e", "F3"],
    "open_with_os": ["g x"],                   # Vim's gx; Ctrl-O goes back here
    "diff_files": [],                          # '=' filters here
    "edit_file": ["F4"],
    "copy_files": ["F5"],
    "move_files": ["F6"],
    "create_directory": ["F7"],
    "quick_view": ["w"],
    "file_details": ["Ctrl-G"],
    "jobs": [],                                # Ctrl-G is file details here
    # Search, hidden files, filters
    "isearch": ["/"],
    "search_next": ["n"],
    "search_prev": ["Shift-N"],
    "index_search": [],                        # Ctrl-F pages here
    "toggle_hidden": ["z a"],
    "filter": ["="],
    "clear_filter": ["z r"],
    "sort": ["Shift-S"],
    # Application
    "command_palette": [":", "Ctrl-T"],
    "context_menu": ["APPS", "Shift-F10"],     # '/' searches here
    "subshell": ["s"],
    "reread": ["Ctrl-L"],
    "redraw": [],                              # F5 copies here
    "quit": ["Shift-Z Shift-Z", "Shift-Z Shift-Q"],
    # The text viewer, as vifm's view mode with Vim's motions
    "text_viewer.scroll_down": ["j", "DOWN"],
    "text_viewer.scroll_up": ["k", "UP"],
    "text_viewer.scroll_left": ["h", "LEFT"],
    "text_viewer.scroll_right": ["l", "RIGHT"],
    "text_viewer.page_down": ["Ctrl-F", "Ctrl-D", "PAGE_DOWN", "SPACE"],
    "text_viewer.page_up": ["Ctrl-B", "Ctrl-U", "PAGE_UP"],
    "text_viewer.scroll_top": ["g g", "HOME"],
    "text_viewer.scroll_bottom": ["Shift-G", "END"],
    "text_viewer.quit": ["q", "Shift-Z Shift-Z"],
}

_VIM = Preset(
    name=VIM,
    label="Vim style",
    description=("hjkl to move, gg / G, yy / dd / p, cw rename, / and n to "
                 "search, ZZ to quit."),
    bindings=_VIM_BINDINGS,
)

def _afx_bindings() -> dict:
    from xefm import keymap_afx
    return keymap_afx.own_bindings()


_AFX = Preset(
    name=AFX,
    label="AFX style",
    description=("C copy, M move, K delete, V view, E edit; one letter runs "
                 "one command."),
    bindings=_afx_bindings,
)

PRESETS: dict[str, Preset] = {AFX: _AFX, ORTHODOX: _ORTHODOX, NATIVE: _NATIVE,
                               VIM: _VIM}

LABELS = {name: preset.label for name, preset in PRESETS.items()}


def get(name: Optional[str]) -> Preset:
    """The preset called ``name``; :data:`FALLBACK` for None and for a name
    nothing answers to (which is logged)."""
    name = canonical(name)
    preset = PRESETS.get(name) if name else None
    if preset is None:
        if name:
            logger.warning(f"Unknown keymap preset {name!r}; using {FALLBACK!r}")
        preset = PRESETS[FALLBACK]
    return preset


def resolve(config, chosen: Optional[str]) -> Optional[str]:
    """The preset in force: ``KEY_PRESET`` from the config when it names one,
    else ``chosen`` (the first-launch or View menu choice). None when neither
    names a preset — nothing has been chosen yet."""
    for name in (canonical(getattr(config, "KEY_PRESET", None)), canonical(chosen)):
        if name in PRESETS:
            return name
    return None


def _keys_of(value) -> list:
    if isinstance(value, dict):
        return list(value.get("keys", []))
    return list(value or [])


def is_typing_key(expr: str) -> bool:
    """A binding a user types as text: a bare letter or digit, or a Shift'ed
    letter (which is a capital)."""
    if len(expr) == 1:
        return expr.isalnum()
    if expr.startswith("Shift-") and len(expr) == len("Shift-") + 1:
        return expr[-1].isalpha()
    return False


def _typing_contexts() -> set:
    """The action names the common table binds no bare letter or digit for:
    the file list's own and the shared ones, where a letter is the preset's
    to give (a command in AFX and Vim style, type-ahead in Orthodox and OS
    native). A viewer's own actions (``text_viewer.toggle_wrap``) keep their
    letters there — nothing is typed into a viewer."""
    from xefm.actions import COMMON, FILER, registry
    return {a.name for a in registry.actions(FILER)} | \
        {a.name for a in registry.actions(COMMON)}


def table(name: Optional[str]) -> dict:
    """Preset ``name``'s whole keymap, before ``config.py`` is laid over it:
    the common table with the preset's ``bindings`` laid over it, in the
    common table's order."""
    from xefm import keymap_common
    preset = get(name)
    result = keymap_common.bindings()
    bindings = preset.bindings() if callable(preset.bindings) else preset.bindings
    for action, keys in bindings.items():
        # A preset may name actions of features this XeFM does not have yet;
        # binding them would only claim their keys for nothing.
        if not _known(action):
            continue
        # A plain list carries no selection gate (an orthodox F5 copies the
        # cursor item when nothing is marked); AFX's {'keys', 'selection'}
        # entries keep theirs.
        result[action] = copy.deepcopy(keys) if isinstance(keys, dict) else list(keys)
    return result


def _known(action: str) -> bool:
    """Whether a preset may bind ``action``: an action of any context — a
    viewer's own ('text_viewer.scroll_down') as much as the file list's, since
    the Vim style moves the text viewer too — or a context-qualified rebind
    ('text_viewer.quit'), the same spelling ``KEY_BINDINGS`` takes."""
    from xefm.actions import CONTEXTS, registry
    if any(registry.resolve(context, action) for context in CONTEXTS):
        return True
    context, _, name = action.partition(".")
    return context in CONTEXTS and bool(name) and \
        registry.canonical(context, name) is not None


def _current_name(name: str) -> str:
    """The current name of the action ``name`` refers to — an old name
    (``branch_view``) resolves to the one the preset tables use."""
    from xefm.actions import FILER, registry
    context = name.split(".", 1)[0] if "." in name else FILER
    for ctx in dict.fromkeys((context, FILER)):
        try:
            current = registry.canonical(ctx, name)
        except Exception as e:
            logger.error(f"Could not resolve action name {name!r}: {e}")
            current = None
        if current:
            return current
    return name


def overrides(config) -> dict:
    """``config.py``'s own ``KEY_BINDINGS`` — what :func:`apply` lays over
    the preset — as it was loaded."""
    base = getattr(config, "_KEY_BINDINGS_BASE", None)
    if base is None:
        base = copy.deepcopy(getattr(config, "KEY_BINDINGS", None) or {})
        config._KEY_BINDINGS_BASE = base
    return base


def replaced(config, name: Optional[str]) -> list:
    """The actions whose keys ``config.py``'s ``KEY_BINDINGS`` changes from
    preset ``name``'s — an empty list when it changes none."""
    preset_table = table(name)
    result = []
    for action, value in overrides(config).items():
        current = _current_name(action) if isinstance(action, str) else action
        if preset_table.get(current) != value:
            result.append(action)
    return result


def _selection_of(value) -> str:
    if isinstance(value, dict):
        return value.get("selection", "any")
    return "any"


def _reach(name: str) -> frozenset:
    """The contexts in which a ``KEY_BINDINGS`` entry named ``name`` binds
    keys. A scoped rebind (``'diff_viewer.quit'``, not itself an action)
    reaches its one context; any other name, every context that resolves it —
    all of them, for a ``common`` action."""
    from xefm.actions import registry
    if "." in name:
        context, rest = name.split(".", 1)
        if registry.has_context(context) and registry.resolve(context, name) is None:
            return frozenset({context}) if registry.canonical(context, rest) else frozenset()
    return frozenset(c for c in registry.contexts() if registry.canonical(c, name))


def _release_claimed_keys(result: dict, own: dict) -> None:
    """Take each key ``config.py`` binds off the preset actions it does not
    mention (#662), so binding ``Shift-T`` to one action is enough — without
    also emptying the action the preset gave ``Shift-T`` to.

    A preset action keeps the key where the user's entry would not take its
    place: when the action is reached in a context the user's entry is not
    (a ``common`` action's key, rebound for the file list alone, still works in
    the viewers), or when the two selection gates never hold together
    (``required`` and ``none``). :func:`apply` lists ``config.py``'s entries
    first, so in what overlap is left the user's entry is still the one
    matched."""
    from xefm.config import KeyBindings
    parse = KeyBindings({})._parse_key_expression
    claims = []
    for action, value in own.items():
        if not isinstance(action, str):
            continue
        keys = {parse(k) for k in _keys_of(value)}
        if keys:
            claims.append((keys, _reach(action), _selection_of(value)))
    if not claims:
        return
    for action, value in list(result.items()):
        if not isinstance(action, str):
            continue
        reach = _reach(action)
        selection = _selection_of(value)

        def claimed(key) -> bool:
            parsed = parse(key)
            return any(parsed in keys and reach <= where
                       and {selection, theirs} != {"required", "none"}
                       for keys, where, theirs in claims)

        keys = _keys_of(value)
        kept = [k for k in keys if not claimed(k)]
        if len(kept) != len(keys):
            result[action] = dict(value, keys=kept) if isinstance(value, dict) else kept


def apply(config, name: Optional[str]) -> None:
    """Make ``config.KEY_BINDINGS`` preset ``name``'s keymap with
    ``config.py``'s entries laid over it, and set ``config._KEY_TYPE_AHEAD``.
    None applies :data:`FALLBACK`."""
    own = overrides(config)
    result = table(name)
    for action in own:
        # Under an old name, the entry still replaces the action: the preset's
        # entry under the current name would otherwise be matched first.
        current = _current_name(action) if isinstance(action, str) else action
        result.pop(current, None)
        result.pop(action, None)
    _release_claimed_keys(result, own)
    # config.py's entries first: the context tables try entries in this order,
    # so where a preset action keeps a key the user also bound, the user's
    # binding is still the one a press finds.
    merged = {action: copy.deepcopy(value) for action, value in own.items()}
    merged.update(result)
    config._KEY_TYPE_AHEAD = get(name).type_ahead
    config.KEY_BINDINGS = merged


def type_ahead(config) -> bool:
    """Whether the preset in force starts a search on an unbound typed key."""
    return bool(getattr(config, "_KEY_TYPE_AHEAD", False))

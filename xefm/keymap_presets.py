"""Keymap presets (#565, #597): the whole keymap, chosen as one.

A preset is a complete keymap. The presets are peers: none is the default
the others are laid over, and a launch with none chosen — a new install or
an upgrade from before presets alike — asks which one to use.

- **AFX** (:mod:`xefm.keymaps.afx`) — one letter runs one command.
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

Every preset is laid over :mod:`xefm.keymaps.common`: the viewers', dialogs'
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

from xefm import keymaps
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
    bindings=keymaps.orthodox.own_bindings,
)

#: Finder's and Explorer's keys, with the two-pane operations on F5 / F6.
_NATIVE = Preset(
    name=NATIVE,
    label="OS native",
    description=("Finder's keys on macOS, Explorer's elsewhere, for copy, "
                 "paste, rename and delete; F5 copies and F6 moves to the "
                 "other pane; typing a letter selects by name."),
    bindings=keymaps.native.own_bindings,
    type_ahead=True,
)

_VIM = Preset(
    name=VIM,
    label="Vim style",
    description=("hjkl to move, gg / G, yy / dd / p, cw rename, / and n to "
                 "search, ZZ to quit."),
    bindings=keymaps.vim.own_bindings,
)

_AFX = Preset(
    name=AFX,
    label="AFX style",
    description=("C copy, M move, K delete, V view, E edit; one letter runs "
                 "one command."),
    bindings=keymaps.afx.own_bindings,
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
    preset = get(name)
    result = keymaps.common.bindings()
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

"""When a menu bar item is enabled (#1019).

The menu bar is on every screen of the window - the file manager's and each
session's - so each item says where it can act, and on what, with ``when``:
a preset name, a function returning a bool, or a tuple of them that must all
hold::

    MenuItem("Copy to Other Pane", on_select=..., when="entry")
    MenuItem("Background Jobs…", on_select=..., when=("always", has_jobs))
    MenuItem("Theme", submenu=..., when="always")

The presets:

``files``      the file manager is on screen
``always``     any screen
``entry``      the file manager, with an entry under the cursor
``selection``  the file manager, with entries selected

The screen an item serves is ``files`` unless ``always`` says otherwise - on
the item, or on the nearest parent that names one (``files`` names it back).
So an item that says nothing, or gives only a function, acts on the file
manager and is off on a session's screen: adding a file-manager item can never
leave it enabled where its panes are out of view. ``entry`` and ``selection``
are about the file manager, so they stay ``files`` whatever a parent says.

``MENU_ITEMS`` (:data:`xefm.user_api.MENU_WHEN`) shares the vocabulary -
``always``, ``entry``, ``selection`` - for the menus it reaches, which are the
file manager's.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from puikit import MenuItem as _MenuItem

#: The presets ``when`` takes, and what each means.
PRESETS = {
    "files": "the file manager is on screen",
    "always": "any screen",
    "entry": "the file manager, with an entry under the cursor",
    "selection": "the file manager, with entries selected",
}

#: The presets that say which screens, rather than what must be there.
_SCOPES = ("files", "always")


@dataclass
class MenuItem(_MenuItem):
    """PuiKit's menu item with a ``when`` (see the module docstring), which
    :func:`apply` turns into its ``enabled``. ``enabled`` still works and must
    hold too."""

    when: Any = None


def _conditions(when: Any) -> tuple:
    if when is None:
        return ()
    if isinstance(when, (str,)) or callable(when):
        return (when,)
    return tuple(when)


def _check(conditions: tuple) -> None:
    for condition in conditions:
        if isinstance(condition, str) and condition not in PRESETS:
            raise ValueError(f"unknown menu condition {condition!r} - known: "
                             f"{', '.join(PRESETS)}")
        if not isinstance(condition, str) and not callable(condition):
            raise TypeError(f"a menu condition is a preset name or a function, "
                            f"not {condition!r}")


def apply(menu: Any, presets: dict[str, Callable[[], bool]], scope: str = "files") -> None:
    """Turn the ``when`` of every item under ``menu`` (a Menu) into its
    ``enabled``, with ``presets`` saying what ``files``, ``entry`` and
    ``selection`` are now (``always`` is always true). ``scope`` is the
    screens the parent serves."""
    for item in getattr(menu, "items", ()):
        if not isinstance(item, _MenuItem):
            continue  # a separator
        conditions = _conditions(getattr(item, "when", None))
        _check(conditions)
        own_scope = next((c for c in conditions if c in _SCOPES), None)
        item_scope = own_scope or scope
        if any(c in ("entry", "selection") for c in conditions):
            item_scope = "files"
        tests = [presets[c] for c in conditions
                 if isinstance(c, str) and c not in _SCOPES]
        tests += [c for c in conditions if not isinstance(c, str)]
        if item_scope == "files":
            tests.insert(0, presets["files"])
        before = item.enabled
        if tests:
            item.enabled = (lambda tests=tuple(tests), before=before:
                            all(t() for t in tests)
                            and (before() if callable(before) else bool(before)))
        if item.submenu is not None:
            apply(item.submenu, presets, own_scope or scope)


def apply_bar(bar: Any, presets: dict[str, Callable[[], bool]]) -> None:
    """:func:`apply` over a menu bar. The bar's own entries - File, View,
    Tools - take no ``when``: each item under them starts from ``files``, so
    an item added to Tools without one is the file manager's too. An entry is
    enabled while any of its items is, so File greys whole on a session's
    screen and Tools does not."""
    for top in getattr(bar, "items", ()):
        if not isinstance(top, _MenuItem) or top.submenu is None:
            continue
        apply(top.submenu, presets, "files")
        items = [i for i in top.submenu.items if isinstance(i, _MenuItem)]
        top.enabled = lambda items=items: any(i.is_enabled() for i in items)

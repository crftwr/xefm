"""Which parts of XeFM's public API are Preview (#632).

Preview is a property of one API, not of the whole surface: a method, a class,
a ``config.py`` table or a manifest section is Preview — free to change in any
release — until it is declared stable, and the rest of the API need not wait
for it. ``API_VERSION`` promises only what is *not* Preview.

The mark lives on the definition, where whoever reads the code meets it:

- A function, method, property or class carries ``@preview``. That records it
  in :data:`PREVIEW_APIS` and opens its docstring with the word, so the source,
  ``help()`` and the registry all say the same thing. On a class it covers
  every member; a member of an unmarked class carries its own.
- A ``config.py`` table or a manifest section is not a Python object, so its
  name is listed here, below.

Stabilizing an API is deleting its mark. ``API_VERSION`` 1 was the first
release with a stable part (doc/dev/STABLE_API_PLAN.md §1 has the split).

Use is also told at run time (plan §4.1): the first time code outside XeFM
calls a Preview function or method, one line in the log names who — an
extension by its id, or ``config.py`` — and what. :func:`record_use` is that
line, and ``xefm.path_base`` calls it for a backend that subclasses a Preview
class or defines a Preview member.

Deprecated is the other mark, and the first step of removing a stable API
(doc/dev/STABLE_API_PLAN.md §9): ``@deprecated("use … instead")`` keeps the
API working, opens its docstring saying so, lists it in
:data:`DEPRECATED_APIS`, logs its first use from outside XeFM, and makes
``xefm ext check`` warn. It is removed no earlier than the next minor release,
and the removal bumps ``API_VERSION``.

This module is XeFM's own. Extensions read the result as
``xefm.user_api.PREVIEW_APIS`` and ``xefm.user_api.DEPRECATED_APIS``.
"""

from __future__ import annotations

import functools
import inspect
import sys
from typing import TypeVar

from xefm.log_manager import getLogger

T = TypeVar("T")

logger = getLogger("PreviewAPI")

#: ``(who, api)`` pairs already logged, so each is said once per session.
_recorded: set[tuple[str, str]] = set()

#: Every deprecated API by name, as :data:`PREVIEW_APIS` spells names, mapped
#: to what to use instead. An entry for a class covers its members. Empty
#: while nothing stable is on its way out.
DEPRECATED_APIS: dict[str, str] = {}

#: The module name ``config.py`` is executed under (:mod:`xefm.config`).
_CONFIG_MODULE = "user_config"

#: The note a Preview API's docstring opens with.
NOTE = "Preview — may change in any release."

#: Every Preview API by name: ``xefm.user_api.ActionContext.run_task`` for
#: code, ``config.MENU_ITEMS`` for a ``config.py`` table,
#: ``manifest.contributes.menus`` for a manifest section. An entry for a class
#: covers its members.
PREVIEW_APIS: set[str] = {
    # config.py tables. ACTIONS, SORT_KEYS, FILTERS and PATH_SCHEMES are
    # stable; replacing a built-in scheme is not.
    *(f"config.{table}" for table in (
        "EVENT_HOOKS", "IMAGE_DECODERS", "LEXERS", "MENU_ITEMS",
        "ATTRIBUTES", "LAYOUTS", "LAYOUT_EXTRAS", "DEFAULT_LAYOUT")),
    "config.PATH_SCHEMES.override",
    # xefm-extension.toml. actions, sort_keys, filters, path_schemes and
    # key_suggestions are stable.
    *(f"manifest.contributes.{kind}" for kind in (
        "event_hooks", "image_decoders", "lexers", "themes", "menus",
        "attributes", "layouts", "layout_extras")),
    "manifest.extension.updates",
    "manifest.extension.agent_guide",
    "manifest.contributes.agent_prompts",
    # AI agent sessions (#880).
    "config.AGENTS", "config.AGENT_RULES", "config.AGENT_PROMPTS",
    "manifest.settings",
    "manifest.requires",
}


def preview(obj: T) -> T:
    """Mark a function, method, property getter or class as Preview. Put it
    under ``@property`` for a property, so the getter is what it marks.

    A function or method comes back wrapped, so that the first call from
    outside XeFM is recorded (:func:`record_use`). A class is not: the ones
    XeFM hands over (``TaskJob``, ``HookEvent``) are reached only through a
    Preview entry point that is already recorded, and subclassing one says so
    in its own ``__init_subclass__``."""
    name = f"{obj.__module__}.{obj.__qualname__}"
    PREVIEW_APIS.add(name)
    doc = obj.__doc__ or ""
    obj.__doc__ = f"{NOTE}\n\n{doc}" if doc else NOTE
    if inspect.isclass(obj) or not callable(obj):
        return obj
    api = obj.__qualname__

    @functools.wraps(obj)
    def recorded(*args, **kwargs):
        record_use(api, sys._getframe(1).f_globals.get("__name__", ""))
        return obj(*args, **kwargs)

    return recorded  # type: ignore[return-value]


def deprecated(instead: str):
    """Mark a stable function, method, property getter or class as on its way
    out, saying what replaces it: ``@deprecated("use ctx.pane.select")``. It
    keeps working; a function or method comes back wrapped so its first call
    from outside XeFM is logged as a warning (:func:`record_use`)."""
    def mark(obj: T) -> T:
        DEPRECATED_APIS[f"{obj.__module__}.{obj.__qualname__}"] = instead
        note = f"Deprecated — {instead}. Removed in a later API_VERSION."
        doc = obj.__doc__ or ""
        obj.__doc__ = f"{note}\n\n{doc}" if doc else note
        if inspect.isclass(obj) or not callable(obj):
            return obj
        api = obj.__qualname__

        @functools.wraps(obj)
        def recorded(*args, **kwargs):
            record_use(api, sys._getframe(1).f_globals.get("__name__", ""),
                       deprecated=instead)
            return obj(*args, **kwargs)

        return recorded  # type: ignore[return-value]
    return mark


def record_use(api: str, module: str, *, deprecated: str | None = None) -> None:
    """Log, once per session, that ``module`` used the Preview API ``api``
    (``ActionContext.run_task``) — or, with ``deprecated`` (what to use
    instead), a deprecated one, as a warning. XeFM's own modules are not
    reported: XeFM calls some of these APIs itself."""
    if module == "xefm" or module.startswith("xefm."):
        return
    if module == _CONFIG_MODULE:
        who = "config.py"
    else:
        from xefm.extensions import handle_for_module
        handle = handle_for_module(module)
        who = f"Extension {handle.id}" if handle is not None else module
    if (who, api) in _recorded:
        return
    _recorded.add((who, api))
    if deprecated is not None:
        logger.warning(f"{who} uses deprecated API {api} — {deprecated}; it "
                       f"will be removed in a later release")
    else:
        logger.info(f"{who} uses Preview API {api} — it may change in any release")


def is_preview(name: str) -> bool:
    """Whether the API called ``name`` (as :data:`PREVIEW_APIS` spells names)
    is Preview, itself or through the class that holds it."""
    parts = name.split(".")
    return any(".".join(parts[:i]) in PREVIEW_APIS for i in range(1, len(parts) + 1))


def is_deprecated(name: str) -> str | None:
    """What replaces the API called ``name``, if it is deprecated — itself or
    through the class that holds it — else ``None``."""
    parts = name.split(".")
    for i in range(len(parts), 0, -1):
        instead = DEPRECATED_APIS.get(".".join(parts[:i]))
        if instead is not None:
            return instead
    return None

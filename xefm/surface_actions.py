"""App-wide actions a surface runs on the app's behalf (#900).

A viewer or XeFM's terminal handles its own actions. A few of the app's
actions do not depend on the file list at all - the text size, the theme, the
keymap, the config - so any surface may offer them too: by key, in the
surface's own context (they are ``common`` actions, which every context
inherits), and in the command palette opened over it. The palette lists what
the surface can run and nothing else, so an action that would act on the file
list hidden behind it is never offered there.

A surface takes these from :func:`handlers` into the table it dispatches its
actions from; the app installs the runner once (:func:`set_runner`).
"""

from __future__ import annotations

from collections.abc import Callable

#: The app's actions a surface may run without the file list being in view.
APP_WIDE = frozenset({
    "increase_font_size", "decrease_font_size", "reset_font_size",
    "toggle_color_scheme", "choose_keymap", "reload_config", "edit_config",
    # The screen switcher (#953): from a viewer, another screen is a switch
    # away; the viewer stays where it is.
    "screens",
})

_run: Callable[[str], None] | None = None
_available: Callable[[str], bool] = lambda name: True


def set_runner(run: Callable[[str], None] | None,
               available: Callable[[str], bool] | None = None) -> None:
    """Install the app's runner for :data:`APP_WIDE` actions, and the test of
    which ones this frontend can run (the desktop-only text size)."""
    global _run, _available
    _run = run
    _available = available or (lambda name: True)


def handlers() -> dict[str, Callable[[], None]]:
    """``{name: handler}`` for every app-wide action runnable here, for a
    surface to merge into its own action table. Empty without a runner (a
    viewer built outside the app, as tests do)."""
    if _run is None:
        return {}
    run = _run
    return {name: (lambda n=name: run(n)) for name in sorted(APP_WIDE) if _available(name)}

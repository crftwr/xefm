"""Screens: what fills the window, and what the screen switcher switches between
(discussions #900, #951).

A screen is the file manager or a terminal session. Each is a group in
PuiKit's layer tree (:class:`puikit.LayerGroup`): what is opened on a screen -
a viewer, a dialog, the palette - is pushed under its group, so it hides and
comes back with it. Only the screen on now is shown; the others stay stacked,
hidden, with their state, and a layer can still close itself while its screen
is out of view. The screen on now is PuiKit's default layer parent, so code
that knows nothing of screens opens its dialogs on it.

The file manager's own content, the panes, is the Panel's base, not a layer:
its group holds only what is opened over the panes. A terminal session's
group holds its terminal view and what is opened over that.

A screen is not a terminal session: the session is a process and lives as
long as it; the screen is what is shown and lives as long as that. A failed
session keeps its screen (its last output, the exit bar) after its process is
gone. The two point at each other (:attr:`Screen.session`,
``Session.screen``).

This module keeps the bookkeeping - the groups, which one is shown, the
order screens were on - and does no animation; the app plays the transitions
around :meth:`ScreenManager.make_current`.
"""

from __future__ import annotations

import time
from typing import Any

#: Screen kinds.
FILES = "files"
TERMINAL = "terminal"

#: z of the screens' groups at the top level of the layer tree. Terminal
#: screens sit above the file manager's, so a terminal coming up over the
#: panes (and going back behind them) crosses them in the right order.
_FILES_Z = 0
_TERMINAL_Z = 10

#: z of a terminal view inside its own screen's group: under anything opened
#: on that screen (dialogs come at 70 and up).
VIEW_Z = 1


class Screen:
    """One screen: the file manager (``kind == FILES``) or a terminal
    session's (``kind == TERMINAL``, :attr:`session` set)."""

    def __init__(self, sid: str, kind: str, group: Any, session: Any = None) -> None:
        self.id = sid
        self.kind = kind
        self.group = group
        self.session = session
        self.created_at = time.time()
        self.last_shown_at = self.created_at

    @property
    def name(self) -> str:
        return "File manager" if self.kind == FILES else self.session.name

    def __repr__(self) -> str:
        return f"Screen({self.id!r})"


class ScreenManager:
    """The screens of one Panel: the file manager's, made at once, and one per
    terminal session, most recently shown first."""

    def __init__(self, panel: Any) -> None:
        self.panel = panel
        group = panel.push_layer_group(z=_FILES_Z, name=FILES)
        self.files = Screen(FILES, FILES, group)
        self.current = self.files
        #: Every screen, most recently on screen first; FILES always in it.
        self._recent: list[Screen] = [self.files]
        panel.set_default_layer_parent(group)

    # --- reading ---------------------------------------------------------------

    def recent(self) -> list[Screen]:
        """Every screen, the one on now first, then most recently shown."""
        return list(self._recent)

    def started(self) -> list[Screen]:
        """Every screen in the order it was made (the file manager first)."""
        return sorted(self._recent, key=lambda s: (s.kind != FILES, s.created_at))

    def by_id(self, sid: str) -> Screen | None:
        return next((s for s in self._recent if s.id == sid), None)

    def for_session(self, session: Any) -> Screen | None:
        return next((s for s in self._recent if s.session is session), None)

    def previous(self, screen: Screen | None = None) -> Screen:
        """The screen shown before ``screen`` (the current one by default):
        where closing it goes back to."""
        screen = screen or self.current
        return next((s for s in self._recent if s is not screen), self.files)

    def top_layer(self, screen: Screen | None = None) -> Any:
        """The topmost layer shown on ``screen`` (the current one), or None
        - a viewer or dialog over the panes, the terminal or what is over
        it."""
        screen = screen or self.current
        layers = self.panel.shown_layers(under=screen.group) \
            if self.panel.is_layer_shown(screen.group) else []
        return layers[-1] if layers else None

    def layers(self, screen: Screen) -> list:
        """What is stacked on ``screen``, hidden or not, bottom first: its
        group's direct children."""
        return self.panel.layer_children(screen.group)

    # --- changing ---------------------------------------------------------------

    def add_terminal(self, session: Any, view: Any, *, hints: dict, reflow: Any) -> Screen:
        """A new, hidden screen for ``session``, with ``view`` on it."""
        group = self.panel.push_layer_group(z=_TERMINAL_Z, parent=_top_level(),
                                            name=f"terminal {session.id}")
        self.panel.set_layer_hidden(group, True)
        self.panel.push_layer(view, z=VIEW_Z, hints=hints, reflow=reflow, parent=group)
        screen = Screen(str(session.id), TERMINAL, group, session)
        session.screen = screen
        self._recent.append(screen)  # last until it is first shown
        return screen

    def reveal(self, screen: Screen) -> None:
        """Show ``screen``'s group, without making it current: the moment a
        transition starts, when both screens draw."""
        self.panel.set_layer_hidden(screen.group, False)

    def conceal(self, screen: Screen) -> None:
        """Hide ``screen``'s group: the end of a transition away from it."""
        if self.panel.has_layer(screen.group):
            self.panel.set_layer_hidden(screen.group, True)

    def make_current(self, screen: Screen, *, conceal_others: bool = True) -> Screen:
        """Make ``screen`` the one on now: shown, first in the recent order,
        and where layers opened without a parent go. ``conceal_others``
        hides the rest at once; a transition passes False and hides the one
        it leaves when it ends. Returns the screen that was current."""
        before = self.current
        self.reveal(screen)
        if conceal_others:
            for other in self._recent:
                if other is not screen:
                    self.conceal(other)
        self.current = screen
        screen.last_shown_at = time.time()
        if screen in self._recent:
            self._recent.remove(screen)
        self._recent.insert(0, screen)
        self.panel.set_default_layer_parent(screen.group)
        for s in self._recent:
            if s.session is not None:
                s.session.view.shown = s is screen
        return before

    def remove(self, screen: Screen) -> None:
        """Take a terminal screen away, with everything on it. When it was the
        current one, the previous screen becomes current (shown at once)."""
        if screen.kind == FILES:
            raise ValueError("the file manager's screen cannot be removed")
        was_current = screen is self.current
        if screen in self._recent:
            self._recent.remove(screen)
        if was_current:
            self.make_current(self._recent[0] if self._recent else self.files)
        self.panel.remove_layer(screen.group)
        if screen.session is not None:
            screen.session.screen = None


def _top_level() -> Any:
    from puikit.panel import TOP_LEVEL
    return TOP_LEVEL

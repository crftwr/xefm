"""Reusable TAB-completion engine for XeFM's text prompts.

This module is intentionally **UI-agnostic** — it holds no PuiKit drawing code and
carries no dialog dependency, so the same logic drives completion anywhere a
single-line field is edited (see :class:`xefm.input_dialog.InputDialog`, and any
future consumer). It carries the completion logic
(``SingleLineTextEdit`` + ``FilepathCompleter``, commit ``b8e4719``) onto the
current widgets, keeping the proven behaviour and the Kiro spec
(``.kiro/specs/tab-completion/``).

Three pieces:

- :func:`calculate_common_prefix` — the longest common prefix inserted on TAB.
- :class:`FilepathCompleter` — a :class:`Completer` that lists filesystem entries
  matching the token under the caret. Local-filesystem only; a virtual (S3/SSH)
  path simply yields no candidates rather than blocking or erroring.
- :class:`CompletionController` — binds a PuiKit ``TextEdit`` to a ``Completer``
  and owns all TAB/candidate state (LCP insertion, the live candidate list, the
  highlighted row, apply/dismiss). This is the reusable seam: a widget attaches
  one and forwards keys to it; the controller mutates the field's ``text`` /
  ``cursor`` directly and exposes the candidate list for a UI layer to render.

A completer itself stays synchronous, but the controller can run it **threaded**
(issue #246): each fetch happens on a worker thread and its result is applied on
the UI thread through :meth:`CompletionController.pump`, so a listing that stalls
on a slow mount never freezes the field (issue #202's original constraint, now
met by threading rather than by hoping the filesystem is fast).
"""

from __future__ import annotations

import os
import queue
import threading
from typing import Any, List, Protocol, runtime_checkable

from xefm.dir_scan import scan_dir
from xefm.log_manager import getLogger


def calculate_common_prefix(candidates: List[str]) -> str:
    """The longest string shared by every candidate, from the start.

    This is the maximum unambiguous text TAB can insert. Comparison is
    **case-sensitive**, matching filesystem behaviour on most platforms.

    Empty list -> ``""``; a single candidate -> that whole candidate.

        >>> calculate_common_prefix([])
        ''
        >>> calculate_common_prefix(['hello'])
        'hello'
        >>> calculate_common_prefix(['hello', 'help', 'hero'])
        'he'
        >>> calculate_common_prefix(['abc', 'def'])
        ''
    """
    if not candidates:
        return ""
    if len(candidates) == 1:
        return candidates[0]

    prefix = candidates[0]
    for candidate in candidates[1:]:
        common_len = 0
        for a, b in zip(prefix, candidate):
            if a == b:
                common_len += 1
            else:
                break
        prefix = prefix[:common_len]
        if not prefix:
            return ""
    return prefix


@runtime_checkable
class Completer(Protocol):
    """Strategy that turns the text-before-caret into completion candidates.

    A completer is pure and synchronous: given the field text and caret index it
    returns the list of candidate tokens and reports where in the text the token
    being completed starts. It performs no UI and holds no field state.
    """

    def get_candidates(self, text: str, cursor_pos: int) -> List[str]:
        """Candidate tokens for the text up to ``cursor_pos`` (may be empty)."""
        ...

    def get_completion_start_pos(self, text: str, cursor_pos: int) -> int:
        """Index in ``text`` where the token under the caret begins."""
        ...


class FilepathCompleter:
    """A :class:`Completer` for filesystem paths.

    Splits the text before the caret at the last separator into a directory and a
    filename prefix, reads that directory **in one pass** via
    :func:`xefm.dir_scan.scan_dir` — the same bulk enumeration the pane listing
    uses, so a large directory costs one enumeration rather than a ``stat``
    round trip per entry (issue #246) — and returns entries whose name starts
    with the prefix (case-sensitive). Directory candidates carry a trailing
    ``os.sep`` so a following TAB descends into them; with ``directories_only``
    the files are dropped. A leading ``~`` / ``~user`` is expanded for the
    *listing*, but the returned tokens are the plain entry names, so the field
    keeps whatever the user typed to their left.

    ``show_hidden`` mirrors the panes' hidden-files toggle (issue #258): when
    False, dot-entries are left out of the candidates — *unless* the typed token
    itself starts with a ``.``, which is an explicit request for them (the shell
    convention; without it there would be no way to complete into ``.config``
    while hidden files are off). Entries the platform marks hidden by attribute
    rather than by name (Windows, issue #284) are left out too, and a typed dot
    does not bring them back: there is nothing to type that asks for them.

    Errors reaching the filesystem (missing directory, permission denied, or a
    non-local path that ``os`` can't stat) yield ``[]`` — completing a path that
    does not exist yet is a no-op, never a crash.
    """

    def __init__(self, base_directory: str | None = None, directories_only: bool = False,
                 show_hidden: bool = True):
        self.base_directory = base_directory or os.getcwd()
        self.directories_only = directories_only
        self.show_hidden = show_hidden
        self.logger = getLogger("Completion")

    def get_candidates(self, text: str, cursor_pos: int) -> List[str]:
        text_to_cursor = text[:cursor_pos]

        # Expand a leading ~ / ~user for the directory lookup only. os.path
        # .expanduser is a no-op when there's nothing to expand, so it is safe to
        # apply unconditionally.
        expanded = os.path.expanduser(text_to_cursor)

        last_sep_pos = expanded.rfind(os.sep)
        if last_sep_pos == -1:
            # No separator: complete within the base directory.
            directory = self.base_directory
            prefix = expanded
        else:
            directory = expanded[: last_sep_pos + 1]
            prefix = expanded[last_sep_pos + 1:]
            if not os.path.isabs(directory):
                directory = os.path.join(self.base_directory, directory)

        directory = os.path.normpath(directory)

        # Honour the hidden-files toggle, except when the token itself starts
        # with a dot — typing the dot is an explicit ask for hidden entries.
        hide_dotfiles = not self.show_hidden and not prefix.startswith(".")

        candidates: List[str] = []
        try:
            # One bulk enumeration answers name + is_dir for the whole
            # directory; a broken symlink (attrs["ok"] False) reads as "not a
            # directory", matching what os.path.isdir said here before.
            for entry, attrs in scan_dir(directory):
                if not entry.startswith(prefix):  # case-sensitive
                    continue
                if hide_dotfiles and entry.startswith("."):
                    continue
                # The platform's own hidden mark (a Windows file attribute) has
                # no spelling in the typed token, so nothing overrides it.
                if not self.show_hidden and attrs["hidden"]:
                    continue
                is_directory = attrs["is_dir"]
                if self.directories_only and not is_directory:
                    continue
                candidates.append(entry + os.sep if is_directory else entry)
        except (PermissionError, FileNotFoundError, NotADirectoryError, OSError) as exc:
            # Expected while typing a path that doesn't exist yet, or on a virtual
            # (non-local) path os can't list; report nothing rather than failing.
            self.logger.debug(f"No completions for '{directory}': {exc}")
            return []

        return sorted(candidates)

    def get_completion_start_pos(self, text: str, cursor_pos: int) -> int:
        # Position after the last separator in the ORIGINAL (un-expanded) text —
        # this indexes the field's real buffer, which is what the controller slices
        # when it inserts a completion.
        last_sep_pos = text[:cursor_pos].rfind(os.sep)
        return last_sep_pos + 1 if last_sep_pos != -1 else 0


class CompletionController:
    """TAB-completion behaviour bound to a single ``TextEdit`` + ``Completer``.

    The controller reads and writes only ``edit.text`` and ``edit.cursor`` (plus
    clearing ``edit._anchor`` after a programmatic edit so no stale selection
    lingers), so it stays independent of any particular dialog. A host widget
    forwards key events to :meth:`on_tab`, :meth:`move_focus`, :meth:`accept`,
    :meth:`dismiss`, and calls :meth:`on_text_changed` after ordinary edits; it
    reads :attr:`active`, :attr:`candidates`, and :attr:`focused_index` to render
    the candidate list.

    With ``threaded=True`` each candidate fetch runs the completer on a daemon
    worker thread instead of inline, so a listing that stalls (a slow or dead
    network mount) never blocks the UI. The host then also calls :meth:`pump`
    on the UI thread to apply arrived results — optionally after :meth:`wait`,
    which gives a fetch a brief synchronous window so the fast local case still
    completes within the triggering key event. Fetches are single-flight by
    generation: a result whose fetch was superseded (a newer fetch, a
    :meth:`dismiss`), or whose text/caret snapshot no longer matches the field,
    is dropped, so a slow listing can never clobber what the user typed since.
    """

    def __init__(self, edit: Any, completer: Completer, *, threaded: bool = False):
        self.edit = edit
        self.completer = completer
        self.threaded = threaded
        self.active = False
        self.candidates: List[str] = []
        self.focused_index = -1  # -1 == no row highlighted
        self.completion_start_pos = 0
        self.logger = getLogger("Completion")
        # Threaded-fetch state. ``_fetch_gen`` is the newest fetch requested,
        # ``_settled_gen`` the newest one whose result arrived (or was
        # invalidated); results cross threads through ``_results``. All fields
        # except the queue are touched on the UI thread only.
        self._fetch_gen = 0
        self._settled_gen = 0
        self._results: "queue.Queue[tuple[int, str, str, int, List[str]]]" = queue.Queue()
        self._fetch_done = threading.Event()

    # --- key entry points ----------------------------------------------------

    def on_tab(self) -> bool:
        """Handle a TAB press. Insert the longest common prefix of the matches,
        and open the candidate list when more than one match remains. Returns
        True if there were any candidates (TAB was consumed), False otherwise.
        Threaded mode starts the fetch and returns True; the outcome is applied
        by a later :meth:`pump`."""
        text, cursor = self.edit.text, self.edit.cursor
        if self.threaded:
            self._spawn_fetch("tab", text, cursor)
            return True
        return self._apply_tab(text, cursor, self.completer.get_candidates(text, cursor))

    def on_text_changed(self) -> None:
        """Refresh the candidate list after an ordinary edit. Typing narrows it
        and deleting widens it; it hides when nothing matches, and stays open for
        a lone remaining match. Typing clears the highlight (arrows navigate)."""
        if not self.active:
            return
        text, cursor = self.edit.text, self.edit.cursor
        if self.threaded:
            self._spawn_fetch("refresh", text, cursor)
            return
        self._apply_refresh(text, cursor, self.completer.get_candidates(text, cursor))

    # --- threaded fetch ------------------------------------------------------

    def _spawn_fetch(self, kind: str, text: str, cursor: int) -> None:
        """Run ``completer.get_candidates`` on a worker thread. The worker only
        touches its snapshot arguments and the thread-safe queue/event; the
        result is applied by :meth:`pump` on the UI thread."""
        self._fetch_gen += 1
        gen = self._fetch_gen
        done = self._fetch_done = threading.Event()

        def worker() -> None:
            try:
                candidates = self.completer.get_candidates(text, cursor)
            except Exception as exc:
                self.logger.error(f"Candidate listing failed for '{text[:cursor]}': {exc}")
                candidates = []
            self._results.put((gen, kind, text, cursor, candidates))
            done.set()

        threading.Thread(target=worker, name="xefm-completion", daemon=True).start()

    def fetch_pending(self) -> bool:
        """True while a threaded fetch is in flight — i.e. :meth:`pump` still has
        a result to wait for. The host polls this to keep pumping."""
        return self._settled_gen < self._fetch_gen

    def wait(self, timeout: float) -> None:
        """Block up to ``timeout`` seconds for the newest fetch to finish, so a
        fast (local) listing can be pumped within the same key event that asked
        for it. No-op when nothing is pending."""
        if self.fetch_pending():
            self._fetch_done.wait(timeout)

    def pump(self) -> bool:
        """UI thread: apply any arrived fetch results. A result is dropped when a
        newer fetch (or a dismiss) superseded it, or when the field's text/caret
        moved on while it ran. Returns True when the candidate state changed, so
        the host re-syncs its overlay."""
        applied = False
        while True:
            try:
                gen, kind, text, cursor, candidates = self._results.get_nowait()
            except queue.Empty:
                break
            self._settled_gen = max(self._settled_gen, gen)
            if gen != self._fetch_gen:
                continue  # superseded
            if text != self.edit.text or cursor != self.edit.cursor:
                continue  # the user typed / moved the caret meanwhile
            if kind == "tab":
                self._apply_tab(text, cursor, candidates)
            else:
                self._apply_refresh(text, cursor, candidates)
            applied = True
        return applied

    # --- applying a fetch ----------------------------------------------------

    def _apply_tab(self, text: str, cursor: int, candidates: List[str]) -> bool:
        """The TAB outcome, given the fetched candidates: insert the longest
        common prefix and open the list when several matches remain."""
        if not candidates:
            self.dismiss()
            return False

        start = self.completer.get_completion_start_pos(text, cursor)
        already_typed = text[start:cursor]
        common = calculate_common_prefix(candidates)

        # Extend the token to the common prefix, but only when that actually adds
        # characters (nothing to do when the caret is already at the common
        # prefix — the classic "second TAB just lists" behaviour).
        if common.startswith(already_typed) and len(common) > len(already_typed):
            self._replace_token(start, cursor, common)

        self.candidates = candidates
        self.completion_start_pos = start
        self.focused_index = -1
        self.active = len(candidates) > 1
        return True

    def _apply_refresh(self, text: str, cursor: int, candidates: List[str]) -> None:
        """The after-an-edit outcome: swap in the narrowed/widened candidates,
        hiding the list when nothing matches."""
        if not candidates:
            self.dismiss()
            return
        self.candidates = candidates
        self.completion_start_pos = self.completer.get_completion_start_pos(text, cursor)
        self.focused_index = -1

    def move_focus(self, delta: int) -> None:
        """Move the highlight by ``delta`` rows, wrapping. From no highlight, a
        forward step lands on the first row and a backward step on the last."""
        if not self.active or not self.candidates:
            return
        n = len(self.candidates)
        if self.focused_index == -1:
            self.focused_index = 0 if delta > 0 else n - 1
        else:
            self.focused_index = (self.focused_index + delta) % n

    def accept(self) -> bool:
        """Apply the highlighted candidate, if any, and close the list. Returns
        True when a candidate was applied (so the host treats Enter as consumed);
        False when no row is highlighted (Enter is an ordinary submit)."""
        if self.active and 0 <= self.focused_index < len(self.candidates):
            text, cursor = self.edit.text, self.edit.cursor
            self._replace_token(self.completion_start_pos, cursor,
                                self.candidates[self.focused_index])
            self.dismiss()
            return True
        return False

    def apply_index(self, index: int) -> None:
        """Apply the candidate at ``index`` and close the list — used when a row
        is chosen by mouse."""
        if 0 <= index < len(self.candidates):
            self._replace_token(self.completion_start_pos, self.edit.cursor,
                                self.candidates[index])
        self.dismiss()

    def dismiss(self) -> None:
        """Close the candidate list and clear its state (Esc, focus loss). Also
        invalidates any in-flight threaded fetch, so its late result is dropped
        rather than re-opening a list the user just closed."""
        self.active = False
        self.candidates = []
        self.focused_index = -1
        self._fetch_gen += 1
        self._settled_gen = self._fetch_gen

    # --- helpers -------------------------------------------------------------

    def _replace_token(self, start: int, end: int, value: str) -> None:
        """Replace ``text[start:end]`` with ``value`` and put the caret at its
        end, dropping any selection so a programmatic edit leaves no stray
        highlight."""
        text = self.edit.text
        self.edit.text = text[:start] + value + text[end:]
        self.edit.cursor = start + len(value)
        self.edit._anchor = None

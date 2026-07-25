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
  matching the token under the caret. Local-filesystem and fully synchronous (per
  issue #202's "local-first, no blocking on slow mounts" constraint); a virtual
  (S3/SSH) path simply yields no candidates rather than blocking or erroring.
- :class:`CompletionController` — binds a PuiKit ``TextEdit`` to a ``Completer``
  and owns all TAB/candidate state (LCP insertion, the live candidate list, the
  highlighted row, apply/dismiss). This is the reusable seam: a widget attaches
  one and forwards keys to it; the controller mutates the field's ``text`` /
  ``cursor`` directly and exposes the candidate list for a UI layer to render.
"""

from __future__ import annotations

import os
from typing import Any, List, Protocol, runtime_checkable

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
    filename prefix, lists that directory, and returns entries whose name starts
    with the prefix (case-sensitive). Directory candidates carry a trailing
    ``os.sep`` so a following TAB descends into them; with ``directories_only``
    the files are dropped (jump-to-path navigation). A leading ``~`` / ``~user``
    is expanded for the *listing*, but the returned tokens are the plain entry
    names, so the field keeps whatever the user typed to their left.

    Errors reaching the filesystem (missing directory, permission denied, or a
    non-local path that ``os`` can't stat) yield ``[]`` — completing a path that
    does not exist yet is a no-op, never a crash.
    """

    def __init__(self, base_directory: str | None = None, directories_only: bool = False):
        self.base_directory = base_directory or os.getcwd()
        self.directories_only = directories_only
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

        candidates: List[str] = []
        try:
            for entry in os.listdir(directory):
                if not entry.startswith(prefix):  # case-sensitive
                    continue
                is_directory = os.path.isdir(os.path.join(directory, entry))
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
    """

    def __init__(self, edit: Any, completer: Completer):
        self.edit = edit
        self.completer = completer
        self.active = False
        self.candidates: List[str] = []
        self.focused_index = -1  # -1 == no row highlighted
        self.completion_start_pos = 0

    # --- key entry points ----------------------------------------------------

    def on_tab(self) -> bool:
        """Handle a TAB press. Insert the longest common prefix of the matches,
        and open the candidate list when more than one match remains. Returns
        True if there were any candidates (TAB was consumed), False otherwise."""
        text, cursor = self.edit.text, self.edit.cursor
        candidates = self.completer.get_candidates(text, cursor)
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

    def on_text_changed(self) -> None:
        """Refresh the candidate list after an ordinary edit. Typing narrows it
        and deleting widens it; it hides when nothing matches, and stays open for
        a lone remaining match. Typing clears the highlight (arrows navigate)."""
        if not self.active:
            return
        text, cursor = self.edit.text, self.edit.cursor
        candidates = self.completer.get_candidates(text, cursor)
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
        """Close the candidate list and clear its state (Esc, focus loss)."""
        self.active = False
        self.candidates = []
        self.focused_index = -1

    # --- helpers -------------------------------------------------------------

    def _replace_token(self, start: int, end: int, value: str) -> None:
        """Replace ``text[start:end]`` with ``value`` and put the caret at its
        end, dropping any selection so a programmatic edit leaves no stray
        highlight."""
        text = self.edit.text
        self.edit.text = text[:start] + value + text[end:]
        self.edit.cursor = start + len(value)
        self.edit._anchor = None

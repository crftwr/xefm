"""Rename in the editor — batch rename by editing a list of names (#581).

The vidir idiom: the names go to a text file one per line, the user edits that
file in ``TEXT_EDITOR`` with whatever the editor offers (multi-cursor, search and
replace, a full-width space typed as itself), and each line that changed is a
rename of the file that line stood for.

This module is the part with no UI: :func:`names_text` writes the list,
:func:`parse_plan` reads an edited one back into a :class:`RenamePlan` — or into
the reasons it cannot be one — and :func:`apply_plan` carries a plan out. The app
owns the editor round trip and the confirmation (:meth:`XeFMApp.rename_in_editor`).

Lines are matched to files by position, so the line count is the contract: a
file with lines added or removed is refused rather than guessed at. Everything
is compared in NFC (:mod:`xefm.name_key`), as the regex batch rename does: the
list shows names as the pane shows them, and an untouched line compares equal
to its file whatever spelling the disk holds.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from xefm import name_key
from xefm.rename_check import (Listings, fold, is_valid_name, must_park,
                               obstacle)


class UnlistableName(ValueError):
    """A name that cannot be written as one line: it holds a line break."""


def names_text(files: Sequence[Any]) -> str:
    """The list the editor opens: each file's (NFC) name on its own line.

    Raises :class:`UnlistableName` for a name holding a line break — legal on
    POSIX, and impossible to round-trip through a line-per-name file."""
    lines = []
    for entry in files:
        name = name_key.nfc(entry.name)
        if "\n" in name or "\r" in name:
            raise UnlistableName(f"{name!r} contains a line break")
        lines.append(name)
    return "".join(line + "\n" for line in lines)


def _edited_lines(text: str) -> list[str]:
    """The edited file as one name per line. A CRLF the editor wrote is a line
    ending, not part of a name; one missing final newline is not a missing line.
    Nothing else is stripped: a trailing space may be the point of the edit."""
    text = text.replace("\r\n", "\n")
    if text.endswith("\n"):
        text = text[:-1]
    return text.split("\n") if text else []


@dataclass
class RenamePlan:
    """What an edited list asks for: ``renames`` as ``(entry, new_name)`` pairs
    in list order, or the ``errors`` that make it unusable (one per offending
    line, already phrased for the user). A plan with errors is never applied."""
    renames: list[tuple[Any, str]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def parse_plan(files: Sequence[Any], text: str) -> RenamePlan:
    """Read the edited ``text`` back against the ``files`` it was written from.

    Refused, with the line named: a changed line count, an empty or invalid
    name, two lines landing on one name in the same directory, and a name that
    already belongs to a file outside the batch. A name held by another file *in*
    the batch is fine as long as that file is renamed away too — that is a swap
    or a chain, which :func:`apply_plan` routes through temporary names."""
    plan = RenamePlan()
    lines = _edited_lines(text)
    if len(lines) != len(files):
        plan.errors.append(
            f"The list has {len(lines)} line(s) for {len(files)} file(s) — "
            "change names in place; lines cannot be added, removed or joined")
        return plan

    originals = [name_key.nfc(f.name) for f in files]
    news = [name_key.nfc(line) for line in lines]
    listings = Listings()
    # The files renamed away from their names: an entry under one of those is
    # a batch member on its way out, not an obstacle (xefm.rename_check).
    leaving = [f for i, f in enumerate(files) if news[i] != originals[i]]

    # Every name each directory will hold once the batch is done, from the
    # files that keep theirs and the files that move — the collision set.
    # Names that differ only in case claim one slot, as they are one file
    # where the disk ignores case, unless the directory is seen to keep such
    # names apart (#873); only a pair like that costs a listing.
    def slot(i: int) -> tuple[str, str]:
        return (str(files[i].parent), fold(news[i]))

    by_slot: dict[tuple[str, str], list[int]] = {}
    for i in range(len(files)):
        by_slot.setdefault(slot(i), []).append(i)
    claimed: dict[int, list[int]] = {}
    for members in by_slot.values():
        if (len({news[j] for j in members}) > 1
                and listings.case_matters(files[members[0]].parent)):
            for j in members:
                claimed[j] = [k for k in members if news[k] == news[j]]
        else:
            for j in members:
                claimed[j] = members

    for i, entry in enumerate(files):
        old, new = originals[i], news[i]
        if new == old:
            continue
        where = f"line {i + 1} ({old})"
        if not is_valid_name(new):
            plan.errors.append(f"{where}: {new!r} is not a valid name")
            continue
        if len(claimed[i]) > 1:
            others = ", ".join(str(j + 1) for j in claimed[i] if j != i)
            plan.errors.append(f"{where}: {new} is also on line {others}")
            continue
        if obstacle(entry, new, leaving, listings):
            plan.errors.append(f"{where}: {new} already exists")
            continue
        plan.renames.append((entry, new))
    if plan.errors:
        plan.renames.clear()
    return plan


def _temp_name(i: int) -> str:
    return f".xefm-rename-{i}-{uuid.uuid4().hex[:8]}"


def apply_plan(plan: RenamePlan,
               rename: Callable[[Any, Any], None] | None = None,
               ) -> tuple[dict[str, str], list[str]]:
    """Carry out ``plan``; returns ``(renamed, errors)`` — old path → new name
    for every rename that landed, and one message per one that did not.

    A file whose new name is another batch file's *current* name (a swap, a
    cycle, a shift down a numbered list) cannot go there directly, so those go
    in three steps: to a temporary name first, then every direct rename, then
    from the temporary names to their targets — by which point each target has
    been vacated. A step that fails leaves the file where that step found it,
    and when that is a temporary name the message says which, so nothing is
    lost under a name the user has never seen.

    ``rename(src, dst)`` defaults to ``src.rename(dst)``; the app passes one
    that releases archive handles first."""
    if rename is None:
        def rename(src, dst):
            src.rename(dst)

    renamed: dict[str, str] = {}
    errors: list[str] = []
    # Park every rename whose target is, compared broadly, another batch
    # file's current name: it may be that file until that file has moved
    # (#869). Parking one that did not need it only costs a detour.
    movers = [e for e, _ in plan.renames]
    chained = [(e, n) for e, n in plan.renames if must_park(e, n, movers)]
    direct = [(e, n) for e, n in plan.renames if (e, n) not in chained]

    def taken(src, entry, new) -> bool:
        # Checked again just before each rename into a real name: something
        # may have taken it since the plan was read (xefm.rename_check).
        if obstacle(src, new):
            errors.append(f"{entry.name}: {new} already exists"
                          + (f" — the file is now named {src.name}"
                             if src is not entry else ""))
            return True
        return False

    parked: list[tuple[Any, Any, str]] = []   # (entry, temp path, new name)
    for i, (entry, new) in enumerate(chained):
        temp = entry.parent / _temp_name(i)
        try:
            rename(entry, temp)
        except OSError as exc:
            errors.append(f"{entry.name}: {exc}")
            continue
        parked.append((entry, temp, new))

    for entry, new in direct:
        if taken(entry, entry, new):
            continue
        try:
            rename(entry, entry.parent / new)
        except OSError as exc:
            errors.append(f"{entry.name}: {exc}")
            continue
        renamed[str(entry)] = new

    for entry, temp, new in parked:
        if taken(temp, entry, new):
            continue
        try:
            rename(temp, entry.parent / new)
        except OSError as exc:
            errors.append(f"{entry.name}: {exc} — the file is now named "
                          f"{temp.name}")
            continue
        renamed[str(entry)] = new
    return renamed, errors

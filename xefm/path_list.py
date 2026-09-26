#!/usr/bin/env python3
"""A list of paths from outside XeFM, turned into something a pane can show.

The inverse of ``copy_paths``: that action decided what a file list looks like
when it leaves XeFM — one full path per line — and this module reads one back
in, from wherever it came (#453). The search that produced it happened in some
other tool; all that crosses over is the list.

Everything here is storage-agnostic and pane-free, so the pieces run on a
worker thread and are tested without an app:

- :func:`parse` — text to candidate lines. Dull on purpose: one path per line,
  whitespace and one surrounding pair of quotes trimmed, blank lines skipped.
  No delimiter guessing, no CSV, no globs, no URLs; anything cleverer belongs in
  the tool that produced the list.
- :func:`resolve` — lines to ``Path`` objects. Absolute lines and URIs stand as
  they are; a relative line resolves against a base the *caller* chooses,
  because the right anchor depends on where the list came from.
- :func:`common_root` — the directory the pane names its rows relative to.
- :func:`probe` — one attribute read per path, which is also the existence
  check, with an unreachable location tried once rather than once per row.

**Verbatim, never normalized.** A line addresses a file on disk, so it is kept
exactly as it arrived; NFC is for what the pane *shows* (:mod:`xefm.name_key`).
Normalizing before the existence check would lose every decomposed name on a
filesystem that matches bytes exactly.
"""

from __future__ import annotations

import os
from typing import Iterable, NamedTuple

from xefm import path_schemes
from xefm.path import Path, attrs_via_path

#: How far up a parent chain :func:`common_root` walks before giving up. A real
#: path is nowhere near this deep; the cap exists so a backend whose ``parent``
#: never reaches a fixed point cannot hang the walk.
_MAX_DEPTH = 256

_QUOTES = ('"', "'")


def parse(text: str | None) -> list[str]:
    """The candidate paths in ``text``, one per line, in order, each once.

    Each line loses its surrounding whitespace and then one surrounding pair of
    matching quotes — what a shell or Explorer's "Copy as path" adds. Blank
    lines are skipped. A path listed twice is kept once: a pane addresses its
    rows by path, so a duplicate row would be one file shown twice.
    """
    if not text:
        return []
    seen = set()
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if len(line) >= 2 and line[0] == line[-1] and line[0] in _QUOTES:
            line = line[1:-1].strip()
        if not line or line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return lines


def is_absolute(line: str) -> bool:
    """Whether ``line`` names a place on its own, without a base to resolve
    against: a URI (``ssh://host/x``, ``s3://bucket/key``) or an absolute
    filesystem path."""
    return path_schemes.is_uri(line) or os.path.isabs(line)


class Resolved(NamedTuple):
    """:func:`resolve`'s answer: the paths, and how many of them were relative.

    The count is reported, not hidden: a relative line resolved against the
    wrong base finds a real file that is not the one meant, which cannot be
    prevented — only said."""
    paths: list
    relative: int


def resolve(lines: Iterable[str], base) -> Resolved:
    """``lines`` as ``Path`` objects, relative ones joined onto ``base``.

    ``base`` is the anchor the source implies — the active pane for the
    clipboard, the directory the command ran in for a command, the list's own
    directory for a file. On a remote pane that is a remote directory, so a
    relative line resolves there too. Two lines that resolve to the same place
    are kept once.
    """
    paths, seen, relative = [], set(), 0
    for line in lines:
        if is_absolute(line):
            path = Path(line)
        else:
            path = Path(base) / line
            relative += 1
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        paths.append(path)
    return Resolved(paths, relative)


def _ancestors(path) -> list:
    """``path``'s ancestors, nearest first, ending at its root.

    Built from ``parent`` alone, which every backend answers without I/O, and
    stopped where ``parent`` returns the path itself — the fixed point every
    root reaches (``/``, ``C:\\``, a host root, a bucket root)."""
    chain = []
    current = path
    for _ in range(_MAX_DEPTH):
        parent = current.parent
        if str(parent) == str(current):
            break
        chain.append(parent)
        current = parent
    return chain


def common_root(paths):
    """The deepest directory every one of ``paths`` lies under, or ``None``.

    Derived from the data, not from where the user is standing: ``rg -l`` run
    inside one repository gives that repository, and the pane shows
    ``src/main.py``. Paths on two drives, two hosts or two schemes share
    nothing, and ``None`` is the honest answer there.

    One outlier drags the answer up to a drive root. That is correct and not
    very useful, and still better than a basename, which says nothing about
    which of several same-named files a row is.
    """
    if not paths:
        return None
    candidates = _ancestors(paths[0])
    for path in paths[1:]:
        if not candidates:
            return None
        chain = {str(p) for p in _ancestors(path)}
        # Drop the nearest candidates until one lies on this path's chain too;
        # the candidates only ever move toward the root.
        while candidates and str(candidates[0]) not in chain:
            candidates.pop(0)
    return candidates[0] if candidates else None


class Probed(NamedTuple):
    """:func:`probe`'s answer.

    ``entries`` holds ``(Path, attrs)`` for every path that is there, in the
    order given, ready for a listing. ``missing`` counts paths whose location
    answered and said no; ``unreachable`` counts paths whose location could not
    be reached at all — a host that refused the connection, a drive that is not
    mounted. The two are kept apart because they call for different things: a
    missing file is gone, an unreachable one may be back after a reconnect."""
    entries: list
    missing: int
    unreachable: int


def _reachable(anchor: str) -> bool:
    """Whether the root ``anchor`` names can be reached at all — asked once per
    location rather than once per path, so a dead host costs one connection
    timeout instead of one per row."""
    try:
        return Path(anchor).exists()
    except Exception:
        return False


def probe(paths, cancel=None) -> Probed:
    """Read each of ``paths``' attributes once, keeping those that are there.

    The attribute read *is* the existence check — one call per path, not an
    ``exists()`` followed by a ``stat()``. Before any path under a location is
    read, its root is tried once; if that fails, every path under it counts as
    unreachable without being tried. Blocking I/O throughout: call it on a
    worker thread. ``cancel`` (a ``threading.Event``) stops the walk early and
    returns what was read so far.
    """
    entries = []
    missing = unreachable = 0
    reachable: dict[str, bool] = {}
    for path in paths:
        if cancel is not None and cancel.is_set():
            break
        try:
            anchor = path.anchor
        except Exception:
            anchor = ""
        if anchor:
            if anchor not in reachable:
                reachable[anchor] = _reachable(anchor)
            if not reachable[anchor]:
                unreachable += 1
                continue
        attrs = attrs_via_path(path)
        if attrs.get("ok"):
            entries.append((path, attrs))
        else:
            missing += 1
    return Probed(entries, missing, unreachable)

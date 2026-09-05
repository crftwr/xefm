#!/usr/bin/env python3
"""The one string XeFM compares an entry by.

An entry has the name it carries on disk and the name a pane *compares* it by,
and those are deliberately not the same string. The compared form is:

**NFC-normalized.** A filesystem stores whatever form it was handed, and plenty
of names arrive decomposed — from HFS+ volumes, network mounts, archives, and
anything that wrote them that way in the first place. ``が`` stored NFD is
``か`` followed by a combining mark, which sorts it after every ``か``-something
instead of between ``か`` and ``き`` where it looks like it belongs, and an
incremental search typed at an IME — which emits NFC — never matches it at all.
Comparing the NFC form is what makes a pane behave the way its names look. There
is no setting for this: NFC is the only form anything but a filesystem call ever
sees.

**Pane-relative.** A search-results pane shows ``sub/dir/a.txt`` — the whole
path below the search root — so that is what the sort orders by and what the
filter and the incremental search match (#383). On an ordinary directory pane
every entry is a direct child, so the pane-relative name *is* the basename and
nothing changes there.

**Never hand a compared name to a filesystem call.** The temptation is real
because on macOS it appears to work: APFS lookup is normalization-*insensitive*
(so completely that the two forms of one name are the same file there), and an
NFC name happily opens a file stored NFD, so the mistake goes unnoticed on the
machine most of this is written on. ext4, NTFS, S3 keys and archive members all
match bytes exactly, and there the same call fails — or, for a remote key,
quietly addresses something else. ``Path`` and ``EntryInfo.name`` stay verbatim
for exactly that reason; what this module returns is for ordering, matching and
display only, which is why nothing here is named ``name``.
"""

from __future__ import annotations

import unicodedata


def nfc(text: str) -> str:
    """``text`` in NFC.

    Cheap enough to call per entry: CPython's ``normalize`` quick-checks first
    and hands back an already-NFC string in about 20ns — the same order as the
    ``str.lower()`` the search already does per entry per keystroke — so
    guarding this with ``is_normalized`` only pays for the check twice. Real
    conversion work (~900ns) happens only on the names that are actually NFD,
    which is why listings cache the result rather than the caller skipping it.
    """
    return unicodedata.normalize('NFC', text)


def rel_name(path, root=None) -> str:
    """``path``'s name relative to ``root`` — the whole ``sub/dir/a.txt`` a
    search-results pane shows in its name column.

    Falls back to the basename when there is no root, when ``path`` does not lie
    under it, or when the two name the same place. That fallback is also the
    ordinary directory pane's answer: its entries are direct children, so the
    relative name and the basename are one and the same.
    """
    if root:
        root_str = str(root)
        full = str(path)
        if full.startswith(root_str):
            rel = full[len(root_str):].lstrip("/\\")
            if rel:
                return rel
    return path.name


def compare_name(path, root=None) -> str:
    """The string every pane-side comparison uses: :func:`rel_name` in NFC.

    A listing caches this per entry as ``attrs['cmp_name']`` (see
    :meth:`xefm.file_list_manager.FileListManager._assemble_listing`), so the
    sort, the filter and every i-search keystroke read it back rather than
    re-normalizing the whole pane.
    """
    return nfc(rel_name(path, root))

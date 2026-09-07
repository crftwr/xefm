"""What the search dialog's options *mean*.

The declarations live here rather than in :mod:`xefm.app` because they are read
before any app exists: :mod:`xefm.actions` grows one unbound ``toggle_<name>``
action per option at import time, so a config can bind a direct chord to the one
option it changes hourly. Keeping them next to the functions that interpret them
also keeps the two honest — a value in ``values`` that nothing here reads would
be visibly dead.

Three options, and they are two different kinds of thing:

* **How the query is read** (``case``, ``pattern``). Both can be *derived* from
  the query, which is why their defaults are rules rather than switches: smart
  case reads a capital letter as "you meant it", and the ``.*`` chip lights when
  the query actually contains something a regex would treat specially. Deriving
  them is what makes the rule discoverable — the chip moves while you type,
  which teaches the rule that issue #305 shows nobody can guess. The switch is
  there for the times the rule guesses wrong.
* **What is walked** (``subdirs``). Cannot be derived from anything, changes the
  cost of the search, and so does not persist: a scope narrowed for one search
  must not silently narrow the next one.

The pattern default stays ``regex`` — that is what content search has always
been, and #312 is about making it *visible*, not about changing what a shipped
query does.
"""

from __future__ import annotations

import fnmatch
import re
from typing import Callable

from xefm import name_key
from xefm.options import Option

#: Option names. Constants because the walk, the dialog and the action names all
#: spell them, and a typo in any one of those fails silently.
CASE = "case"
PATTERN = "pattern"
SUBDIRS = "subdirs"

#: What makes a content query behave as a regular expression rather than as the
#: text it looks like. Deliberately includes ``\`` — ``\s`` is the escape hatch
#: the query field's trim leaves for a trailing space.
_META = re.compile(r"[.^$*+?()\[\]{}|\\]")


def case_sensitive(value: str, query: str) -> bool:
    """Whether a search for ``query`` distinguishes case under ``value``.

    Smart case (the default) is ripgrep's rule: an all-lowercase query matches
    either case, and any capital letter means you typed it on purpose. It is
    stated once here and read by the walk, the chip and the tests alike.
    """
    if value == "sensitive":
        return True
    if value == "insensitive":
        return False
    return any(ch.isupper() for ch in query)


def has_meta(query: str) -> bool:
    """Whether ``query`` contains anything a regex reads as more than itself."""
    return bool(_META.search(query))


def content_regex(query: str, *, case: str, pattern: str) -> re.Pattern:
    """The compiled matcher for one content search.

    Raises ``re.error`` for an invalid pattern exactly as before — the dialog
    turns that into its "Invalid pattern: …" status line, and a *literal* search
    can no longer raise it at all, which is the second half of what #305 asked
    for.
    """
    text = re.escape(query) if pattern == "literal" else query
    flags = 0 if case_sensitive(case, query) else re.IGNORECASE
    return re.compile(text, flags)


def filename_matcher(pattern: str, *, case: str) -> Callable[[str], bool]:
    """``(name) -> bool`` for the filename walk — the exact-glob rule of issue
    #231, now case-aware. Names arrive already NFC (:mod:`xefm.name_key`); the
    pattern is normalized here so a pasted decomposed query still matches."""
    pat = name_key.nfc(pattern)
    if case_sensitive(case, pattern):
        return lambda name: fnmatch.fnmatchcase(name, pat)
    low = pat.lower()
    return lambda name: fnmatch.fnmatchcase(name.lower(), low)


SEARCH_OPTIONS = (
    Option(
        CASE, "Case", accel="c", flag="Aa",
        values=("smart", "sensitive", "insensitive"),
        # The chip names the state rather than the mode: under smart case it is
        # the query that decides, and "Aa" lit is the answer to the question the
        # user is actually asking — is this search reading my capitals?
        flags=("Aa", "Aa", "aa"),
        labels=("smart — a capital makes it exact",
                "always case sensitive",
                "always case insensitive"),
        active=case_sensitive,
    ),
    Option(
        PATTERN, "Pattern", accel="p", flag=".*",
        values=("regex", "literal"),
        flags=(".*", "abc"),
        labels=("regular expression", "plain text"),
        modes=("content",),  # filename search speaks glob, not regex
        # Lit while the query holds a metacharacter, so the one thing #305's
        # reporters could not know — that their query is a regex — shows itself
        # the moment it starts to matter.
        active=lambda value, query: value == "literal" or has_meta(query),
    ),
    Option(
        SUBDIRS, "Search subfolders", accel="s", flag="sub",
        values=(True, False),
        flags=("sub", "no sub"),
        persist=False,
    ),
)

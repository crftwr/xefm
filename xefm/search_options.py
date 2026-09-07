"""What the search dialog's options *mean*.

The declarations live here rather than in :mod:`xefm.app` because they are read
before any app exists: :mod:`xefm.actions` grows one unbound ``toggle_<name>``
action per option at import time, so a config can bind a direct chord to the one
option it changes hourly. Keeping them next to the functions that interpret them
also keeps the two honest.

Four options, and they are two different kinds of thing:

* **How the query is read** — ``case``, ``word``, ``regex``. The same three a
  find bar anywhere offers, in the same order, because a user who has met one
  find bar has met this one. They persist for the session.
* **What is walked** — ``subdirs``. Changes the cost of the search rather than
  its meaning, and so does not persist: a scope narrowed for one search must not
  silently narrow the next one.

Every default is what content search already did before there were options:
case-insensitive, no word boundaries, a regular expression, the whole tree. The
point of #312 is to make those visible and reversible, not to change what a
query that shipped already does.
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
WORD = "word"
REGEX = "regex"
SUBDIRS = "subdirs"


def content_regex(query: str, *, case: bool, word: bool, regex: bool) -> re.Pattern:
    """The compiled matcher for one content search.

    ``regex=False`` escapes the query, which is the half of #305 nobody could
    work around: ``C++(`` becomes a search rather than "Invalid pattern".
    ``word`` wraps whatever is left in word boundaries — the group matters, or
    ``a|b`` would anchor only its first branch.

    Raises ``re.error`` for an invalid pattern exactly as before; the dialog
    turns that into its status line, and a non-regex search can no longer raise
    it at all.
    """
    text = query if regex else re.escape(query)
    if word:
        text = rf"\b(?:{text})\b"
    return re.compile(text, 0 if case else re.IGNORECASE)


def filename_matcher(pattern: str, *, case: bool) -> Callable[[str], bool]:
    """``(name) -> bool`` for the filename walk — the exact-glob rule of issue
    #231, now case-aware. Names arrive already NFC (:mod:`xefm.name_key`); the
    pattern is normalized here so a pasted decomposed query still matches."""
    pat = name_key.nfc(pattern)
    if case:
        return lambda name: fnmatch.fnmatchcase(name, pat)
    low = pat.lower()
    return lambda name: fnmatch.fnmatchcase(name.lower(), low)


SEARCH_OPTIONS = (
    # Labels first, chips second: the label's initial is the key that toggles it
    # (c, w, r, s here), so the four labels have to start apart.
    Option(CASE, "Case sensitive", flag="Aa"),
    Option(WORD, "Whole word", flag="Word", modes=("content",)),
    Option(REGEX, "Regular expression", flag=".*", default=True,
           modes=("content",)),  # filename search speaks glob, not regex
    Option(SUBDIRS, "Search subfolders", flag="Sub", default=True, persist=False),
)

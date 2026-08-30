"""The incremental-search query language — one matcher for the pane and the
dialogs (#349).

A query is whitespace-separated tokens. A token matches a candidate string when
the token, wrapped in ``*`` for "contains" semantics, matches it as an
``fnmatch`` glob, *or* when the token's Migemo regex does (romaji finds
Japanese — see :mod:`xefm.migemo_search`). Tokens combine with AND, so typing
more words narrows; :func:`hit` also offers OR for the pane's non-incremental
callers.

The wrapping is what keeps a bare word a substring search, and it is why a glob
keeps working while staying asymmetric: ``*.py`` wraps to ``*.py*``, i.e.
"contains ``.py``" rather than "ends with ``.py``". The file pane's incremental
search has behaved this way since it was written; the filter-list dialogs now
share the behavior rather than each growing their own dialect.

Compile once per query, match many times: building a token's Migemo regex is
the expensive step (#332 §3.3) while matching with the compiled result is
cheap. So callers hoist :func:`compile_query` out of their row loop — including
the loop that runs again for each streamed batch of rows
(``FilterListDialog.add_items``).
"""

from __future__ import annotations

import fnmatch
import re
from typing import Sequence

from xefm import migemo_search

#: One compiled token: its "contains"-wrapped, lowercased glob paired with the
#: Migemo regex unioned into it (``None`` where Migemo doesn't apply — disabled,
#: too short, a glob, or no engine).
Token = tuple[str, "re.Pattern | None"]


def compile_query(pattern: str) -> list[Token]:
    """``pattern``'s whitespace-separated tokens, each compiled once for reuse
    across every candidate — see the module docstring on why this is hoisted."""
    tokens: list[Token] = []
    for token in pattern.split():
        glob = token.lower()
        if not glob.startswith('*'):
            glob = '*' + glob
        if not glob.endswith('*'):
            glob = glob + '*'
        tokens.append((glob, migemo_search.get_regex(token)))
    return tokens


def hit(tokens: Sequence[Token], text: str, *, match_all: bool = True) -> bool:
    """Whether ``text`` passes a compiled query.

    ``match_all`` combines the tokens with AND (the narrowing a filter field
    wants); ``False`` makes it OR. An empty query passes everything under AND
    and nothing under OR — the vacuous truth an empty filter field wants, and
    why the dialogs need no separate "no filter" branch.
    """
    lowered = text.lower()
    hits = (fnmatch.fnmatch(lowered, glob)
            or (regex is not None and migemo_search.search_nfc(regex, text))
            for glob, regex in tokens)
    return all(hits) if match_all else any(hits)

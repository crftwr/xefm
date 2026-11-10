"""What a rename may land on — shared by the rename prompt, the batch rename
dialog and Rename in Editor.

A case-insensitive disk (Windows, and macOS by default) finds ``Foo.txt`` when
asked for ``foo.txt``; a case-sensitive one (Linux by default, a case-sensitive
APFS volume) holds them as two files. A rename check that compares names alone
is wrong on one of the two: exact comparison refuses a case-only rename on the
first (#867) and misses a batch member freeing a name typed in another case
(#869); casefolded comparison lets ``foo.txt -> Foo.txt`` replace a separate
``Foo.txt`` on the second (#873). So the disk is asked:

- :func:`is_itself` — does the existing file under the new name turn out to be
  the file being renamed?
- :func:`folding_dirs` — which of the batch's directories find a name in another
  case? :func:`landing_key` then gives the key under which two names in one
  directory are one file, for collisions between names that do not exist yet
  (two lines of one batch) and for names a batch frees.
"""

from __future__ import annotations

from typing import Any, Iterable

from xefm import name_key

#: Characters we refuse in a result name.
_INVALID_CHARS = set('/\\:*?"<>|')


def is_valid_name(name: str) -> bool:
    if not name or name in (".", ".."):
        return False
    return not any(ch in _INVALID_CHARS for ch in name)


def is_itself(entry: Any, new: str) -> bool:
    """Whether ``new``, in ``entry``'s directory, names ``entry`` itself in
    another case. A case-insensitive disk finds a case-only rename's own file
    under the new name, which is no collision. The disk is asked, not just the
    names compared, so on a case-sensitive disk another file that differs only
    in case still is one."""
    if new.casefold() != name_key.nfc(entry.name).casefold():
        return False
    try:
        return (entry.parent / new).samefile(entry)
    except OSError:
        return False


def _dir_folds(entry: Any) -> bool | None:
    """Whether ``entry``'s directory finds ``entry`` under its name in another
    case; None when the name has no letters with a case to swap."""
    name = entry.name
    swapped = name.swapcase()
    if swapped == name:
        return None
    try:
        other = entry.parent / swapped
        return other.exists() and other.samefile(entry)
    except OSError:
        return False


def folding_dirs(entries: Iterable[Any]) -> set[str]:
    """The directories, among those holding ``entries``, whose disk finds a name
    in another case. One entry per directory with a cased letter in its name
    settles it, by looking that entry up under its name with the case swapped.

    A directory none of the entries can settle — every name there is digits and
    punctuation — counts as folding. That is the cautious side: it refuses two
    new names differing only in case (a case-sensitive disk would have held
    both) and sends more renames by way of a temporary name, which always works.
    It cannot wrongly free a name, since a name the batch frees there has no
    case to fold."""
    verdict: dict[str, bool | None] = {}
    for entry in entries:
        where = str(entry.parent)
        if verdict.get(where) is not None:
            continue
        verdict[where] = _dir_folds(entry)
    return {where for where, folds in verdict.items() if folds is not False}


def landing_key(folding: set[str], parent: Any, name: str) -> tuple[str, str]:
    """The key two (NFC) names in ``parent`` share exactly when they are one
    file there: the name itself, casefolded where the disk folds case."""
    where = str(parent)
    return (where, name.casefold() if where in folding else name)

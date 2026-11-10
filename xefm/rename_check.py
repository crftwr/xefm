"""What a rename may land on — shared by the rename prompt, the batch rename
dialog and Rename in Editor.

A rename replaces whatever directory entry already holds the new name on macOS,
Linux, SSH and S3 (Windows refuses instead), so the one thing every check here
has to get right is: *is there an entry under the new name that is not one of
the files being renamed away?* Names alone cannot say. ``Foo.txt`` finds
``foo.txt`` on a disk that ignores case (Windows, macOS by default), and is a
separate entry on one where case matters (Linux by default, a case-sensitive
APFS volume) — #867, #869, #873. And "the same file" is not "the same entry":
``samefile`` follows symlinks, so a symlink ``foo.txt`` to ``Foo.txt`` is "the
same file" as the ``Foo.txt`` its rename would replace (#875).

So the rule is lopsided on purpose:

- **Comparing names may only refuse, or take the cautious road.** Two new names
  that differ only in case are refused, unless the directory has been seen to
  hold two such names already (:meth:`Listings.case_matters`); a rename onto a
  name that differs only in case from another batch file's current name goes
  by way of a temporary name (:func:`must_park`).
- **Letting a rename through takes evidence from the storage.** An entry found
  under the new name is acceptable only when it is shown to be one of the files
  leaving it (:func:`obstacle`): by the entry's own identity where the backend
  declares ``entry_identity`` (``lstat``'s device and inode, which do not follow
  symlinks), or else by the directory listing. Anything that cannot be shown is
  an obstacle.

What remains is a race: another program creating the new name between the
check and the rename. Every rename path checks again just before each rename
(:func:`obstacle` once more), which narrows that to the moment in between.
"""

from __future__ import annotations

from typing import Any, Iterable

from xefm import name_key

#: Characters we refuse in a result name.
_INVALID_CHARS = set('/\\:*?"<>|')

#: Only ASCII letters, lowered — every disk that ignores case folds these, so
#: two names this makes equal cannot both be held by one (unlike ``casefold``,
#: whose ``ß``/``ss`` or Kelvin-sign/``k`` some such disks keep apart).
_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                             "abcdefghijklmnopqrstuvwxyz")


def is_valid_name(name: str) -> bool:
    if not name or name in (".", ".."):
        return False
    return not any(ch in _INVALID_CHARS for ch in name)


def fold(name: str) -> str:
    """The broad key names are compared by when only refusing: NFC, then
    ``casefold``. Broader than any disk's own folding, which is the safe side —
    it can only find more names alike, never fewer."""
    return name_key.nfc(name).casefold()


class Listings:
    """Directory listings, read once each and only when a check needs one."""

    def __init__(self) -> None:
        self._names: dict[str, list[str]] = {}

    def names(self, parent: Any) -> list[str]:
        """Every name ``parent`` holds now, as stored. Raises ``OSError``."""
        where = str(parent)
        if where not in self._names:
            self._names[where] = [p.name for p in parent.iterdir()]
        return self._names[where]

    def case_matters(self, parent: Any) -> bool:
        """Whether ``parent`` is shown to keep names apart by case: it holds
        two names that differ only in the case of ASCII letters. False when it
        cannot be shown, which is the cautious answer."""
        try:
            names = self.names(parent)
        except OSError:
            return False
        seen: set[str] = set()
        for name in names:
            key = name.translate(_ASCII_LOWER)
            if key in seen:
                return True
            seen.add(key)
        return False


def _lexists(path: Any) -> bool:
    """Whether anything — a dangling symlink included — is under ``path``. An
    error answers yes: an entry that cannot be looked at is not known to be
    absent."""
    try:
        return path.exists() or path.is_symlink()
    except OSError:
        return True


def _identity(path: Any) -> tuple | None:
    """The directory entry ``path`` names, as ``lstat``'s device and inode, or
    None where the backend does not declare that this identifies an entry."""
    supports = getattr(path, "supports", None)
    if not (supports and supports("entry_identity")):
        return None
    try:
        st = path.lstat()
    except OSError:
        return None
    if not st.st_ino:
        return None  # a filesystem with no file IDs reports 0 for all of them
    return (st.st_dev, st.st_ino)


def obstacle(entry: Any, new: str, leaving: Iterable[Any] = (),
             listings: Listings | None = None) -> bool:
    """Whether an entry under ``new`` in ``entry``'s directory would be replaced
    by renaming ``entry`` there — something other than ``entry`` itself and the
    ``leaving`` files (batch members renamed away from that directory).

    True also whenever that cannot be shown either way, so a caller refuses."""
    new = name_key.nfc(new)
    target = entry.parent / new
    if not _lexists(target):
        return False
    where = str(entry.parent)
    gone = [entry, *(m for m in leaving if str(m.parent) == where)]
    # A name exactly as stored is one entry on every disk: if it is a leaving
    # file's, it is that file. (Equal only once composed is not enough — a
    # disk that keeps NFC and NFD apart can hold both.)
    if any(m.name == new for m in gone):
        return False
    # Found under another case: only a leaving file with the same folded name
    # can be it, and the storage has to say which entry it is.
    alike = [m for m in gone if fold(m.name) == fold(new)]
    if not alike:
        return True
    found = _identity(target)
    if found is not None:
        return not any(_identity(m) == found for m in alike)
    try:
        names = (listings or Listings()).names(entry.parent)
    except OSError:
        return True
    if new in names:
        return True  # an entry under exactly that name, and none of ours
    held = {name for name in names if fold(name) == fold(new)}
    return not held or not held <= {m.name for m in alike}


def must_park(entry: Any, new: str, others: Iterable[Any]) -> bool:
    """Whether renaming ``entry`` to ``new`` has to wait, by way of a temporary
    name, for one of ``others`` (batch files being renamed too) to leave first:
    ``new`` is, compared broadly, the current name of one of them in the same
    directory. Parking more than needed costs only a detour."""
    where, key = str(entry.parent), fold(new)
    return any(m is not entry and str(m.parent) == where and fold(m.name) == key
               for m in others)

"""Locate and rewrite XeFM's single version literal.

The version lives in exactly one place — ``xefm/__init__.py``'s ``__version__``
— and every consumer derives it: pyproject.toml through setuptools' dynamic
``version = { attr = "xefm.__version__" }``, ``xefm.const``/``xefm.app`` by
re-export, and the macOS/Windows bundle builders by extracting this same
literal with ``sed`` / ``Select-String``. Both release scripts go through this
module so they can never disagree about where the literal is.

The literal is read statically (regex, no ``import xefm``) so the release
tooling never needs XeFM's runtime deps — puikit, pillow, boto3 — merely to
learn the version. That is the same static approach setuptools itself uses to
resolve the ``attr`` at build time, and it keeps these scripts runnable with a
bare interpreter.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INIT = REPO_ROOT / "xefm" / "__init__.py"

#: Anchored to a whole line so nothing else in the file can match — in
#: particular the ``#:`` comment block above the literal, which mentions
#: ``__version__`` several times.
PATTERN = re.compile(r'^__version__\s*=\s*"([^"]+)"\s*$', re.M)


def read_version() -> str:
    """Return the current version literal.

    Raises SystemExit if it is absent or duplicated — either means the single
    source of truth has been disturbed, which a release must not paper over.
    """
    found = PATTERN.findall(INIT.read_text(encoding="utf-8"))
    if len(found) != 1:
        raise SystemExit(
            f'ERROR: expected exactly one `__version__ = "..."` line in {INIT}, '
            f"found {len(found)}"
        )
    return found[0]


def write_version(new: str) -> str:
    """Rewrite the literal to ``new``. Returns the previous value."""
    old = read_version()
    text = INIT.read_text(encoding="utf-8")
    # A lambda replacement, so backslashes/group refs in `new` stay literal.
    new_text, count = PATTERN.subn(lambda _m: f'__version__ = "{new}"', text)
    if count != 1:
        raise SystemExit(f"ERROR: expected 1 substitution in {INIT}, made {count}")
    INIT.write_text(new_text, encoding="utf-8")
    return old

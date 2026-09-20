#!/usr/bin/env python3
"""The one list of URI schemes XeFM understands.

``Path`` picks a storage backend from a URI's scheme. That decision was spread
over four places that had to agree and did not:

- ``Path.__init__`` — the guard that keeps a URI away from ``PathlibPath``
- ``Path._create_implementation`` — the if-chain that actually builds a backend
- ``XeFMApp._REMOTE_SCHEMES`` — what Jump to Path resolves against
- ``config._REMOTE_SCHEMES`` — what ``FAVORITE_DIRECTORIES`` and
  ``DRIVE_LOCATIONS`` pass through unprobed

Patch only the first two and Jump to Path treats ``reg://…`` as a path relative
to the current directory and reports "Path does not exist". That report is
accurate.

They are one table here. The contract each entry keeps is the one the if-chain
already kept: **a URI string goes in, a** ``PathImpl`` **comes out**, with the
parsing inside the class. Nothing here looks at a URI beyond its scheme, which
is what lets a backend be written and tested with this module nowhere in sight.

Registration is lazy on purpose. A factory imports its backend when it is first
asked for one, so listing the schemes — which the favourites picker does to
decide whether a row needs probing — never pulls in ``boto3`` for an ``s3://``
row nobody selected.

Schemes with no backend
-----------------------

``scp://`` and ``ftp://`` sat in all three lists above with no branch in the
if-chain, so they quietly resolved to a *local* path: ``Path('ftp://h/p')``
became ``PathlibPath('ftp:/h/p')``, with the ``//`` collapsed, and reported
itself missing. They are registered here with :class:`Unsupported` instead,
which keeps them recognised as URIs — a subshell still refuses to ``cd`` into
one — while saying plainly what is wrong when something tries to read one.
"""

from typing import Callable, Optional

#: ``scheme -> {'factory', 'source'}``, in registration order. A factory takes
#: the full URI string and returns a ``PathImpl``.
_schemes: dict[str, dict] = {}

#: ``('archive://', 's3://', …)``, kept as a tuple because ``Path.__init__``
#: passes it straight to ``str.startswith`` for every path XeFM builds.
_prefixes: tuple = ()

#: Characters a scheme name may hold, from RFC 3986 — a letter first, then
#: letters, digits, ``+``, ``-`` and ``.``.
_SCHEME_TAIL = set('abcdefghijklmnopqrstuvwxyz0123456789+-.')


def _rebuild_prefixes() -> None:
    global _prefixes
    _prefixes = tuple(f'{scheme}://' for scheme in _schemes)


def validate_scheme(scheme) -> Optional[str]:
    """``None`` if ``scheme`` could name a backend, or why it could not.

    Returned rather than raised, because the caller that most needs it is a
    config load, which reports every problem it finds and skips the entry.
    """
    if not isinstance(scheme, str) or not scheme:
        return 'a scheme must be a non-empty string'
    lowered = scheme.lower()
    if lowered != scheme:
        return f"scheme {scheme!r} must be lowercase"
    if '://' in scheme:
        return f"scheme {scheme!r} is written without '://'"
    if not scheme[0].isalpha() or not set(scheme[1:]) <= _SCHEME_TAIL:
        return (f"scheme {scheme!r} must start with a letter and hold only "
                f"letters, digits, '+', '-' and '.'")
    return None


def register(scheme: str, factory: Callable[[str], object], *,
             source: str = 'builtin') -> None:
    """Make ``scheme://`` resolve through ``factory``.

    ``source`` groups registrations so a config reload can drop its own without
    touching the built-ins — the same shape ``actions.registry`` uses, and for
    the same reason: a registration that *shadows* another has to be
    undoable. Overriding ``s3://`` and then reloading the config must give
    ``s3://`` back, not take it away, so the entry being covered is kept.

    Re-registering the same source over itself — which is what a reload does —
    does not stack: the covered entry stays the one that was there before that
    source first arrived.
    """
    problem = validate_scheme(scheme)
    if problem:
        raise ValueError(problem)
    covered = _schemes.get(scheme)
    if covered is not None and covered['source'] == source:
        covered = covered['covered']
    _schemes[scheme] = {'factory': factory, 'source': source, 'covered': covered}
    _rebuild_prefixes()


def unregister_source(source: str) -> None:
    """Drop every scheme registered under ``source``, uncovering whatever each
    one was shadowing. A config reload rebuilds from scratch, so a virtual
    folder removed from the config stops resolving."""
    for scheme, entry in list(_schemes.items()):
        if entry['source'] != source:
            continue
        if entry['covered'] is not None:
            _schemes[scheme] = entry['covered']
        else:
            del _schemes[scheme]
    _rebuild_prefixes()


def schemes(source: Optional[str] = None) -> list:
    """The registered scheme names, all of them or just one source's."""
    return [s for s, e in _schemes.items() if source is None or e['source'] == source]


def prefixes() -> tuple:
    """``('archive://', 's3://', …)`` — what a ``startswith`` test needs."""
    return _prefixes


def is_uri(text) -> bool:
    """Whether ``text`` names a location by scheme rather than by filesystem
    path. A path that is one must survive verbatim: running it through
    ``PathlibPath`` collapses ``scheme://`` to ``scheme:/``."""
    return isinstance(text, str) and text.startswith(_prefixes)


def scheme_of(text) -> Optional[str]:
    """The registered scheme ``text`` uses, or ``None``."""
    if not isinstance(text, str):
        return None
    scheme, sep, _ = text.partition('://')
    return scheme if sep and scheme in _schemes else None


def create(path_str: str):
    """The ``PathImpl`` for ``path_str``, or ``None`` if no scheme claims it —
    in which case the caller falls back to the local filesystem."""
    scheme = scheme_of(path_str)
    if scheme is None:
        return None
    return _schemes[scheme]['factory'](path_str)


# --------------------------------------------------------------------------- #
# The built-ins
# --------------------------------------------------------------------------- #

def _archive(uri: str):
    try:
        from xefm.archive import ArchivePathImpl
    except ImportError as e:
        raise ImportError(f"Archive support not available: {e}")
    return ArchivePathImpl(uri)


def _s3(uri: str):
    try:
        from xefm.s3 import S3PathImpl
    except ImportError as e:
        raise ImportError(f"S3 support not available: {e}")
    return S3PathImpl(uri)


def _ssh(uri: str):
    try:
        from xefm.ssh import SSHPathImpl
    except ImportError as e:
        raise ImportError(f"SSH support not available: {e}")
    return SSHPathImpl(uri)


def _unsupported(uri: str):
    from xefm.path_base import UnsupportedPathImpl
    return UnsupportedPathImpl(uri)


register('archive', _archive)
register('s3', _s3)
register('ssh', _ssh)
register('scp', _unsupported)
register('ftp', _unsupported)

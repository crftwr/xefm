#!/usr/bin/env python3
"""
XeFM String Formatting Utilities

Common string formatting functions used throughout XeFM.
"""

import re
from pathlib import Path


def format_size(size: int, compact: bool = False) -> str:
    """Format file size in human-readable format.
    
    Args:
        size: Size in bytes
        compact: If True, use compact format without spaces (e.g., "1.5M")
                If False, use standard format with spaces (e.g., "1.5 MB")
    
    Returns:
        str: Formatted size string
        
    Examples:
        >>> format_size(0)
        '0 B'
        >>> format_size(512)
        '512 B'
        >>> format_size(1536)
        '1.5 KB'
        >>> format_size(1536, compact=True)
        '1.5K'
        >>> format_size(1048576)
        '1.0 MB'
        >>> format_size(1073741824)
        '1.0 GB'
    """
    if size < 0:
        size = 0
    
    if compact:
        # Compact format: no space, single letter, 1 decimal place
        for unit in ['B', 'K', 'M', 'G', 'T']:
            if size < 1024.0:
                if unit == 'B':
                    return f"{int(size)}{unit}"
                else:
                    return f"{size:.1f}{unit}"
            size /= 1024.0
        return f"{size:.1f}P"
    else:
        # Standard format: with space, full unit name, 1 decimal place
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0:
                if unit == 'B':
                    # Show bytes as integer without decimal
                    return f"{int(size)} {unit}"
                else:
                    return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} PB"


#: Leading ``scheme://`` of a location URI (``s3://``, ``ssh://``, ``archive://``).
#: Kept intact when abbreviating: without it a path is not just shortened, it is
#: wrong — ``s3://bucket/k`` and ``bucket/k`` name different things.
_SCHEME_RE = re.compile(r'^[A-Za-z][A-Za-z0-9+.\-]*://')

#: Sentinel returned instead of a path component that was dropped.
_ELLIPSIS = '…'


def _fit_prefix(text: str, budget: float, measure) -> str:
    """Longest prefix of ``text`` that measures at most ``budget``.

    Assumes ``measure`` is monotonic in string length (true for any character-
    or glyph-width metric), which lets this binary-search instead of walking
    one character at a time.
    """
    if budget <= 0:
        return ''
    if measure(text) <= budget:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if measure(text[:mid]) <= budget:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo]


def _fit_suffix(text: str, budget: float, measure) -> str:
    """Longest suffix of ``text`` that measures at most ``budget``."""
    if budget <= 0:
        return ''
    if measure(text) <= budget:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if measure(text[len(text) - mid:]) <= budget:
            lo = mid
        else:
            hi = mid - 1
    return text[len(text) - lo:]


def abbreviate_path(path_str: str, avail: float, measure=None,
                    home: str = None) -> str:
    """Fit a location into ``avail`` units by dropping whole path components.

    Blind middle-elision cuts wherever the character budget happens to run out,
    so ``/Users/crftwr/projects/xefm/src`` degrades to ``/Users/crf…/xefm/src`` —
    a fragment of a directory name that names nothing. This drops *entire*
    components instead, so every name left on screen is a real one, and keeps
    the two parts that carry the most meaning: the anchor (root, ``~``, or
    ``scheme://host``) and the leaf (where you actually are).

    A ``scheme://`` prefix is never abbreviated, and on local paths the user's
    home directory contracts to ``~`` before any components are dropped —
    often enough on its own to make the path fit.

    Args:
        path_str: The location to display.
        avail: Budget in the same units ``measure`` returns.
        measure: Callable mapping a string to its display width. Defaults to
            ``len`` (character cells); pass ``ctx.measure_text`` on a vector
            backend, where glyphs are not uniformly wide.
        home: Home directory to contract to ``~``. Defaults to ``Path.home()``;
            pass explicitly in tests to avoid depending on the environment.

    Returns:
        The path, abbreviated only as much as ``avail`` requires.

    Examples:
        >>> abbreviate_path('/Users/me/projects/xefm/src', 80)
        '/Users/me/projects/xefm/src'
        >>> abbreviate_path('/Users/me/projects/xefm/src', 18)
        '/…/xefm/src'
        >>> abbreviate_path('s3://bucket/a/b/c/leaf', 18)
        's3://bucket/…/leaf'
    """
    if measure is None:
        measure = len
    if avail <= 0:
        return ''

    scheme_match = _SCHEME_RE.match(path_str)
    scheme = scheme_match.group(0) if scheme_match else ''
    rest = path_str[len(scheme):]

    # Contract $HOME to '~' first — it is free (no information is lost, the
    # reader reconstructs it) so it should happen before dropping components.
    # Only meaningful for local paths: '~' under an s3:// or ssh:// URI would
    # claim a remote home directory that has nothing to do with the local user.
    if not scheme:
        if home is None:
            try:
                home = str(Path.home())
            except (RuntimeError, OSError):
                home = None
        if home and home != '/':
            if rest == home:
                rest = '~'
            elif rest.startswith(home + '/'):
                rest = '~' + rest[len(home):]

    if measure(scheme + rest) <= avail:
        return scheme + rest

    # Trailing separator carries no name; drop it so it cannot become an empty
    # component that reads as a phantom directory level. '/' itself is exempt.
    if len(rest) > 1 and rest.endswith('/'):
        rest = rest.rstrip('/') or '/'

    components = rest.split('/')
    if len(components) <= 1:
        # Nothing to drop (a bare name, or a scheme with no path). Fall through
        # to a character-level middle cut — the only option left.
        return _elide_middle(scheme + rest, avail, measure)

    # components[0] is the anchor: '' for an absolute path (so join restores the
    # leading '/'), '~' for home, or the host/bucket under a scheme.
    anchor, leaf = components[0], components[-1]

    # Keep the longest run of trailing components that still fits. Trailing
    # components are the ones nearest where the user is, so they are the ones
    # worth keeping when something has to go.
    for take in range(len(components) - 2, 0, -1):
        candidate = scheme + '/'.join([anchor, _ELLIPSIS, *components[-take:]])
        if measure(candidate) <= avail:
            return candidate

    # Even anchor + leaf alone overflows; try dropping the anchor too.
    candidate = scheme + '/'.join([anchor, _ELLIPSIS, leaf])
    if measure(candidate) <= avail:
        return candidate
    candidate = scheme + _ELLIPSIS + '/' + leaf
    if measure(candidate) <= avail:
        return candidate

    # The leaf by itself does not fit. Cut inside it as a last resort.
    return _elide_middle(leaf, avail, measure)


def _elide_middle(text: str, avail: float, measure) -> str:
    """Character-level middle cut, for when no component boundary helps."""
    if measure(text) <= avail:
        return text
    ell_w = measure(_ELLIPSIS)
    if ell_w > avail:
        return _fit_prefix(text, avail, measure)
    budget = avail - ell_w
    left = _fit_prefix(text, budget / 2, measure)
    right = _fit_suffix(text, budget - measure(left), measure)
    return left + _ELLIPSIS + right

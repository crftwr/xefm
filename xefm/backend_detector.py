#!/usr/bin/env python3
"""
XeFM Backend Detector

Provides utilities to detect which backend XeFM is currently running with.
This is useful for configuration that needs to adapt based on the actual
runtime backend rather than just the preferred backend setting.
"""

import sys
import os


# Cache the backend detection result to avoid repeated checks
_cached_backend = None

# PuiKit backend names that mean "desktop / GUI" rather than "terminal".
# We match the raw string from XEFM_BACKEND/--backend: XeFM and both app
# launchers always pass the platform-agnostic ``gui`` alias (PuiKit resolves it
# to the concrete ``macos``/``windows`` backend), which is why ``gui`` must be
# here. ``macos``/``windows`` are the concrete backend names, accepted in case
# they're passed explicitly and mirroring the Method-3 module check below.
_DESKTOP_BACKEND_NAMES = frozenset({
    'gui', 'macos', 'windows',
    # The web backend renders in a browser but is a pixel/GUI backend (real
    # fonts, mouse, pointer), so XeFM treats it as desktop mode too — the config
    # picks its GUI-appropriate settings (proportional UI font, GUI editor, ...).
    'web', 'webbrowser', 'browser',
})


def _is_desktop_backend_name(name):
    """True if ``name`` is one of the GUI backends (case-insensitive)."""
    return name.lower() in _DESKTOP_BACKEND_NAMES


def is_desktop_mode():
    """
    Detect if XeFM is running in desktop mode (native GUI backend).

    This function checks multiple indicators to determine if XeFM is running
    with the native GUI backend (desktop mode — ``macos``/``windows``, launched
    via the ``gui`` alias) or the curses backend (terminal mode).

    Detection methods (in order of priority):
    1. Check XEFM_BACKEND environment variable (set by main() at startup)
    2. Check command-line arguments for the --backend flag
    3. Check if a GUI backend module is already loaded
    4. Default to terminal mode (curses)

    Note: Results are cached after first detection for performance.

    Returns:
        bool: True if running in desktop mode, False if running in terminal mode

    Examples:
        >>> if is_desktop_mode():
        ...     editor = 'code'
        ... else:
        ...     editor = 'vim'
    """
    global _cached_backend

    # Return cached result if available
    if _cached_backend is not None:
        return _cached_backend

    # Method 1: Check environment variable (most reliable — set by main()).
    backend_env = os.environ.get('XEFM_BACKEND')
    if backend_env:
        _cached_backend = _is_desktop_backend_name(backend_env)
        return _cached_backend

    # Method 2: Check command-line arguments. XeFM (and the macOS .app bundle)
    # launch with e.g. ``--backend gui`` / ``--backend macos``; the bundle sets
    # sys.argv before importing xefm, so this is reliable even at config-load
    # time before main() runs.
    if '--backend' in sys.argv:
        try:
            backend_idx = sys.argv.index('--backend')
            if backend_idx + 1 < len(sys.argv):
                _cached_backend = _is_desktop_backend_name(sys.argv[backend_idx + 1])
                return _cached_backend
        except (ValueError, IndexError):
            pass

    # Method 3: Check if a native GUI backend module is already loaded.
    # This indicates the backend is actually running.
    if 'puikit.backends.macos_backend' in sys.modules or \
       'puikit.backends.windows_backend' in sys.modules:
        _cached_backend = True
        return _cached_backend

    # Default to terminal mode (don't cache this default)
    return False


def get_backend_name():
    """
    Get the name of the currently running backend.

    Returns:
        str: 'gui' for desktop mode, 'curses' for terminal mode

    Examples:
        >>> backend = get_backend_name()
        >>> print(f"Running with {backend} backend")
    """
    return 'gui' if is_desktop_mode() else 'curses'

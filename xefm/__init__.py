"""
XeFM - Terminal File Manager

A dual-pane file manager for the terminal with support for local and remote
filesystems. ``xefm.app`` is the entry module (``python -m xefm`` and the
``xefm`` console script both land in ``xefm.app.main``); its siblings hold the
storage-agnostic business logic.
"""

#: Single source of truth for the version string. Packaging reads it via
#: pyproject.toml's dynamic ``version`` (``attr = "xefm.__version__"``), the
#: macOS/Windows bundle builders sed it out of this file, and ``xefm.app`` /
#: ``xefm.const`` re-export it rather than duplicating the literal.
__version__ = "0.99"

__author__ = "Tomonori Shimomura"

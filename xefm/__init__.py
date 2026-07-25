"""
XeFM - a dual-pane file manager for the desktop and the terminal

Runs as a native desktop app on Windows and macOS and as a terminal (TUI) app on
Windows, macOS and Linux — the same widget code on either, chosen with
``--backend``. Supports local and remote filesystems (S3, SFTP, archives).

``xefm.app`` is the entry module (``python -m xefm`` and the ``xefm`` console
script both land in ``xefm.app.main``); its siblings hold the storage-agnostic
business logic.
"""

#: Single source of truth for the version string. Packaging reads it via
#: pyproject.toml's dynamic ``version`` (``attr = "xefm.__version__"``), the
#: macOS/Windows bundle builders sed it out of this file, and ``xefm.app`` /
#: ``xefm.const`` re-export it rather than duplicating the literal.
__version__ = "0.99"

__author__ = "Tomonori Shimomura"

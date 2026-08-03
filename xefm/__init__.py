"""
XeFM - a dual-pane file manager for the desktop and the terminal

Runs as a native desktop app on Windows and macOS and as a terminal (TUI) app on
Windows, macOS and Linux — the same widget code on either, chosen with
``--backend``. Supports local and remote filesystems (S3, SFTP, archives).

``xefm.app`` is the entry module (``python -m xefm`` and the ``xefm`` console
script both land in ``xefm.app.main``); its siblings hold the storage-agnostic
business logic.
"""

#: Single source of truth for the version string -- the ONLY place the literal
#: appears in this repo. Bumping the version means editing this line and nothing
#: else; every consumer derives it:
#:
#:   * pyproject.toml     -- dynamic ``version`` (``attr = "xefm.__version__"``)
#:   * xefm.app / .const  -- re-export it (``--version`` output)
#:   * macos_app/build.sh, macos_app/create_dmg.sh -- ``sed`` this literal out
#:   * windows_app/build.ps1 -- ``Select-String`` this literal out (-> XeFM.rc)
#:   * test/test_argparse_integration.py -- imports it, asserts no literal
#:
#: Don't reintroduce a copy: prose docs point here instead of restating the
#: number, and the bundle builders accept a ``VERSION`` override for one-off
#: builds without editing anything.
__version__ = "1.0.5"
__author__ = "craftware"

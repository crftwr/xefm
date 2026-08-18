"""Jump-to-Path input resolution (Shift-J), including remote URIs (issue #318).

``XeFMApp._resolve_jump_target`` turns the dialog's text into a
:class:`xefm.path.Path` against the pane's current directory. Local input keeps
the historical rules (``~`` expansion, relative join, ``os.path.normpath``);
a remote URI (``s3://…``, ``ssh://…``) must be taken as-is — ``os.path.isabs``
calls it relative and ``normpath`` collapses ``scheme://`` to ``scheme:/``,
which is exactly the bug this guards against.

Run with: python -m pytest test/test_jump_to_path.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from xefm.app import XeFMApp


def resolve(text, current):
    return str(XeFMApp._resolve_jump_target(text, current))


# --- local paths keep the historical behaviour --------------------------------


def test_absolute_local_path():
    assert resolve("/usr/lib", "/home/user") == os.path.normpath("/usr/lib")


def test_relative_local_path_joins_current():
    assert resolve("sub", "/home/user") == os.path.normpath("/home/user/sub")


def test_relative_local_path_normalizes_dotdot():
    assert resolve("../other", "/home/user/x") == os.path.normpath("/home/user/other")


def test_tilde_expands_to_home():
    assert resolve("~/sub", "/elsewhere") == os.path.normpath(
        os.path.join(os.path.expanduser("~"), "sub"))


def test_surrounding_whitespace_is_stripped():
    assert resolve("  /usr/lib  ", "/home/user") == os.path.normpath("/usr/lib")


# --- remote URIs are taken as-is (issue #318) ---------------------------------


def test_s3_uri_keeps_scheme():
    assert resolve("s3://bucket/key/path", "/home/user") == "s3://bucket/key/path"


def test_s3_uri_keeps_scheme_from_remote_pane():
    assert resolve("s3://other-bucket/x", "s3://bucket/dir") == "s3://other-bucket/x"


def test_ssh_uri_keeps_scheme():
    assert resolve("ssh://host/var/log", "/home/user") == "ssh://host/var/log"


def test_relative_input_joins_remote_current():
    # Typing a bare child name while the pane shows an S3 directory must stay
    # inside that S3 directory — and must not be normpath-mangled.
    result = resolve("sub", "s3://bucket/dir")
    assert result.startswith("s3://bucket/dir")
    assert result.rstrip("/").endswith("/sub")


def test_absolute_local_input_leaves_remote_pane():
    # An absolute local path typed while browsing S3 jumps to the local path.
    assert resolve("/usr/lib", "s3://bucket/dir") == os.path.normpath("/usr/lib")

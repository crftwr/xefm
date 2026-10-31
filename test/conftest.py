"""Fixtures shared by the whole test suite.

Run with: python -m pytest test/ -v
"""

import os
import shutil
import tempfile

import pytest

_saved_home_env = {}
_fake_home = None


def pytest_configure(config):
    """Point the home directory at an empty temporary one for the whole run
    (#808), so no test reads the runner's own ``~/.xefm/config.py``.

    Its ``MENUS``, ``FILTERS`` and status-bar items would otherwise be live
    while a test runs, and ``make tag`` fails on a configured machine while
    passing on a bare one. Set here rather than in a fixture so it is already
    in place for anything that reads the home at collection time. ``realpath``
    because macOS hands out ``/var/...``, a symlink to ``/private/var/...``.
    A test that needs a home of its own still sets ``HOME`` itself."""
    global _fake_home
    _fake_home = os.path.realpath(tempfile.mkdtemp(prefix="xefm-test-home-"))
    for name in ("HOME", "USERPROFILE"):
        _saved_home_env[name] = os.environ.get(name)
        os.environ[name] = _fake_home


def pytest_unconfigure(config):
    for name, value in _saved_home_env.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    if _fake_home is not None:
        shutil.rmtree(_fake_home, ignore_errors=True)


@pytest.fixture(autouse=True)
def restore_ssl():
    """Undo ``truststore.inject_into_ssl()`` after a test that ran the real
    ``xefm.app.main()`` (#676). The injection replaces ``ssl.SSLContext`` for
    the whole process, so without this every later test in the same worker —
    the S3 ones first — would build its contexts through the OS verifier."""
    yield
    import sys
    truststore = sys.modules.get("truststore")
    if truststore is not None and hasattr(truststore, "extract_from_ssl"):
        truststore.extract_from_ssl()


@pytest.fixture(autouse=True)
def reset_s3_clients():
    """Hand every test a clean S3 client registry.

    ``xefm.s3`` shares one boto3 client per region for the life of the process
    (issue #418) — which is exactly wrong between tests: without this, the first
    test to stub ``boto3.client`` would have its stub handed to every test that
    ran after it. Cleared on the way in as well as out, so a test that leaves one
    behind (or a stray import at collection time) can't reach the next one."""
    try:
        from xefm.s3 import clear_s3_clients
    except ImportError:  # boto3 not installed: nothing caches a client
        yield
        return
    clear_s3_clients()
    yield
    clear_s3_clients()


@pytest.fixture(autouse=True)
def drop_user_config_entries():
    """Leave no config-defined entry behind for the next test.

    A test that builds an ``XeFMApp`` loads ``~/.xefm/config.py`` (the
    temporary home's, see ``pytest_configure``, which a test may write), and
    its ``ACTIONS``, ``EVENT_HOOKS``, ``SORT_KEYS``, ``FILTERS``,
    ``IMAGE_DECODERS``, ``PATH_SCHEMES`` and ``LEXERS`` land in process-wide
    registries. Left there, they reach every later test in the process, which
    then passes or fails depending on which test happened to run first. Dropped the way a config
    reload drops them (``user_api._process_user_entries``)."""
    yield
    from xefm import (actions, filters, image_decoders, lexer_registry,
                      path_schemes, sort_keys)
    from xefm.user_api import hooks
    actions.registry.unregister_source("user")
    hooks.clear()
    sort_keys.clear()
    filters.clear()
    image_decoders.clear()
    path_schemes.unregister_source("user")
    lexer_registry.clear()


@pytest.fixture(autouse=True)
def no_real_trash(monkeypatch):
    """Keep every test away from the developer's own Trash / Recycle Bin.

    ``delete_files`` sends to the system's trash, and on macOS and Windows
    that is the user's real one, not a temp directory. A test that wants the
    trash path patches ``xefm.trash.send`` itself (or drives the freedesktop
    code with its own ``XDG_DATA_HOME``); anything else reaching the real
    platform call fails loudly instead of leaving files in the user's Trash."""
    from xefm import trash

    def refuse(path):
        raise AssertionError(f"a test reached the real {trash.NAME}: {path}")

    monkeypatch.setattr(trash, "_trash_macos", refuse)
    monkeypatch.setattr(trash, "_trash_windows", refuse)

"""Fixtures shared by the whole test suite.

Run with: python -m pytest test/ -v
"""

import pytest


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

    A test that builds an ``XeFMApp`` loads the developer's own
    ``~/.xefm/config.py``, and its ``ACTIONS``, ``EVENT_HOOKS``, ``SORT_KEYS``,
    ``FILTERS``, ``IMAGE_DECODERS`` and ``PATH_SCHEMES`` land in process-wide
    registries. Left there, they reach every later test in the process — the
    key-help test then finds the developer's unbound actions and fails, or not,
    depending on which test happened to run first. Dropped the way a config
    reload drops them (``user_api._process_user_entries``)."""
    yield
    from xefm import actions, filters, image_decoders, path_schemes, sort_keys
    from xefm.user_api import hooks
    actions.registry.unregister_source("user")
    hooks.clear()
    sort_keys.clear()
    filters.clear()
    image_decoders.clear()
    path_schemes.unregister_source("user")

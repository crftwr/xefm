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

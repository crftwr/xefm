"""
Tests for ~/.xefm/extensions/ — importable from config.py, and re-imported on
every config reload.

Run with: python -m pytest test/test_user_extensions_dir.py -v
"""

import os
import sys

import pytest

from xefm.config import ConfigManager
from xefm.path import Path


CONFIG = """\
import xefm_test_ext

class Config:
    FAVORITE_DIRECTORIES = [xefm_test_ext.VALUE]
"""


def make_manager(tmp_path):
    """A ConfigManager whose config tree lives under a temp directory."""
    manager = ConfigManager()
    manager.config_dir = Path(str(tmp_path / '.xefm'))
    manager.config_file = manager.config_dir / 'config.py'
    manager.user_tools_dir = manager.config_dir / 'tools'
    manager.user_extensions_dir = manager.config_dir / 'extensions'
    return manager


@pytest.fixture
def manager(tmp_path):
    saved_path = list(sys.path)
    manager = make_manager(tmp_path)
    yield manager
    sys.path[:] = saved_path
    for name in [n for n in sys.modules if n.split('.')[0] == 'xefm_test_ext']:
        del sys.modules[name]


def write(path, text):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(str(path), 'w', encoding='utf-8') as f:
        f.write(text)


def test_creates_extensions_dir_and_appends_to_sys_path(manager):
    """The directory is created and appended — never ahead of the stdlib"""
    first = sys.path[0]
    manager.prepare_user_extensions()

    resolved = os.path.realpath(str(manager.user_extensions_dir))
    assert os.path.isdir(resolved)
    assert sys.path[-1] == resolved
    assert sys.path[0] == first


def test_not_added_twice(manager):
    """Reloading does not grow sys.path"""
    manager.prepare_user_extensions()
    length = len(sys.path)
    manager.prepare_user_extensions()
    assert len(sys.path) == length


def test_config_dir_itself_stays_off_sys_path(manager):
    """~/.xefm and ~/.xefm/tools are not importable locations"""
    manager.prepare_user_extensions()
    entries = {os.path.realpath(e) for e in sys.path if e}
    assert os.path.realpath(str(manager.config_dir)) not in entries
    assert os.path.realpath(str(manager.user_tools_dir)) not in entries


def test_config_imports_extension_and_reload_picks_up_edit(manager):
    """config.py can import from extensions/, and a reload sees the edit"""
    write(manager.config_file, CONFIG)
    module = manager.user_extensions_dir / 'xefm_test_ext.py'
    write(module, "VALUE = 'first'\n")

    config = manager.load_config()
    assert config.FAVORITE_DIRECTORIES == ['first']

    # Same length, so a same-second .pyc would validate against the old source.
    write(module, "VALUE = 'secnd'\n")
    config = manager.reload_config()
    assert config.FAVORITE_DIRECTORIES == ['secnd']


def test_reload_reimports_package_submodules(manager):
    """A package under extensions/ is evicted as a whole on reload"""
    write(manager.config_file, CONFIG)
    package = manager.user_extensions_dir / 'xefm_test_ext'
    write(package / '__init__.py', "from .inner import VALUE\n")
    write(package / 'inner.py', "VALUE = 'first'\n")

    assert manager.load_config().FAVORITE_DIRECTORIES == ['first']

    write(package / 'inner.py', "VALUE = 'secnd'\n")
    assert manager.reload_config().FAVORITE_DIRECTORIES == ['secnd']

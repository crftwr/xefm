"""
Tests for the first-launch creation of ~/.xefm/tools/ with the example tool.

Run with: python -m pytest test/test_user_tools_dir.py -v
"""

import os
import subprocess
import sys

import xefm.config
from xefm.config import ConfigManager
from xefm.path import Path


BUNDLED_EXAMPLE = os.path.join(
    os.path.dirname(xefm.config.__file__), 'tools', 'example_tool.py')


def make_manager(tmp_path):
    """A ConfigManager whose config tree lives under a temp directory."""
    manager = ConfigManager()
    manager.config_dir = Path(str(tmp_path / '.xefm'))
    manager.config_file = manager.config_dir / 'config.py'
    manager.user_tools_dir = manager.config_dir / 'tools'
    return manager


def test_creates_tools_dir_with_example(tmp_path):
    """First run creates ~/.xefm/tools/ containing a copy of the example"""
    manager = make_manager(tmp_path)

    assert manager.ensure_user_tools_dir() is True
    assert manager.user_tools_dir.exists()

    example = manager.user_tools_dir / 'example_tool.py'
    assert example.exists()

    with open(str(example), 'r', encoding='utf-8') as f:
        copied = f.read()
    with open(BUNDLED_EXAMPLE, 'r', encoding='utf-8') as f:
        bundled = f.read()
    assert copied == bundled


def test_existing_dir_left_alone(tmp_path):
    """A pre-existing tools directory is never touched"""
    manager = make_manager(tmp_path)
    manager.user_tools_dir.mkdir(parents=True)

    assert manager.ensure_user_tools_dir() is False
    assert not (manager.user_tools_dir / 'example_tool.py').exists()


def test_deleted_example_not_resurrected(tmp_path):
    """Deleting the example keeps it deleted on subsequent runs"""
    manager = make_manager(tmp_path)
    manager.ensure_user_tools_dir()

    example = manager.user_tools_dir / 'example_tool.py'
    os.remove(str(example))

    assert manager.ensure_user_tools_dir() is False
    assert not example.exists()


def test_example_tool_runs(tmp_path):
    """The example runs standalone and reports the XeFM environment"""
    env = os.environ.copy()
    env['XEFM_THIS_DIR'] = str(tmp_path)
    env['XEFM_THIS_SELECTED'] = '"file one.txt" "file2.txt"'
    env['XEFM_OTHER_DIR'] = str(tmp_path)
    env['XEFM_ACTIVE'] = '1'

    result = subprocess.run(
        [sys.executable, BUNDLED_EXAMPLE],
        env=env, capture_output=True, text=True, timeout=30)

    assert result.returncode == 0
    assert str(tmp_path) in result.stdout
    assert '2 file(s)' in result.stdout
    assert os.path.join(str(tmp_path), 'file one.txt') in result.stdout

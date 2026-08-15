#!/usr/bin/env python3
"""
SSH directory listings go through ``listdir_attrs``.

A pane reads a directory with :meth:`Path.listdir_attrs`, which every backend
must answer. ``SSHPathImpl`` used to stand outside the ``PathImpl`` hierarchy, so
it simply had no such method and every SSH pane failed with "'SSHPathImpl' object
has no attribute 'listdir_attrs'". These tests pin both halves of the fix: the
class is a ``PathImpl``, and it answers the listing from the single ``ls -la``
the connection already ran.
"""

import unittest
from unittest.mock import patch

from xefm.path import Path, PathImpl
from xefm.ssh import SSHPathImpl


def _entry(name, *, size=0, mtime=0.0, is_dir=False, is_symlink=False):
    """One record shaped like SSHConnection.list_directory returns."""
    return {'name': name, 'size': size, 'mtime': mtime, 'mode': 0o644,
            'is_dir': is_dir, 'is_file': not (is_dir or is_symlink),
            'is_symlink': is_symlink}


class FakeConnection:
    """Answers list_directory from a fixed table, counting the calls."""

    def __init__(self, entries):
        self.entries = entries
        self.calls = []

    def list_directory(self, remote_path):
        self.calls.append(remote_path)
        return self.entries

    def stat(self, remote_path):
        raise AssertionError(
            f"listdir_attrs must not stat entries one by one ({remote_path})")


class TestSSHListdirAttrs(unittest.TestCase):

    def setUp(self):
        self.entries = [
            _entry('docs', size=4096, mtime=100.0, is_dir=True),
            _entry('notes.txt', size=12, mtime=200.0),
            _entry('current', size=7, mtime=300.0, is_symlink=True),
        ]
        self.conn = FakeConnection(self.entries)

        # A real SSHPathImpl, minus the config parse and the connection.
        patcher = patch('xefm.ssh_config.SSHConfigParser')
        self.addCleanup(patcher.stop)
        patcher.start()
        self.path = Path('ssh://test-host/home/user')
        self.impl = self.path._impl
        self.impl._get_connection = lambda: self.conn

    def test_ssh_path_impl_is_a_path_impl(self):
        """Inheritance is what keeps a new interface method from being missed"""
        self.assertIsInstance(self.impl, PathImpl)

    def test_listing_reaches_the_impl_through_path(self):
        """The pane calls Path.listdir_attrs — it must not raise here"""
        names = [child.name for child, _ in self.path.listdir_attrs()]
        self.assertEqual(names, ['docs', 'notes.txt', 'current'])

    def test_entries_are_ssh_paths_under_this_directory(self):
        children = [str(child) for child, _ in self.impl.listdir_attrs()]
        self.assertEqual(children, [
            'ssh://test-host/home/user/docs',
            'ssh://test-host/home/user/notes.txt',
            'ssh://test-host/home/user/current',
        ])

    def test_attributes_match_the_dir_scan_record(self):
        attrs = {child.name: a for child, a in self.impl.listdir_attrs()}

        # 'hidden' is the platform attribute, which a remote host has no way to
        # report here — a dot in the name is the whole of hidden over SSH.
        self.assertEqual(attrs['docs'],
                         {'is_dir': True, 'is_link': False, 'size': 0,
                          'mtime': 100.0, 'hidden': False, 'ok': True})
        self.assertEqual(attrs['notes.txt'],
                         {'is_dir': False, 'is_link': False, 'size': 12,
                          'mtime': 200.0, 'hidden': False, 'ok': True})
        self.assertEqual(attrs['current'],
                         {'is_dir': False, 'is_link': True, 'size': 7,
                          'mtime': 300.0, 'hidden': False, 'ok': True})

    def test_whole_listing_costs_one_remote_call(self):
        """The point of the method: no per-entry round trip over the link"""
        self.impl.listdir_attrs()
        self.assertEqual(self.conn.calls, ['/home/user'])

    def test_empty_directory(self):
        self.conn.entries = []
        self.assertEqual(self.impl.listdir_attrs(), [])

    def test_root_directory_entries_are_not_double_slashed(self):
        root = Path('ssh://test-host/')
        root._impl._get_connection = lambda: self.conn
        children = [str(child) for child, _ in root._impl.listdir_attrs()]
        self.assertEqual(children[0], 'ssh://test-host/docs')

    def test_iterdir_still_lists_the_same_entries(self):
        self.assertEqual([child.name for child in self.impl.iterdir()],
                         ['docs', 'notes.txt', 'current'])


if __name__ == '__main__':
    unittest.main()

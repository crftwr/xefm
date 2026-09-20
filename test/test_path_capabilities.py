"""What a storage backend *is*, as a declaration rather than twelve methods.

The matrix below (discussion #426 §5) used to be spread over four classes as
twelve one-line method overrides each. It is compile-time constant for every
backend XeFM ships, so it is now five class attributes on :class:`PathImpl`,
read back through :meth:`Path.supports` and :attr:`PathImpl.SEARCH_STRATEGY`.

The point of testing it here rather than per backend is that the interesting
content is the *differences* between columns — S3 can be written to but its
directories cannot be renamed; SSH's can; an archive is read-only whatever it
sits on. A single table keeps those differences where they can be compared.

Run with: python -m pytest test/test_path_capabilities.py -v
"""

import unittest
from unittest.mock import Mock

from xefm.path import (KNOWN_CAPABILITIES, SEARCH_STRATEGIES, LocalPathImpl,
                       Path, PathImpl)


#: scheme -> (capabilities, search strategy, display prefix, is_remote)
MATRIX = {
    'file': (
        {'write_operations', 'directory_rename', 'file_editing',
         'streaming_read'},
        'streaming', '', False),
    's3': (
        {'write_operations', 'extraction_for_reading', 'cache_for_search'},
        'buffered', 'S3: ', True),
    'ssh': (
        {'write_operations', 'directory_rename', 'extraction_for_reading',
         'cache_for_search'},
        'buffered', 'SSH: ', True),
    'archive': (
        {'extraction_for_reading', 'cache_for_search'},
        'extracted', 'ARCHIVE: ', None),   # None: varies per path, see below
}


def _impls():
    """The four shipped implementations, by scheme, imported lazily so that a
    missing optional dependency fails this module rather than importing it at
    collection time."""
    from xefm.archive import ArchivePathImpl
    from xefm.s3 import S3PathImpl
    from xefm.ssh import SSHPathImpl
    return {'file': LocalPathImpl, 's3': S3PathImpl, 'ssh': SSHPathImpl,
            'archive': ArchivePathImpl}


class TestDeclaredCapabilities(unittest.TestCase):
    """Every shipped backend declares the row #426 §5 measured for it."""

    def test_matrix(self):
        for scheme, cls in _impls().items():
            caps, strategy, prefix, remote = MATRIX[scheme]
            with self.subTest(scheme=scheme):
                self.assertEqual(cls.SCHEME, scheme)
                self.assertEqual(set(cls.CAPABILITIES), caps)
                self.assertEqual(cls.SEARCH_STRATEGY, strategy)
                self.assertEqual(cls.DISPLAY_PREFIX, prefix)
                if remote is not None:
                    self.assertEqual(cls.IS_REMOTE, remote)

    def test_every_implementation_names_its_scheme(self):
        """``get_scheme`` reads ``SCHEME``, and file operations compare two
        paths' schemes to decide whether a move can be a rename. A backend that
        left the attribute at its empty default would compare equal to every
        other such backend, so the emptiness has to be caught here — the ABC
        cannot catch it, because a class attribute is not an abstract method."""
        for scheme, cls in _impls().items():
            with self.subTest(scheme=scheme):
                self.assertTrue(cls.SCHEME, f"{cls.__name__} declares no SCHEME")

    def test_search_strategies_are_from_the_vocabulary(self):
        for scheme, cls in _impls().items():
            with self.subTest(scheme=scheme):
                self.assertIn(cls.SEARCH_STRATEGY, SEARCH_STRATEGIES)

    def test_supports_reads_the_declaration(self):
        local = Path('/tmp/test-directory')
        self.assertTrue(local.supports('directory_rename'))
        self.assertTrue(local.supports('write_operations'))
        self.assertFalse(local.supports('extraction_for_reading'))

        s3 = Path('s3://test-bucket/test-directory/')
        self.assertFalse(s3.supports('directory_rename'))
        self.assertTrue(s3.supports('write_operations'))

    def test_an_unknown_capability_is_absent_not_an_error(self):
        """A caller written against a later vocabulary asks a question this
        version has never heard of, and gets ``False`` rather than a crash."""
        self.assertFalse(Path('/tmp/test').supports('time_travel'))
        self.assertFalse(Path('s3://bucket/key').supports(''))

    def test_scheme_and_remoteness_come_back_through_the_methods(self):
        self.assertEqual(Path('/tmp/test').get_scheme(), 'file')
        self.assertFalse(Path('/tmp/test').is_remote())
        s3 = Path('s3://bucket/key')
        self.assertEqual(s3.get_scheme(), 's3')
        self.assertTrue(s3.is_remote())

    def test_archive_still_decides_remoteness_per_path(self):
        """The one answer in the group that is not a constant: an archive on
        disk is local, the same archive on S3 is not. It stays a method."""
        from xefm.archive import ArchivePathImpl
        self.assertIn('is_remote', vars(ArchivePathImpl))


class TestDeclarationValidation(unittest.TestCase):
    """``__init_subclass__`` warns and ignores, the way ``EVENT_HOOKS`` does."""

    def test_unknown_capability_names_are_dropped(self):
        class Weird(LocalPathImpl):
            CAPABILITIES = frozenset({'write_operations', 'teleportation'})

        self.assertEqual(set(Weird.CAPABILITIES), {'write_operations'})
        self.assertFalse(Weird(Mock()).supports('teleportation'))

    def test_an_unknown_search_strategy_falls_back(self):
        class Weird(LocalPathImpl):
            SEARCH_STRATEGY = 'telepathy'

        self.assertEqual(Weird.SEARCH_STRATEGY, PathImpl.SEARCH_STRATEGY)

    def test_a_plain_set_is_accepted_and_frozen(self):
        """A config writes ``CAPABILITIES = {"streaming_read"}``; nobody should
        have to remember ``frozenset``."""
        class Plain(LocalPathImpl):
            CAPABILITIES = {'streaming_read'}

        self.assertIsInstance(Plain.CAPABILITIES, frozenset)
        self.assertTrue(Plain(Mock()).supports('streaming_read'))

    def test_declaring_nothing_is_the_conservative_answer(self):
        """A backend that says nothing is treated as read-only and
        unstreamable — never as capable of something it never claimed."""
        class Silent(LocalPathImpl):
            CAPABILITIES = frozenset()

        for name in KNOWN_CAPABILITIES:
            with self.subTest(capability=name):
                self.assertFalse(Silent(Mock()).supports(name))


class TestTheSurfaceThatWasPublished(unittest.TestCase):
    """The ten methods #426 §5 found to have no caller are gone from the
    façade. Re-adding one means finding a caller for it first."""

    RETIRED = ('supports_directory_rename', 'supports_file_editing',
               'supports_write_operations', 'requires_extraction_for_reading',
               'supports_streaming_read', 'should_cache_for_search',
               'get_search_strategy', 'get_display_prefix')

    def test_retired_methods_are_gone(self):
        for name in self.RETIRED:
            with self.subTest(method=name):
                self.assertFalse(hasattr(Path, name))
                self.assertFalse(hasattr(PathImpl, name))

    def test_the_two_computed_ones_kept_defaults_instead(self):
        """``get_display_title`` and ``get_extended_metadata`` compute
        something per instance, so they stay methods — but with a default, so
        an outside implementation is not asked a question nothing reads."""
        for name in ('get_display_title', 'get_extended_metadata'):
            with self.subTest(method=name):
                method = getattr(PathImpl, name)
                self.assertNotIn(name, PathImpl.__abstractmethods__)
                self.assertFalse(getattr(method, '__isabstractmethod__', False))

    def test_the_default_title_is_the_path_itself(self):
        self.assertEqual(Path('s3://bucket/key').get_display_title(),
                         's3://bucket/key')


if __name__ == '__main__':
    unittest.main(verbosity=2)

"""One list of schemes, and the four places that used to keep their own (#426 §1).

`Path` picks a backend from a URI's scheme, and that decision lived in four
places that had to agree: the guard in `Path.__init__`, the if-chain in
`Path._create_implementation`, `XeFMApp._REMOTE_SCHEMES` and
`config._REMOTE_SCHEMES`. #413's monkeypatch found all of them the hard way —
patch only the first two and Jump to Path treats the new URI as a path relative
to the current directory and reports "Path does not exist".

So the test that matters here is not that registration works. It is that
registering *once* is enough: `TestOneRegistrationReachesEverything` walks the
same four call sites with a scheme invented in the test.

Run with: python -m pytest test/test_path_schemes.py -v
"""

import io
import os
import subprocess
import sys
import textwrap
import unittest
from unittest.mock import patch

from xefm import config, path_schemes
from xefm.path import LocalPathImpl, Path
from xefm.path_base import ReadOnlyPathImpl, UriStatResult


class DemoPathImpl(ReadOnlyPathImpl):
    """A backend invented here, to stand in for #413's registry browser."""

    SCHEME = 'demo'

    def exists(self): return True
    def is_dir(self): return not self.name.endswith('.txt')
    def iterdir(self): yield self._child('leaf.txt')
    def stat(self): return UriStatResult(size=1, mtime=1.0, is_dir=self.is_dir())
    def open(self, mode='r', **kwargs): return io.StringIO('demo')


class ShadowS3PathImpl(DemoPathImpl):
    """A stand-in for a config that replaces a built-in backend on purpose."""

    SCHEME = 's3'


class SchemeFixture(unittest.TestCase):
    """Register ``demo://`` for one test and take it back out again."""

    def setUp(self):
        path_schemes.register('demo', DemoPathImpl, source='test')
        self.addCleanup(path_schemes.unregister_source, 'test')


class TestOneRegistrationReachesEverything(SchemeFixture):
    """The four call sites of #426 §1, walked with one registration."""

    def test_the_uri_survives_construction(self):
        """``Path.__init__``'s guard. Without it ``PathlibPath`` collapses
        ``demo://`` to ``demo:/`` and the URI is gone before any backend sees
        it."""
        self.assertEqual(str(Path('demo://root/leaf.txt')), 'demo://root/leaf.txt')

    def test_the_factory_builds_the_registered_class(self):
        self.assertIsInstance(Path('demo://root')._impl, DemoPathImpl)

    def test_the_app_treats_it_as_remote(self):
        """``XeFMApp._REMOTE_SCHEMES``. A subshell or terminal editor must
        refuse a path it cannot ``cd`` into."""
        from xefm import app as xefm_app
        self.assertFalse(xefm_app.XeFMApp._is_local('demo://root'))
        self.assertTrue(xefm_app.XeFMApp._is_local('/tmp/x'))

    def test_jump_to_path_resolves_it_as_a_uri(self):
        """The one #413's monkeypatch missed: a URI resolved against the pane's
        current directory comes back as a relative local path, and Jump to Path
        reports it missing. Accurately."""
        from xefm import app as xefm_app
        target = xefm_app.XeFMApp._resolve_jump_target('demo://root/leaf.txt',
                                                       current='/home/user')
        self.assertEqual(str(target), 'demo://root/leaf.txt')
        self.assertIsInstance(target._impl, DemoPathImpl)

    def test_favorites_pass_it_through_unprobed(self):
        """``config._REMOTE_SCHEMES``. The picker lists a remote row exactly as
        configured — probing it would be a round trip on the UI thread."""
        class FakeConfig:
            FAVORITE_DIRECTORIES = [{'name': 'Demo', 'path': 'demo://root'}]

        with patch.object(config, 'get_config', return_value=FakeConfig()):
            rows = config.get_favorite_directories()
        self.assertEqual(rows, [{'name': 'Demo', 'path': 'demo://root'}])


class TestRegistry(SchemeFixture):

    def test_prefixes_and_schemes(self):
        self.assertIn('demo://', path_schemes.prefixes())
        self.assertEqual(path_schemes.schemes(source='test'), ['demo'])
        self.assertTrue(path_schemes.is_uri('demo://x'))
        self.assertFalse(path_schemes.is_uri('/tmp/x'))
        self.assertEqual(path_schemes.scheme_of('demo://x'), 'demo')
        self.assertIsNone(path_schemes.scheme_of('/tmp/x'))
        self.assertIsNone(path_schemes.scheme_of('nope://x'))

    def test_unregistering_a_source_leaves_the_builtins(self):
        path_schemes.unregister_source('test')
        self.assertNotIn('demo://', path_schemes.prefixes())
        self.assertFalse(path_schemes.is_uri('demo://x'))
        for scheme in ('archive', 's3', 'ssh'):
            self.assertIn(scheme, path_schemes.schemes())

    def test_a_shadowed_builtin_comes_back_when_the_source_goes(self):
        """Overriding ``s3://`` and then reloading the config must give
        ``s3://`` back, not take it away."""
        builtin = path_schemes.create('s3://bucket/key')
        path_schemes.register('s3', ShadowS3PathImpl, source='test')
        self.assertIsInstance(Path('s3://bucket/key')._impl, ShadowS3PathImpl)

        path_schemes.unregister_source('test')
        self.assertIn('s3://', path_schemes.prefixes())
        self.assertEqual(type(Path('s3://bucket/key')._impl), type(builtin))

    def test_reloading_the_same_source_does_not_stack(self):
        """A reload registers over itself; what is uncovered afterwards is
        still the built-in, not the previous reload's class."""
        for _ in range(3):
            path_schemes.register('s3', ShadowS3PathImpl, source='test')
        path_schemes.unregister_source('test')
        self.assertEqual(type(Path('s3://bucket/key')._impl).__name__,
                         'S3PathImpl')

    def test_an_unclaimed_path_falls_back_to_local(self):
        self.assertIsNone(path_schemes.create('/tmp/x'))
        self.assertIsInstance(Path('/tmp/x')._impl, LocalPathImpl)

    def test_scheme_validation(self):
        self.assertIsNone(path_schemes.validate_scheme('reg'))
        self.assertIsNone(path_schemes.validate_scheme('ms-appx'))
        self.assertIsNone(path_schemes.validate_scheme('a+b.c-d'))
        for bad in ('', 'REG', 'reg://', '1reg', 'reg/x', 'reg x', None, 7):
            with self.subTest(scheme=bad):
                self.assertIsNotNone(path_schemes.validate_scheme(bad))

    def test_register_refuses_an_invalid_scheme(self):
        with self.assertRaises(ValueError):
            path_schemes.register('Bad Scheme', DemoPathImpl, source='test')

    def test_backends_are_imported_only_when_asked_for(self):
        """Listing the schemes is what the favourites picker does to decide
        whether a row needs probing, so it must not cost an ``import boto3``.

        In a subprocess, because the check is about what a *fresh* interpreter
        has loaded, and every other test in this run has already imported
        plenty."""
        probe = textwrap.dedent("""
            import sys
            from xefm import path_schemes
            path_schemes.prefixes(); path_schemes.schemes()
            path_schemes.is_uri('s3://bucket/key')
            assert 'xefm.s3' not in sys.modules, 'listing schemes imported the S3 backend'
            from xefm.path import Path
            Path('s3://bucket/key')
            assert 'xefm.s3' in sys.modules, 'building an s3:// path did not'
            print('ok')
        """)
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        done = subprocess.run([sys.executable, '-c', probe], cwd=root,
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)


class TestTheBuiltins(unittest.TestCase):

    def test_every_shipped_scheme_builds_its_own_backend(self):
        for uri, name in (('archive:///a.zip#x', 'ArchivePathImpl'),
                          ('s3://bucket/key', 'S3PathImpl'),
                          ('ssh://host/path', 'SSHPathImpl')):
            with self.subTest(uri=uri):
                self.assertEqual(type(Path(uri)._impl).__name__, name)


class TestSchemesWithNoBackend(unittest.TestCase):
    """#426 §1's second small finding: ``scp://`` and ``ftp://`` were in every
    list of remote schemes and in none of the factory's branches."""

    def test_the_uri_is_no_longer_silently_a_local_path(self):
        """It used to become ``PathlibPath('ftp:/h/p')`` — the ``//``
        collapsed, the scheme reported as ``file``, and a report about a path
        the user never typed."""
        p = Path('ftp://host/some/path')
        self.assertEqual(str(p), 'ftp://host/some/path')
        self.assertEqual(p.get_scheme(), 'ftp')
        self.assertTrue(p.is_remote())

    def test_reading_one_says_what_is_actually_wrong(self):
        with self.assertRaises(OSError) as caught:
            list(Path('scp://host/path').iterdir())
        self.assertIn('scp://', str(caught.exception))
        self.assertIn('not supported', str(caught.exception))

    def test_they_are_still_recognised_as_remote(self):
        """A subshell must keep refusing them, which is what having them in the
        list bought in the first place."""
        from xefm import app as xefm_app
        for uri in ('scp://h/p', 'ftp://h/p'):
            with self.subTest(uri=uri):
                self.assertFalse(xefm_app.XeFMApp._is_local(uri))
                self.assertTrue(path_schemes.is_uri(uri))

    def test_a_missing_one_probes_as_missing_rather_than_raising(self):
        self.assertFalse(Path('ftp://host/path').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)

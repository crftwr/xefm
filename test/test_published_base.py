"""The published base classes, and the promise they exist to keep (#426 §2–§4).

Two things are tested here, and the second matters more than the first.

The first is that :class:`~xefm.path_base.UriPathImpl` gets the string
arithmetic right — ``parent``, ``joinpath``, ``parts``, behaviour at the root.

The second is :class:`TestTheCompatibilityBuffer`. ``PathImpl`` grows: nine
methods were added between v0.98 and v1.0.4. The failure mode for a backend
defined in a user's ``config.py`` is not a changed signature — no signature has
ever changed — it is a *new* ``@abstractmethod``, which makes every external
subclass raise ``TypeError`` at import and takes the user's whole config down
with it. ``ReadOnlyPathImpl`` is the buffer: a method that arrives carrying a
default there is invisible outside. The test below fails the moment one arrives
without a default, so the rule does not depend on anyone remembering it.

Run with: python -m pytest test/test_published_base.py -v
"""

import errno
import io
import unittest

from xefm.path import Path, PathImpl
from xefm.path_base import ReadOnlyPathImpl, UriPathImpl, UriStatResult


#: What a backend written against ``ReadOnlyPathImpl`` is asked for. Changing
#: this set is a breaking change for every config that defines a virtual
#: folder, so it is spelled out rather than computed.
THE_FIVE = frozenset({'exists', 'is_dir', 'iterdir', 'stat', 'open'})


class Sample(ReadOnlyPathImpl):
    """A minimal read-only backend: one directory holding one file."""

    SCHEME = 'sample'

    def exists(self):
        return self._key in ('', 'dir', 'dir/a.tar.gz')

    def is_dir(self):
        return self._key in ('', 'dir')

    def iterdir(self):
        if self._key == '':
            yield self._child('dir')
        elif self._key == 'dir':
            yield self._child('a.tar.gz')

    def stat(self):
        return UriStatResult(size=3, mtime=1.0, is_dir=self.is_dir())

    def open(self, mode='r', buffering=-1, encoding=None, errors=None,
             newline=None):
        return io.StringIO('abc')


class Bucketed(UriPathImpl):
    """A backend whose root names a container, to exercise both hooks — the
    shape ``S3PathImpl`` has."""

    SCHEME = 'buck'

    def _parse(self, uri):
        rest = uri[len('buck://'):]
        self._bucket, _, key = rest.partition('/')
        return key

    def _root_prefix(self):
        return f'buck://{self._bucket}/'

    def exists(self): return True
    def is_dir(self): return not self.name
    def iterdir(self): return iter(())
    def stat(self): return UriStatResult()
    def open(self, mode='r', **kwargs): return io.StringIO('')
    def mkdir(self, mode=0o777, parents=False, exist_ok=False): pass
    def rmdir(self): pass
    def unlink(self, missing_ok=False): pass
    def rename(self, target): return target
    def replace(self, target): return target
    def symlink_to(self, target, target_is_directory=False): pass
    def hardlink_to(self, target): pass
    def touch(self, mode=0o666, exist_ok=True): pass
    def chmod(self, mode): pass


class TestTheCompatibilityBuffer(unittest.TestCase):
    """#426 §4: the intermediate class is the compatibility buffer."""

    def test_the_published_base_asks_for_exactly_five_methods(self):
        """If this fails with something *added*, a new ``@abstractmethod``
        reached ``PathImpl`` without a default in ``ReadOnlyPathImpl`` — and
        every virtual folder defined in a user's config now raises
        ``TypeError`` at import. Give it a default here, do not widen the set.
        """
        self.assertEqual(set(ReadOnlyPathImpl.__abstractmethods__), set(THE_FIVE))

    def test_a_writable_backend_is_asked_for_those_five_plus_the_writes(self):
        extra = set(UriPathImpl.__abstractmethods__) - THE_FIVE
        self.assertEqual(extra, {'mkdir', 'rmdir', 'unlink', 'rename', 'replace',
                                 'symlink_to', 'hardlink_to', 'touch', 'chmod'})

    def test_the_strict_abc_is_still_strict(self):
        """``PathImpl`` itself keeps its abstract methods, so a backend *inside*
        this repository that forgets one still fails at import. Leniency lives
        in the published subclass, not in the interface."""
        self.assertGreater(len(PathImpl.__abstractmethods__), 40)

    def test_a_five_method_subclass_instantiates(self):
        self.assertEqual(str(Sample('sample://dir')), 'sample://dir')


class TestArithmetic(unittest.TestCase):
    """The 27 methods #426 §3 found to be the same operation everywhere."""

    def test_the_invariant(self):
        p = Sample('sample://dir/a.tar.gz')
        self.assertEqual(str(p), p._root_prefix() + p._key)

    def test_name_components(self):
        p = Sample('sample://dir/a.tar.gz')
        self.assertEqual(p.name, 'a.tar.gz')
        self.assertEqual(p.stem, 'a.tar')
        self.assertEqual(p.suffix, '.gz')
        self.assertEqual(p.suffixes, ['.tar', '.gz'])

    def test_parts_and_anchor(self):
        p = Sample('sample://dir/a.tar.gz')
        self.assertEqual(p.parts, ('sample://', 'dir', 'a.tar.gz'))
        self.assertEqual(p.anchor, 'sample://')

    def test_parent_and_parents(self):
        p = Sample('sample://dir/a.tar.gz')
        self.assertEqual(str(p.parent), 'sample://dir')
        self.assertEqual([str(a) for a in p.parents],
                         ['sample://dir', 'sample://'])

    def test_the_root_is_its_own_parent(self):
        """As ``pathlib`` makes ``/`` its own parent. Without this the
        ``parents`` walk would not terminate."""
        root = Sample('sample://')
        self.assertEqual(str(root.parent), 'sample://')
        self.assertEqual(root.name, '')
        self.assertEqual(root.parents, [])

    def test_joinpath_and_with_name(self):
        p = Sample('sample://dir')
        self.assertEqual(str(p.joinpath('x', 'y')), 'sample://dir/x/y')
        self.assertEqual(str(Path._from_impl(p) / 'x'), 'sample://dir/x')
        q = Sample('sample://dir/a.tar.gz')
        self.assertEqual(str(q.with_name('b.txt')), 'sample://dir/b.txt')
        self.assertEqual(str(q.with_suffix('.bz2')), 'sample://dir/a.tar.bz2')
        self.assertEqual(str(q.with_stem('b')), 'sample://dir/b.gz')

    def test_relative_to(self):
        p = Sample('sample://dir/a.tar.gz')
        self.assertEqual(str(p.relative_to('sample://dir')), 'a.tar.gz')
        with self.assertRaises(ValueError):
            p.relative_to('sample://other')

    def test_keys_are_normalised(self):
        for written, expected in (('sample:///dir//a', 'sample://dir/a'),
                                  ('sample://dir/./a', 'sample://dir/a'),
                                  ('sample://dir/a/', 'sample://dir/a')):
            with self.subTest(written=written):
                self.assertEqual(str(Sample(written)), expected)

    def test_arithmetic_keeps_the_class_that_produced_it(self):
        """The reason ``_at`` does not call ``Path(uri)``: a scheme the factory
        has never heard of would come back as a local path, so a virtual
        folder's own ``parent`` would leave the virtual folder."""
        parent = Sample('sample://dir/a.tar.gz').parent
        self.assertIsInstance(parent, Path)
        self.assertIsInstance(parent._impl, Sample)

    def test_listing_and_globbing(self):
        root = Sample('sample://')
        self.assertEqual([str(c) for c in root.iterdir()], ['sample://dir'])
        self.assertEqual([str(c) for c in root.rglob('*.gz')],
                         ['sample://dir/a.tar.gz'])
        self.assertEqual([str(c) for c in Sample('sample://dir').glob('*.gz')],
                         ['sample://dir/a.tar.gz'])
        self.assertTrue(Sample('sample://dir/a.tar.gz').match('*.gz'))

    def test_derived_io(self):
        p = Sample('sample://dir/a.tar.gz')
        self.assertTrue(p.is_file())
        self.assertFalse(p.is_symlink())
        self.assertEqual(p.read_text(), 'abc')
        self.assertEqual(p.lstat().st_size, p.stat().st_size)
        self.assertTrue(p.is_absolute())
        self.assertEqual(str(p.absolute()), str(p))
        self.assertEqual(p.as_uri(), 'sample://dir/a.tar.gz')
        self.assertTrue(p.samefile('sample://dir/a.tar.gz'))


class TestTheTwoHooks(unittest.TestCase):
    """#426 §3: two hooks cover the prefix spelling and the key convention."""

    def test_a_container_in_the_root_round_trips(self):
        p = Bucketed('buck://mybucket/some/key')
        self.assertEqual(str(p), 'buck://mybucket/some/key')
        self.assertEqual(p.anchor, 'buck://mybucket/')
        self.assertEqual(p.parts, ('buck://mybucket/', 'some', 'key'))
        self.assertEqual(str(p.parent), 'buck://mybucket/some')
        self.assertEqual(str(p.parent.parent), 'buck://mybucket/')
        self.assertEqual([str(a) for a in p.parents],
                         ['buck://mybucket/some', 'buck://mybucket/'])

    def test_a_wrong_scheme_is_rejected_by_the_default_parse(self):
        with self.assertRaises(ValueError):
            Sample('elpmas://dir')


class TestReadOnlyPolicy(unittest.TestCase):
    """#426 §3: the write group is shared policy, not shared code."""

    WRITES = ('mkdir', 'rmdir', 'unlink', 'rename', 'replace', 'symlink_to',
              'hardlink_to', 'touch', 'chmod', 'write_text', 'write_bytes')

    def test_every_write_refuses_with_erofs(self):
        p = Sample('sample://dir/a.tar.gz')
        for name in self.WRITES:
            with self.subTest(operation=name):
                with self.assertRaises(OSError) as caught:
                    getattr(p, name)(*self._args_for(name))
                self.assertEqual(caught.exception.errno, errno.EROFS)

    @staticmethod
    def _args_for(name):
        return {'rename': ('sample://x',), 'replace': ('sample://x',),
                'symlink_to': ('sample://x',), 'hardlink_to': ('sample://x',),
                'chmod': (0o644,), 'write_text': ('x',),
                'write_bytes': (b'x',)}.get(name, ())

    def test_the_refusal_says_which_backend(self):
        with self.assertRaises(OSError) as caught:
            Sample('sample://dir').unlink()
        self.assertIn('sample://', str(caught.exception))

    def test_a_backend_can_word_its_own_refusal(self):
        class Worded(Sample):
            READ_ONLY_MESSAGE = 'the registry is edited with regedit'

        with self.assertRaises(OSError) as caught:
            Worded('sample://dir').unlink()
        self.assertIn('regedit', str(caught.exception))

    def test_read_only_declares_no_write_capability(self):
        p = Sample('sample://dir')
        self.assertFalse(p.supports('write_operations'))
        self.assertFalse(p.supports('directory_rename'))
        self.assertFalse(p.supports('file_editing'))
        self.assertTrue(p.supports('extraction_for_reading'))

    def test_the_split_leaves_arithmetic_usable_by_a_writable_backend(self):
        """``UriPathImpl`` is not read-only-specific — that is why it is a
        separate class from ``ReadOnlyPathImpl``. A backend that inherits only
        the arithmetic keeps its own write behaviour; nothing refuses for it."""
        Bucketed('buck://b/k').unlink()          # no raise


if __name__ == '__main__':
    unittest.main(verbosity=2)

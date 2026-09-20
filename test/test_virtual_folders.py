"""``PATH_SCHEMES``: a browsable location defined in a config (#426 ①b, #413).

The ask behind this is someone who wants to browse the Windows registry in a
pane, read-only, with the editing handed off to regedit. The promise is that
they write a class and name it, and every part of XeFM that deals in locations
follows — the pane, Jump to Path, the favourites picker, the subshell guard.

What is tested here is mostly the *refusals*, because a config is edited by
hand and a bad entry must cost that entry and nothing else: a malformed
``PATH_SCHEMES`` is a warning per entry, never a load failure, exactly as
``ACTIONS`` and ``FILTERS`` already are.

Run with: python -m pytest test/test_virtual_folders.py -v
"""

import io
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import path_schemes, user_api  # noqa: E402
from xefm._config import Config as DefaultConfig  # noqa: E402
from xefm.path import Path, PathImpl  # noqa: E402
from xefm.path_base import ReadOnlyPathImpl, UriStatResult  # noqa: E402


TREE = {'': ['HKEY_CURRENT_USER'],
        'HKEY_CURRENT_USER': ['Software', 'Console'],
        'HKEY_CURRENT_USER/Software': [],
        'HKEY_CURRENT_USER/Console': []}


class RegistryPathImpl(ReadOnlyPathImpl):
    """#413's ask, written the way the docs say to write it."""

    READ_ONLY_MESSAGE = 'the registry is edited with regedit'

    def exists(self):
        return self._key in TREE

    def is_dir(self):
        return self._key in TREE

    def iterdir(self):
        for name in TREE.get(self._key, []):
            yield self._child(name)

    def stat(self):
        return UriStatResult(is_dir=self.is_dir())

    def open(self, mode='r', buffering=-1, encoding=None, errors=None,
             newline=None):
        return io.StringIO('')


class Incomplete(ReadOnlyPathImpl):
    """Missing ``open`` and ``stat`` — the mistake a half-written class makes."""

    SCHEME = 'incomplete'

    def exists(self): return True
    def is_dir(self): return True
    def iterdir(self): return iter(())


def config_with(**attrs):
    cfg = DefaultConfig()
    for name, value in attrs.items():
        setattr(cfg, name, value)
    return cfg


@pytest.fixture
def clean_schemes():
    RegistryPathImpl.SCHEME = ''     # as written in a config, before loading
    yield
    path_schemes.unregister_source('user')
    RegistryPathImpl.SCHEME = ''


def load(**attrs):
    """``(warnings, path_scheme_count)`` for one config."""
    result = user_api.load_user_entries(config_with(**attrs))
    return result[0], result[5]


# --------------------------------------------------------------------------- #
# The thing itself
# --------------------------------------------------------------------------- #

def test_a_registered_scheme_is_browsable(clean_schemes):
    warnings, count = load(PATH_SCHEMES={'reg': RegistryPathImpl})
    assert warnings == []
    assert count == 1

    root = Path('reg://')
    assert isinstance(root._impl, RegistryPathImpl)
    assert [str(c) for c in root.iterdir()] == ['reg://HKEY_CURRENT_USER']

    branch = Path('reg://HKEY_CURRENT_USER')
    assert sorted(str(c) for c in branch.iterdir()) == [
        'reg://HKEY_CURRENT_USER/Console', 'reg://HKEY_CURRENT_USER/Software']
    assert str(branch.parent) == 'reg://'
    assert branch.get_scheme() == 'reg'
    assert branch.is_remote()


def test_jump_to_path_and_the_subshell_guard_follow(clean_schemes):
    """The three call sites beyond the factory — registering once is enough."""
    load(PATH_SCHEMES={'reg': RegistryPathImpl})
    from xefm import app as xefm_app

    target = xefm_app.XeFMApp._resolve_jump_target('reg://HKEY_CURRENT_USER',
                                                   current='/home/user')
    assert str(target) == 'reg://HKEY_CURRENT_USER'
    assert isinstance(target._impl, RegistryPathImpl)
    assert not xefm_app.XeFMApp._is_local('reg://HKEY_CURRENT_USER')
    assert path_schemes.is_uri('reg://x')


def test_writes_are_refused_in_the_backend_s_own_words(clean_schemes):
    load(PATH_SCHEMES={'reg': RegistryPathImpl})
    with pytest.raises(OSError) as caught:
        Path('reg://HKEY_CURRENT_USER').unlink()
    assert 'regedit' in str(caught.value)
    assert not Path('reg://HKEY_CURRENT_USER').supports('write_operations')


def test_the_key_names_the_scheme(clean_schemes):
    """``PATH_SCHEMES = {'reg': …}`` has already said it once. A class that
    leaves ``SCHEME`` unset gets it from the key rather than being asked for
    the same word twice."""
    load(PATH_SCHEMES={'reg': RegistryPathImpl})
    assert RegistryPathImpl.SCHEME == 'reg'


def test_a_reload_replaces_the_whole_table(clean_schemes):
    load(PATH_SCHEMES={'reg': RegistryPathImpl})
    assert path_schemes.is_uri('reg://x')

    RegistryPathImpl.SCHEME = ''
    load(PATH_SCHEMES={'hive': RegistryPathImpl})
    assert not path_schemes.is_uri('reg://x')
    assert path_schemes.is_uri('hive://x')
    assert str(Path('reg://x')) == 'reg:/x'    # a plain path again


def test_no_path_schemes_at_all_is_not_a_problem(clean_schemes):
    warnings, count = load()
    assert warnings == []
    assert count == 0


def test_the_preview_notice_counts_them(clean_schemes):
    notice = user_api.preview_notice(0, 0, 0, 0, 2)
    assert '2 path scheme(s)' in notice
    assert 'Preview' in notice


# --------------------------------------------------------------------------- #
# Refusals — a bad entry costs that entry, never the config
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('scheme, spec, expected', [
    ('reg', 'RegistryPathImpl', 'must be a PathImpl subclass'),
    ('reg', 42, 'must be a PathImpl subclass'),
    ('reg', dict, 'must be a PathImpl subclass'),
    ('reg', Incomplete, 'does not implement open, stat'),
    ('REG', RegistryPathImpl, 'must be lowercase'),
    ('reg://', RegistryPathImpl, "written without '://'"),
    ('', RegistryPathImpl, 'non-empty string'),
    ('1reg', RegistryPathImpl, 'must start with a letter'),
    ('s3', RegistryPathImpl, "would replace the built-in 's3://'"),
])
def test_a_bad_entry_is_one_warning(clean_schemes, scheme, spec, expected):
    warnings, count = load(PATH_SCHEMES={scheme: spec})
    assert count == 0
    assert len(warnings) == 1
    assert expected in warnings[0]


def test_a_class_registered_under_the_wrong_scheme_is_refused(clean_schemes):
    """Its ``_root_prefix`` would build ``reg://`` paths while the registry
    answers to ``hive://``, so its own ``parent`` would leave the folder."""
    RegistryPathImpl.SCHEME = 'reg'
    warnings, count = load(PATH_SCHEMES={'hive': RegistryPathImpl})
    assert count == 0
    assert "whose SCHEME is 'reg'" in warnings[0]


def test_a_builtin_can_be_replaced_on_purpose(clean_schemes):
    class MyS3(RegistryPathImpl):
        SCHEME = 's3'

    warnings, count = load(PATH_SCHEMES={'s3': {'class': MyS3, 'override': True}})
    assert warnings == []
    assert count == 1
    assert isinstance(Path('s3://bucket/key')._impl, MyS3)


def test_one_bad_entry_does_not_take_the_good_one_with_it(clean_schemes):
    warnings, count = load(PATH_SCHEMES={'reg': RegistryPathImpl,
                                         'broken': Incomplete})
    assert count == 1
    assert len(warnings) == 1
    assert path_schemes.is_uri('reg://x')


def test_path_schemes_must_be_a_dict(clean_schemes):
    warnings, count = load(PATH_SCHEMES=[RegistryPathImpl])
    assert count == 0
    assert 'PATH_SCHEMES must be a dictionary' in warnings[0]


def test_validation_reports_without_registering(clean_schemes):
    """``validate_config`` runs this to report on a config it is not loading."""
    warnings = user_api.validate_user_entries(
        config_with(PATH_SCHEMES={'reg': RegistryPathImpl}))
    assert warnings == []
    assert not path_schemes.is_uri('reg://x')


def test_a_plain_pathimpl_subclass_is_accepted_too(clean_schemes):
    """``ReadOnlyPathImpl`` is the recommendation, not the requirement — the
    registry's contract is ``PathImpl``."""
    assert issubclass(RegistryPathImpl, PathImpl)
    warnings, count = load(PATH_SCHEMES={'reg': RegistryPathImpl})
    assert (warnings, count) == ([], 1)

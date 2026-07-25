"""The three-way outcome a view/edit/open lookup can produce.

Deciding what to do with a file is not a yes/no question, and collapsing it to
one is the easiest way to get this wrong:

  1. an explicit command   -> launch that external program
  2. an explicit ``None``  -> deliberately use the built-in viewer
  3. no association at all -> fall back to the is-it-text? check

Cases 2 and 3 both make ``get_program_for_file`` return ``None``, so that
function alone cannot tell them apart — ``has_explicit_association`` is what
separates "configured to use the built-in viewer" from "not configured".

These tests inject their own associations rather than asserting against
whatever ``_config.py`` happens to ship. The previous version of this file
hard-coded claims about the default config ("readme.txt opens in less") that
were already false, and asserted nothing, so it passed regardless.

Run with: python -m pytest test/test_view_file_fallback.py -v
"""

import pytest

import xefm.config
from xefm.config import (get_program_for_file, has_action_for_file,
                        has_explicit_association)


class _Config:
    def __init__(self, associations):
        self.FILE_ASSOCIATIONS = associations


@pytest.fixture
def associations(monkeypatch):
    def install(entries):
        monkeypatch.setattr(xefm.config, "get_config", lambda: _Config(entries))
    return install


ASSOC = [
    {'pattern': '*.jpg', 'open|view': ['open', '-a', 'Preview'], 'edit': None},
    {'pattern': '*.txt', 'view': None},          # explicitly: built-in viewer
    {'pattern': '*.log', 'view': ['less']},
]


def classify(filename, action='view'):
    """The decision a caller has to make, as a single label."""
    command = get_program_for_file(filename, action)
    if command is not None:
        return 'external'
    if has_explicit_association(filename, action):
        return 'builtin'
    return 'unconfigured'


class TestThreeWayOutcome:
    @pytest.mark.parametrize("filename,expected", [
        ('photo.jpg', 'external'),      # command present
        ('server.log', 'external'),
        ('readme.txt', 'builtin'),      # explicit None
        ('mystery.xyz', 'unconfigured'),  # no entry matches
    ])
    def test_classification(self, associations, filename, expected):
        associations(ASSOC)
        assert classify(filename) == expected

    def test_explicit_none_and_no_association_are_distinguishable(self, associations):
        associations(ASSOC)
        # Indistinguishable by command alone...
        assert get_program_for_file('readme.txt', 'view') is None
        assert get_program_for_file('mystery.xyz', 'view') is None
        # ...but not by explicitness.
        assert has_explicit_association('readme.txt', 'view')
        assert not has_explicit_association('mystery.xyz', 'view')

    def test_has_action_is_false_for_both_none_cases(self, associations):
        """has_action_for_file answers "is there a program?", so an explicit
        None reads False — it must not be used to mean "unconfigured"."""
        associations(ASSOC)
        assert not has_action_for_file('readme.txt', 'view')
        assert not has_action_for_file('mystery.xyz', 'view')


class TestPerActionIndependence:
    def test_one_file_can_be_external_for_one_action_and_builtin_for_another(
            self, associations):
        associations(ASSOC)
        assert classify('photo.jpg', 'open') == 'external'
        assert classify('photo.jpg', 'view') == 'external'
        assert classify('photo.jpg', 'edit') == 'builtin'   # explicit None

    def test_unlisted_action_is_unconfigured_not_builtin(self, associations):
        associations(ASSOC)
        # *.log defines only 'view'; 'edit' was never mentioned.
        assert classify('server.log', 'edit') == 'unconfigured'

    def test_view_and_open_resolve_independently(self, associations):
        associations([{'pattern': '*.md', 'open': ['typora'], 'view': None}])
        assert classify('notes.md', 'open') == 'external'
        assert classify('notes.md', 'view') == 'builtin'


class TestEmptyConfiguration:
    def test_everything_is_unconfigured(self, associations):
        associations([])
        assert classify('photo.jpg') == 'unconfigured'
        assert not has_explicit_association('photo.jpg', 'view')

    def test_missing_associations_do_not_raise(self, associations):
        associations(None)
        assert get_program_for_file('photo.jpg', 'view') is None
        assert not has_explicit_association('photo.jpg', 'view')

"""Priority-based matching in FILE_ASSOCIATIONS.

Entries are checked top to bottom and the first entry that matches *and*
defines the requested action wins. The subtle part — and the reason this needs
real coverage — is that a matching entry which does *not* define the action
must not stop the search: lookup falls through to later entries.

These tests drive the production ``xefm.config.get_program_for_file`` against an
injected config. An earlier version of this file reimplemented the matching
logic locally and asserted nothing, so it passed no matter what production did.

Run with: python -m pytest test/test_priority_matching.py -v
"""

import pytest

import xefm.config
from xefm.config import get_program_for_file, has_action_for_file


class _Config:
    def __init__(self, associations):
        self.FILE_ASSOCIATIONS = associations


@pytest.fixture
def associations(monkeypatch):
    """Install a FILE_ASSOCIATIONS list for the duration of one test."""
    def install(entries):
        monkeypatch.setattr(xefm.config, "get_config", lambda: _Config(entries))
    return install


#: Specific rules ahead of general ones, plus a pair of *.txt entries where the
#: first deliberately omits 'view' so lookup has to fall through to the second.
ORDERED = [
    {'pattern': 'test_*.py', 'open': ['pytest'], 'view': ['cat'], 'edit': ['nano']},
    {'pattern': '*.py', 'open': ['python3'], 'view': ['less'], 'edit': ['vim']},
    {'pattern': '*.txt', 'open': ['open', '-e'], 'edit': ['vim']},  # no 'view'
    {'pattern': '*.txt', 'view': ['less']},
]


class TestFirstMatchWins:
    def test_specific_entry_beats_later_general_one(self, associations):
        associations(ORDERED)
        assert get_program_for_file('test_foo.py', 'open') == ['pytest']
        assert get_program_for_file('test_foo.py', 'edit') == ['nano']

    def test_general_entry_used_when_specific_does_not_match(self, associations):
        associations(ORDERED)
        assert get_program_for_file('helper.py', 'open') == ['python3']
        assert get_program_for_file('helper.py', 'edit') == ['vim']

    def test_order_is_what_decides(self, associations):
        """Same two entries, reversed — the general one now wins."""
        associations(list(reversed(ORDERED[:2])))
        assert get_program_for_file('test_foo.py', 'open') == ['python3']


class TestFallThroughOnMissingAction:
    def test_matching_entry_without_the_action_does_not_halt_lookup(self, associations):
        associations(ORDERED)
        # Entry 3 matches *.txt but defines no 'view'; entry 4 must supply it.
        assert get_program_for_file('notes.txt', 'view') == ['less']

    def test_earlier_entry_still_wins_for_actions_it_does_define(self, associations):
        associations(ORDERED)
        assert get_program_for_file('notes.txt', 'open') == ['open', '-e']
        assert get_program_for_file('notes.txt', 'edit') == ['vim']


class TestCombinedActionKeys:
    def test_open_pipe_view_serves_both(self, associations):
        associations([{'pattern': '*.jpg', 'open|view': ['open', '-a', 'Preview']}])
        assert get_program_for_file('a.jpg', 'open') == ['open', '-a', 'Preview']
        assert get_program_for_file('a.jpg', 'view') == ['open', '-a', 'Preview']

    def test_whitespace_around_the_pipe_is_tolerated(self, associations):
        associations([{'pattern': '*.jpg', 'open | view': ['preview']}])
        assert get_program_for_file('a.jpg', 'view') == ['preview']

    def test_combined_key_does_not_supply_unlisted_actions(self, associations):
        associations([{'pattern': '*.jpg', 'open|view': ['preview']}])
        assert get_program_for_file('a.jpg', 'edit') is None


class TestExplicitNone:
    def test_none_stops_the_search_rather_than_falling_through(self, associations):
        """An explicit None means "deliberately nothing" — a later entry must
        not quietly override it."""
        associations([
            {'pattern': '*.pdf', 'edit': None},
            {'pattern': '*.pdf', 'edit': ['vim']},
        ])
        assert get_program_for_file('doc.pdf', 'edit') is None
        assert not has_action_for_file('doc.pdf', 'edit')


class TestPatternForms:
    def test_pattern_may_be_a_list(self, associations):
        associations([{'pattern': ['*.jpg', '*.png'], 'open': ['viewer']}])
        assert get_program_for_file('a.jpg', 'open') == ['viewer']
        assert get_program_for_file('b.png', 'open') == ['viewer']
        assert get_program_for_file('c.gif', 'open') is None

    def test_matching_is_case_insensitive(self, associations):
        associations([{'pattern': '*.JPG', 'open': ['viewer']}])
        assert get_program_for_file('photo.jpg', 'open') == ['viewer']
        assert get_program_for_file('PHOTO.JPG', 'open') == ['viewer']

    def test_string_command_is_split_into_a_list(self, associations):
        associations([{'pattern': '*.txt', 'open': 'open -e'}])
        assert get_program_for_file('a.txt', 'open') == ['open', '-e']


class TestMalformedEntries:
    """A bad entry should be skipped, not crash the lookup."""

    @pytest.mark.parametrize("bad", [
        {'open': ['x']},              # no 'pattern'
        {'pattern': 42, 'open': ['x']},  # pattern is neither str nor list
        "not-a-dict",
        None,
    ])
    def test_bad_entry_is_skipped_and_later_entries_still_work(self, associations, bad):
        associations([bad, {'pattern': '*.txt', 'open': ['good']}])
        assert get_program_for_file('a.txt', 'open') == ['good']

    def test_empty_associations(self, associations):
        associations([])
        assert get_program_for_file('a.txt', 'open') is None

    def test_no_match_returns_none(self, associations):
        associations(ORDERED)
        assert get_program_for_file('archive.xyz', 'open') is None

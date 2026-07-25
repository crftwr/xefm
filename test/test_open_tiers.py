"""The two tiers of "open" in FILE_ASSOCIATIONS.

Enter is the casual open: it stays inside XeFM, and an ``enter`` rule names a
built-in *handler*. Cmd/Ctrl-Enter is the deliberate one: ``open`` names an
external *program*. The two value spaces are different, which is why they have
separate accessors — routing a handler name through the command accessor would
quietly turn ``'viewer'`` into the command ``['viewer']``.

Run with: python -m pytest test/test_open_tiers.py -v
"""

import pytest

import xefm.config
from xefm.config import (BUILTIN_HANDLERS, get_builtin_handler_for_file,
                        get_program_for_file)


class _Config:
    def __init__(self, associations):
        self.FILE_ASSOCIATIONS = associations


@pytest.fixture
def associations(monkeypatch):
    def install(entries):
        monkeypatch.setattr(xefm.config, "get_config", lambda: _Config(entries))
    return install


class TestBuiltinHandler:
    @pytest.mark.parametrize("handler", BUILTIN_HANDLERS)
    def test_recognised_handlers_resolve(self, associations, handler):
        associations([{'pattern': '*.x', 'enter': handler}])
        assert get_builtin_handler_for_file('a.x') == (True, handler)

    def test_unconfigured_is_distinct_from_explicit_none(self, associations):
        associations([{'pattern': '*.x', 'enter': None}])
        # Explicit None: configured, do nothing.
        assert get_builtin_handler_for_file('a.x') == (True, None)
        # No rule at all: caller applies its own default.
        assert get_builtin_handler_for_file('b.y') == (False, None)

    def test_handler_name_is_case_insensitive(self, associations):
        associations([{'pattern': '*.x', 'enter': 'VIEWER'}])
        assert get_builtin_handler_for_file('a.x') == (True, 'viewer')

    def test_unknown_handler_falls_back_to_default(self, associations):
        """A typo must not silently disable Enter — it reads as unconfigured,
        so the caller's default dispatch still runs."""
        associations([{'pattern': '*.x', 'enter': 'vewier'}])
        assert get_builtin_handler_for_file('a.x') == (False, None)

    def test_handler_is_not_coerced_into_a_command(self, associations):
        """The bug this accessor exists to prevent."""
        associations([{'pattern': '*.x', 'enter': 'viewer'}])
        _configured, handler = get_builtin_handler_for_file('a.x')
        assert handler == 'viewer'
        assert not isinstance(handler, list)

    def test_priority_applies_to_enter_too(self, associations):
        associations([
            {'pattern': 'test_*.py', 'enter': 'navigate'},
            {'pattern': '*.py', 'enter': 'viewer'},
        ])
        assert get_builtin_handler_for_file('test_a.py') == (True, 'navigate')
        assert get_builtin_handler_for_file('lib.py') == (True, 'viewer')


class TestTiersAreIndependent:
    def test_same_file_can_have_both_tiers(self, associations):
        associations([{
            'pattern': '*.csv',
            'enter': 'viewer',
            'open': ['open', '-a', 'Numbers'],
        }])
        assert get_builtin_handler_for_file('data.csv') == (True, 'viewer')
        assert get_program_for_file('data.csv', 'open') == ['open', '-a', 'Numbers']

    def test_enter_does_not_leak_into_open(self, associations):
        associations([{'pattern': '*.x', 'enter': 'viewer'}])
        assert get_program_for_file('a.x', 'open') is None

    def test_open_does_not_leak_into_enter(self, associations):
        associations([{'pattern': '*.x', 'open': ['someapp']}])
        assert get_builtin_handler_for_file('a.x') == (False, None)


class TestNoTerminalDeclaration:
    """Associations do not describe display handover.

    Whether to suspend follows from the backend: terminal mode hands over the
    tty and waits, desktop mode detaches. A per-entry flag used to exist here
    and was removed -- it duplicated a decision XeFM can already make, and its
    failure mode was bad: forgetting it on `less` corrupts the terminal, while
    the backend rule cannot be forgotten.
    """

    def test_a_leftover_terminal_key_is_inert(self, associations):
        """It stays reserved, so an old hand-written config keeps working
        rather than gaining a phantom action named 'terminal'."""
        associations([{'pattern': '*.log', 'view': ['less'], 'terminal': True}])
        assert get_program_for_file('a.log', 'view') == ['less']
        assert get_program_for_file('a.log', 'terminal') is None
        assert not xefm.config.has_explicit_association('a.log', 'terminal')

    def test_one_entry_can_mix_terminal_and_gui_programs(self, associations):
        """The case the removed flag could not express: `less` to view and a
        GUI editor to edit, without splitting into two entries."""
        associations([{
            'pattern': '*.log',
            'view': ['less'],
            'edit': ['code'],
        }])
        assert get_program_for_file('a.log', 'view') == ['less']
        assert get_program_for_file('a.log', 'edit') == ['code']

    def test_the_engine_exposes_no_terminal_query(self):
        assert not hasattr(xefm.config, 'needs_terminal')


@pytest.fixture
def shipped_defaults(monkeypatch):
    """Pin lookups to the shipped _config.py template.

    ``get_config()`` returns the *user's* ~/.xefm/config.py when one exists, so
    asserting against it would make these tests pass or fail depending on whose
    machine they run on.
    """
    from xefm import _config
    monkeypatch.setattr(xefm.config, "get_config", lambda: _config.Config)


@pytest.mark.usefixtures("shipped_defaults")
class TestShippedDefaults:
    """The defaults in _config.py, which is what a new user starts from."""

    @pytest.mark.parametrize("filename", ['lib.jar', 'pkg.whl', 'old.egg'])
    def test_zip_shaped_files_navigate(self, filename):
        assert get_builtin_handler_for_file(filename) == (True, 'navigate')

    @pytest.mark.parametrize("filename", ['sheet.xlsx', 'report.docx'])
    def test_office_files_do_not_navigate(self, filename):
        """They are zip files underneath, which is exactly why 'navigate'
        cannot be sniffed — you want Word here, not a file listing."""
        assert get_builtin_handler_for_file(filename) == (False, None)

    @pytest.mark.parametrize("filename", ['notes.txt', 'app.py', 'Makefile', 'x.qqq'])
    def test_text_files_need_no_rule_at_all(self, filename):
        """The default already routes these to the built-in viewer, which
        sniffs content. Listing text extensions here would add a list to
        maintain and change nothing — including for 'Makefile' and unknown
        extensions, which no list would have caught."""
        assert get_builtin_handler_for_file(filename) == (False, None)
        assert get_program_for_file(filename, 'view') is None
        assert not xefm.config.has_explicit_association(filename, 'view')

    def test_media_files_still_open_externally(self):
        assert get_program_for_file('doc.pdf', 'open') == ['open', '-a', 'Preview']
        assert get_program_for_file('clip.mp4', 'open') == [
            'open', '-a', 'QuickTime Player']

    def test_no_default_entry_declares_a_terminal_flag(self):
        """The key is gone from the shipped template, not merely unused."""
        from xefm import _config
        for entry in _config.Config.FILE_ASSOCIATIONS:
            assert 'terminal' not in entry, entry.get('pattern')

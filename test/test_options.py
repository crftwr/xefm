"""Surface options (xefm.options): what one declaration says, and what the live
set does with it.

The declaration is the single source the chip strip, the options dialog, the
generated actions and the search itself all read, so these tests pin down the
parts they disagree about most easily — which value is the default, when a chip
is lit, which options a mode shows, and what survives a reopen.

Run with: python -m pytest test/test_options.py -v
"""

import pytest

from xefm.options import Option, OptionSet, accel_map


BOOL = Option("wrap", "Wrap lines", accel="w", flag="wrap")
TRI = Option("case", "Case", accel="c", flag="Aa",
             values=("smart", "sensitive", "insensitive"),
             flags=("Aa", "Aa", "aa"),
             labels=("smart", "always on", "always off"),
             active=lambda value, hint: value == "sensitive" or bool(hint))
GATED = Option("regex", "Pattern", accel="p", flag=".*", modes=("content",))
TRANSIENT = Option("subdirs", "Subfolders", accel="s", flag="sub",
                   values=(True, False), flags=("sub", "no sub"), persist=False)

ALL = (BOOL, TRI, GATED, TRANSIENT)


class TestOption:
    def test_default_is_the_first_value(self):
        assert BOOL.default is False
        assert TRI.default == "smart"
        assert TRANSIENT.default is True

    def test_next_value_wraps(self):
        assert TRI.next_value("smart") == "sensitive"
        assert TRI.next_value("insensitive") == "smart"
        assert TRI.next_value("smart", -1) == "insensitive"

    def test_unknown_value_degrades_to_the_default(self):
        # A persisted value from an older release must not raise.
        assert TRI.index_of("nonsense") == 0
        assert TRI.flag_for("nonsense") == "Aa"

    def test_flag_names_the_state_when_per_value_flags_were_given(self):
        assert TRANSIENT.flag_for(True) == "sub"
        assert TRANSIENT.flag_for(False) == "no sub"

    def test_flag_is_constant_without_them(self):
        assert BOOL.flag_for(True) == BOOL.flag_for(False) == "wrap"

    def test_bool_labels_read_as_on_off(self):
        assert BOOL.label_for(True) == "on"
        assert BOOL.label_for(False) == "off"

    def test_declared_labels_win(self):
        assert TRI.label_for("sensitive") == "always on"

    def test_default_lit_rule_is_not_at_the_default(self):
        assert BOOL.is_active(True) is True
        assert BOOL.is_active(False) is False

    def test_declared_predicate_can_read_the_hint(self):
        assert TRI.is_active("smart", "") is False
        assert TRI.is_active("smart", "TODO") is True   # the query decided
        assert TRI.is_active("sensitive", "") is True

    def test_modes_gate_the_option(self):
        assert GATED.applies("content") is True
        assert GATED.applies("filename") is False
        assert BOOL.applies("filename") is True   # declared no modes: always
        assert GATED.applies(None) is True        # a surface with no modes


class TestOptionSet:
    def test_starts_at_the_declared_defaults(self):
        assert OptionSet(ALL).snapshot() == {
            "wrap": False, "case": "smart", "regex": False, "subdirs": True}

    def test_seed_values_are_taken_and_unknown_names_ignored(self):
        options = OptionSet(ALL, {"case": "sensitive", "nope": 1})
        assert options["case"] == "sensitive"
        assert "nope" not in options.snapshot()

    def test_set_reports_whether_it_changed(self):
        options = OptionSet(ALL)
        assert options.set("wrap", True) is True
        assert options.set("wrap", True) is False   # the caller's cue not to re-run

    def test_change_notifies_the_owner(self):
        seen = []
        options = OptionSet(ALL, on_change=lambda n, v: seen.append((n, v)))
        options.cycle("case")
        options.set("wrap", True)
        assert seen == [("case", "sensitive"), ("wrap", True)]

    def test_unchanged_set_does_not_notify(self):
        seen = []
        options = OptionSet(ALL, on_change=lambda n, v: seen.append((n, v)))
        options.set("wrap", False)
        assert seen == []

    def test_cycle_walks_the_declared_order(self):
        options = OptionSet(ALL)
        assert options.cycle("case") == "sensitive"
        assert options.cycle("case") == "insensitive"
        assert options.cycle("case") == "smart"
        assert options.cycle("case", -1) == "insensitive"

    def test_unknown_name_is_inert(self):
        options = OptionSet(ALL)
        assert options.cycle("nope") is None
        assert options.set("nope", 1) is False

    def test_visible_filters_by_mode_and_keeps_declaration_order(self):
        options = OptionSet(ALL)
        assert [o.name for o in options.visible("content")] == [
            "wrap", "case", "regex", "subdirs"]
        assert [o.name for o in options.visible("filename")] == [
            "wrap", "case", "subdirs"]

    def test_chips_pair_text_with_lit(self):
        options = OptionSet(ALL)
        assert options.chips("filename") == [
            ("wrap", False), ("Aa", False), ("sub", False)]
        options.cycle("subdirs")
        assert options.chips("filename")[-1] == ("no sub", True)

    def test_chips_read_the_shared_hint(self):
        options = OptionSet(ALL)
        options.hint = "TODO"
        assert ("Aa", True) in options.chips("filename")
        assert options.chips("filename", hint="") == [
            ("wrap", False), ("Aa", False), ("sub", False)]

    def test_reset_transient_restores_only_the_transient_ones(self):
        options = OptionSet(ALL)
        options.cycle("case")        # persists
        options.cycle("subdirs")     # does not
        options.reset_transient()
        assert options["case"] == "sensitive"
        assert options["subdirs"] is True

    def test_reset_transient_is_silent(self):
        # It runs as a surface opens; a notification there would start a search
        # against a query nobody has typed yet.
        seen = []
        options = OptionSet(ALL, on_change=lambda n, v: seen.append(n))
        options.cycle("subdirs")
        seen.clear()
        options.reset_transient()
        assert seen == []


class TestAccelMap:
    def test_maps_letters_to_options(self):
        table = accel_map(ALL)
        assert table["c"] is TRI
        assert table["s"] is TRANSIENT

    def test_first_declaration_keeps_a_duplicated_letter(self):
        other = Option("clash", "Clash", accel="c", flag="x")
        assert accel_map([TRI, other])["c"] is TRI

"""Surface options (xefm.options): what one declaration says, and what the live
set does with it.

The declaration is the single source the chip strip, the options dialog, the
generated actions and the search itself all read, so these tests pin down the
parts they disagree about most easily — which letter toggles an option, which
options a mode shows, and what survives a reopen.

Run with: python -m pytest test/test_options.py -v
"""

import pytest

from xefm.options import Option, OptionSet, accel_map, state_label


CASE = Option("case", "Case sensitive", flag="Aa")
WORD = Option("word", "Whole word", flag="Word", modes=("content",))
REGEX = Option("regex", "Regular expression", flag=".*", default=True,
               modes=("content",))
SUBDIRS = Option("subdirs", "Search subfolders", flag="Sub", default=True,
                 persist=False)

ALL = (CASE, WORD, REGEX, SUBDIRS)


class TestOption:
    def test_the_labels_initial_is_the_key(self):
        # The Sort dialog's convention: the word carries its own key, so the
        # letter is never drawn.
        assert (CASE.key, WORD.key, REGEX.key, SUBDIRS.key) == ("c", "w", "r", "s")

    def test_accel_overrides_the_initial(self):
        assert Option("x", "Case sensitive", flag="Aa", accel="K").key == "k"

    def test_defaults_are_the_declared_ones(self):
        assert CASE.default is False
        assert REGEX.default is True

    def test_modes_gate_the_option(self):
        assert REGEX.applies("content") is True
        assert REGEX.applies("filename") is False
        assert CASE.applies("filename") is True   # declared no modes: always
        assert REGEX.applies(None) is True        # a surface with no modes

    def test_state_reads_as_a_word(self):
        assert (state_label(True), state_label(False)) == ("on", "off")


class TestOptionSet:
    def test_starts_at_the_declared_defaults(self):
        assert OptionSet(ALL).snapshot() == {
            "case": False, "word": False, "regex": True, "subdirs": True}

    def test_seed_values_are_taken_and_unknown_names_ignored(self):
        options = OptionSet(ALL, {"case": True, "nope": True})
        assert options["case"] is True
        assert "nope" not in options.snapshot()

    def test_set_reports_whether_it_changed(self):
        options = OptionSet(ALL)
        assert options.set("case", True) is True
        assert options.set("case", True) is False  # the caller's cue not to re-run

    def test_change_notifies_the_owner(self):
        seen = []
        options = OptionSet(ALL, on_change=lambda n, v: seen.append((n, v)))
        options.toggle("case")
        options.set("regex", False)
        assert seen == [("case", True), ("regex", False)]

    def test_unchanged_set_does_not_notify(self):
        seen = []
        options = OptionSet(ALL, on_change=lambda n, v: seen.append(n))
        options.set("case", False)
        assert seen == []

    def test_toggle_flips_and_returns_the_new_value(self):
        options = OptionSet(ALL)
        assert options.toggle("case") is True
        assert options.toggle("case") is False

    def test_unknown_name_is_inert(self):
        options = OptionSet(ALL)
        assert options.toggle("nope") is False
        assert options.set("nope", True) is False

    def test_visible_filters_by_mode_and_keeps_declaration_order(self):
        options = OptionSet(ALL)
        assert [o.name for o in options.visible("content")] == [
            "case", "word", "regex", "subdirs"]
        assert [o.name for o in options.visible("filename")] == ["case", "subdirs"]

    def test_chips_pair_the_flag_with_its_state(self):
        options = OptionSet(ALL)
        assert options.chips("filename") == [("Aa", False), ("Sub", True)]
        options.toggle("case")
        assert options.chips("filename") == [("Aa", True), ("Sub", True)]

    def test_a_chip_keeps_its_name_in_both_states(self):
        # The fill carries on/off, so the word never has to — which is what
        # keeps a chip from growing a space inside it ("no sub").
        options = OptionSet(ALL)
        before = [text for text, _on in options.chips("filename")]
        options.toggle("subdirs")
        assert [text for text, _on in options.chips("filename")] == before

    def test_reset_transient_restores_only_the_transient_ones(self):
        options = OptionSet(ALL)
        options.toggle("case")       # persists
        options.toggle("subdirs")    # does not
        options.reset_transient()
        assert options["case"] is True
        assert options["subdirs"] is True

    def test_reset_transient_is_silent(self):
        # It runs as a surface opens; a notification there would start a search
        # against a query nobody has typed yet.
        seen = []
        options = OptionSet(ALL, on_change=lambda n, v: seen.append(n))
        options.toggle("subdirs")
        seen.clear()
        options.reset_transient()
        assert seen == []


class TestAccelMap:
    def test_maps_initials_to_options(self):
        table = accel_map(ALL)
        assert table["c"] is CASE
        assert table["s"] is SUBDIRS

    def test_first_declaration_keeps_a_duplicated_initial(self):
        other = Option("clash", "Case folding", flag="x")
        assert accel_map([CASE, other])["c"] is CASE

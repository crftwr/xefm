"""Tests for abbreviate_path — component-aware path shortening for header bars.

The property that matters throughout: whatever comes back must fit the budget,
and every path component still visible must be a *whole* component, never a
fragment of one. A fragment names nothing and misleads the reader.
"""

import pytest

from xefm.str_format import abbreviate_path

HOME = "/Users/me"


def components_of(text):
    """Visible path components, ignoring the dropped-component marker."""
    return [c for c in text.split("/") if c and c != "…"]


class TestFits:
    """Whatever the budget, the result fits it."""

    @pytest.mark.parametrize("path", [
        "/Users/me/projects/xefm/src/widgets",
        "/usr/local/share/man/man1",
        "s3://my-bucket/data/2026/07/reports",
        "ssh://host/var/log/nginx",
        "[archive.zip]/deep/nested/dir",
        "/singlelongdirectorynamehere",
        "/",
    ])
    @pytest.mark.parametrize("width", [1, 2, 3, 5, 8, 12, 14, 20, 30, 60, 200])
    def test_result_never_exceeds_budget(self, path, width):
        assert len(abbreviate_path(path, width, home=HOME)) <= width

    def test_zero_or_negative_budget_is_empty(self):
        assert abbreviate_path("/Users/me/x", 0, home=HOME) == ""
        assert abbreviate_path("/Users/me/x", -5, home=HOME) == ""

    def test_untouched_when_it_already_fits(self):
        assert abbreviate_path("/usr/bin", 80, home=HOME) == "/usr/bin"


class TestComponentIntegrity:
    """Components are dropped whole, not cut in half."""

    def test_surviving_components_are_whole(self):
        path = "/Users/me/projects/xefm/src/widgets"
        result = abbreviate_path(path, 20, home=HOME)
        original = set(components_of(path)) | {"~"}
        assert set(components_of(result)) <= original

    def test_leaf_is_preserved_while_room_remains(self):
        result = abbreviate_path("/usr/local/share/man/man1", 12, home=HOME)
        assert result.endswith("man1")

    def test_dropping_is_marked(self):
        result = abbreviate_path("/usr/local/share/man/man1", 20, home=HOME)
        assert "…" in result
        assert result == "/…/share/man/man1"

    def test_keeps_more_when_given_more_room(self):
        path = "/usr/local/share/man/man1"
        wide = abbreviate_path(path, 24, home=HOME)
        narrow = abbreviate_path(path, 12, home=HOME)
        assert len(components_of(wide)) > len(components_of(narrow))


class TestHomeContraction:
    def test_home_becomes_tilde(self):
        assert abbreviate_path("/Users/me/projects", 80, home=HOME) == "~/projects"

    def test_home_itself_becomes_tilde(self):
        assert abbreviate_path("/Users/me", 80, home=HOME) == "~"

    def test_only_a_whole_component_matches(self):
        # /Users/meredith must not become ~redith
        assert abbreviate_path("/Users/meredith", 80, home=HOME) == "/Users/meredith"

    def test_contraction_alone_can_make_it_fit(self):
        # Contracting is lossless, so it happens before anything is dropped.
        assert abbreviate_path("/Users/me/projects", 12, home=HOME) == "~/projects"
        assert "…" not in abbreviate_path("/Users/me/projects", 12, home=HOME)


class TestSchemes:
    """A scheme is part of the location's identity and is never abbreviated."""

    @pytest.mark.parametrize("scheme", ["s3://", "ssh://", "archive://", "ftp://"])
    def test_scheme_survives(self, scheme):
        path = f"{scheme}host/some/deep/nested/path/leaf"
        result = abbreviate_path(path, 24, home=HOME)
        assert result.startswith(scheme)

    def test_host_kept_before_inner_components(self):
        result = abbreviate_path("s3://my-bucket/data/2026/07/reports", 28, home=HOME)
        assert result == "s3://my-bucket/…/07/reports"

    def test_no_tilde_under_a_scheme(self):
        # '~' under ssh:// would claim a remote home that has nothing to do
        # with the local user.
        result = abbreviate_path(f"ssh://host{HOME}/work", 80, home=HOME)
        assert "~" not in result


class TestEdgeCases:
    def test_root_is_left_alone(self):
        assert abbreviate_path("/", 10, home=HOME) == "/"

    def test_empty_string(self):
        assert abbreviate_path("", 10, home=HOME) == ""

    def test_trailing_separator_makes_no_empty_component(self):
        result = abbreviate_path("/Users/me/a/b/c/trailing/", 14, home=HOME)
        assert "//" not in result

    def test_single_component_falls_back_to_middle_cut(self):
        result = abbreviate_path("/singlelongdirectoryname", 12, home=HOME)
        assert len(result) <= 12
        assert "…" in result

    def test_bare_name_keeps_its_extension(self):
        # The progress dialog passes a bare file name, which has no component
        # boundary to cut on. The middle goes and the extension stays — it is
        # what says which kind of file is being worked on.
        result = abbreviate_path("quarterly_report_2026_final_revised.pdf", 20,
                                 home=HOME)
        assert len(result) <= 20
        assert result.startswith("quarterly") and result.endswith(".pdf")

    def test_custom_measure_is_honoured(self):
        # A measure where every character counts double: the same path must
        # abbreviate as if the budget were half.
        double = lambda s: 2 * len(s)
        path = "/usr/local/share/man/man1"
        assert abbreviate_path(path, 40, measure=double, home=HOME) == \
            abbreviate_path(path, 20, home=HOME)

    def test_fractional_budget(self):
        # Vector backends measure in fractional units.
        result = abbreviate_path("/usr/local/share/man/man1", 17.5, home=HOME)
        assert len(result) <= 17.5

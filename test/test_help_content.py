"""The help dialog's section list, and the end-user doc that describes it.

``doc/HELP_DIALOG_FEATURE.md`` tells a user what the help dialog contains. The
dialog builds that content from ``XeFMApp._HELP_SECTIONS`` plus two sections
generated at display time, so the doc is a hand-written copy of something the
code owns — and it had silently drifted by four renamed sections, one missing
and one that never existed (#389).

These tests close that gap from both ends: the doc's section list is compared
against the real titles, and every action the dialog lists is checked to be an
action the keymap actually knows. Nothing here asserts which *key* does what —
the dialog reads the live keymap, so a test that pinned key letters would be
asserting one particular config, which is the same mistake the doc made.
"""

import re
import unittest
from pathlib import Path

from xefm import actions as _ctx
from xefm.actions import Action, registry
from xefm.app import XeFMApp

_DOC = Path(__file__).parent.parent / "doc" / "HELP_DIALOG_FEATURE.md"

#: ``- **Section Name** — description`` at the start of a doc bullet.
_BULLET = re.compile(r"^- \*\*(.+?)\*\*\s+—", re.MULTILINE)

#: A parenthesised run of bare keys or key chords — "(C)", "(A, Shift-A)",
#: "(S, 1-4)". Every item is one character or a modifier chord, so ordinary
#: parentheticals ("(grep)", "(config.py)") do not match.
_KEY_ITEM = r"(?:Shift-|Ctrl-|Alt-|Command-)?[A-Za-z0-9.]"
_KEY_PARENTHETICAL = re.compile(
    rf"\({_KEY_ITEM}(?:\s*[,/–-]\s*{_KEY_ITEM})*\)"
)


def doc_section(name: str) -> str:
    """The body of one ``## name`` section of the doc, up to the next heading."""
    text = _DOC.read_text(encoding="utf-8")
    match = re.search(rf"^## {re.escape(name)}$(.*?)(?=^## |\Z)",
                      text, re.MULTILINE | re.DOTALL)
    assert match is not None, f"doc has no '## {name}' section"
    return match.group(1)


def generated_section_titles() -> list[str]:
    """Every section title the help dialog can show, in display order.

    Taken from the three places that produce them, rather than written down
    here: the static table, the config-actions section (present only when a
    config defines actions, so one is registered to make it appear), and the
    generated archive section's own Markdown heading."""
    titles = [title for title, _entries in XeFMApp._HELP_SECTIONS]

    probe = Action(name="_help_doc_probe", context=_ctx.FILER,
                   description="probe", default_keys=(),
                   func=lambda ctx: None, source="user")
    registry.register(probe, override=True)
    try:
        titles += [title for title, _entries in XeFMApp._user_help_sections(None)]
    finally:
        registry.unregister_source("user")

    # Both helpers reach only classmethods/staticmethods through ``self``, so
    # the class stands in for an instance and no app has to be constructed.
    archive = XeFMApp._archive_help_section(XeFMApp)
    titles += [line[3:].strip() for line in archive.splitlines()
               if line.startswith("## ")]
    return titles


class TestHelpDocSections(unittest.TestCase):
    """``doc/HELP_DIALOG_FEATURE.md`` against the dialog it describes."""

    def test_doc_lists_every_section_in_order(self):
        documented = _BULLET.findall(doc_section("Content"))
        self.assertEqual(
            documented, generated_section_titles(),
            "doc/HELP_DIALOG_FEATURE.md's Content list no longer matches the "
            "dialog's sections — update the doc to match _HELP_SECTIONS",
        )

    def test_user_actions_section_appears_only_with_user_actions(self):
        # The claim the doc makes about the config-actions section: it is there
        # when the config defines actions and absent when it does not.
        self.assertEqual(XeFMApp._user_help_sections(None), ())

    def test_content_list_quotes_no_key_letters(self):
        # The dialog renders the live keymap; a key spelled out in the doc is
        # right only for a default config and goes stale in silence (#389).
        found = _KEY_PARENTHETICAL.findall(doc_section("Content"))
        self.assertEqual(
            found, [],
            "the Content list names key bindings; describe what the section "
            "covers instead — the dialog shows the user's own keys",
        )


class TestHelpSectionActions(unittest.TestCase):
    """The action names ``_HELP_SECTIONS`` lists, against the action registry."""

    def entries(self):
        return [(title, name)
                for title, actions in XeFMApp._HELP_SECTIONS
                for name, _desc in actions]

    def test_every_listed_action_is_a_real_action(self):
        # _keys_label searches these contexts, and renders "—" for a name none
        # of them knows — which is what a typo or a renamed action looks like
        # in the dialog: a row with no key and no complaint.
        contexts = (_ctx.FILER,) + _ctx.CONTEXTS
        unknown = [f"{title}: {name}" for title, name in self.entries()
                   if not any(registry.resolve(c, name) for c in contexts)]
        self.assertEqual(unknown, [], f"help lists unknown actions: {unknown}")

    def test_no_action_is_listed_twice(self):
        names = [name for _title, name in self.entries()]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        self.assertEqual(duplicates, [],
                         f"actions listed in two help sections: {duplicates}")

    def test_every_entry_has_a_description(self):
        blank = [f"{title}: {name}"
                 for title, actions in XeFMApp._HELP_SECTIONS
                 for name, desc in actions if not desc.strip()]
        self.assertEqual(blank, [], f"help entries with no description: {blank}")


if __name__ == "__main__":
    unittest.main()

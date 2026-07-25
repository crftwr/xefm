"""IME composition is forwarded to the text field of every text-input dialog.

A modal layer receives *every* event exclusively (the Panel routes to the top
layer), so a dialog that hosts a ``TextEdit`` must relay ``IME_COMPOSITION``
events to its field itself — otherwise CJK preedit (the in-progress, underlined
composition) is swallowed and the user sees nothing until the text commits. Each
dialog's ``handle_event`` is driven directly here with a composition event and the
field's ``_preedit`` is checked, pinning the forwarding for all five dialogs.
"""

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from puikit import Panel  # noqa: E402
from puikit.backends import create_backend  # noqa: E402
from puikit.event import Event, EventType  # noqa: E402
from puikit.widgets.text_edit import TextEdit  # noqa: E402

from xefm.input_dialog import InputDialog, show_input  # noqa: E402
from xefm.filter_list_dialog import FilterListDialog, show_filter_list  # noqa: E402
from xefm.progressive_search_dialog import ProgressiveSearchDialog, show_progressive_search  # noqa: E402
from xefm.batch_rename_dialog import BatchRenameDialog, show_batch_rename  # noqa: E402
from xefm.isearch_bar import ISearchBar  # noqa: E402


class _Entry:  # the batch-rename dialog reads only .name off each file
    def __init__(self, name):
        self.name = name


def _compose(text="にほん", caret=3):
    return Event(type=EventType.IME_COMPOSITION, hints={"preedit": text, "caret": caret})


class DialogImeForwarding(unittest.TestCase):
    def _assert_forwards(self, dialog, field):
        self.assertEqual(field._preedit, "")  # nothing composed yet
        handled = dialog.handle_event(_compose("にほん", 3))
        self.assertTrue(handled)
        self.assertEqual(field._preedit, "にほん")
        self.assertEqual(field._preedit_caret, 3)
        # A commit (empty preedit) clears it again.
        dialog.handle_event(_compose("", 0))
        self.assertEqual(field._preedit, "")

    def test_input_dialog(self):
        dlg = InputDialog(title="t", prompt="Name:", text="")
        self._assert_forwards(dlg, dlg.edit)

    def test_filter_list_dialog(self):
        dlg = FilterListDialog(items=["alpha", "beta"], title="Pick")
        self._assert_forwards(dlg, dlg.filter_edit)

    def test_progressive_search_dialog(self):
        dlg = ProgressiveSearchDialog(
            search_iter=lambda mode, q, cancel: iter(()),
            to_label=lambda mode, v: str(v),
        )
        self._assert_forwards(dlg, dlg.query_edit)

    def test_batch_rename_dialog(self):
        dlg = BatchRenameDialog(files=[_Entry("a.txt"), _Entry("b.txt")])
        # Composition lands in whichever field is active (Tab switches).
        self._assert_forwards(dlg, dlg.active)

    def test_isearch_bar(self):
        bar = ISearchBar()
        self._assert_forwards(bar, bar.edit)


class DialogEngagesTextInput(unittest.TestCase):
    """Pushing a text-input dialog must engage the backend's text input (IME): the
    Panel's focus leaf has to resolve to the field, or ``begin_text_input`` never
    fires and IME stays off — the Jump-to-Path regression (InputDialog never set
    its focus to the edit)."""

    def setUp(self):
        self.b = create_backend("memory")
        self.b.open()
        self.panel = Panel(self.b)

    def _assert_engaged(self):
        self.panel.render()
        self.assertIsInstance(self.panel.focused_leaf(), TextEdit)
        self.assertTrue(self.b.text_input_active)

    def test_input_dialog_engages(self):
        show_input(self.panel, title="Jump to Path", prompt="Path:", text="/tmp/")
        self._assert_engaged()

    def test_filter_list_dialog_engages(self):
        show_filter_list(self.panel, ["alpha", "beta"], title="Go to Favorite")
        self._assert_engaged()

    def test_progressive_search_dialog_engages(self):
        show_progressive_search(
            self.panel,
            search_iter=lambda mode, q, cancel: iter(()),
            to_label=lambda mode, v: str(v),
        )
        self._assert_engaged()

    def test_batch_rename_dialog_engages(self):
        show_batch_rename(self.panel, [_Entry("a.txt"), _Entry("b.txt")])
        self._assert_engaged()

    def test_isearch_bar_engages(self):
        bar = ISearchBar()
        self.panel.push_layer(bar, z=70, hints={"w": 40.0, "h": 1.0})
        self._assert_engaged()


if __name__ == "__main__":
    unittest.main()

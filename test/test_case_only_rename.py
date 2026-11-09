"""A case-only rename — ``foo.txt`` to ``Foo.txt`` — does not collide with the
file it renames (issue #867).

On a case-insensitive disk (Windows, and macOS by default) the new name already
exists: it is the file being renamed. The rename prompt refused it as "already
exists" and the batch rename dialog marked it as a conflict. Another file that
differs only in case, which only a case-sensitive disk can hold, still collides.

Each file holds the name it was created with, so the tests can tell which file
ended up under which name.

Run with: python -m pytest test/test_case_only_rename.py -v
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import app as xefm_app  # noqa: E402
from xefm.batch_rename_dialog import BatchRenameDialog  # noqa: E402


def _ignores_case() -> bool:
    """Whether the disk under the temp directory finds ``a`` as ``A``."""
    tmp = tempfile.mkdtemp()
    try:
        open(os.path.join(tmp, "a"), "w").close()
        return os.path.exists(os.path.join(tmp, "A"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


_IGNORES_CASE = _ignores_case()


class _Type:
    """Stands in for ``show_input``: type ``text`` and press Enter, which the
    prompt's validation may refuse."""

    def __init__(self, text):
        self.text = text
        self.refusal = None

    def __call__(self, panel, *, on_accept, validate=None, **kwargs):
        if validate is not None:
            self.refusal = validate(self.text)
        if self.refusal is None:
            on_accept(self.text)


class _BatchRenameImmediately:
    """Stands in for ``show_batch_rename``: drives the real dialog headlessly,
    and keeps it so its preview can be read afterwards."""

    def __init__(self, search, replace):
        self.search = search
        self.replace = replace
        self.dialog = None

    def __call__(self, panel, files, *, on_done=None, **kwargs):
        self.dialog = BatchRenameDialog(files, on_done=on_done)
        self.dialog.search_edit.text = self.search
        self.dialog.replace_edit.text = self.replace
        self.dialog._refresh_preview()
        self.dialog._accept()
        return self.dialog


class _Rename(unittest.TestCase):
    """A headless XeFMApp on the memory backend over a real temp directory
    holding ``names``."""

    names = ()

    def setUp(self):
        from xefm.state_manager import XeFMStateManager
        from puikit.backends import create_backend
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.cfgdir = tempfile.mkdtemp()
        for name in self.names:
            with open(os.path.join(self.tmp, name), "w") as f:
                f.write(name)
        self.sm = XeFMStateManager(db_path=os.path.join(self.cfgdir, "state.db"))
        self.backend = create_backend("memory")
        self.backend.open()
        self.app = xefm_app.XeFMApp(self.backend, self.tmp, self.tmp,
                                    left_provided=True, right_provided=True,
                                    state_manager=self.sm)
        self.app._settle_listings()

    def tearDown(self):
        try:
            self.app.file_monitor.stop_monitoring()
        except Exception:
            pass
        try:
            self.backend.close()
            if hasattr(self.sm, "close"):
                self.sm.close()
        except Exception:
            pass
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.cfgdir, ignore_errors=True)

    def contents(self):
        """name -> the name the file was created with."""
        out = {}
        for name in os.listdir(self.tmp):
            with open(os.path.join(self.tmp, name)) as f:
                out[name] = f.read()
        return out

    def prompt_rename(self, name, new):
        """Rename ``name`` to ``new`` through the prompt; returns its refusal,
        or None when it took the name."""
        pane = self.app.active_pane()
        pane["focused_index"] = next(i for i, f in enumerate(pane["files"])
                                     if f.name == name)
        prompt = _Type(new)
        with mock.patch.object(xefm_app, "show_input", prompt):
            self.app.rename()
        self.app._settle_listings()
        return prompt.refusal

    def batch_rename(self, search, replace):
        """Batch-rename every file with the two patterns; returns the preview
        row of each, by original name."""
        pane = self.app.active_pane()
        pane["selected_files"] = {str(f) for f in pane["files"]}
        batch = _BatchRenameImmediately(search, replace)
        with mock.patch.object(xefm_app, "show_batch_rename", batch):
            self.app.rename()  # >1 selected ⇒ the batch dialog
        self.app._settle_listings()
        return {row["original"]: row for row in batch.dialog.preview}


@unittest.skipUnless(_IGNORES_CASE, "needs a case-insensitive disk")
class ACaseOnlyRenameIsNotACollision(_Rename):
    names = ("foo.txt", "bar.txt")

    def test_the_rename_prompt_takes_it(self):
        self.assertIsNone(self.prompt_rename("foo.txt", "Foo.txt"))
        self.assertEqual(self.contents(),
                         {"Foo.txt": "foo.txt", "bar.txt": "bar.txt"})

    def test_the_batch_rename_dialog_takes_it(self):
        rows = self.batch_rename("^foo", "Foo")
        self.assertFalse(rows["foo.txt"]["conflict"])
        self.assertEqual(self.contents(),
                         {"Foo.txt": "foo.txt", "bar.txt": "bar.txt"})

    def test_another_file_under_another_case_still_collides(self):
        # On this disk BAR.txt is bar.txt, not the file being renamed.
        self.assertEqual(self.prompt_rename("foo.txt", "BAR.txt"),
                         "'BAR.txt' already exists")
        rows = self.batch_rename("^foo", "BAR")
        self.assertTrue(rows["foo.txt"]["conflict"])
        self.assertEqual(self.contents(),
                         {"foo.txt": "foo.txt", "bar.txt": "bar.txt"})


@unittest.skipIf(_IGNORES_CASE, "needs a case-sensitive disk")
class AFileThatDiffersOnlyInCaseStillCollides(_Rename):
    names = ("foo.txt", "Foo.txt")

    def test_the_rename_prompt_refuses_it(self):
        self.assertEqual(self.prompt_rename("foo.txt", "Foo.txt"),
                         "'Foo.txt' already exists")
        self.assertEqual(self.contents(),
                         {"foo.txt": "foo.txt", "Foo.txt": "Foo.txt"})

    def test_the_batch_rename_dialog_refuses_it(self):
        rows = self.batch_rename("^foo", "Foo")
        self.assertTrue(rows["foo.txt"]["conflict"])
        self.assertEqual(self.contents(),
                         {"foo.txt": "foo.txt", "Foo.txt": "Foo.txt"})


if __name__ == "__main__":
    unittest.main()

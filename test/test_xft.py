""".xft tree files (#573): the format, the xft:// scheme, and the pane.

Run with: python -m pytest test/test_xft.py -v
"""

import errno
import json
import os
import shutil
import sys
import tempfile
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import attributes, layouts, xft  # noqa: E402
from xefm import app as xefm_app  # noqa: E402
from xefm.path import Path  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402
from xefm.user_api import load_user_entries  # noqa: E402


def _doc(nodes, **top):
    data = {"format": "xft", "version": 1, "title": "Test", "nodes": nodes}
    data.update(top)
    return data


def _leaf(name, target, size=5, mtime=1_700_000_000.0, role="member", similarity=0.9):
    return {"name": name, "target": target, "attrs": {"size": size, "mtime": mtime},
            "extra": {"role": role, "similarity": similarity}}


class Format(unittest.TestCase):

    def test_duplicate_and_slashed_names_are_made_unique(self):
        doc = xft.parse(_doc([
            {"name": "a/b", "children": [_leaf("x", "/1"), _leaf("X", "/2"), _leaf("x", "/3")]},
            {"name": "a_b", "children": []},
        ]))
        names = [n.name for n in doc.root.children]
        self.assertEqual(names, ["a_b", "a_b [2]"])
        self.assertEqual([c.name for c in doc.root.children[0].children],
                         ["x", "X [2]", "x [3]"])

    def test_defaults_and_refusals(self):
        doc = xft.parse(_doc([]))
        self.assertTrue(doc.final and doc.complete)
        with self.assertRaises(ValueError):
            xft.parse({"format": "xft", "version": 2, "nodes": []})
        with self.assertRaises(ValueError):
            xft.parse({"format": "other"})

    def test_a_group_is_known_by_its_anchor(self):
        doc = xft.parse(_doc([
            {"name": "g (2)", "children": [_leaf("m", "/m"), _leaf("a", "/a", role="anchor")]},
        ]))
        self.assertEqual(doc.root.children[0].anchor_target(), "/a")
        self.assertEqual(xft.find_group(doc, "/a"), "g (2)")


class _Files(unittest.TestCase):

    def setUp(self):
        xft.forget()
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.real = os.path.join(self.tmp, "real")
        os.makedirs(os.path.join(self.real, "deep"))
        for rel in ("one.txt", os.path.join("deep", "two.txt")):
            with open(os.path.join(self.real, rel), "w") as f:
                f.write("content of " + rel)
        self.tree = os.path.join(self.tmp, "scan.xft")
        self._write([
            {"name": "one.txt (1)", "children": [
                _leaf("one.txt", os.path.join(self.real, "one.txt"), size=123, role="anchor",
                      similarity=1.0),
                _leaf("two.txt", os.path.join(self.real, "deep", "two.txt"), size=456),
            ]},
            {"name": "a folder", "target": self.real, "attrs": {"is_dir": True}},
        ])

    def tearDown(self):
        xft.forget()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write(self, nodes, **top):
        with open(self.tree, "w", encoding="utf-8") as f:
            json.dump(_doc(nodes, **top), f)
        xft.forget()

    def _at(self, key=""):
        return Path(xft.uri_for(self.tree) + key)


class Scheme(_Files):

    def test_browsing(self):
        top = self._at()
        self.assertTrue(top.exists() and top.is_dir())
        self.assertEqual(top.name, "scan.xft")
        self.assertEqual(str(top.parent), str(Path(self.tmp)))
        self.assertEqual(sorted(p.name for p in top.iterdir()), ["a folder", "one.txt (1)"])
        group = self._at("one.txt (1)")
        self.assertEqual([p.name for p in group.iterdir()], ["one.txt", "two.txt"])

    def test_a_reference_shows_what_was_recorded_and_reads_its_target(self):
        ref = self._at("one.txt (1)/two.txt")
        self.assertFalse(ref.is_dir())
        self.assertEqual(ref.stat().st_size, 456)        # recorded, not the real 23
        self.assertEqual(ref.read_text(), "content of " + os.path.join("deep", "two.txt"))
        self.assertEqual(str(ref.target()), os.path.join(self.real, "deep", "two.txt"))

    def test_nothing_inside_can_be_changed(self):
        ref = self._at("one.txt (1)/one.txt")
        for attempt in (ref.unlink, lambda: ref.rename(ref), lambda: ref.write_text("x"),
                        lambda: ref.open("w")):
            with self.assertRaises(OSError) as cm:
                attempt()
            self.assertEqual(cm.exception.errno, errno.EROFS)
        self.assertTrue(os.path.exists(os.path.join(self.real, "one.txt")))

    def test_a_rewrite_is_picked_up(self):
        self._write([{"name": "new", "children": []}])
        self.assertEqual([p.name for p in self._at().iterdir()], ["new"])

    def test_copying_out_copies_the_real_bytes(self):
        from puikit import Panel
        from puikit.backends.memory_backend import MemoryBackend
        from xefm import _config
        from xefm.file_operations import FileOperationService
        config = _config.Config()
        config.CONFIRM_COPY = False
        out = os.path.join(self.tmp, "out")
        os.makedirs(out)
        done = []
        FileOperationService(config).copy(
            Panel(MemoryBackend(width=80, height=24)), [self._at("one.txt (1)")],
            Path(out), on_complete=done.append, background=False)
        self.assertEqual(done[0]["failed"], 0)
        with open(os.path.join(out, "one.txt (1)", "two.txt")) as f:
            self.assertEqual(f.read(), "content of " + os.path.join("deep", "two.txt"))

    def test_targets_of_ordinary_paths_are_none(self):
        self.assertIsNone(Path(self.real).target())


SIMILARITY = {"similarity": {"label": "Similarity", "type": "ratio",
                              "show": {"columns": [{"before": "size"}]}}}


def _reset_declared():
    attributes._declared.clear()
    layouts._declared_specs.clear()
    layouts._declared.clear()
    layouts.clear()


class Declared(_Files):
    """Attributes a tree declares (``attributes``): XeFM knows none of them."""

    def setUp(self):
        super().setUp()
        _reset_declared()

    def tearDown(self):
        _reset_declared()
        load_user_entries(types.SimpleNamespace())
        super().tearDown()

    def _value(self, key, name="xft.similarity"):
        path = self._at(key)
        return attributes.get(name).sync(path, {}) if attributes.get(name) else None

    def test_nothing_is_known_until_a_tree_declares_it(self):
        xft.load(self.tree)
        self.assertIsNone(attributes.get("xft.similarity"))
        self.assertNotIn("xft.similarity", [e.name for e in layouts.all_extras()])

    def test_a_declared_attribute_reads_extra_and_its_extra_shows_it(self):
        self._write(self._nodes(), attributes=SIMILARITY)
        xft.load(self.tree)
        attr = attributes.get("xft.similarity")
        self.assertEqual((attr.label, attr.type), ("Similarity", "ratio"))
        self.assertEqual(self._value("one.txt (1)/one.txt"), 1.0)
        self.assertEqual(self._value("one.txt (1)/two.txt"), 0.9)
        extra = layouts.get_extra("xft.similarity")
        self.assertEqual([(c.column.attr, c.before) for c in extra.columns],
                         [("xft.similarity", "size")])
        self.assertTrue(layouts.applies(extra, self._at("one.txt (1)")))
        self.assertFalse(layouts.applies(extra, Path(self.real)))
        details = dict(xft.XftPathImpl(str(self._at("one.txt (1)/two.txt"))).get_extended_metadata()["details"])
        self.assertEqual(details["Similarity"], "90%")

    def test_a_tree_that_shows_nothing_still_defines_the_attribute(self):
        self._write(self._nodes(), attributes={"similarity": {"type": "ratio"}})
        xft.load(self.tree)
        self.assertEqual(self._value("one.txt (1)/two.txt"), 0.9)
        self.assertIsNone(layouts.get_extra("xft.similarity"))

    def test_values_of_the_wrong_type_are_none(self):
        self._write([{"name": "g", "children": [
            {"name": "none", "target": "/n"},
            {"name": "flag", "target": "/f", "extra": {"similarity": True}},
            {"name": "word", "target": "/w", "extra": {"similarity": "high"}},
        ]}], attributes=SIMILARITY)
        xft.load(self.tree)
        for name in ("g", "g/none", "g/flag", "g/word", "g/gone"):
            self.assertIsNone(self._value(name), name)

    def test_a_bad_declaration_is_left_out_with_a_warning(self):
        bad = {"a": {"type": "tags"}, "b": {"type": "ratio", "show": {"columns": [{"when": "always"}]}},
               "c": {"type": "ratio", "show": {"columns": [{"format": "clock"}]}}}
        self._write(self._nodes(), attributes=bad)
        with self.assertLogs(xft.logger, "WARNING") as logs:
            xft.load(self.tree)
        self.assertIsNone(attributes.get("xft.a"))
        self.assertIsNone(attributes.get("xft.b"))
        self.assertIsNone(layouts.get_extra("xft.c"))
        self.assertEqual(len(logs.output), 3)

    def test_config_names_them_before_any_tree_and_overrides_key_by_key(self):
        result = load_user_entries(types.SimpleNamespace(
            LAYOUTS={"mine": {"columns": ["name", "xft.similarity"]}},
            LAYOUT_EXTRAS={"xft.similarity": {"when": "never"}}))
        self.assertEqual(result.warnings, [])
        self._write(self._nodes(), attributes=SIMILARITY)
        xft.load(self.tree)
        extra = layouts.get_extra("xft.similarity")
        self.assertEqual(extra.when, "never")
        self.assertEqual(extra.columns[0].before, "size")
        problems = load_user_entries(types.SimpleNamespace(
            ATTRIBUTES={"xft.x": {"read": lambda d, e: []}})).warnings
        self.assertTrue(any("declared by the files" in w for w in problems), problems)

    def test_a_config_reload_keeps_what_trees_declared(self):
        self._write(self._nodes(), attributes=SIMILARITY)
        xft.load(self.tree)
        load_user_entries(types.SimpleNamespace())
        self.assertIsNotNone(attributes.get("xft.similarity"))
        self.assertIsNotNone(layouts.get_extra("xft.similarity"))

    def test_percent_rounds_down_so_only_a_match_says_100(self):
        attr = attributes.Attribute("r", "R", "ratio")
        cell = lambda v: layouts.render(layouts.resolve_format(None, attr), v,
                                        layouts.Row(attr=attr), lambda: None)
        self.assertEqual([c.text for c in cell(0.996)], ["99%"])
        self.assertEqual([c.text for c in cell(1.0)], ["100%"])
        self.assertEqual([c.text for c in cell(0.29)], ["29%"])
        self.assertEqual(cell(None), [])
        self.assertEqual(layouts.resolve_format("decimal", attr).align, "right")
        self.assertEqual(layouts.words(attr, 0.93), "93%")

    def _nodes(self):
        return [{"name": "one.txt (1)", "children": [
            _leaf("one.txt", os.path.join(self.real, "one.txt"), role="anchor", similarity=1.0),
            _leaf("two.txt", os.path.join(self.real, "deep", "two.txt")),
        ]}]


class InThePane(_Files):

    def setUp(self):
        super().setUp()
        from puikit.backends import create_backend
        self.state = tempfile.mkdtemp()
        self.b = create_backend("memory")
        self.b.open()
        self.app = xefm_app.XeFMApp(
            self.b, self.tmp, self.tmp, left_provided=True, right_provided=True,
            state_manager=XeFMStateManager(db_path=os.path.join(self.state, "s.db")))
        self.app.file_monitor.stop_monitoring()
        self.app.file_monitor.enabled = False
        self.app._settle_listings()
        self.pane = self.app.active_pane()

    def tearDown(self):
        self.app.file_monitor.stop_monitoring()
        self.b.close()
        shutil.rmtree(self.state, ignore_errors=True)
        super().tearDown()

    def _focus(self, name):
        self.pane["focused_index"] = [f.name for f in self.pane["files"]].index(name)

    def _enter(self, name):
        self._focus(name)
        self.app.dispatch("open_item")
        self.app._settle_listings()

    def _names(self, pane=None):
        return sorted(f.name for f in (pane or self.pane)["files"])

    def test_enter_goes_in_and_backspace_lands_on_the_file(self):
        self._enter("scan.xft")
        self.assertTrue(xft.is_xft_path(self.pane["path"]))
        self.assertEqual(self._names(), ["a folder", "one.txt (1)"])
        self._enter("one.txt (1)")
        self.assertEqual(self._names(), ["one.txt", "two.txt"])
        info = self.pane["file_info"][str(self.pane["files"][1])]
        self.assertFalse(info["is_dir"])
        self.app.dispatch("go_parent")
        self.app._settle_listings()
        self.app.dispatch("go_parent")
        self.app._settle_listings()
        self.assertEqual(str(self.pane["path"]), str(Path(self.tmp)))
        self.assertEqual(self.pane["files"][self.pane["focused_index"]].name, "scan.xft")

    def test_a_declared_attribute_is_a_column_and_a_sort(self):
        _reset_declared()
        self.addCleanup(_reset_declared)
        with open(self.tree) as f:
            data = json.load(f)
        self._write(data["nodes"], attributes=SIMILARITY)
        self._enter("scan.xft")
        self._enter("one.txt (1)")
        self.assertIn("xft.similarity", [e.name for e in layouts.active_extras(self.pane)])
        columns = [c.attr for c in layouts.effective(self.pane).columns]
        self.assertEqual(columns, ["name", "ext", "xft.similarity", "size", "mtime"])
        rows = {mode: (label, ready) for mode, label, ready, _note
                in self.app._attribute_sort_rows(self.pane)}
        self.assertEqual(rows[self.app._ATTR_SORT + "xft.similarity"], ("Similarity", True))
        store = attributes.store_of(self.pane)
        values = store.snapshot("xft.similarity", self.pane["files"], {})
        self.assertEqual(sorted(values.values()), [0.9, 1.0])

    def test_a_reference_to_a_folder_goes_there(self):
        self._enter("scan.xft")
        self._enter("a folder")
        self.assertEqual(str(self.pane["path"]), str(Path(self.real)))

    def test_shift_o_reveals_the_real_file_in_the_other_pane(self):
        self._enter("scan.xft")
        self._enter("one.txt (1)")
        self._focus("two.txt")
        self.app.dispatch("sync_other_to_current")
        self.app._settle_listings()
        other = self.app.pm.get_inactive_pane()
        self.assertEqual(str(other["path"]), str(Path(os.path.join(self.real, "deep"))))
        self.assertEqual(other["files"][other["focused_index"]].name, "two.txt")
        # The tree stays where it was.
        self.assertTrue(xft.is_xft_path(self.pane["path"]))

    def test_what_leaves_xefm_gets_the_real_file(self):
        """#612: the OS's open, the editor and a copied path get the file an
        entry stands for, not its xft:// address."""
        from unittest.mock import patch
        self._enter("scan.xft")
        self._enter("one.txt (1)")
        self._focus("two.txt")
        real = os.path.join(self.real, "deep", "two.txt")
        opened = []
        with patch.object(xefm_app.subprocess, "run",
                          lambda argv, **k: opened.append(argv)), \
                patch.object(xefm_app.platform, "system", lambda: "Darwin"), \
                patch.object(xefm_app, "get_program_for_file", lambda *a: None), \
                patch.object(xefm_app, "has_explicit_association", lambda *a: False):
            self.app.open_with_os()
            self.app.reveal_in_os()
        self.assertEqual(opened, [["open", real], ["open", "-R", real]])
        copied = []
        self.app._set_text_clipboard = copied.append
        self.app.copy_paths_to_clipboard()
        self.assertEqual(copied, [real])
        edited = []
        self.app._edit_entries = edited.append
        self.app.edit_file()
        self.assertEqual([str(p) for p in edited[0]], [real])

    def test_shift_o_on_a_selection_lists_every_target(self):
        self._enter("scan.xft")
        self._enter("one.txt (1)")
        for f in self.pane["files"]:
            self.pane["selected_files"].add(str(f))
        self.app.dispatch("sync_other_to_current")
        self.app._settle_listings()
        other = self.app.pm.get_inactive_pane()
        self.assertEqual(other["virtual"]["kind"], "list")
        self.assertEqual(sorted(str(f) for f in other["files"]), sorted([
            os.path.join(self.real, "one.txt"), os.path.join(self.real, "deep", "two.txt")]))

    def test_a_provisional_tree_says_so_and_asks_before_bulk_work(self):
        self._write([
            {"name": "g (1)", "children": [
                _leaf("one.txt", os.path.join(self.real, "one.txt"), role="anchor"),
                _leaf("two.txt", os.path.join(self.real, "deep", "two.txt")),
            ]},
        ], final=False, progress={"done": 3, "total": 12})
        self._enter("scan.xft")
        text = xefm_app._xft_header_text(self.pane["path"], 200)
        self.assertIn("groups may change", text)
        self.assertIn("25%", text)
        self._enter("g (1)")
        for f in self.pane["files"]:
            self.pane["selected_files"].add(str(f))
        self.app.dispatch("sync_other_to_current")
        self.app.panel.render()
        self.assertIn("still being written", "\n".join(self.b.snapshot()))
        from puikit import Event, EventType
        self.app.panel.dispatch_event(Event(type=EventType.KEY, key="enter"))  # Cancel
        self.assertIsNone(self.app.pm.get_inactive_pane().get("virtual"))

    def test_a_rewrite_follows_the_group_by_its_anchor(self):
        anchor = os.path.join(self.real, "one.txt")
        self._write([{"name": "one.txt (1)", "children": [
            _leaf("one.txt", anchor, role="anchor"),
            _leaf("two.txt", os.path.join(self.real, "deep", "two.txt"))]}], final=False)
        self._enter("scan.xft")
        self._enter("one.txt (1)")
        # The producer finds another member: the group's name changes.
        self._write([{"name": "one.txt (2)", "children": [
            _leaf("one.txt", anchor, role="anchor"),
            _leaf("two.txt", os.path.join(self.real, "deep", "two.txt")),
            _leaf("three.txt", "/elsewhere/three.txt")]}], final=False)
        self.app._xft_dirty = True
        self.app._pump_xft()
        self.app._settle_listings()
        self.assertTrue(str(self.pane["path"]).endswith("#one.txt (2)"))
        self.assertEqual(self._names(), ["one.txt", "three.txt", "two.txt"])

    def test_a_group_that_is_gone_returns_to_the_top(self):
        self._write([{"name": "g", "children": [
            _leaf("one.txt", os.path.join(self.real, "one.txt"), role="anchor")]}], final=False)
        self._enter("scan.xft")
        self._enter("g")
        self._write([{"name": "other", "children": [
            _leaf("x", "/x", role="anchor")]}], final=False)
        self.app._xft_dirty = True
        self.app._pump_xft()
        self.app._settle_listings()
        self.assertTrue(str(self.pane["path"]).endswith("#"))
        self.assertIn("back at the top", self.app.log.lines[-1][0])


if __name__ == "__main__":
    unittest.main()

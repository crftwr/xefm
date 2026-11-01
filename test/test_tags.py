"""File tags (#585): the stores (Finder, XDG, NTFS stream, SSH, S3), the edit
helpers, carrying tags on copy, the file list's tag cache, and the B / J
integration.

Store tests that need the real OS facility skip elsewhere: Finder tags run on
macOS, XDG tags on Linux. The NTFS-stream store is exercised through its file
format (on a non-Windows system ``name:xefm.tags`` is an ordinary file); the
SSH store runs its remote scripts through a local ``sh``.

Run with: python -m pytest test/test_tags.py -v
"""

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from xefm import tags  # noqa: E402
from xefm.tags import Tag  # noqa: E402

DARWIN = sys.platform == "darwin"
LINUX = sys.platform.startswith("linux")


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def file(self, name="a.txt"):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as f:
            f.write(name)
        return path


class Helpers(unittest.TestCase):
    def test_finder_format_round_trips(self):
        tagged = [Tag("Work"), Tag("Red", 6), Tag("日本語", 4)]
        self.assertEqual(tags.parse_finder(tags.format_finder(tagged)), tagged)

    def test_finder_parse_tolerates_junk(self):
        self.assertEqual(tags.parse_finder(b"not a plist"), [])
        import plistlib
        self.assertEqual(tags.parse_finder(plistlib.dumps(["A\n99", 3, ""])),
                         [Tag("A", 0)])

    def test_a_tag_without_a_color_is_written_as_finder_writes_it(self):
        """Finder shows a colorless tag only as "Name\n0" (#605)."""
        import plistlib
        data = tags.format_finder([Tag("Work"), Tag("Red", 6)])
        self.assertEqual(plistlib.loads(data), ["Work\n0", "Red\n6"])

    def test_apply_change_ignores_case_and_keeps_order(self):
        cur = [Tag("Work"), Tag("Red", 6)]
        self.assertEqual(tags.apply_change(cur, add=[Tag("work"), Tag("New")],
                                           remove=["red"]),
                         [Tag("Work"), Tag("New")])

    def test_parse_names(self):
        self.assertEqual(tags.parse_names(" a, b ,,A, c "), ["a", "b", "c"])

    def test_common(self):
        self.assertEqual(tags.common([[Tag("a"), Tag("b")], [Tag("B"), Tag("c")]]),
                         [Tag("b")])
        self.assertEqual(tags.common([]), [])

    def test_new_tag_colors(self):
        finder = tags.NtfsStreamTags()   # a store with colors
        self.assertEqual(tags.new_tag("Red", finder), Tag("Red", 6))
        self.assertEqual(tags.new_tag("work", finder, [Tag("Work", 4)]), Tag("work", 4))
        self.assertEqual(tags.new_tag("Red", tags.XdgTags()), Tag("Red", 0))

    def test_recolor_and_the_color_choices(self):
        current = [Tag("Keep", 6), Tag("Work")]
        self.assertEqual(tags.recolor(current, "work", 4), [Tag("Keep", 6), Tag("Work", 4)])
        self.assertEqual(sorted(tags.COLOR_CHOICES), sorted(tags.COLORS))
        self.assertEqual(tags.COLOR_CHOICES[0], 0, "none comes first")
        self.assertEqual(tags.names_color("Grey"), 1)
        self.assertEqual(tags.names_color("Work"), 0)

    def test_rename_keeps_place_and_color_and_merges(self):
        self.assertEqual(tags.rename([Tag("A"), Tag("Work", 4), Tag("B")], "work", "Job"),
                         [Tag("A"), Tag("Job", 4), Tag("B")])
        self.assertEqual(tags.rename([Tag("Work", 4), Tag("job", 6)], "Work", "Job"),
                         [Tag("job", 6)])
        self.assertEqual(tags.rename([Tag("work", 4)], "work", "Work"), [Tag("Work", 4)])

    def test_store_for(self):
        self.assertIs(tags.store_for("s3://bucket/key.txt"), tags._s3)
        self.assertIsNone(tags.store_for("s3://bucket/"))
        self.assertIs(tags.store_for("ssh://host/a"), tags._ssh)
        self.assertIsNone(tags.store_for("archive:///x.zip#a.txt"))
        with patch.object(sys, "platform", "win32"):
            self.assertIs(tags.store_for("C:\\a.txt"), tags._ntfs)


@unittest.skipUnless(DARWIN, "Finder tags are macOS")
class FinderStore(_Tmp):
    def test_write_read_remove(self):
        path = self.file()
        store = tags.store_for(path)
        self.assertIsInstance(store, tags.FinderTags)
        self.assertEqual(store.read(path), [])
        store.write(path, [Tag("Work"), Tag("Red", 6)])
        self.assertEqual(store.read(path), [Tag("Work"), Tag("Red", 6)])
        out = subprocess.run(["xattr", "-p", "com.apple.metadata:_kMDItemUserTags", path],
                             capture_output=True)
        self.assertEqual(out.returncode, 0, "what Finder reads is there")
        store.write(path, [])
        self.assertEqual(store.read(path), [])
        store.write(path, [])  # removing nothing is fine

    def test_missing_file_is_an_error(self):
        with self.assertRaises(tags.TagError):
            tags.FinderTags().read(os.path.join(self.tmp, "nope"))


@unittest.skipUnless(LINUX and hasattr(os, "setxattr"), "user.xdg.tags is Linux")
class XdgStore(_Tmp):
    def test_write_read_remove(self):
        path = self.file()
        store = tags.XdgTags()
        try:
            store.write(path, [Tag("Work"), Tag("Red", 6)])
        except tags.TagError as exc:
            self.skipTest(f"no user xattrs on this filesystem: {exc}")
        self.assertEqual(os.getxattr(path, "user.xdg.tags"), b"Work,Red")
        self.assertEqual(store.read(path), [Tag("Work"), Tag("Red")])
        store.write(path, [])
        self.assertEqual(store.read(path), [])


class NtfsStreamStore(_Tmp):
    def test_round_trip_and_remove(self):
        path = self.file()
        store = tags.NtfsStreamTags()
        self.assertEqual(store.read(path), [])
        store.write(path, [Tag("Work"), Tag("Red", 6)])
        self.assertEqual(store.read(path), [Tag("Work"), Tag("Red", 6)])
        store.write(path, [])
        self.assertEqual(store.read(path), [])
        self.assertFalse(os.path.exists(path + ":xefm.tags"))


class _LocalShell:
    """A stand-in SSH connection that runs the remote command with ``sh``."""
    hostname = "local"

    def __init__(self):
        self.commands = []

    def run_remote(self, command, **kwargs):
        self.commands.append(command)
        return subprocess.run(["sh", "-c", command], capture_output=True)


class _SshPath:
    def __init__(self, remote, conn):
        self.remote_path, self.hostname, self._conn = remote, "local", conn

    def _get_connection(self):
        return self._conn

    def __str__(self):
        return f"ssh://local{self.remote_path}"


class SshStore(_Tmp):
    @unittest.skipUnless(DARWIN, "the macOS branch runs xattr locally")
    def test_macos_host_round_trip_in_one_command_each(self):
        conn = _LocalShell()
        store = tags.SshTags()
        a = _SshPath(self.file("a b.txt"), conn)
        c = _SshPath(self.file("c.txt"), conn)
        self.assertEqual(store.write_many([(a, [Tag("Work"), Tag("Red", 6)]),
                                           (c, [])]), [])
        found = store.read_many([a, c])
        self.assertEqual(found[str(a)], [Tag("Work"), Tag("Red", 6)])
        self.assertEqual(found[str(c)], [])
        self.assertEqual(tags.FinderTags().read(a.remote_path),
                         [Tag("Work"), Tag("Red", 6)], "Finder sees the same tags")
        self.assertEqual(len(conn.commands), 3, "probe once, then one command per batch")

    def test_linux_host_parsing(self):
        """The Linux branch, fed canned getfattr output."""
        store = tags.SshTags()
        store._hosts["local"] = ("Linux", {"getfattr", "setfattr"})

        class Canned:
            hostname = "local"

            def run_remote(self, command, **kwargs):
                if command.startswith("getfattr -R"):
                    out = (b"# file: /d/a\\303\\244.txt\n"
                           b'user.xdg.tags="Work,Red"\n\n'
                           b"# file: /d/b.txt\n"
                           b'user.xdg.tags="Other"\n')
                else:
                    out = b"/d/a.txt\0Work,Red\0/d/b.txt\0\0"
                return subprocess.CompletedProcess([], 0, out, b"")

        conn = Canned()
        a, b = _SshPath("/d/a.txt", conn), _SshPath("/d/b.txt", conn)
        found = store.read_many([a, b])
        self.assertEqual(found[str(a)], [Tag("Work"), Tag("Red")])
        self.assertEqual(found[str(b)], [])
        self.assertEqual(store.find(_SshPath("/d", conn), "work"),
                         ["ssh://local/d/aä.txt"])

    def test_a_missing_tool_names_the_package(self):
        store = tags.SshTags()
        store._hosts["local"] = ("Linux", set())
        found = store.read_many([_SshPath("/a", _LocalShell())])
        error = found["ssh://local/a"]
        self.assertIsInstance(error, tags.TagError)
        self.assertIn("'attr' package", str(error))


class S3Store(unittest.TestCase):
    def test_tags_are_valueless_keys_and_other_tags_are_kept(self):
        calls = []

        class Client:
            def get_object_tagging(self, **kw):
                return {"TagSet": [{"Key": "Work", "Value": ""},
                                   {"Key": "owner", "Value": "ops"}]}

            def put_object_tagging(self, **kw):
                calls.append(kw)

        class Impl:
            _bucket, _key = "b", "k.txt"

            def _client(self):
                return Client()

        store = tags.S3Tags()
        self.assertEqual(store.read(Impl()), [Tag("Work")])
        store.write(Impl(), [Tag("New")])
        self.assertEqual(calls[0]["Tagging"]["TagSet"],
                         [{"Key": "owner", "Value": "ops"}, {"Key": "New", "Value": ""}])


class Carry(_Tmp):
    def test_tags_follow_a_copy(self):
        src, dest = self.file("a.txt"), self.file("b.txt")
        store = tags.store_for(src)
        if store is None or not store.cheap:
            self.skipTest("no local tag store here")
        try:
            store.write(src, [Tag("Work"), Tag("Red", 6)])
        except tags.TagError as exc:
            self.skipTest(f"no tags on this filesystem: {exc}")
        tags.carry(src, dest)
        self.assertEqual([t.name for t in store.read(dest)], ["Work", "Red"])

    def test_untagged_source_writes_nothing(self):
        with patch.object(tags, "store_for") as store_for:
            store = store_for.return_value
            store.read.return_value = []
            tags.carry("a", "b")
            store.write.assert_not_called()


class Cache(unittest.TestCase):
    """The file list reads tags as the ``tags`` attribute (xefm.attributes)."""

    def test_reads_off_thread_then_answers(self):
        from xefm import attributes
        from xefm.path import Path
        ready = threading.Event()
        attributes.on_ready = ready.set
        try:
            store = attributes.AttributeStore()
            path = Path("/a")
            files = [path]
            records = {"/a": {"is_dir": False, "ok": True, "size": 1, "mtime": 1.0}}
            with patch.object(tags, "store_for", return_value=tags.XdgTags()), \
                 patch.object(tags, "read", return_value=[Tag("Work")]):
                store.sync(files, records, "/", {"tags"})
                self.assertTrue(ready.wait(2))
                self.assertEqual(store.get(path, records["/a"], "tags"), [Tag("Work")])
            self.assertIn("work", tags.SEEN)
        finally:
            attributes.on_ready = None

    def test_costly_stores_are_skipped(self):
        from xefm import attributes
        attr = attributes.get("tags")
        with patch.object(tags, "store_for", return_value=tags.S3Tags()):
            self.assertFalse(attr.applies_to("s3://b/k"))
        with patch.object(tags, "store_for", return_value=None):
            self.assertFalse(attr.applies_to("/a"))


class AppIntegration(_Tmp):
    """B toggles and edits tags; J lists tags; picking one finds the files."""

    def setUp(self):
        super().setUp()
        from puikit.backends import create_backend
        from xefm import app as xefm_app
        from xefm import favorites
        from xefm.state_manager import XeFMStateManager
        self.file("a.txt")
        self.file("b.txt")
        os.mkdir(os.path.join(self.tmp, "sub"))
        self.deep = self.file(os.path.join("sub", "deep.txt"))
        store = tags.store_for(self.deep)
        if store is None or not store.cheap:
            self.skipTest("no local tag store here")
        try:
            store.write(self.deep, [])
        except tags.TagError as exc:
            self.skipTest(f"no tags on this filesystem: {exc}")
        self.store = store
        self.state_dir = tempfile.mkdtemp()
        self.sm = XeFMStateManager(db_path=os.path.join(self.state_dir, "state.db"))
        patcher = patch.object(favorites, "get_config_favorites", lambda: [])
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(favorites, "get_state_manager", lambda: self.sm)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.b = create_backend("memory")
        self.b.open()
        self.app = xefm_app.XeFMApp(self.b, self.tmp, self.tmp,
                                    left_provided=True, right_provided=True,
                                    state_manager=self.sm)
        self.app.file_monitor.stop_monitoring()
        self.app.file_monitor.enabled = False
        self.app._settle_listings()

    def tearDown(self):
        try:
            self.app.file_monitor.stop_monitoring()
            self.b.close()
        except Exception:
            pass
        shutil.rmtree(getattr(self, "state_dir", ""), ignore_errors=True)
        super().tearDown()

    def top(self):
        return self.app.panel._layers[-1].widget

    def focus(self, name):
        pane = self.app.active_pane()
        pane["focused_index"] = [f.name for f in pane["files"]].index(name)

    def drain(self):
        deadline = time.time() + 5
        while self.app.tasks.has_active() and time.time() < deadline:
            self.b.run_animation_ticks()
            time.sleep(0.005)
        self.b.run_animation_ticks()

    def choose(self, label_part):
        from xefm.choice_dialog import ChoiceDialog, label_text
        dialog = self.top()
        self.assertIsInstance(dialog, ChoiceDialog)
        labels = [label_text(label) for _, label in dialog._rows]
        index = next(i for i, label in enumerate(labels) if label_part in label)
        dialog._index = index
        dialog._accept()

    def test_b_edits_then_toggles_tags(self):
        from xefm.input_dialog import InputDialog
        self.focus("a.txt")
        a = os.path.join(self.tmp, "a.txt")
        self.app.add_favorite()
        self.choose("Edit tags…")
        dialog = self.top()
        self.assertIsInstance(dialog, InputDialog)
        dialog.edit.text = "Work, Red"
        dialog._accept()
        self.assertEqual([t.name for t in self.store.read(a)], ["Work", "Red"])
        if self.store.has_colors:
            self.assertEqual(self.store.read(a)[1].color, 6, "Red gets Finder's red")
        # Known now: B offers it as a toggle, checked, and choosing it removes it.
        self.app.add_favorite()
        self.choose("✓ ● Work")
        self.assertEqual([t.name for t in self.store.read(a)], ["Red"])

    def test_b_on_a_selection_tags_every_item(self):
        pane = self.app.active_pane()
        pane["selected_files"] = {str(f) for f in pane["files"]
                                  if f.name in ("a.txt", "b.txt")}
        self.app._remember_tags([Tag("Shared")])
        self.app.add_favorite()
        self.choose("Shared")
        for name in ("a.txt", "b.txt"):
            self.assertEqual([t.name for t in self.store.read(
                os.path.join(self.tmp, name))], ["Shared"])

    def test_search_tags_lists_the_tag_and_finds_tagged_files_below(self):
        """Search Tags (#605) is its own action: J goes to places only."""
        self.store.write(self.deep, [Tag("Deep")])
        self.app._remember_tags([Tag("Deep")])
        self.app.show_favorites()
        dialog = self.top()
        labels = [dialog.to_label(r) for r in getattr(dialog, "all_items", [])]
        self.assertFalse(any("Deep" in label for label in labels), labels)
        self.app.panel.pop_layer()
        self.app.dispatch("find_by_tag")
        dialog = self.top()
        labels = [dialog.to_label(r) for r in dialog.all_items]
        self.assertTrue(any(label.startswith("Deep") for label in labels), labels)
        self.app.panel.pop_layer()
        with patch.object(type(self.store), "find", return_value=None):
            self.app.find_by_tag("deep")
            self.drain()
        self.app._settle_listings()
        pane = self.app.active_pane()
        self.assertTrue(pane.get("virtual"))
        self.assertEqual([str(f) for f in pane["files"]], [self.deep])

    def tag_two_files_work(self):
        a = os.path.join(self.tmp, "a.txt")
        for path in (a, self.deep):
            self.store.write(path, [Tag("Keep"), Tag("Work")])
        self.app._remember_tags([Tag("Work")])
        return a

    def test_a_new_tag_gets_its_color_chosen(self):
        """#792: Edit tags… asks a new tag's color, where the store keeps one."""
        self.focus("a.txt")
        a = os.path.join(self.tmp, "a.txt")
        self.app.add_favorite()
        self.choose("Edit tags…")
        dialog = self.top()
        dialog.edit.text = "Project, Red"
        dialog._accept()
        if self.store.has_colors:
            self.assertEqual(self.top().title, "Color of tag Project",
                             "asked for the new tag only: Red has its color")
            self.choose("Blue")
        self.assertFalse(self.app.panel.has_layers, "every dialog closed")
        got = self.store.read(a)
        self.assertEqual([t.name for t in got], ["Project", "Red"])
        if self.store.has_colors:
            self.assertEqual(got[0].color, 4)
            self.assertIn(["Project", 4], self.sm.get_state("tags.known"))

    def test_manage_recolors_the_tag_on_every_file(self):
        if not self.store.has_colors:
            self.skipTest("this store keeps no colors")
        a = self.tag_two_files_work()
        self.focus("a.txt")
        with patch.object(type(self.store), "find_everywhere", return_value=None), \
             patch.object(type(self.store), "find", return_value=None):
            self.app.add_favorite()
            self.choose("Manage tags…")
            self.choose("Work")
            self.choose("Change color…")
            self.choose("Green")
            self.drain()
        for path in (a, self.deep):
            self.assertEqual(self.store.read(path), [Tag("Keep"), Tag("Work", 2)])
        self.assertEqual(self.sm.get_state("tags.known")[0], ["Work", 2])

    def test_manage_deletes_the_tag_from_every_file_after_asking(self):
        from puikit.widgets.message_box import MessageBox
        a = self.tag_two_files_work()
        with patch.object(type(self.store), "find_everywhere", return_value=None), \
             patch.object(type(self.store), "find", return_value=None):
            self.app._manage_tags(self.app.active_pane()["path"])
            self.choose("Work")
            self.choose("Delete tag…")
            self.drain()
            box = self.top()
            self.assertIsInstance(box, MessageBox)
            self.assertIn("from 2 item(s)", box.message)
            self.assertEqual([t.name for t in self.store.read(a)], ["Keep", "Work"],
                             "nothing changes before Delete")
            box._close(box.buttons.index("Delete"))
            self.drain()
        for path in (a, self.deep):
            self.assertEqual([t.name for t in self.store.read(path)], ["Keep"])
        self.assertNotIn("work", [str(i[0]).casefold()
                                  for i in self.sm.get_state("tags.known", [])])

    def test_manage_renames_the_tag_on_every_file(self):
        a = self.tag_two_files_work()
        with patch.object(type(self.store), "find_everywhere", return_value=None), \
             patch.object(type(self.store), "find", return_value=None):
            self.app._manage_tags(self.app.active_pane()["path"])
            self.choose("Work")
            self.choose("Rename tag…")
            dialog = self.top()
            dialog.edit.text = "Job"
            dialog._accept()
            self.drain()
        for path in (a, self.deep):
            self.assertEqual([t.name for t in self.store.read(path)], ["Keep", "Job"])
        names = [str(i[0]) for i in self.sm.get_state("tags.known", [])]
        self.assertIn("Job", names)
        self.assertNotIn("Work", names)

    def test_manage_is_offered_with_nothing_to_tag(self):
        pane = self.app.active_pane()
        pane["focused_index"] = 0
        pane["files"] = []
        rows = self.app._tag_rows(pane)
        self.assertEqual([v for v, _ in rows], [("tag-manage", None)])

    def test_tag_dialogs_draw_colored_dots(self):
        """The B rows, the color picker and Manage Tags lead each tag with its
        dot (#792), in its color."""
        self.app._remember_tags([Tag("Urgent", 6), Tag("Plain")])
        self.focus("a.txt")
        rows = dict(self.app._tag_rows(self.app.active_pane()))
        runs = {v[1][0].name: label for v, label in rows.items() if v[0] == "tag-toggle"}
        self.assertEqual(runs["Urgent"][1], ("●", tags.RGB["red"]))
        self.assertEqual(runs["Plain"][1], ("●", None), "no color: the muted ink")
        self.app._choose_tag_color("Work", 0, lambda c: None)
        labels = [label for _, label in self.top()._rows]
        self.assertEqual(labels[0], [("●", None), " None"])
        self.app.panel.render()  # the runs draw
        self.app.panel.pop_layer()
        self.app._manage_tags(self.app.active_pane()["path"])
        rows = {v.name: label for v, label in self.top()._rows}
        self.assertEqual(rows["Urgent"], [("●", tags.RGB["red"]), " Urgent"],
                         "Manage Tags marks each tag with its dot")
        self.app.panel.pop_layer()
        self.app.dispatch("find_by_tag")
        rows = {r[0]: r for r in self.top().list.items}
        self.assertEqual(rows["Urgent"][2], [("●", tags.RGB["red"])],
                         "so does Search Tags")
        self.app.panel.render()  # the marks draw

    def test_unsupported_places_offer_no_tag_rows(self):
        with patch.object(tags, "store_for", return_value=None):
            rows = self.app._tag_rows(self.app.active_pane())
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()


class CarryAheadBatches(unittest.TestCase):
    def test_reads_in_batches_and_a_failed_batch_is_not_retried_per_file(self):
        class Costly(tags.TagStore):
            cheap = False

            def __init__(self):
                self.calls = []

            def read(self, path):
                raise AssertionError("read one at a time")

            def read_many(self, paths):
                self.calls.append(len(paths))
                raise tags.TagError(5, "ssh failed")

        source, dest = Costly(), Mock()
        ahead = tags.CarryAhead()
        ahead.BATCH = 2
        with patch.object(tags, "store_for",
                          side_effect=lambda p: source if p.startswith("s") else dest):
            ahead.read([(f"s{i}", f"d{i}") for i in range(5)])
            with patch.object(tags.logger, "warning") as warning:
                ahead.carry("s0", "d0")
        self.assertEqual(source.calls, [2, 2, 1])
        warning.assert_called_once()
        dest.write.assert_not_called()

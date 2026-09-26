"""A list of paths from outside XeFM, shown as a pane (#453).

Two halves. :mod:`xefm.path_list` is pure — parsing, resolving, the common
root, the probe — and is tested here with no app at all. The app half is the
clipboard import and ``PaneApi.open_list``, driven headless on the ``memory``
backend as ``test_search_results_pane.py`` does.

Remote rows are exercised through a scheme registered for the test, never a
real ``ssh://`` or ``s3://``: what is under test is that a URI row goes through
the same door as a local one, and that a location which cannot be reached costs
one attempt, not one per row.

Run with: python -m pytest test/test_path_list.py -v
"""

import os
import shutil
import sys
import tempfile
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))

from xefm import _config, name_key, path_list, path_schemes  # noqa: E402
from xefm import app as xefm_app  # noqa: E402
from xefm.file_list_manager import FileListManager  # noqa: E402
from xefm.path import Path  # noqa: E402
from xefm.path_base import ReadOnlyPathImpl, UriStatResult  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402
from xefm.user_api import PaneApi  # noqa: E402


# --------------------------------------------------------------------------- #
# A remote location, registered for the test
# --------------------------------------------------------------------------- #

#: host -> the keys that exist there. A host missing from here is "down".
FILES = {}
#: How many times a down host was asked anything — the probe should ask once.
DOWN_CALLS = []


class RemotePathImpl(ReadOnlyPathImpl):
    """``fake://host/key`` — ssh's shape, a host as the root, with no network."""

    SCHEME = "fake"

    def _parse(self, uri):
        rest = uri[len("fake://"):]
        self._host, _, key = rest.partition("/")
        return key

    def _root_prefix(self):
        return f"fake://{self._host}/"

    def _check(self):
        if self._host not in FILES:
            DOWN_CALLS.append(self._host)
            raise ConnectionError(f"{self._host} is unreachable")

    def exists(self):
        self._check()
        return self._key == "" or self._key in FILES[self._host]

    def is_dir(self):
        self._check()
        return self._key == ""

    def iterdir(self):
        return iter(())

    def stat(self):
        if not self.exists():
            raise FileNotFoundError(str(self))
        return UriStatResult(size=7, is_dir=self.is_dir())

    def open(self, *args, **kwargs):
        raise OSError("not in this test")


class RemoteScheme(unittest.TestCase):
    """Registers ``fake://`` for the length of each test."""

    def setUp(self):
        FILES.clear()
        DOWN_CALLS.clear()
        path_schemes.register("fake", RemotePathImpl, source="test")

    def tearDown(self):
        path_schemes.unregister_source("test")


# --------------------------------------------------------------------------- #
# parse
# --------------------------------------------------------------------------- #

class Parse(unittest.TestCase):
    def test_one_path_per_line_blank_lines_skipped(self):
        self.assertEqual(path_list.parse("/a/x\n\n  \n/b/y\n"), ["/a/x", "/b/y"])

    def test_windows_line_endings(self):
        self.assertEqual(path_list.parse("C:\\a\\x\r\nC:\\b\\y\r\n"),
                         ["C:\\a\\x", "C:\\b\\y"])

    def test_surrounding_whitespace_and_one_pair_of_quotes_go(self):
        # What Explorer's "Copy as path" and a shell's quoting add.
        self.assertEqual(path_list.parse('  "C:\\a b\\x"  \n\'/c d/y\''),
                         ["C:\\a b\\x", "/c d/y"])

    def test_unmatched_quotes_are_part_of_the_path(self):
        self.assertEqual(path_list.parse('"/a/x'), ['"/a/x'])

    def test_a_path_listed_twice_is_kept_once(self):
        self.assertEqual(path_list.parse("/a/x\n/b/y\n/a/x"), ["/a/x", "/b/y"])

    def test_nothing(self):
        self.assertEqual(path_list.parse(""), [])
        self.assertEqual(path_list.parse(None), [])
        self.assertEqual(path_list.parse("\n \n"), [])


# --------------------------------------------------------------------------- #
# resolve
# --------------------------------------------------------------------------- #

class Resolve(RemoteScheme):
    def setUp(self):
        super().setUp()
        self.base = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)
        super().tearDown()

    def test_an_absolute_path_stands_as_it_is(self):
        absolute = os.path.join(self.base, "x.txt")
        got = path_list.resolve([absolute], "/somewhere/else")
        self.assertEqual([str(p) for p in got.paths], [absolute])
        self.assertEqual(got.relative, 0)

    def test_a_relative_path_joins_the_base_and_is_counted(self):
        got = path_list.resolve(["src/main.py"], self.base)
        self.assertEqual(str(got.paths[0]),
                         str(Path(self.base) / "src/main.py"))
        self.assertEqual(got.relative, 1)

    def test_a_uri_stands_as_it_is(self):
        got = path_list.resolve(["fake://h/a/b.txt"], self.base)
        self.assertEqual([str(p) for p in got.paths], ["fake://h/a/b.txt"])
        self.assertIsInstance(got.paths[0]._impl, RemotePathImpl)
        self.assertEqual(got.relative, 0)

    def test_a_relative_path_on_a_remote_base_resolves_remotely(self):
        got = path_list.resolve(["sub/c.txt"], Path("fake://h/dir"))
        self.assertEqual(str(got.paths[0]), "fake://h/dir/sub/c.txt")

    def test_two_lines_naming_one_place_are_kept_once(self):
        absolute = str(Path(self.base) / "x.txt")
        got = path_list.resolve(["x.txt", absolute], self.base)
        self.assertEqual(len(got.paths), 1)


# --------------------------------------------------------------------------- #
# common_root
# --------------------------------------------------------------------------- #

class CommonRoot(RemoteScheme):
    def test_one_path_is_named_relative_to_its_directory(self):
        root = path_list.common_root([Path(os.path.join("/r", "a", "x.txt"))])
        self.assertEqual(str(root), str(Path(os.path.join("/r", "a"))))

    def test_the_deepest_directory_every_path_shares(self):
        paths = [Path(os.path.join("/r", "src", "a", "x.py")),
                 Path(os.path.join("/r", "src", "b", "y.py")),
                 Path(os.path.join("/r", "src", "z.py"))]
        self.assertEqual(str(path_list.common_root(paths)),
                         str(Path(os.path.join("/r", "src"))))

    def test_one_outlier_drags_the_root_up(self):
        paths = [Path(os.path.join("/r", "src", "a", "x.py")),
                 Path(os.path.join("/other", "y.py"))]
        root = path_list.common_root(paths)
        self.assertEqual(str(root), str(Path(os.path.join("/r")).parent))

    def test_on_a_remote_host(self):
        paths = [Path("fake://h/proj/a/x"), Path("fake://h/proj/b/y")]
        self.assertEqual(str(path_list.common_root(paths)), "fake://h/proj")

    def test_two_hosts_share_nothing(self):
        paths = [Path("fake://h1/a/x"), Path("fake://h2/a/y")]
        self.assertIsNone(path_list.common_root(paths))

    def test_local_and_remote_share_nothing(self):
        paths = [Path(os.path.join(tempfile.gettempdir(), "x")),
                 Path("fake://h/a/y")]
        self.assertIsNone(path_list.common_root(paths))

    @unittest.skipUnless(sys.platform == "win32", "drive letters")
    def test_two_drives_share_nothing(self):
        self.assertIsNone(path_list.common_root([Path("C:\\a\\x"),
                                                 Path("D:\\a\\y")]))

    def test_nothing(self):
        self.assertIsNone(path_list.common_root([]))


# --------------------------------------------------------------------------- #
# probe
# --------------------------------------------------------------------------- #

class Probe(RemoteScheme):
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        super().tearDown()

    def _touch(self, name):
        p = os.path.join(self.tmp, name)
        with open(p, "w") as f:
            f.write("x")
        return Path(p)

    def test_what_is_there_is_kept_in_order_with_its_attributes(self):
        b, a = self._touch("b.txt"), self._touch("a.txt")
        got = path_list.probe([b, a])
        self.assertEqual([p for p, _ in got.entries], [b, a])
        self.assertTrue(all(attrs["ok"] for _, attrs in got.entries))
        self.assertEqual((got.missing, got.unreachable), (0, 0))

    def test_what_is_not_there_is_counted_missing(self):
        a = self._touch("a.txt")
        got = path_list.probe([a, Path(os.path.join(self.tmp, "gone.txt"))])
        self.assertEqual([p for p, _ in got.entries], [a])
        self.assertEqual((got.missing, got.unreachable), (1, 0))

    def test_a_remote_row_is_read_like_a_local_one(self):
        FILES["h"] = {"a/x.txt"}
        got = path_list.probe([Path("fake://h/a/x.txt"), Path("fake://h/a/no")])
        self.assertEqual([str(p) for p, _ in got.entries], ["fake://h/a/x.txt"])
        self.assertEqual(got.entries[0][1]["size"], 7)
        self.assertEqual((got.missing, got.unreachable), (1, 0))

    def test_an_unreachable_host_is_tried_once_not_once_per_row(self):
        FILES["up"] = {"x"}
        rows = [Path(f"fake://down/r{i}") for i in range(50)]
        got = path_list.probe(rows + [Path("fake://up/x")])
        self.assertEqual([str(p) for p, _ in got.entries], ["fake://up/x"])
        self.assertEqual((got.missing, got.unreachable), (0, 50))
        self.assertEqual(DOWN_CALLS, ["down"])

    def test_cancel_stops_the_walk(self):
        import threading
        cancel = threading.Event()
        cancel.set()
        got = path_list.probe([self._touch("a.txt")], cancel=cancel)
        self.assertEqual(got.entries, [])


# --------------------------------------------------------------------------- #
# naming: a list with no common root
# --------------------------------------------------------------------------- #

class WholePathNames(RemoteScheme):
    def test_rel_name_is_the_whole_path(self):
        p = Path("fake://h/a/x.txt")
        self.assertEqual(name_key.rel_name(p, name_key.WHOLE_PATH),
                         "fake://h/a/x.txt")

    def test_none_still_means_a_directory_pane_basename(self):
        self.assertEqual(name_key.rel_name(Path("fake://h/a/x.txt"), None), "x.txt")

    def test_a_listing_with_no_common_root_compares_whole_paths(self):
        FILES["h1"] = {"a/x"}
        FILES["h2"] = {"b/y"}
        flm = FileListManager(_config.Config())
        result = flm.compute_virtual_listing(
            [Path("fake://h2/b/y"), Path("fake://h1/a/x")],
            sort_mode="name", derive_root=True)
        self.assertIs(result["root"], name_key.WHOLE_PATH)
        self.assertEqual([str(f) for f in result["files"]],
                         ["fake://h1/a/x", "fake://h2/b/y"])
        attrs = {str(p): a for p, a in result["entries"]}
        self.assertEqual(attrs["fake://h1/a/x"]["cmp_name"], "fake://h1/a/x")

    def test_a_listing_with_a_common_root_derives_it_from_the_survivors(self):
        FILES["h"] = {"proj/a/x", "proj/b/y"}
        flm = FileListManager(_config.Config())
        result = flm.compute_virtual_listing(
            [Path("fake://h/proj/a/x"), Path("fake://h/proj/b/y"),
             Path("fake://h/elsewhere/gone")],
            derive_root=True)
        # The missing row does not drag the root up to the host.
        self.assertEqual(str(result["root"]), "fake://h/proj")
        self.assertEqual(result["missing"], 1)


# --------------------------------------------------------------------------- #
# the header
# --------------------------------------------------------------------------- #

class Header(RemoteScheme):
    LIST = {"kind": "list", "title": "My list"}

    def _text(self, root, avail=200, title="My list"):
        virtual = dict(self.LIST, root=root, title=title)
        return xefm_app._virtual_header_text(virtual, avail)

    def test_a_list_reads_title_then_root_with_no_count(self):
        self.assertEqual(self._text(Path("fake://h/proj/src")),
                         "[My list] fake://h/proj/src")

    def test_no_common_root_shows_the_title_alone(self):
        self.assertEqual(self._text(name_key.WHOLE_PATH), "[My list]")

    def test_the_title_gives_way_before_the_root(self):
        root = "fake://h/proj/src"
        title = "A rather long title for a list"
        text = self._text(Path(root), avail=len(f"[My list] {root}"), title=title)
        self.assertTrue(text.endswith(root))           # the whole root survives
        self.assertTrue(text.startswith("[A"))
        self.assertIn("…", text)
        self.assertLessEqual(len(text), len(f"[My list] {root}"))

    def test_then_the_root_drops_whole_components(self):
        root = Path("fake://h/" + "/".join(f"dir{i:02d}" for i in range(20)) + "/leaf")
        text = self._text(root, avail=40, title="Clipboard")
        self.assertLessEqual(len(text), 40)
        self.assertTrue(text.startswith("[Cl"))
        self.assertIn("fake://h/", text)
        self.assertTrue(text.endswith("/leaf"))

    def test_a_search_keeps_its_banner_first_and_no_count(self):
        virtual = {"kind": "search", "mode": "filename", "query": "q",
                   "root": Path("fake://h/proj")}
        self.assertEqual(xefm_app._virtual_header_text(virtual, 200),
                         '⌕ "q" (filename)  ·  fake://h/proj')

    def test_a_search_drops_its_root_before_its_banner(self):
        virtual = {"kind": "search", "mode": "filename", "query": "q",
                   "root": Path("fake://h/proj")}
        self.assertEqual(xefm_app._virtual_header_text(virtual, 22),
                         '⌕ "q" (filename)')


# --------------------------------------------------------------------------- #
# the app: the clipboard import and PaneApi.open_list
# --------------------------------------------------------------------------- #

class AppImport(RemoteScheme):
    def setUp(self):
        super().setUp()
        from puikit.backends import create_backend
        self.tmp = tempfile.mkdtemp()
        self.state_dir = tempfile.mkdtemp()
        self.sm = XeFMStateManager(db_path=os.path.join(self.state_dir, "state.db"))
        self.b = create_backend("memory")
        self.b.open()
        self.app = xefm_app.XeFMApp(self.b, self.tmp, self.tmp,
                                    left_provided=True, right_provided=True,
                                    state_manager=self.sm)
        self.app.file_monitor.stop_monitoring()
        self.app.file_monitor.enabled = False
        self.app._settle_listings()
        self.pane = self.app.active_pane()

    def tearDown(self):
        self.app.file_monitor.stop_monitoring()
        self.b.close()
        shutil.rmtree(self.tmp, ignore_errors=True)
        shutil.rmtree(self.state_dir, ignore_errors=True)
        super().tearDown()

    def _write(self, rel):
        p = os.path.join(self.tmp, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f:
            f.write("x")
        return p

    def _import(self, text):
        self.app.panel.set_clipboard(text)
        self.assertTrue(self.app.dispatch("import_list_from_clipboard"))
        self.app._settle_listings()

    def _last_log(self):
        text, _style = self.app.log.lines[-1]
        return text

    def _shown(self):
        view = self.app._active_view()
        return [view._display_name(f) for f in self.pane["files"]]

    def test_the_clipboard_becomes_the_pane(self):
        a = self._write(os.path.join("one", "a.txt"))
        b = self._write(os.path.join("two", "b.txt"))
        self._import(f"{a}\n\n{b}\n")
        virtual = self.pane["virtual"]
        self.assertEqual(virtual["kind"], "list")
        self.assertEqual(virtual["title"], "Clipboard")
        self.assertEqual(sorted(str(f) for f in self.pane["files"]), sorted([a, b]))
        # Named relative to what they share, which here is the pane's own dir.
        self.assertEqual(str(virtual["root"]), str(Path(self.tmp)))
        self.assertEqual(sorted(self._shown()),
                         [os.path.join("one", "a.txt"), os.path.join("two", "b.txt")])

    def test_the_root_comes_from_the_list_not_the_pane(self):
        a = self._write(os.path.join("deep", "er", "a.txt"))
        b = self._write(os.path.join("deep", "er", "b.txt"))
        self._import(f"{a}\n{b}")
        self.assertEqual(str(self.pane["virtual"]["root"]),
                         str(Path(os.path.join(self.tmp, "deep", "er"))))
        self.assertEqual(sorted(self._shown()), ["a.txt", "b.txt"])

    def test_a_missing_path_is_left_out_and_said(self):
        a = self._write("a.txt")
        self._import(f"{a}\n{os.path.join(self.tmp, 'gone.txt')}")
        self.assertEqual([str(f) for f in self.pane["files"]], [a])
        self.assertIn("1 not found", self._last_log())

    def test_relative_lines_resolve_against_the_pane_and_are_said(self):
        self._write(os.path.join("src", "main.py"))
        self._import(os.path.join("src", "main.py"))
        self.assertEqual([f.name for f in self.pane["files"]], ["main.py"])
        self.assertIn("1 resolved relative to", self._last_log())

    def test_an_empty_clipboard_leaves_the_pane_alone(self):
        before = list(self.pane["files"])
        self._import("\n  \n")
        self.assertIsNone(self.pane["virtual"])
        self.assertEqual(self.pane["files"], before)
        self.assertIn("no paths", self._last_log())

    def test_a_list_none_of_which_exists_leaves_the_pane_alone(self):
        self._write("keep.txt")
        self.app._relist(self.pane)
        self.app._settle_listings()
        before = list(self.pane["files"])
        self._import(os.path.join(self.tmp, "gone1") + "\n"
                     + os.path.join(self.tmp, "gone2"))
        self.assertIsNone(self.pane["virtual"])
        self.assertEqual(self.pane["files"], before)
        self.assertIn("none of the 2 paths", self._last_log())
        self.assertIn("2 not found", self._last_log())

    def test_local_and_remote_rows_in_one_list(self):
        a = self._write("a.txt")
        FILES["h"] = {"srv/x.log"}
        self._import(f"{a}\nfake://h/srv/x.log\nfake://down/y")
        self.assertIs(self.pane["virtual"]["root"], name_key.WHOLE_PATH)
        self.assertEqual(sorted(self._shown()), sorted([a, "fake://h/srv/x.log"]))
        self.assertIn("1 unreachable", self._last_log())

    def test_no_common_root_runs_programs_from_where_the_pane_was(self):
        a = self._write("a.txt")
        FILES["h"] = {"x"}
        self._import(f"{a}\nfake://h/x")
        _env, cwd = self.app._program_env(self.pane)
        self.assertEqual(cwd, str(Path(self.tmp)))

    def test_go_parent_goes_back_to_the_directory(self):
        a = self._write(os.path.join("one", "a.txt"))
        self._import(a)
        self.assertIsNotNone(self.pane["virtual"])
        self.app.dispatch("go_parent")
        self.app._settle_listings()
        self.assertIsNone(self.pane["virtual"])
        self.assertEqual(str(self.pane["path"]), str(Path(self.tmp)))

    def test_a_deleted_row_leaves_the_list_on_refresh(self):
        a = self._write("a.txt")
        b = self._write("b.txt")
        self._import(f"{a}\n{b}")
        os.remove(a)
        self.app._refresh(self.pane)
        self.app._settle_listings()
        self.assertEqual([str(f) for f in self.pane["files"]], [b])
        self.assertEqual([str(p) for p in self.pane["virtual"]["results"]], [b])

    def test_the_header_names_the_list_and_its_root(self):
        a = self._write(os.path.join("deep", "a.txt"))
        b = self._write(os.path.join("deep", "b.txt"))
        self._import(f"{a}\n{b}")
        text = xefm_app._virtual_header_text(self.pane["virtual"], 500)
        self.assertTrue(text.startswith("[Clipboard] "))
        self.assertTrue(text.endswith("deep"))

    def test_pane_api_open_list(self):
        a = self._write(os.path.join("x", "a.txt"))
        PaneApi(self.app, self.app.pm.active_pane).open_list(
            [Path(a), os.path.join("x", "missing.txt")], title="My search")
        self.app._settle_listings()
        self.assertEqual(self.pane["virtual"]["title"], "My search")
        self.assertEqual([str(f) for f in self.pane["files"]], [a])
        self.assertIn("My search: 1 item", self._last_log())


if __name__ == "__main__":
    unittest.main()

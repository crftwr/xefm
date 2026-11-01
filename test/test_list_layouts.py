"""Attributes and file list layouts (#633, #756).

The attribute layer (``xefm.attributes``): what ``ATTRIBUTES`` accepts, how a
pane's store computes values off the UI thread and keeps them across a re-read,
and ``size``, whose folder half is on request. The display layer (``xefm.layouts``): what
``LAYOUTS`` and ``LAYOUT_RULES`` accept, the built-in formats, and a pane drawn
with a layout of its own. And where they meet the rest: an attribute sort over
one directory, ``EntryInfo.attr``, and the config loader.

Run with: python -m pytest test/test_list_layouts.py -v
"""

import os
import shutil
import sys
import tempfile
import threading
import time
import types
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from puikit import Panel  # noqa: E402
from puikit.backends.memory_backend import MemoryBackend  # noqa: E402

from xefm import attributes, layouts  # noqa: E402
from xefm.file_list_manager import FileListManager  # noqa: E402
from xefm.file_pane import FilePane  # noqa: E402
from xefm.path import Path  # noqa: E402
from xefm.user_api import Cell, EntryInfo, load_user_entries  # noqa: E402


class _Config:
    SHOW_HIDDEN_FILES = True
    DATE_FORMAT = "short"
    SEPARATE_EXTENSIONS = True
    MAX_EXTENSION_LENGTH = 5
    DEFAULT_SORT_MODE = "filename"


def _load(**tables):
    config = types.SimpleNamespace(**tables)
    return load_user_entries(config)


class _Clean(unittest.TestCase):
    def tearDown(self):
        load_user_entries(types.SimpleNamespace())


class _Tree(_Clean):
    """A small real directory, listed the way a pane lists it."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        for name in ("a.txt", "b.md", "c.py"):
            with open(os.path.join(self.tmp, name), "w") as f:
                f.write("x" * 10)
        os.mkdir(os.path.join(self.tmp, "sub"))
        with open(os.path.join(self.tmp, "sub", "inner.bin"), "wb") as f:
            f.write(b"\0" * 1000)
        self.flm = FileListManager(_Config())

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def pane(self, **extra):
        pane = {"path": Path(self.tmp), "focused_index": 0, "selected_files": set(),
                "filter_pattern": "", "sort_mode": "filename", "sort_reverse": False,
                "layout": None}
        pane.update(extra)
        self.flm.apply_listing(pane, self.flm.compute_listing(Path(self.tmp)))
        return pane

    @staticmethod
    def records(pane):
        return {str(p): a for p, a in pane["_listing_entries"]}

    def render(self, pane, width=60):
        backend = MemoryBackend(width=width, height=8)
        panel = Panel(backend)
        view = FilePane(pane, config=_Config())
        view.active = True
        panel.add(view, x=0, y=0, w=width, h=8, hints={"surface": "content"})
        panel.render()
        for wid in list(panel._text_anims):
            panel._text_anims[wid] -= 99.0
        panel.render()
        return ["".join(row) for row in backend.snapshot()]


def _wait(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


# --- the tables -------------------------------------------------------------------

class AttributesTable(_Clean):

    def test_a_good_entry_registers(self):
        loaded = _load(ATTRIBUTES={"lines": {"type": "count",
                                             "read": lambda d, es: [1] * len(es)}})
        self.assertEqual(loaded.warnings, [])
        self.assertEqual(loaded.attributes, 1)
        self.assertEqual(attributes.get("lines").label, "lines")

    def test_problems_are_named(self):
        cases = {
            "noread": {"type": "text"},
            "oldkey": {"entry": lambda e: 1},
            "badtype": {"type": "colour", "read": lambda d, es: []},
            "arity": {"read": lambda es: []},
            "badwhen": {"compute": "later", "read": lambda d, es: []},
        }
        loaded = _load(ATTRIBUTES=cases)
        self.assertEqual(loaded.attributes, 0)
        self.assertEqual(len(loaded.warnings), len(cases))
        self.assertIsNone(attributes.get("noread"))

    def test_a_built_in_cannot_be_replaced(self):
        loaded = _load(ATTRIBUTES={"size": {"read": lambda d, es: []}})
        self.assertIn("built-in", loaded.warnings[0])


class LayoutsTable(_Clean):

    def test_a_good_layout_registers_and_needs_a_name_column(self):
        loaded = _load(LAYOUTS={"slim": {"columns": ["name", "size"]},
                                "noname": {"columns": ["size"]}})
        self.assertEqual(loaded.layouts, 1)
        self.assertIn("no 'name' column", loaded.warnings[0])
        self.assertEqual([c.attr for c in layouts.get("slim").columns], ["name", "size"])

    def test_a_format_must_suit_its_type(self):
        loaded = _load(LAYOUTS={"x": {"columns": ["name", {"attr": "size", "format": "relative"}]}})
        self.assertIn("not a format for a size value", loaded.warnings[0])

    def test_default_is_replaced_only_on_purpose(self):
        loaded = _load(LAYOUTS={"default": {"columns": ["name"]}})
        self.assertIn("'override': True", loaded.warnings[0])
        self.assertEqual(layouts.get("default"), layouts.BUILTIN_DEFAULT)
        _load(LAYOUTS={"default": {"columns": ["name"], "override": True}})
        self.assertEqual([c.attr for c in layouts.get("default").columns], ["name"])

    def test_an_unknown_attribute_is_reported_but_the_layout_loads(self):
        loaded = _load(LAYOUTS={"g": {"columns": ["name", "git"]}})
        self.assertEqual(loaded.layouts, 1)
        self.assertIn("git", loaded.warnings[0])

    def test_the_old_total_size_name_says_what_it_is_now(self):
        loaded = _load(LAYOUTS={"t": {"columns": ["name", "total_size"]}})
        self.assertIn("'total_size' is now 'size'", loaded.warnings[0])

    def test_markers_take_side_and_limit(self):
        _load(LAYOUTS={"m": {"columns": [{"attr": "name", "markers": [
            "tags", {"attr": "size", "side": "before", "limit": 2}]}]}})
        (name,) = layouts.get("m").columns
        self.assertEqual([(m.attr, m.side, m.limit) for m in name.markers],
                         [("tags", "after", None), ("size", "before", 2)])
        loaded = _load(LAYOUTS={"m": {"columns": [{"attr": "name", "markers": [
            {"attr": "tags", "side": "under"}]}]}})
        self.assertIn("side", loaded.warnings[0])
        loaded = _load(LAYOUTS={"m": {"columns": [{"attr": "name", "markers": [
            {"attr": "tags", "max_width": 1}]}]}})
        self.assertIn("'limit'", loaded.warnings[0])

    def test_default_layout_names_a_layout(self):
        _load(LAYOUTS={"slim": {"columns": ["name"]}}, DEFAULT_LAYOUT="slim")
        self.assertEqual(layouts.layout_of({}).name, "slim")
        self.assertEqual(layouts.layout_of({"layout": "default"}).name, "default")
        loaded = _load(DEFAULT_LAYOUT="nowhere")
        self.assertIn("DEFAULT_LAYOUT", loaded.warnings[0])
        self.assertEqual(layouts.layout_of({}).name, "default")

    def test_layout_rules_are_gone_and_say_so(self):
        loaded = _load(LAYOUT_RULES=[("*", "x")])
        self.assertIn("LAYOUT_RULES is gone", loaded.warnings[0])


def _kind(directory, entries):
    return ["F" if not e.is_dir else None for e in entries]


KIND = {"kind": {"type": "enum", "read": _kind,
                 "values": {"F": {"label": "File", "color": "green"}}}}


class Extras(_Clean):

    def test_tags_is_a_built_in_extra(self):
        (tags,) = [e for e in layouts.all_extras() if e.name == "tags"]
        self.assertEqual([(m.marker.attr, m.on, m.marker.limit) for m in tags.markers],
                         [("tags", "name", 3)])

    def test_config_overrides_an_existing_extra_key_by_key(self):
        _load(LAYOUT_EXTRAS={"tags": {"when": "never"}})
        tags = layouts.get_extra("tags")
        self.assertEqual(tags.when, "never")
        self.assertEqual(tags.label, "Tags")            # the rest as it was
        self.assertTrue(tags.markers)

    def test_problems_are_named(self):
        loaded = _load(ATTRIBUTES=KIND, LAYOUT_EXTRAS={
            "empty": {"label": "Nothing"},
            "both": {"columns": [{"attr": "kind", "after": "name", "replace": "size"}]},
            "badwhen": {"when": 3, "markers": ["kind"]},
        })
        self.assertEqual(loaded.extras, 0)
        self.assertEqual(len(loaded.warnings), 3)

    def test_when_decides_where_auto_shows_it(self):
        def boom(path):
            raise RuntimeError("no")
        _load(ATTRIBUTES=KIND, LAYOUT_EXTRAS={
            "data": {"when": "/data/*", "markers": ["kind"]},
            "broken": {"when": boom, "markers": ["kind"]},
            "nowhere": {"when": "never", "markers": ["kind"]}})
        self.assertIn("data", layouts.extras_for("/data/x"))
        self.assertNotIn("data", layouts.extras_for("/elsewhere"))
        self.assertNotIn("broken", layouts.extras_for("/data/x"))
        self.assertNotIn("nowhere", layouts.extras_for("/data/x"))

    def test_the_tab_s_state_beats_when(self):
        _load(ATTRIBUTES=KIND, LAYOUT_EXTRAS={"k": {"when": "never", "markers": ["kind"]}})
        names = lambda pane: [e.name for e in layouts.active_extras(pane)]  # noqa: E731
        self.assertNotIn("k", names({"_extras_auto": frozenset()}))
        self.assertIn("k", names({"extras": {"k": "on"}}))
        self.assertNotIn("k", names({"extras": {"k": "off"},
                                     "_extras_auto": frozenset({"k"})}))

    def test_compose_places_after_replace_end_and_markers(self):
        _load(ATTRIBUTES=KIND, LAYOUT_EXTRAS={
            "a": {"columns": [{"attr": "kind", "after": "name"}],
                  "markers": [{"attr": "kind", "on": "mtime", "side": "before"}]},
            "b": {"columns": [{"attr": "kind", "replace": "mtime"}]},
            "c": {"columns": [{"attr": "kind", "replace": "nothing"}],
                  "markers": [{"attr": "kind", "on": "nothing"}]},
        })
        row = layouts.compose(layouts.BUILTIN_DEFAULT,
                              [layouts.get_extra(n) for n in "abc"])
        self.assertEqual([(c.attr, c.extra) for c in row.columns],
                         [("name", None), ("kind", "a"), ("ext", None),
                          ("size", None), ("kind", "b"), ("kind", "c")])
        before = layouts.compose(layouts.BUILTIN_DEFAULT, [layouts.build_extra(
            "d", {"columns": [{"attr": "kind", "before": "name"}]})[0]])
        self.assertEqual([c.attr for c in before.columns][:2], ["kind", "name"])
        replaced = row.columns[4]
        self.assertEqual(replaced.priority, 1)          # the date's
        self.assertEqual([m.slot for m in row.columns[0].markers], ["c"])

    def test_a_shared_glyph_in_one_color_is_reported(self):
        def mark(value, entry):
            return Cell("●", color="yellow")
        loaded = _load(ATTRIBUTES=KIND, LAYOUT_EXTRAS={
            "k": {"markers": [{"attr": "kind", "format": mark}]}})
        self.assertTrue(any("both draw ●" in w for w in loaded.warnings), loaded.warnings)


# --- formats -----------------------------------------------------------------------

class Formats(unittest.TestCase):

    def render(self, kind, fmt, value, **row):
        attr = attributes.Attribute("x", "X", kind, values=row.pop("values", {}))
        resolved = layouts.resolve_format(fmt, attr)
        return layouts.render(resolved, value, layouts.Row(attr=attr, **row), lambda: None)

    def test_sizes(self):
        self.assertEqual(self.render("size", "bytes", 1234567)[0].text, "1,234,567")
        self.assertEqual(self.render("size", None, None, is_dir=True)[0].text, "<DIR>")
        self.assertEqual(self.render("size", None, None, ok=False)[0].text, "---")

    def test_relative_time(self):
        now = time.time()
        self.assertEqual(self.render("time", "relative", now - 5)[0].text, "just now")
        self.assertEqual(self.render("time", "relative", now - 3 * 86400)[0].text,
                         "3 days ago")

    def test_recent_time_is_as_short_as_its_age_allows(self):
        from datetime import datetime
        now = datetime.now()
        self.assertEqual(self.render("time", "recent", now.timestamp())[0].text,
                         now.strftime("%H:%M"))
        old = datetime(2019, 3, 4, 5, 6).timestamp()
        self.assertEqual(self.render("time", "recent", old)[0].text, "2019")

    def test_enum_values_give_letter_and_word_their_color(self):
        values = {"M": {"label": "Modified", "color": "yellow"}}
        (cell,) = self.render("enum", "word", "M", values=values)
        self.assertEqual((cell.text, cell.color), ("Modified", "yellow"))
        self.assertEqual(self.render("enum", "letter", "M", values=values)[0].text, "M")

    def test_a_duration_reads_as_a_clock(self):
        self.assertEqual(self.render("duration", None, 187.4)[0].text, "3:07")
        self.assertEqual(self.render("duration", "clock", 3765)[0].text, "1:02:45")
        self.assertEqual(self.render("duration", None, None), [])
        self.assertEqual(layouts.resolve_format(None, attributes.Attribute(
            "d", "D", "duration")).align, "right")

    def test_words_spell_a_value_out_for_file_details(self):
        def words(kind, value, **kw):
            return layouts.words(attributes.Attribute("x", "X", kind, **kw), value)
        self.assertEqual(words("enum", "M", values={"M": {"label": "Modified"}}),
                         "Modified")
        self.assertEqual(words("enum", "Z", values={"M": {"label": "Modified"}}), "Z")
        self.assertEqual(words("size", 2048), "2.0 KB (2,048 bytes)")
        self.assertEqual(words("duration", 75), "1:15")
        self.assertEqual(words("count", 12345), "12,345")
        self.assertEqual(words("tags", [types.SimpleNamespace(name="Work"),
                                        types.SimpleNamespace(name="Red")]), "Work, Red")
        from datetime import datetime
        when = datetime(2024, 3, 15, 14, 30, 22)
        self.assertEqual(words("time", when.timestamp()), "2024-03-15 14:30:22")

    def test_a_user_format_may_return_text_a_cell_or_cells(self):
        attr = attributes.Attribute("x", "X", "text")
        for out, expect in (("hi", ["hi"]), (Cell("a", color="red"), ["a"]),
                            ([Cell("a"), "b"], ["a", "b"]), (None, [])):
            resolved = layouts.resolve_format(lambda v, e, out=out: out, attr)
            cells = layouts.render(resolved, 1, layouts.Row(), lambda: None)
            self.assertEqual([c.text for c in cells], expect)

    def test_a_failing_user_format_draws_nothing(self):
        def broken(value, entry):
            raise ValueError("no")
        resolved = layouts.resolve_format(broken, attributes.Attribute("x", "X"))
        self.assertEqual(layouts.render(resolved, 1, layouts.Row(), lambda: None), [])


# --- the store ---------------------------------------------------------------------

class Store(_Tree):

    def test_an_automatic_attribute_is_read_once_for_the_whole_folder(self):
        calls = []

        def upper(directory, entries):
            calls.append((str(directory), len(entries)))
            return [e.name.upper() for e in entries]

        _load(ATTRIBUTES={"up": {"read": upper}})
        pane = self.pane()
        store = attributes.store_of(pane)
        files, records = pane["files"], self.records(pane)
        store.sync(files, records, pane["path"], {"up"})
        self.assertTrue(_wait(lambda: store.ready("up", files, records)))
        self.assertEqual(calls, [(self.tmp, len(files))])
        a = next(p for p in files if p.name == "a.txt")
        self.assertEqual(store.get(a, records[str(a)], "up"), "A.TXT")

    def test_a_re_read_asks_again_for_the_whole_folder(self):
        """A Git status changes without the file it is about changing, so a
        re-read cannot keep the values of the rows that look the same."""
        calls = []

        def names(directory, entries):
            calls.append(len(entries))
            return [e.name for e in entries]

        _load(ATTRIBUTES={"n": {"read": names}})
        pane = self.pane()
        store = attributes.store_of(pane)
        store.sync(pane["files"], self.records(pane), pane["path"], {"n"})
        self.assertTrue(_wait(lambda: len(calls) == 1))
        self.flm.apply_listing(pane, self.flm.compute_listing(Path(self.tmp)))
        store.sync(pane["files"], self.records(pane), pane["path"], {"n"})
        self.assertTrue(_wait(lambda: len(calls) == 2))
        self.assertEqual(calls, [len(pane["files"])] * 2)

    def test_a_provider_answering_the_wrong_count_costs_its_values(self):
        _load(ATTRIBUTES={"bad": {"read": lambda d, es: ["x"]}})
        pane = self.pane()
        store = attributes.store_of(pane)
        files, records = pane["files"], self.records(pane)
        store.sync(files, records, pane["path"], {"bad"})
        self.assertTrue(_wait(lambda: store.ready("bad", files, records)))
        self.assertEqual({store.get(p, records[str(p)], "bad") for p in files}, {None})

    def test_an_on_request_attribute_is_read_one_entry_at_a_time(self):
        calls = []

        def size_of(directory, entries):
            calls.append([e.name for e in entries])
            return [e.size for e in entries]

        _load(ATTRIBUTES={"sz": {"type": "size", "compute": "on_request", "read": size_of}})
        pane = self.pane()
        store = attributes.store_of(pane)
        records = self.records(pane)
        targets = [p for p in pane["files"] if p.name in ("a.txt", "b.md")]
        done = threading.Event()
        store.request("sz", targets, records, on_done=lambda n, c: done.set())
        self.assertTrue(done.wait(3))
        self.assertEqual(calls, [["a.txt"], ["b.md"]])
        self.assertEqual(store.get(targets[0], records[str(targets[0])], "sz"), 10)

    def test_another_directory_starts_afresh(self):
        _load(ATTRIBUTES={"n": {"read": lambda d, es: [e.name for e in es]}})
        pane = self.pane()
        store = attributes.store_of(pane)
        store.sync(pane["files"], self.records(pane), pane["path"], {"n"})
        self.assertTrue(_wait(lambda: store.ready("n", pane["files"], self.records(pane))))
        store.sync([], {}, "/elsewhere", {"n"})
        self.assertEqual(store.value(str(pane["files"][0]), "n"), (False, None))

    def test_size_is_computed_only_on_request(self):
        pane = self.pane()
        store = attributes.store_of(pane)
        records = self.records(pane)
        sub = next(p for p in pane["files"] if p.name == "sub")
        self.assertIsNone(store.get(sub, records[str(sub)], "size"))
        a = next(p for p in pane["files"] if p.name == "a.txt")
        self.assertEqual(store.get(a, records[str(a)], "size"), 10)
        done = threading.Event()
        store.request("size", [sub], records, on_done=lambda n, c: done.set())
        self.assertTrue(done.wait(3))
        self.assertEqual(store.get(sub, records[str(sub)], "size"), 1000)
        self.assertEqual(EntryInfo(sub, is_dir=True).attr("size"), 1000)

    def test_fill_computes_only_what_is_missing_auto_and_on_request_alike(self):
        calls = []

        def read(name):
            def fn(directory, entries):
                calls.append((name, [e.name for e in entries]))
                return [f"{name}:{e.name}" for e in entries]
            return fn

        _load(ATTRIBUTES={"au": {"read": read("au")},
                          "rq": {"read": read("rq"), "compute": "on_request"},
                          "far": {"read": read("far"), "where": "s3"}})
        pane = self.pane()
        store = attributes.store_of(pane)
        files, records = pane["files"], self.records(pane)
        a = next(p for p in files if p.name == "a.txt")
        store.sync(files, records, pane["path"], {"au"})
        self.assertTrue(_wait(lambda: store.ready("au", files, records)))
        calls.clear()
        done = threading.Event()
        store.fill(["au", "rq", "far", "size", "name"], [a], records,
                   on_done=lambda cancelled: done.set())
        self.assertTrue(done.wait(3))
        # 'au' was already there, 'far' is not asked about a local file, and
        # 'size' and 'name' are the dialog's own rows.
        self.assertEqual(calls, [("rq", ["a.txt"])])
        self.assertEqual(store.value(str(a), "rq"), (True, "rq:a.txt"))

    def test_a_fill_stops_when_cancelled(self):
        started, release = threading.Event(), threading.Event()
        seen = []

        def slow(directory, entries):
            seen.append(entries[0].name)
            started.set()
            release.wait(3)
            return [1]

        _load(ATTRIBUTES={"slow": {"read": slow, "type": "count"}})
        pane = self.pane()
        store = attributes.store_of(pane)
        records = self.records(pane)
        targets = [p for p in pane["files"] if not p.is_dir()]
        done = threading.Event()
        cancel = store.fill(["slow"], targets, records,
                            on_done=lambda cancelled: done.set())
        self.assertTrue(started.wait(3))
        cancel.set()
        release.set()
        self.assertTrue(done.wait(3))
        self.assertEqual(len(seen), 1)
        self.assertEqual(store.value(str(targets[0]), "slow"), (False, None))

    def test_entry_attr_never_computes(self):
        _load(ATTRIBUTES={"n": {"read": lambda d, es: ["computed"] * len(es)}})
        self.assertIsNone(EntryInfo(Path(self.tmp) / "a.txt").attr("n"))
        self.assertEqual(EntryInfo(Path(self.tmp) / "a.txt").attr("ext"), ".txt")


# --- drawing -----------------------------------------------------------------------

class Drawing(_Tree):

    def test_an_extra_marks_the_name_and_adds_a_column(self):
        _load(ATTRIBUTES=KIND, LAYOUT_EXTRAS={"k": {
            "markers": [{"attr": "kind", "side": "before"}],
            "columns": [{"attr": "kind", "format": "word", "after": "name"}]}})
        pane = self.pane(extras={"k": "on"})
        self.render(pane)
        store = attributes.store_of(pane)
        self.assertTrue(_wait(lambda: store.ready("kind", pane["files"], self.records(pane))))
        lines = self.render(pane)
        row = next(line for line in lines if "a.txt" in line or " a " in line)
        sub = next(line for line in lines if "sub" in line)
        self.assertIn("F a", row)                     # the mark, against the name
        self.assertIn("File", row)                    # the extra's own column
        # nothing is reserved: a name without a mark starts where the mark would
        self.assertEqual(sub.index("sub"), row.index("F"))

    def test_a_marker_on_a_value_column_sits_against_its_value(self):
        _load(ATTRIBUTES=KIND, LAYOUT_EXTRAS={"k": {
            "markers": [{"attr": "kind", "on": "size", "side": "after"}]}})
        pane = self.pane(extras={"k": "on"})
        self.render(pane)
        store = attributes.store_of(pane)
        self.assertTrue(_wait(lambda: store.ready("kind", pane["files"], self.records(pane))))
        lines = self.render(pane)
        row = next(line for line in lines if " a " in line)
        sub = next(line for line in lines if "sub" in line)
        self.assertIn("10B F", row)                   # the value gives way, right-aligned
        self.assertEqual(row.index("F") + 1, sub.index("<DIR>") + len("<DIR>"))

    def test_a_sparse_extra_takes_no_room_where_nothing_has_it(self):
        _load(ATTRIBUTES={"none": {"type": "enum", "read": lambda d, es: [None] * len(es)}},
              LAYOUT_EXTRAS={"n": {"markers": [{"attr": "none", "side": "before"}],
                            "columns": [{"attr": "none", "after": "name"}]}})
        plain = self.render(self.pane())
        pane = self.pane(extras={"n": "on"})
        self.render(pane)
        store = attributes.store_of(pane)
        self.assertTrue(_wait(lambda: store.ready("none", pane["files"], self.records(pane))))
        self.assertEqual(self.render(pane), plain)

    def test_markers_of_one_extra_share_a_slot_and_limit_counts_cells(self):
        view = FilePane({"files": []}, config=_Config())
        wide = lambda s: 1.15 * len(s)   # noqa: E731 — a proportional font
        one = layouts.resolve_format(lambda v, e: Cell("●", color="yellow"),
                                     attributes.Attribute("x", "X"))
        five = layouts.resolve_format(lambda v, e: [Cell("●")] * 5,
                                      attributes.Attribute("tags", "T"))
        markers = [(layouts.Marker("x", slot="e"), None, one),
                   (layouts.Marker("tags", limit=3, slot="e"), None, five)]
        groups = view._slot_groups(markers, "after", lambda n: 1,
                                   lambda a: layouts.Row(), lambda: None, wide)
        (cells, _w), = groups.values()
        self.assertEqual([c.text for c in cells], ["●", " ", "●", "●", "●"])

    def test_a_column_with_a_priority_goes_first_on_a_narrow_pane(self):
        _load(LAYOUTS={"two": {"columns": ["name", {"attr": "mtime", "priority": 1},
                                           "size"]}})
        pane = self.pane(layout="two")
        wide = next(line for line in self.render(pane, 60) if "a.txt" in line)
        narrow = next(line for line in self.render(pane, 26) if "a" in line[:3])
        self.assertRegex(wide, r"\d\d-\d\d-\d\d")
        self.assertNotRegex(narrow, r"\d\d-\d\d-\d\d")
        self.assertIn("10B", narrow)


# --- sorting -----------------------------------------------------------------------

class AttributeSort(_Tree):

    def test_rows_with_a_value_come_in_its_order_the_rest_last(self):
        pane = self.pane()
        entries = pane["_listing_entries"]
        by_name = {p.name: str(p) for p, _a in entries}
        values = {by_name["a.txt"]: 3, by_name["b.md"]: 1, by_name["sub"]: 9}
        for reverse, expect in ((False, ["sub", "b.md", "a.txt", "c.py"]),
                                (True, ["sub", "a.txt", "b.md", "c.py"])):
            result = self.flm.recompute_from_snapshot(
                entries, overlay=("x", values, reverse))
            self.assertEqual([p.name for p in result["files"]], expect)

    def test_an_empty_value_goes_last_like_none(self):
        """No tags is [], no Git status is None; both go last, so a tag sort
        and a Git sort put the marked files first alike (hand check)."""
        pane = self.pane()
        entries = pane["_listing_entries"]
        by_name = {p.name: str(p) for p, _a in entries}
        values = {by_name["a.txt"]: [], by_name["b.md"]: ["Work"], by_name["c.py"]: []}
        result = self.flm.recompute_from_snapshot(entries, overlay=("tags", values, False))
        self.assertEqual([p.name for p in result["files"]][1], "b.md")


# --- the app -----------------------------------------------------------------------

class App(_Tree):
    """The per-tab choice, folder sizes, and the one-folder attribute sort, run
    through the app as a key would run them."""

    def setUp(self):
        super().setUp()
        from puikit.backends import create_backend
        from xefm import app as xefm_app
        from xefm.state_manager import XeFMStateManager
        self.state_dir = tempfile.mkdtemp()
        sm = XeFMStateManager(db_path=os.path.join(self.state_dir, "state.db"))
        self.b = create_backend("memory")
        self.b.open()
        self.app = xefm_app.XeFMApp(self.b, self.tmp, self.tmp, left_provided=True,
                                    right_provided=True, state_manager=sm)
        self.app.file_monitor.stop_monitoring()
        self.app.file_monitor.enabled = False
        self.app._settle_listings()

    def tearDown(self):
        try:
            self.b.close()
        except Exception:
            pass
        shutil.rmtree(self.state_dir, ignore_errors=True)
        super().tearDown()

    def focus(self, name):
        pane = self.app.active_pane()
        pane["focused_index"] = [f.name for f in pane["files"]].index(name)

    def test_extras_follow_when_and_the_tab_can_override(self):
        _load(ATTRIBUTES=KIND, LAYOUT_EXTRAS={"k": {"when": self.tmp, "markers": ["kind"]}})
        pane = self.app.active_pane()
        self.app._relist(pane)
        self.app._settle_listings()
        active = lambda: [e.name for e in layouts.active_extras(pane)]  # noqa: E731
        self.assertIn("k", active())
        self.app._set_extra(pane, "k", "off")
        self.assertNotIn("k", active())
        self.app._set_extra(pane, "k", "auto")
        self.assertIn("k", active())
        self.assertNotIn("k", pane["extras"])

    def test_the_layout_is_the_tab_s(self):
        _load(LAYOUTS={"slim": {"columns": ["name", "size"]}})
        pane = self.app.active_pane()
        self.app._set_layout(pane, "slim")
        self.assertEqual(layouts.layout_of(pane).name, "slim")
        self.assertEqual(layouts.layout_of(self.app.pm.new_pane(pane["path"], like=pane)).name,
                         "slim")

    def test_help_explains_the_marks_on_screen(self):
        _load(ATTRIBUTES=KIND, LAYOUT_EXTRAS={"k": {"label": "Kind", "markers": ["kind"]}})
        pane = self.app.active_pane()
        self.app._set_extra(pane, "k", "on")
        text = self.app._help_markdown()
        self.assertIn("## Markers in this pane", text)
        self.assertIn("**Kind**", text)
        self.assertIn("- `F` green — File", text)
        self.app._set_extra(pane, "k", "off")
        self.assertNotIn("**Kind**", self.app._help_markdown())

    def test_folder_sizes_then_a_sort_by_them_for_this_folder_only(self):
        with open(os.path.join(self.tmp, "big"), "wb") as f:
            f.write(b"\0" * 5)
        os.mkdir(os.path.join(self.tmp, "empty"))
        pane = self.app.active_pane()
        self.app._relist(pane)
        self.app._settle_listings()
        pane["selected_files"] = {str(p) for p in pane["files"]
                                  if p.name in ("sub", "empty", "a.txt")}
        self.app.dispatch("resolve_attribute")    # names the targets, lists the values
        dialog = self.app.panel._layers[-1].widget
        self.assertIn("3 selected item(s)", dialog.title)
        self.assertEqual([v for v, _l in dialog._rows], ["size"])
        # The built-in Size orders files only; the totals are a row of their own.
        rows = self.app._attribute_sort_rows(pane)
        self.assertEqual(rows[0][:2], ("attr:size", "Size with folder totals"))
        self.app._resolve(pane, "size", self.app._selected_or_focused(pane))
        pane["selected_files"] = set()
        store = attributes.store_of(pane)
        records = self.records(pane)
        sub = next(p for p in pane["files"] if p.name == "sub")
        self.assertTrue(_wait(lambda: store.value(str(sub), "size")[0]))
        self.assertTrue(_wait(lambda: not store.busy()))

        pane["sort_overlay"] = {"attr": "size", "reverse": True,
                                "path": str(pane["path"])}
        self.app._resort(pane)
        self.app._settle_listings()
        self.assertEqual([p.name for p in pane["files"]][:2], ["sub", "empty"])
        self.assertIn("(this folder)", self.app.flm.get_sort_description(pane))
        names = [p.name for p in pane["files"] if not records.get(str(p), {}).get("is_dir")]
        self.assertEqual(names, ["a.txt", "b.md", "c.py", "big"])   # ties keep name order
        pane["path"] = Path(os.path.join(self.tmp, "sub"))
        self.assertIsNone(self.app._sort_overlay(pane))
        self.assertIsNone(pane["sort_overlay"])


if __name__ == "__main__":
    unittest.main()

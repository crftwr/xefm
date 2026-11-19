"""What the stable API promises, behaviour by behaviour (#713, plan §7.2).

**Changing an expectation in this file is a breaking change to the stable
API.** Either the change is undone, or ``API_VERSION`` in ``xefm/user_api.py``
is bumped and the change is called out in the release notes. Adding a test is
always fine.

Signatures are held still by the API snapshot (``test_api_snapshot.py``);
this file holds still what they mean. Each test states one promise a config
or an extension may rely on; the fuller coverage lives beside the feature.
"""

import errno
import io
import os
import sys
import types
from unittest.mock import patch

import pytest

_HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

from test_customization_api import app_with, config_with  # noqa: E402,F401
from xefm import _config, filters, path_schemes, sort_keys, user_api  # noqa: E402
from xefm import actions as xa  # noqa: E402
from xefm.file_list_manager import FileListManager  # noqa: E402
from xefm.path import Path  # noqa: E402
from xefm.path_base import ReadOnlyPathImpl, UriStatResult  # noqa: E402


def run(app, func):
    """Run ``func(ctx)`` as a user action and return what it returned."""
    out = {}
    app_actions = {"probe": lambda ctx: out.setdefault("value", func(ctx))}
    user_api.load_user_entries(config_with(ACTIONS=app_actions))
    app.dispatch("probe")
    return out.get("value")


# --------------------------------------------------------------------------- #
# PaneApi selection
# --------------------------------------------------------------------------- #

def test_selected_never_falls_back_to_the_focused_entry(app_with):
    app, _ = app_with()
    assert run(app, lambda ctx: ctx.pane.selected()) == []


def test_select_adds_and_counts_only_the_newly_selected(app_with):
    app, _ = app_with()
    counts = run(app, lambda ctx: (ctx.pane.select(lambda e: e.suffix == ".docx"),
                                   ctx.pane.select(lambda e: e.suffix == ".docx"),
                                   ctx.pane.select()))
    assert counts == (2, 0, 3)          # 5 entries: a.txt, b.docx, c.docx, d.pdf, sub


def test_unselect_with_no_predicate_clears_and_counts(app_with):
    app, _ = app_with()
    assert run(app, lambda ctx: (ctx.pane.select(), ctx.pane.unselect())) == (5, 5)


def test_a_predicate_that_raises_counts_as_no_match(app_with):
    app, _ = app_with()
    assert run(app, lambda ctx: ctx.pane.select(lambda e: 1 / 0)) == 0


# --------------------------------------------------------------------------- #
# EntryInfo
# --------------------------------------------------------------------------- #

def test_name_is_the_composed_shown_name_and_path_is_verbatim(tmp_path):
    decomposed = "が.txt"                  # か + combining dakuten
    entry = user_api.EntryInfo(Path(str(tmp_path / decomposed)))
    assert entry.name == "が.txt"                 # composed が
    assert entry.path.name == decomposed


def test_size_and_mtime_are_zero_when_the_entry_cannot_be_read(tmp_path):
    entry = user_api.EntryInfo(Path(str(tmp_path / "vanished.txt")))
    assert (entry.size, entry.mtime) == (0, 0.0)


def test_suffix_stem_and_is_file(tmp_path):
    entry = user_api.EntryInfo(Path(str(tmp_path / "a.tar.gz")))
    assert (entry.suffix, entry.stem, entry.is_file) == (".gz", "a.tar", True)
    assert not user_api.EntryInfo(Path(str(tmp_path)), is_dir=True).is_file


# --------------------------------------------------------------------------- #
# SORT_KEYS and FILTERS
# --------------------------------------------------------------------------- #

@pytest.fixture
def tree(tmp_path):
    for name, size in (("a.txt", 300), ("b.txt", 100), ("c.txt", 200)):
        (tmp_path / name).write_text("x" * size)
    (tmp_path / "zdir").mkdir()
    sort_keys.clear()
    filters.clear()
    yield tmp_path
    sort_keys.clear()
    filters.clear()


def listing(tree, *, mode="filename", reverse=False, filter_name=""):
    pane = {"path": Path(str(tree)), "focused_index": 0, "scroll_offset": 0,
            "files": [], "selected_files": set(), "sort_mode": mode,
            "sort_reverse": reverse, "filter_pattern": filter_name}
    FileListManager(_config.Config()).refresh_files(pane)
    return [p.name for p in pane["files"]]


def test_directories_first_and_reverse_are_not_the_sort_key_s_business(tree):
    user_api.load_user_entries(types.SimpleNamespace(SORT_KEYS={"bysize": lambda e: e.size}))
    assert listing(tree, mode="bysize") == ["zdir", "b.txt", "c.txt", "a.txt"]
    assert listing(tree, mode="bysize", reverse=True) == ["zdir", "a.txt", "c.txt", "b.txt"]


def test_a_failing_sort_key_falls_back_to_name_order(tree):
    user_api.load_user_entries(types.SimpleNamespace(SORT_KEYS={"boom": lambda e: 1 / 0}))
    assert listing(tree, mode="boom") == ["zdir", "a.txt", "b.txt", "c.txt"]


def test_a_failing_filter_fails_open(tree):
    user_api.load_user_entries(types.SimpleNamespace(FILTERS={"boom": lambda e: 1 / 0}))
    assert listing(tree, filter_name="boom") == ["zdir", "a.txt", "b.txt", "c.txt"]


def test_a_filter_decides_files_and_never_hides_directories(tree):
    user_api.load_user_entries(types.SimpleNamespace(FILTERS={"none": lambda e: False}))
    assert listing(tree, filter_name="none") == ["zdir"]


# --------------------------------------------------------------------------- #
# ActionContext
# --------------------------------------------------------------------------- #

def test_invoking_your_own_name_reaches_the_builtin_it_overrides(app_with):
    seen = []

    def loud_quit(ctx):
        seen.append("user")
        ctx.invoke("quit")

    app, _ = app_with(ACTIONS={"quit": {"func": loud_quit, "override": True}})
    app.confirm_quit = lambda: seen.append("builtin")
    app.dispatch("quit")
    assert seen == ["user", "builtin"]


def test_run_program_in_the_background_returns_none_at_once(app_with):
    app, _ = app_with()
    assert run(app, lambda ctx: ctx.run_program([sys.executable, "-c", "pass"])) is None


def test_run_program_on_the_terminal_returns_the_exit_code(app_with):
    app, _ = app_with()
    with patch("xefm.app.is_desktop_mode", return_value=False), \
            patch.object(app, "_run_in_terminal", return_value=3):
        assert run(app, lambda ctx: ctx.run_program(["vim"], terminal=True)) == 3


def test_run_program_on_the_desktop_opens_a_terminal_and_returns_none(app_with):
    app, _ = app_with()
    with patch("xefm.app.is_desktop_mode", return_value=True), \
            patch.object(app, "_terminal_unavailable", return_value=None), \
            patch.object(app, "_start_session") as opened:
        assert run(app, lambda ctx: ctx.run_program(["vim"], terminal=True)) is None
    assert opened.called


def test_action_names_are_what_invoke_accepts(app_with):
    app, _ = app_with()
    names = run(app, lambda ctx: ctx.action_names())
    assert "select_all" in names and "quit" in names


def test_an_old_action_name_keeps_resolving():
    aliases = xa.registry.aliases_in(xa.FILER)
    assert aliases, "the file list has renamed actions to keep resolving"
    for old, current in aliases.items():
        assert xa.registry.canonical(xa.FILER, old) == current


# --------------------------------------------------------------------------- #
# PATH_SCHEMES
# --------------------------------------------------------------------------- #

CALLS = []


class Notes(ReadOnlyPathImpl):
    """Only tier A, the way the docs say to write one."""

    NOTES = {"": ["todo"], "todo": []}

    def exists(self):
        CALLS.append("exists")
        return self.key in self.NOTES

    def is_dir(self):
        CALLS.append("is_dir")
        return self.key in self.NOTES

    def iterdir(self):
        CALLS.append("iterdir")
        for name in self.NOTES.get(self.key, []):
            yield self.child(name)

    def stat(self):
        CALLS.append("stat")
        return UriStatResult(is_dir=self.is_dir())

    def open(self, mode="r", buffering=-1, encoding=None, errors=None, newline=None):
        CALLS.append("open")
        return io.StringIO("")


@pytest.fixture
def notes():
    CALLS.clear()
    result = user_api.load_user_entries(config_with(PATH_SCHEMES={"notes": Notes}))
    assert result.warnings == []
    yield
    path_schemes.unregister_source("user")


def test_a_five_method_backend_is_browsable(notes):
    root = Path("notes://")
    assert root.is_dir()
    assert [p.name for p in root.iterdir()] == ["todo"]
    assert str(Path("notes://todo").parent) == "notes://"
    assert {"is_dir", "iterdir"} <= set(CALLS)


def test_writes_are_refused_as_a_read_only_filesystem(notes):
    with pytest.raises(OSError) as raised:
        Path("notes://todo").write_text("x")
    assert raised.value.errno == errno.EROFS
    assert not Path("notes://todo").supports("write_operations")


def test_config_py_wins_over_an_extension_for_the_same_key(tmp_path):
    from xefm import extensions as ext
    layout = ext.Layout(tmp_path)
    root = ext.scaffold("contract-ext", layout.packages)
    (name,) = ext.read_manifest(root).contributes["actions"]
    config = types.SimpleNamespace(ACTIONS={name: "mine"})
    try:
        report = ext.load(config, layout)
    finally:
        for module in [m for m in sys.modules if m.startswith("contract_ext")]:
            del sys.modules[module]
    assert config.ACTIONS[name] == "mine"
    assert any("config.py wins" in w for w in report.warnings)


# --------------------------------------------------------------------------- #
# config.py helpers
# --------------------------------------------------------------------------- #

def test_xefm_tool_prefers_the_user_s_tools_then_the_bundled_ones(tmp_path):
    user_tools = tmp_path / ".xefm" / "tools"
    user_tools.mkdir(parents=True)
    (user_tools / "vscode.py").write_text("")
    with patch("xefm.external_programs.Path.home", return_value=tmp_path):
        assert user_api.xefm_tool("vscode.py") == str(user_tools / "vscode.py")
        assert user_api.xefm_tool("kiro.py").endswith(os.path.join("xefm", "tools", "kiro.py"))
        assert user_api.xefm_tool("nowhere.py") == "nowhere.py"


@pytest.mark.parametrize("bundled", ["vscode.py", "kiro.py", "example_tool.py"])
def test_the_bundled_tools_keep_their_names(bundled):
    # Default PROGRAMS entries copied into users' configs name them.
    assert os.path.isfile(os.path.join(_HERE, "..", "xefm", "tools", bundled))


def test_xefm_python_is_an_interpreter_path_and_is_desktop_mode_a_bool():
    assert isinstance(user_api.xefm_python, str) and user_api.xefm_python
    assert isinstance(user_api.is_desktop_mode(), bool)

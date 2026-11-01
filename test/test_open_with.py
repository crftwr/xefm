"""Open With: choosing which app opens a file this time (#634).

Covers where the candidates come from — the ``open_with`` lists of
FILE_ASSOCIATIONS rules, concatenated across matching rules, and the OS's
applications — how a mixed selection narrows them to what fits every file, and
``XeFMApp.open_with`` bound to a stand-in self: what it skips, what it lists,
what it launches and what it remembers.

Run with: python -m pytest test/test_open_with.py -v
"""

import os

import pytest

from xefm import app as xefm_app
from xefm import config as xefm_config
from xefm import open_with
from xefm.open_with import Candidate


VSCODE = {'name': 'VS Code', 'command': ['code']}
HEX = {'name': 'Hex view', 'command': ['hexyl'], 'options': {'terminal': True}}
GIMP = {'name': 'GIMP', 'command': ['gimp']}
PREVIEW = {'name': 'Preview', 'command': ['open', '-a', 'Preview']}

RULES = [
    {'pattern': ['*.jpg', '*.png'], 'open': ['open'], 'open_with': [GIMP, PREVIEW]},
    {'pattern': '*.pdf', 'open_with': [PREVIEW]},
    {'pattern': '*.txt', 'edit': ['vim']},
    {'pattern': '*', 'open_with': [VSCODE, HEX]},
]


@pytest.fixture
def rules(monkeypatch):
    def use(associations):
        monkeypatch.setattr(xefm_config, "get_file_associations", lambda: associations)
    use(RULES)
    return use


def names(candidates):
    return [c.name for c in candidates]


# --- the config side ---------------------------------------------------------

def test_every_matching_rule_contributes_in_order(rules):
    assert [p['name'] for p in xefm_config.get_open_with_for_file("a.JPG")] == [
        'GIMP', 'Preview', 'VS Code', 'Hex view']


def test_a_catch_all_rule_reaches_files_no_other_rule_names(rules):
    assert [p['name'] for p in xefm_config.get_open_with_for_file("notes.txt")] == [
        'VS Code', 'Hex view']


def test_a_name_declared_twice_keeps_its_first_entry(rules):
    rules([
        {'pattern': '*.py', 'open_with': [{'name': 'VS Code', 'command': ['code', '-n']}]},
        {'pattern': '*', 'open_with': [VSCODE]},
    ])
    assert xefm_config.get_open_with_for_file("a.py") == [
        {'name': 'VS Code', 'command': ['code', '-n'], 'options': {}}]


def test_entries_are_normalized_like_programs(rules):
    assert xefm_config.get_open_with_for_file("a.bin")[1] == {
        'name': 'Hex view', 'command': ['hexyl'], 'options': {'terminal': True}}


def test_malformed_entries_are_dropped_not_fatal(rules):
    rules([
        {'pattern': '*', 'open_with': [{'name': 'no command'},
                                       {'name': 'string', 'command': 'code'},
                                       VSCODE]},
        {'pattern': '*', 'open_with': {'name': 'not a list'}},
    ])
    assert [p['name'] for p in xefm_config.get_open_with_for_file("a")] == ['VS Code']


def test_open_with_is_not_an_action(rules, monkeypatch):
    # A rule holding only open_with must not stop a later rule's 'open'.
    rules([{'pattern': '*.jpg', 'open_with': [GIMP]},
           {'pattern': '*.jpg', 'open': ['open', '-a', 'Preview']}])
    assert xefm_config.get_program_for_file("a.jpg", "open") == ['open', '-a', 'Preview']
    assert not xefm_config.has_explicit_association("a.jpg", "open_with")


# --- intersection ------------------------------------------------------------

def test_a_mixed_selection_keeps_only_what_fits_every_file(rules):
    assert names(open_with.xefm_candidates(["a.jpg", "b.pdf"])) == [
        'Preview', 'VS Code', 'Hex view']
    assert names(open_with.xefm_candidates(["a.jpg", "b.pdf", "c.txt"])) == [
        'VS Code', 'Hex view']


def test_no_common_candidate_is_an_empty_list(rules):
    rules([{'pattern': '*.jpg', 'open_with': [GIMP]},
           {'pattern': '*.pdf', 'open_with': [PREVIEW]}])
    assert open_with.xefm_candidates(["a.jpg", "b.pdf"]) == []


def test_the_first_files_entry_is_the_one_that_runs(rules):
    rules([{'pattern': '*.py', 'open_with': [{'name': 'VS Code', 'command': ['code', '-n']}]},
           {'pattern': '*', 'open_with': [VSCODE]}])
    [only] = open_with.xefm_candidates(["a.py", "b.txt"])
    assert only.program['command'] == ['code', '-n']
    assert only.detail == "code -n"


def test_default_survives_only_where_it_held_for_every_file():
    a = [Candidate("os:x", "X", "os", default=True), Candidate("os:y", "Y", "os")]
    b = [Candidate("os:y", "Y", "os", default=True), Candidate("os:x", "X", "os")]
    both = open_with.intersect([a, b])
    assert [(c.name, c.default) for c in both] == [("X", False), ("Y", False)]
    assert open_with.intersect([a, a])[0].default


def test_os_candidates_ask_once_per_file_type(monkeypatch):
    asked = []

    def lister(path):
        asked.append(path)
        return [Candidate("os:any", "Any", "os"),
                Candidate(f"os:{os.path.splitext(path)[1]}", "Own", "os")]
    monkeypatch.setitem(open_with._PLATFORM_LISTERS, open_with.sys.platform
                        if open_with.sys.platform in open_with._PLATFORM_LISTERS
                        else "linux", lister)
    found = open_with.os_candidates(["/a/1.jpg", "/a/2.JPG", "/a/3.pdf"])
    assert asked == ["/a/1.jpg", "/a/3.pdf"]
    assert names(found) == ["Any"]


def test_os_candidates_failure_is_an_empty_list(monkeypatch):
    def lister(path):
        raise OSError("LaunchServices is away")
    for platform in list(open_with._PLATFORM_LISTERS):
        monkeypatch.setitem(open_with._PLATFORM_LISTERS, platform, lister)
    assert open_with.os_candidates(["/a/1.jpg"]) == []


# --- when the OS's applications are offered ----------------------------------

def test_the_desktop_app_always_offers_them():
    assert open_with.os_apps_available(True, {"SSH_CONNECTION": "1 2 3 4"})


@pytest.mark.parametrize("var", ["SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY"])
def test_a_terminal_over_ssh_does_not(var):
    assert not open_with.os_apps_available(False, {var: "x", "DISPLAY": ":0"})


def test_a_local_terminal_does(monkeypatch):
    monkeypatch.setattr(open_with.sys, "platform", "darwin")
    assert open_with.os_apps_available(False, {})


def test_linux_needs_a_graphical_session(monkeypatch):
    monkeypatch.setattr(open_with.sys, "platform", "linux")
    assert not open_with.os_apps_available(False, {})
    assert open_with.os_apps_available(False, {"WAYLAND_DISPLAY": "wayland-0"})


# --- platform details that need no platform ----------------------------------

def test_parse_gio_mime():
    text = ("Default application for “text/plain”: org.gnome.TextEditor.desktop\n"
            "Registered applications:\n"
            "\tvim.desktop\n"
            "\torg.gnome.TextEditor.desktop\n"
            "Recommended applications:\n"
            "\torg.gnome.TextEditor.desktop\n"
            "\tcode.desktop\n")
    assert open_with.parse_gio_mime(text) == (
        "org.gnome.TextEditor.desktop",
        ["vim.desktop", "org.gnome.TextEditor.desktop", "code.desktop"])


def test_parse_gio_mime_with_no_default():
    text = ("No default applications for “application/x-foo”\n"
            "Registered applications:\n\tfoo.desktop\n")
    assert open_with.parse_gio_mime(text) == (None, ["foo.desktop"])


def test_macos_launch_hands_every_file_to_one_open(monkeypatch):
    started = []
    monkeypatch.setattr(open_with.sys, "platform", "darwin")
    monkeypatch.setattr(open_with.subprocess, "Popen",
                        lambda argv, **kw: started.append((argv, kw)))
    app = Candidate("os:com.apple.Preview", "Preview", "os",
                    handle="/System/Applications/Preview.app")
    open_with.launch(app, ["/a/1.jpg", "/a/2 b.png"])
    [(argv, kw)] = started
    assert argv == ["open", "-a", "/System/Applications/Preview.app",
                    "/a/1.jpg", "/a/2 b.png"]
    assert kw["stdout"] is open_with.subprocess.DEVNULL   # never over our screen


def test_remembered_choice_goes_first():
    cands = [Candidate(k, k, "os") for k in ("a", "b", "c")]
    assert names(open_with.remembered_first(cands, "c")) == ["c", "a", "b"]
    assert names(open_with.remembered_first(cands, "gone")) == ["a", "b", "c"]
    assert names(open_with.remembered_first(cands, None)) == ["a", "b", "c"]


def test_type_key_is_the_selections_extensions():
    assert open_with.type_key(["/x/a.JPG", "/x/b.jpg", "/x/c.pdf"]) == ".jpg,.pdf"
    assert open_with.type_key(["/x/Makefile"]) == ""


# --- XeFMApp.open_with ---------------------------------------------------------

class FakeEntry:
    def __init__(self, path, *, directory=False):
        self._path = path
        self.name = path.rsplit("/", 1)[-1]
        self._directory = directory

    def is_dir(self):
        return self._directory

    def __str__(self):
        return self._path


class FakeState:
    def __init__(self):
        self.values = {}

    def get_state(self, key, default=None):
        return self.values.get(key, default)

    def set_state(self, key, value):
        self.values[key] = value


class FakePanel:
    def render(self):
        pass


class FakeApp:
    _OPEN_WITH_STATE = xefm_app.XeFMApp._OPEN_WITH_STATE

    def __init__(self, targets):
        self.targets = targets
        self.logged = []
        self.launched = []
        self.state_manager = FakeState()
        self.panel = FakePanel()
        self.pane = {"path": "/x"}

    def active_pane(self):
        return self.pane

    def _selected_or_focused(self, pane):
        return self.targets

    def log_info(self, message):
        self.logged.append(message)

    def _active_pane_region(self):
        return None

    def _program_env(self, pane):
        return {"XEFM": "1"}, "/x"

    def _launch_program(self, name, argv, *, cwd, env, terminal):
        self.launched.append((name, argv, cwd, terminal))

    _is_local = xefm_app.XeFMApp._is_local
    _files_label = staticmethod(xefm_app.XeFMApp._files_label)
    open_with = xefm_app.XeFMApp.open_with
    _open_with_candidate = xefm_app.XeFMApp._open_with_candidate


@pytest.fixture
def picker(monkeypatch, rules):
    """Record the picker and message box instead of drawing them; no OS apps
    unless a test adds some."""
    shown = {}

    def show_filter_list(panel, items, **kw):
        shown["items"], shown["kw"] = list(items), kw
    monkeypatch.setattr(xefm_app, "show_filter_list", show_filter_list)
    monkeypatch.setattr(xefm_app, "show_message_box",
                        lambda panel, message, **kw: shown.setdefault("message", message))
    monkeypatch.setattr(xefm_app, "is_desktop_mode", lambda: True)
    monkeypatch.setattr(open_with, "os_candidates", lambda paths: [])
    return shown


def test_lists_xefm_entries_then_the_os_apps(picker, monkeypatch):
    monkeypatch.setattr(open_with, "os_candidates", lambda paths: [
        Candidate("os:com.apple.Preview", "Preview", "os", default=True, handle="/P.app")])
    app = FakeApp([FakeEntry("/x/a.jpg")])
    app.open_with()
    assert [(c.source, c.name) for c in picker["items"]] == [
        ("xefm", "GIMP"), ("xefm", "Preview"), ("xefm", "VS Code"),
        ("xefm", "Hex view"), ("os", "Preview")]
    kw = picker["kw"]
    assert kw["title"] == "Open a.jpg With"
    assert kw["to_right"](picker["items"][-1]) == "default"
    assert kw["to_detail"](picker["items"][0]) == "gimp"


def test_no_os_apps_over_ssh(picker, monkeypatch):
    monkeypatch.setattr(xefm_app, "is_desktop_mode", lambda: False)
    monkeypatch.setenv("SSH_CONNECTION", "1 2 3 4")
    monkeypatch.setattr(open_with, "os_candidates",
                        lambda paths: pytest.fail("asked the OS over SSH"))
    FakeApp([FakeEntry("/x/a.jpg")]).open_with()
    assert all(c.source == "xefm" for c in picker["items"])


def test_choosing_an_entry_runs_it_on_every_file(picker):
    app = FakeApp([FakeEntry("/x/a.jpg"), FakeEntry("/x/b.pdf")])
    app.open_with()
    hex_view = next(c for c in picker["items"] if c.name == "Hex view")
    picker["kw"]["on_accept"](hex_view)
    assert app.launched == [("Hex view", ["hexyl", "/x/a.jpg", "/x/b.pdf"], "/x", True)]


def test_choosing_an_os_app_launches_it(picker, monkeypatch):
    opened = []
    monkeypatch.setattr(open_with, "os_candidates", lambda paths: [
        Candidate("os:p", "Preview", "os", handle="/P.app")])
    monkeypatch.setattr(open_with, "launch", lambda cand, paths: opened.append((cand.name, paths)))
    app = FakeApp([FakeEntry("/x/a.jpg"), FakeEntry("/x/b.png")])
    app.open_with()
    picker["kw"]["on_accept"](picker["items"][-1])
    assert opened == [("Preview", ["/x/a.jpg", "/x/b.png"])]
    assert app.logged == ["Opened 2 files with Preview"]


def test_a_failed_os_launch_is_logged(picker, monkeypatch):
    def fail(cand, paths):
        raise OSError("gone")
    monkeypatch.setattr(open_with, "os_candidates", lambda paths: [
        Candidate("os:p", "Preview", "os", handle="/P.app")])
    monkeypatch.setattr(open_with, "launch", fail)
    app = FakeApp([FakeEntry("/x/a.jpg")])
    app.open_with()
    picker["kw"]["on_accept"](picker["items"][-1])
    assert app.logged == ["Failed to open a.jpg with Preview: gone"]


def test_the_last_choice_for_a_type_comes_first_next_time(picker):
    app = FakeApp([FakeEntry("/x/a.jpg")])
    app.open_with()
    picker["kw"]["on_accept"](next(c for c in picker["items"] if c.name == "VS Code"))
    app.open_with()
    assert names(picker["items"])[:2] == ["VS Code", "GIMP"]
    # Another type keeps its own order.
    app.targets = [FakeEntry("/x/b.pdf")]
    app.open_with()
    assert names(picker["items"])[0] == "Preview"


def test_directories_and_remote_files_are_skipped(picker):
    app = FakeApp([FakeEntry("/x/dir", directory=True),
                   FakeEntry("ssh://host/a.jpg"),
                   FakeEntry("/x/a.pdf")])
    app.open_with()
    assert app.logged == ["dir is a directory",
                          "a.jpg: external programs need a local file"]
    assert picker["kw"]["title"] == "Open a.pdf With"


def test_nothing_left_opens_no_picker(picker):
    FakeApp([FakeEntry("/x/dir", directory=True)]).open_with()
    assert "items" not in picker and "message" not in picker


def test_no_common_app_says_so(picker, rules):
    rules([{'pattern': '*.jpg', 'open_with': [GIMP]},
           {'pattern': '*.pdf', 'open_with': [PREVIEW]}])
    FakeApp([FakeEntry("/x/a.jpg"), FakeEntry("/x/b.pdf")]).open_with()
    assert picker["message"] == "No app can open all selected files."
    assert "items" not in picker


def test_open_with_is_a_registered_action():
    from xefm.actions import FILER, registry
    assert registry.builtin(FILER, "open_with") is not None

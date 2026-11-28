"""When a menu bar item is enabled (#1019): ``xefm.menu_when``.

The menu bar is on every screen; an item acts on the file manager unless its
``when`` says otherwise, so a session's screen enables only what was declared
to serve it.
"""

import os
import shutil
import tempfile
from types import SimpleNamespace

import pytest
from puikit import Menu

from xefm import menu_when
from xefm.menu_when import MenuItem


def _presets(state):
    return {"files": lambda: state["files"],
            "entry": lambda: state["files"] and state["entry"],
            "selection": lambda: state["files"] and state["selection"]}


def _bar(*items):
    return Menu(MenuItem("Top", submenu=Menu(*items)))


def test_an_item_that_says_nothing_is_the_file_managers():
    state = {"files": True, "entry": False, "selection": False}
    plain = MenuItem("Plain")
    func = MenuItem("Func", when=lambda: True)
    always = MenuItem("Always", when="always")
    menu_when.apply_bar(_bar(plain, func, always), _presets(state))
    assert plain.is_enabled() and func.is_enabled() and always.is_enabled()
    state["files"] = False  # a session's screen
    assert not plain.is_enabled() and not func.is_enabled()
    assert always.is_enabled()


def test_a_parents_screen_is_inherited_and_files_names_it_back():
    state = {"files": False, "entry": True, "selection": True}
    inherits = MenuItem("Keymap")
    busy = {"value": False}
    stateful = MenuItem("Check", when=lambda: not busy["value"])
    back = MenuItem("Install", when="files")
    entry = MenuItem("Open", when="entry")  # about the file manager, always
    menu_when.apply_bar(_bar(MenuItem("Advanced", when="always", submenu=Menu(
        inherits, stateful, back, entry))), _presets(state))
    assert inherits.is_enabled() and stateful.is_enabled()
    assert not back.is_enabled() and not entry.is_enabled()
    busy["value"] = True
    assert not stateful.is_enabled()


def test_presets_functions_and_enabled_must_all_hold():
    state = {"files": True, "entry": True, "selection": False}
    jobs = {"value": False}
    item = MenuItem("Jobs", when=("always", lambda: jobs["value"]))
    sel = MenuItem("Clear", when="selection")
    old = MenuItem("Old", enabled=False)
    menu_when.apply_bar(_bar(item, sel, old), _presets(state))
    assert not item.is_enabled()
    jobs["value"] = True
    assert item.is_enabled()
    assert not sel.is_enabled()
    state["selection"] = True
    assert sel.is_enabled()
    assert not old.is_enabled()  # enabled still counts


def test_a_bar_entry_opens_even_with_every_item_greyed():
    # A File greyed whole did not open on a session's screen (#1019).
    state = {"files": False, "entry": False, "selection": False}
    bar = Menu(MenuItem("File", submenu=Menu(MenuItem("New"))),
               MenuItem("Tools", submenu=Menu(MenuItem("Palette", when="always"))))
    menu_when.apply_bar(bar, _presets(state))
    file, tools = bar.items
    assert file.is_enabled() and tools.is_enabled()
    assert not file.submenu.items[0].is_enabled()


def test_an_unknown_condition_is_refused():
    with pytest.raises(ValueError, match="unknown menu condition"):
        menu_when.apply_bar(_bar(MenuItem("X", when="sometimes")), _presets({}))
    with pytest.raises(TypeError):
        menu_when.apply_bar(_bar(MenuItem("X", when=3)), _presets({}))


# --- the real menu bar ------------------------------------------------------------------

#: What the menu bar offers on a session's screen: each declared ``always``
#: (the rest act on the file manager, out of view there). A new item lands
#: here only by saying so.
_ON_A_SESSION = {
    "Tools > Command Palette…", "Tools > Resume AI Conversation…",
    "Tools > Switch Screen", "Tools > Screens…",
    "Tools > Edit Configuration…", "Tools > Reload Configuration",
    "Tools > Advanced", "Tools > Advanced > Keymap…", "Tools > Advanced > Extensions…",
    "Tools > Advanced > Check for Extension Updates…",
    "Tools > Advanced > Sync Python Packages",
    "View > Theme", "View > Font Size",
    "Help > Keyboard Shortcuts…", "Help > Tip of the Day…",
    "Help > XeFM Documentation", "Help > Release Notes", "Help > Report an Issue…",
    "Help > Check for Updates…", "Help > About XeFM",
}


def _paths(menu, prefix=""):
    """Each item's ``Menu > Item`` path and the item; Theme's and Font Size's
    own items (the themes, the sizes) stand behind their parent's path."""
    for item in menu.items:
        label = getattr(item, "label", "")
        if not label:
            continue
        path = f"{prefix}{label}"
        yield path, item
        if item.submenu is not None and label not in ("Theme", "Font Size"):
            yield from _paths(item.submenu, path + " > ")


@pytest.fixture
def app(monkeypatch):
    from puikit.backends import create_backend

    from xefm import app as xefm_app
    from xefm import backend_detector
    from xefm.state_manager import XeFMStateManager
    for mod in (xefm_app, backend_detector):
        monkeypatch.setattr(mod, "is_desktop_mode", lambda: True, raising=False)
    left, right, state = tempfile.mkdtemp(), tempfile.mkdtemp(), tempfile.mkdtemp()
    open(os.path.join(left, "a.txt"), "w").close()
    backend = create_backend("memory")
    backend.open()
    the_app = xefm_app.XeFMApp(
        backend, left, right, left_provided=True, right_provided=True,
        state_manager=XeFMStateManager(db_path=os.path.join(state, "state.db")))
    the_app.file_monitor.stop_monitoring()
    the_app.file_monitor.enabled = False
    the_app._settle_listings()
    the_app._agent_installed = lambda: True
    the_app._closed_agents = lambda: [object()]
    yield the_app
    the_app.file_monitor.stop_monitoring()
    backend.close()
    for d in (left, right, state):
        shutil.rmtree(d, ignore_errors=True)


def test_a_sessions_screen_offers_only_what_serves_every_screen(app, monkeypatch):
    from xefm import updates
    monkeypatch.setattr(updates, "offers_update_check", lambda: True)
    bar = app._build_menu()
    on_files = {p for p, item in _paths(bar) if item.is_enabled()}
    assert "File > Copy to Other Pane" in on_files and "Tools > New Shell Here" in on_files
    screens = app._screens
    monkeypatch.setattr(screens, "current", SimpleNamespace(session=object()))
    on_a_session = {p for p, item in _paths(bar) if item.is_enabled() and " > " in p}
    assert on_a_session == _ON_A_SESSION
    tops = {p for p, item in _paths(bar) if item.is_enabled() and " > " not in p}
    assert tops == {"File", "Edit", "Go", "Select", "View", "Tools", "Help"}
    items = dict(_paths(bar))
    for parent in ("View > Theme", "View > Font Size"):  # their items inherit it
        assert any(i.is_enabled() for i in items[parent].submenu.items
                   if getattr(i, "label", ""))

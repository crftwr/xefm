"""The command palette and the picker extensions it is built on (discussion #550).

Two halves.

The **picker** (``xefm.filter_list_dialog``) gains three opt-in hooks —
``to_right`` (a right-aligned column), ``to_detail`` (a one-line description of
the highlighted row, above the hint band) and ``to_help`` (a Markdown page for
it on the ``describe_list_item`` key). Each is off unless passed, so the tests
check both that they draw and that a picker without them is unchanged.

The **palette** (``XeFMApp.show_command_palette``) lists every file-list action
the app can run, plus the config's own ``ACTIONS``, and runs the one chosen.

Run with: python -m pytest test/test_command_palette.py -v
"""

import os
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from puikit import Panel  # noqa: E402
from puikit.backends.memory_backend import MemoryBackend  # noqa: E402
from puikit.event import Event, EventType  # noqa: E402

from xefm import actions as xa  # noqa: E402
from xefm import app as xefm_app  # noqa: E402
from xefm import user_api  # noqa: E402
from xefm._config import Config as DefaultConfig  # noqa: E402
from xefm.config import config_manager  # noqa: E402
from xefm.filter_list_dialog import FilterListDialog, show_filter_list  # noqa: E402
from xefm.state_manager import XeFMStateManager  # noqa: E402
from xefm.text_dialog import MarkdownDialog  # noqa: E402


def key(name, char=None, mods=()):
    return Event(type=EventType.KEY, key=name, char=char, modifiers=frozenset(mods))


def _type(dialog, text):
    for ch in text:
        dialog.handle_event(key(ch, ch))


# --------------------------------------------------------------------------- #
# The picker's opt-in hooks
# --------------------------------------------------------------------------- #

@pytest.fixture
def screen():
    backend = MemoryBackend(width=100, height=30)
    backend.open()
    panel = Panel(backend)
    panel.set_text_effect(False)
    panel.set_reduced_motion(True)
    yield backend, panel
    backend.close()


def _rows(backend):
    return ["".join(row).rstrip() for row in backend.snapshot()]


ITEMS = [("alpha", "Ctrl-A", "First letter"),
         ("beta", "", "Second letter"),
         ("gamma", "F7", "Third letter")]


def _show(panel, **kw):
    return show_filter_list(panel, ITEMS, title="Pick",
                            to_label=lambda v: v[0], **kw)


def test_the_right_column_is_drawn_beside_the_label(screen):
    backend, panel = screen
    _show(panel, to_right=lambda v: v[1])
    panel.render()
    row = next(r for r in _rows(backend) if "gamma" in r)
    assert "F7" in row
    assert row.index("F7") > row.index("gamma") + 10   # right-aligned, not adjacent


def test_the_detail_row_follows_the_highlighted_entry(screen):
    backend, panel = screen
    dialog = _show(panel, to_detail=lambda v: v[2])
    panel.render()
    assert any("First letter" in r for r in _rows(backend))
    dialog.handle_event(key("down"))
    panel.render()
    rows = _rows(backend)
    assert any("Second letter" in r for r in rows)
    assert not any("First letter" in r for r in rows)


def test_the_detail_row_sits_above_the_hint_band(screen):
    backend, panel = screen
    _show(panel, to_detail=lambda v: v[2])
    panel.render()
    rows = _rows(backend)
    detail = next(i for i, r in enumerate(rows) if "First letter" in r)
    hint = next(i for i, r in enumerate(rows) if "Esc cancel" in r)
    assert detail < hint


def test_a_picker_without_the_hooks_is_unchanged():
    d = FilterListDialog(["alpha", "beta"])
    assert d.list.items == ["alpha", "beta"]
    assert d.list.row_factory is None
    assert "help" not in d.hint()


def test_filtering_matches_the_label_and_keeps_the_column():
    d = FilterListDialog(ITEMS, to_label=lambda v: v[0], to_right=lambda v: v[1])
    d._refilter("gam")
    assert d.filtered == [ITEMS[2]]
    assert d.list.items == [("gamma", "F7")]
    # The right column is shown, not searched: "F7" finds nothing.
    d._refilter("F7")
    assert d.filtered == []


def test_f1_opens_the_row_help_over_the_picker(screen):
    _backend, panel = screen
    dialog = _show(panel, to_help=lambda v: f"# {v[0]}\n\n{v[2]}")
    _type(dialog, "bet")
    dialog.handle_event(key("f1"))
    top = panel._layers[-1].widget
    assert isinstance(top, MarkdownDialog)
    assert top.title == "beta"
    # Closing the help returns to the picker exactly as it was.
    top.handle_event(key("escape"))
    assert panel._layers[-1].widget is dialog
    assert dialog.filter_edit.text == "bet"
    assert dialog.selected_value() == ITEMS[1]


def test_f1_types_nothing_and_opens_nothing_without_to_help(screen):
    _backend, panel = screen
    dialog = _show(panel)
    dialog.handle_event(key("f1"))
    assert panel._layers[-1].widget is dialog
    assert dialog.filter_edit.text == ""


def test_the_hint_names_the_help_key_only_when_offered():
    plain = FilterListDialog(ITEMS, to_label=lambda v: v[0])
    helped = FilterListDialog(ITEMS, to_label=lambda v: v[0], to_help=lambda v: "")
    assert "F1 help" not in plain.hint()
    assert "F1 help" in helped.hint()


def test_describe_list_item_is_registered_on_f1_in_filter_list_only():
    action = xa.registry.resolve(xa.FILTER_LIST, "describe_list_item")
    assert action is not None and action.resolved_default_keys() == ("F1",)
    assert xa.registry.resolve(xa.FILER, "describe_list_item") is None


# --------------------------------------------------------------------------- #
# The palette, against a live app
# --------------------------------------------------------------------------- #

@pytest.fixture
def app_with():
    made = []

    def build(**config_attrs):
        tmp = tempfile.mkdtemp()
        cfgdir = tempfile.mkdtemp()
        for name in ("a.txt", "b.txt"):
            with open(os.path.join(tmp, name), "w") as fh:
                fh.write("x")
        cfg = DefaultConfig()
        for name, value in config_attrs.items():
            setattr(cfg, name, value)
        saved = (config_manager.config, config_manager._key_bindings)
        config_manager.config = cfg
        config_manager._key_bindings = None
        sm = XeFMStateManager(db_path=os.path.join(cfgdir, "state.db"))
        backend = MemoryBackend(width=120, height=40)
        backend.open()
        app = xefm_app.XeFMApp(backend, tmp, tmp, left_provided=True,
                               right_provided=True, state_manager=sm)
        app._settle_listings()
        made.append((app, backend, sm, tmp, cfgdir, saved))
        return app

    yield build

    for app, backend, sm, tmp, cfgdir, saved in made:
        try:
            app._restore_streams()
            app.file_monitor.stop_monitoring()
            backend.close()
            if hasattr(sm, "close"):
                sm.close()
        except Exception:
            pass
        config_manager.config, config_manager._key_bindings = saved
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(cfgdir, ignore_errors=True)
    xa.registry.unregister_source("user")
    user_api.hooks.clear()


def _palette(app):
    app.dispatch("command_palette")
    dialog = app.panel._layers[-1].widget
    assert isinstance(dialog, FilterListDialog)
    return dialog


def test_ctrl_t_opens_the_palette(app_with):
    app = app_with()
    app.on_event(key("t", None, {"ctrl"}))
    assert isinstance(app.panel._layers[-1].widget, FilterListDialog)


def test_the_palette_lists_runnable_filer_and_common_actions(app_with):
    app = app_with()
    names = [a.name for a in _palette(app).all_items]
    assert "copy_files" in names            # a filer action
    assert "quit" in names                  # an inherited common one
    assert "duplicate_files" in names       # unbound, still reachable
    assert "command_palette" not in names   # not itself
    assert "text_viewer.scroll_up" not in names   # a viewer's, meaningless here
    assert len(names) == len(set(names))


def test_every_row_has_a_handler(app_with):
    app = app_with()
    handlers = app._filer_handlers()
    missing = [a.name for a in _palette(app).all_items
               if not a.is_user and a.name not in handlers]
    assert missing == []


def test_the_right_column_is_the_bound_key(app_with):
    app = app_with()
    dialog = _palette(app)
    by_name = {a.name: a for a in dialog.all_items}
    assert dialog.to_right(by_name["view_file"]) == "V"
    assert dialog.to_right(by_name["duplicate_files"]) == ""


def test_typing_narrows_and_enter_runs_the_action(app_with):
    app = app_with()
    dialog = _palette(app)
    _type(dialog, "toggle hidden")
    assert [a.name for a in dialog.filtered] == ["toggle_hidden"]
    before = app.flm.show_hidden
    dialog.handle_event(key("enter"))
    assert app.flm.show_hidden is not before
    assert dialog not in [slot.widget for slot in app.panel._layers]


def test_user_actions_are_listed_and_described_by_their_docstring(app_with):
    ran = []

    def tidy(ctx):
        """Tidy the pane.

        Longer explanation here.
        """
        ran.append(True)

    app = app_with(ACTIONS={"tidy_up": tidy})
    dialog = _palette(app)
    action = next(a for a in dialog.all_items if a.name == "tidy_up")
    assert dialog.to_detail(action) == "Tidy the pane."
    page = dialog.to_help(action)
    assert "Longer explanation here." in page
    assert "config.py" in page
    _type(dialog, "tidy")
    dialog.handle_event(key("enter"))
    assert ran == [True]


def test_the_help_page_names_keys_and_selection_requirement(app_with):
    app = app_with()
    dialog = _palette(app)
    by_name = {a.name: a for a in dialog.all_items}
    page = dialog.to_help(by_name["copy_files"])
    assert "`C`" in page and "Needs a selection" in page
    assert "none — bind one" in dialog.to_help(by_name["duplicate_files"])


def test_the_palette_is_in_the_tools_menu_and_the_help(app_with):
    app = app_with()
    assert "command_palette" in [name for _t, rows in app._HELP_SECTIONS
                                 for name, _d in rows]
    tools = next(item.submenu for item in app.menu_bar.menu.selectable
                 if item.label == "Tools")
    assert "Command Palette…" in [item.label for item in tools.selectable]


# --------------------------------------------------------------------------- #
# The built-in help text
# --------------------------------------------------------------------------- #

def test_every_help_entry_names_a_real_action():
    """A typo in ``_DETAILS`` would silently leave an action without its page."""
    unknown = [name for name in xa._DETAILS
               if xa.registry.resolve(xa.FILER, name) is None]
    assert unknown == []


def test_help_reaches_the_file_list_actions_only():
    """``copy_files`` in the directory diff is the same name doing something
    else — the file list's page must not describe it."""
    assert xa.registry.resolve(xa.FILER, "copy_files").details
    assert xa.registry.resolve(xa.DIR_DIFF, "copy_files").details == ""


def test_the_help_page_does_not_repeat_the_title_or_hang_a_bullet(app_with):
    app = app_with()
    dialog = _palette(app)
    go_root = next(a for a in dialog.all_items if a.name == "go_root")
    page = dialog.to_help(go_root)
    assert "Action name" not in page
    assert "\n- " not in page and not page.startswith("- ")
    assert go_root.details in page


# --------------------------------------------------------------------------- #
# A user action is described by its docstring
# --------------------------------------------------------------------------- #

def _loaded(spec):
    from xefm.user_api import _build_action
    action, problem = _build_action("mine", spec)
    assert problem is None
    return action


def test_the_docstring_summary_is_the_description_and_the_rest_the_help():
    def mine(ctx):
        """Open the item in VS Code.

        Works on directories too.

        A second paragraph.
        """
    action = _loaded(mine)
    assert action.description == "Open the item in VS Code."
    assert action.details == "Works on directories too.\n\nA second paragraph."


def test_a_wrapped_summary_is_joined_onto_one_line():
    def mine(ctx):
        """Open the item under the cursor
        in VS Code."""
    action = _loaded(mine)
    assert action.description == "Open the item under the cursor in VS Code."
    assert action.details == ""


def test_a_description_entry_is_split_like_a_docstring():
    action = _loaded({"func": lambda ctx: None, "description": """
        Open the item in VS Code.

        Works on directories too.
        """})
    assert action.description == "Open the item in VS Code."
    assert action.details == "Works on directories too."


def test_a_description_entry_replaces_the_docstring_whole():
    """Half from each would leave no way to tell which text is showing."""
    def mine(ctx):
        """Summary.

        Details.
        """
    action = _loaded({"func": mine, "description": "Mine"})
    assert (action.description, action.details) == ("Mine", "")


def test_a_one_line_description_entry_reads_as_before():
    """Every config written before the split carries a one-line description."""
    action = _loaded({"func": lambda ctx: None, "description": "Tidy"})
    assert (action.description, action.details) == ("Tidy", "")


def test_without_a_docstring_the_name_stands_in():
    action = _loaded(lambda ctx: None)
    assert action.description == "User action 'mine'"
    assert action.details == ""


# --------------------------------------------------------------------------- #
# Over a viewer or the terminal (#900)
# --------------------------------------------------------------------------- #

def _viewer(app):
    from pathlib import Path
    from xefm.text_viewer import show_text_viewer
    return show_text_viewer(app.panel, Path(app.pm.left_pane["path"]) / "a.txt")


def test_the_palette_over_a_viewer_lists_only_what_the_viewer_runs(app_with):
    app = app_with()
    viewer = _viewer(app)
    app.on_event(key("t", None, {"ctrl"}))
    dialog = app.panel._layers[-1].widget
    assert isinstance(dialog, FilterListDialog)
    names = {a.name for a in dialog.all_items}
    assert names == viewer.palette_actions() - {"command_palette"}
    # Its own actions and the app-wide ones it takes - never a file-list
    # action, which would act on the panes hidden behind it.
    assert "text_viewer.scroll_down" in names and "toggle_color_scheme" in names
    assert "copy_files" not in names and "delete_files" not in names
    # A row runs in the viewer, which is on top again.
    wrap = viewer.wrap
    _type(dialog, "toggle_wrap")
    dialog.handle_event(key("enter"))
    assert app.panel._layers[-1].widget is viewer
    assert viewer.wrap is not wrap


def test_an_app_wide_action_runs_from_the_viewer_by_its_key_too(app_with):
    app = app_with(KEY_BINDINGS={**DefaultConfig().KEY_BINDINGS,
                                 "toggle_color_scheme": ["Ctrl-Y"]})
    _viewer(app)
    before = app._theme_index
    app.on_event(key("y", None, {"ctrl"}))
    assert app._theme_index != before


def test_a_dialog_an_app_wide_action_opens_shows_over_the_viewer(app_with):
    app = app_with()
    viewer = _viewer(app)
    viewer.run_action("choose_keymap")
    top = app.panel.top_layer()
    assert top is not viewer
    # Over the viewer in the layer tree (#951): its child, whatever its z.
    assert app.panel.layer_parent(top) is viewer


class _Terminal:
    """A stand-in for XeFM's terminal: its palette protocol and key rule, no
    emulator (libghostty is not installed where the tests run)."""

    palette_context = "terminal"

    def __init__(self):
        from xefm.terminal import TerminalView
        self.ran = []
        self.takes_binding = lambda e, a: TerminalView.takes_binding(self, e, a)
        self._qualified = TerminalView._qualified

    def palette_actions(self):
        return {"terminal.close"}

    def run_action(self, name):
        self.ran.append(name)
        return True

    def draw(self, ctx):
        pass

    def handle_event(self, event):
        return True


def test_an_inherited_palette_key_stays_the_programs(app_with):
    app = app_with(KEY_BINDINGS={**DefaultConfig().KEY_BINDINGS,
                                 "command_palette": ["Ctrl-T", "Ctrl-Shift-P"]})
    terminal = _Terminal()
    app.panel.push_layer(terminal, z=75)
    app.on_event(key("t", None, {"ctrl"}))            # the shell's Ctrl-T
    assert app.panel._layers[-1].widget is terminal
    app.on_event(key("p", None, {"ctrl", "shift"}))   # a chord no terminal gets
    dialog = app.panel._layers[-1].widget
    assert isinstance(dialog, FilterListDialog)
    assert [a.name for a in dialog.all_items] == ["terminal.close"]
    _type(dialog, "terminal.close")
    dialog.handle_event(key("enter"))
    assert terminal.ran == ["terminal.close"]


def test_a_binding_qualified_for_the_terminal_wins_over_the_program(app_with):
    app = app_with(KEY_BINDINGS={**DefaultConfig().KEY_BINDINGS,
                                 "command_palette": ["Ctrl-T"],
                                 "terminal.command_palette": ["Ctrl-T"]})
    terminal = _Terminal()
    app.panel.push_layer(terminal, z=75)
    app.on_event(key("t", None, {"ctrl"}))
    assert isinstance(app.panel._layers[-1].widget, FilterListDialog)


def test_over_a_session_the_palette_shows_only_the_keys_that_work_there(app_with):
    # A key the terminal leaves to its program reads as a shortcut that does
    # nothing; the palette over it lists only what reaches XeFM (#1019).
    from xefm.terminal import TerminalView
    app = app_with(KEY_BINDINGS={**DefaultConfig().KEY_BINDINGS,
                                 "terminal.close": ["Command-W"],
                                 "screens": ["F5", "Ctrl-Shift-S"]})
    terminal = _Terminal()
    terminal.takes_key = lambda expr, a: TerminalView.takes_key(terminal, expr, a)
    terminal.palette_actions = lambda: {"terminal.close", "screens"}
    app.panel.push_layer(terminal, z=75)
    app.show_command_palette()
    dialog = app.panel._layers[-1].widget
    by_name = {a.name: a for a in dialog.all_items}
    assert dialog.to_right(by_name["screens"]) == app.keys.format_key_for_display(
        "Ctrl-Shift-S")  # F5 is the program's
    assert dialog.to_right(by_name["terminal.close"]) == app.keys.format_key_for_display(
        "Command-W")

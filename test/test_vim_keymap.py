"""The Vim-style keymap preset (#587): vifm's keys, key sequences included.

The table half checks the preset as data: no clashes, nothing a terminal
cannot send, no prefix that is also a key of its own. The app half presses
keys on the memory backend, in the file list and in the text viewer.
"""

import copy
import os
import sys
from collections import defaultdict

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, ".."))
sys.path.insert(0, _HERE)

from puikit import Event, EventType, Panel  # noqa: E402
from puikit.backends.memory_backend import MemoryBackend  # noqa: E402

from test_customization_api import app_with, key  # noqa: E402,F401
from xefm import keymap_presets  # noqa: E402
from xefm.actions import COMMON, FILER, TEXT_VIEWER, registry  # noqa: E402
from xefm.config import KeyBindings, config_manager  # noqa: E402


def press(target, *keys):
    """Send each key — ``'j'``, ``'G'`` for Shift-G, ``'C-d'`` for Ctrl-D, a
    named key such as ``'escape'`` — to ``target``'s event handler."""
    for spec in keys:
        if spec.startswith("C-"):
            event = key(spec[2:], None, ("ctrl",))
        elif len(spec) == 1 and spec.isupper():
            event = key(spec.lower(), spec, ("shift",))
        elif len(spec) == 1:
            event = key(spec, spec)
        else:
            event = key(spec)
        target(event)


# --------------------------------------------------------------------------- #
# The table
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def table():
    return keymap_presets.table(keymap_presets.VIM)


def _keys(value):
    return value["keys"] if isinstance(value, dict) else value


def test_it_is_a_letter_layout_with_no_type_ahead():
    preset = keymap_presets.PRESETS[keymap_presets.VIM]
    assert not preset.type_ahead
    # Its letters are its own: the common table binds none in the file list.
    table = keymap_presets.table(keymap_presets.VIM)
    assert _keys(table["cursor_down"])[0] == "j"
    assert preset.label == "Vim style"


def test_every_binding_names_an_action_this_xefm_has():
    assert [a for a in keymap_presets._VIM_BINDINGS if not keymap_presets._known(a)] == []


@pytest.mark.parametrize("context", [FILER, TEXT_VIEWER])
def test_no_key_runs_two_actions(table, context):
    kb = KeyBindings(table)
    seen = defaultdict(set)
    for parsed, action, selection in kb._context_entries(context):
        seen[(parsed, selection)].add(action)
    assert {k: v for k, v in seen.items() if len(v) > 1} == {}


@pytest.mark.parametrize("context", [FILER, TEXT_VIEWER])
def test_no_prefix_is_also_a_key_of_its_own(table, context):
    """g, y, d, z, c, Z, D only begin sequences, so pressing one never waits
    out KEY_SEQUENCE_TIMEOUT."""
    kb = KeyBindings(table)
    for parsed, action, _sel in kb._context_entries(context):
        if parsed[2] != "seq":
            continue
        first = parsed[0][0]
        identity, mods, _mode = first
        event = key(identity, identity if not mods else
                    (identity.upper() if mods == {"shift"} else None), tuple(mods))
        exact, longer = kb.sequence_lookup([event], False, context)
        assert longer and exact is None, (action, first)


def test_every_key_parses(table):
    kb = KeyBindings(table)
    warnings = []
    kb.logger.warning = warnings.append
    for action in keymap_presets._VIM_BINDINGS:
        for expr in _keys(table.get(action)) or []:
            kb._parse_key_expression(expr)
    assert warnings == []


def test_nothing_a_terminal_cannot_send(table):
    kb = KeyBindings(table)
    for action in keymap_presets._VIM_BINDINGS:
        for expr in _keys(table.get(action)) or []:
            for part in expr.split():
                ident, mods, _mode = kb._parse_key_expression(part)
                assert "cmd" not in mods, (action, expr)
                assert not (len(ident) == 1 and ident.isalpha()
                            and {"ctrl", "shift"} <= mods), (action, expr)
                assert not (ident == "enter" and mods & {"ctrl", "alt"}), (action, expr)


def test_follows_vifm(table):
    expected = {
        "cursor_down": "j", "cursor_up": "k", "go_parent": "h", "open_item": "l",
        "cursor_top": "g g", "cursor_bottom": "Shift-G", "switch_pane": "TAB",
        "toggle_select_in_place": "t", "clipboard_copy": "y y",
        "delete_files": "d d", "delete_permanently": "Shift-D Shift-D",
        "clipboard_paste": "p", "rename": "c w", "isearch": "/",
        "search_next": "n", "search_prev": "Shift-N", "toggle_hidden": "z a",
        "view_file": "e", "quick_view": "w", "half_page_down": "Ctrl-D",
        "half_page_up": "Ctrl-U", "go_back": "Ctrl-O", "command_palette": ":",
        "quit": "Shift-Z Shift-Z",
    }
    for action, first in expected.items():
        assert _keys(table[action])[0] == first, action


# --------------------------------------------------------------------------- #
# In the file list
# --------------------------------------------------------------------------- #

@pytest.fixture
def vim_app(app_with):
    app, tmp = app_with()
    for i in range(30):
        open(os.path.join(tmp, f"n{i:02}.txt"), "w").close()
    app.set_keymap_preset(keymap_presets.VIM)
    app.reread()
    app._settle_listings()
    pane = app.active_pane()
    pane["focused_index"] = 0
    return app


def test_hjkl_gg_and_G(vim_app):
    app = vim_app
    pane = app.active_pane()
    press(app.on_event, "j", "j")
    assert pane["focused_index"] == 2
    press(app.on_event, "k")
    assert pane["focused_index"] == 1
    press(app.on_event, "G")
    assert pane["focused_index"] == len(pane["files"]) - 1
    press(app.on_event, "g")
    assert app.key_sequence.pending           # g waits for its second key
    press(app.on_event, "g")
    assert pane["focused_index"] == 0


def test_half_page(vim_app):
    app = vim_app
    pane = app.active_pane()
    step = max(1, app._display_height() // 2)
    press(app.on_event, "C-d")
    assert pane["focused_index"] == step
    press(app.on_event, "C-u")
    assert pane["focused_index"] == 0


def test_t_marks_without_moving(vim_app):
    app = vim_app
    pane = app.active_pane()
    press(app.on_event, "j", "t")
    assert pane["focused_index"] == 1
    assert str(pane["files"][1]) in pane["selected_files"]
    press(app.on_event, "escape")             # vifm: Esc clears the selection
    assert not pane["selected_files"]


def test_n_and_N_repeat_the_last_search(vim_app):
    app = vim_app
    pane = app.active_pane()
    app._last_isearch_pattern = "n1"
    press(app.on_event, "n")
    first = pane["files"][pane["focused_index"]].name
    assert first.startswith("n1")
    press(app.on_event, "n")
    assert pane["files"][pane["focused_index"]].name > first
    press(app.on_event, "N")
    assert pane["files"][pane["focused_index"]].name == first


def test_n_with_no_search_says_so(vim_app):
    app = vim_app
    lines = []
    app.log_info = lines.append
    press(app.on_event, "n")
    assert lines == ["No previous search"]


def test_za_toggles_hidden_files(vim_app):
    app = vim_app
    before = app.flm.show_hidden
    press(app.on_event, "z", "a")
    assert app.flm.show_hidden is not before


def test_yy_puts_the_file_on_the_clipboard(vim_app):
    app = vim_app
    press(app.on_event, "y", "y")
    assert app.clipboard.paths


def test_ZZ_asks_before_quitting(vim_app):
    app = vim_app
    press(app.on_event, "Z", "Z")
    assert app._quit_confirming and app.panel.has_layers


def test_q_alone_does_nothing_in_the_file_list(vim_app):
    app = vim_app
    press(app.on_event, "q")
    assert not app.panel.has_layers


# --------------------------------------------------------------------------- #
# In the text viewer
# --------------------------------------------------------------------------- #

@pytest.fixture
def vim_keys():
    """The shared config, with the Vim table for the viewer to read."""
    cfg = config_manager.get_config()
    saved = (copy.deepcopy(cfg.KEY_BINDINGS), config_manager._key_bindings)
    cfg.KEY_BINDINGS = keymap_presets.table(keymap_presets.VIM)
    config_manager._key_bindings = None
    yield
    cfg.KEY_BINDINGS, config_manager._key_bindings = saved


@pytest.fixture
def viewer(vim_keys, tmp_path):
    from xefm.path import Path
    from xefm.text_viewer import show_text_viewer
    path = tmp_path / "long.txt"
    path.write_text("\n".join(f"line {i}" for i in range(200)))
    panel = Panel(MemoryBackend(width=60, height=12))
    v = show_text_viewer(panel, Path(str(path)))
    panel.render()
    return v, panel


def test_viewer_jk_gg_G_and_q(viewer):
    v, panel = viewer
    press(panel.dispatch_event, "j", "j")
    assert v.top == 2
    press(panel.dispatch_event, "G")
    assert v.top > 100
    press(panel.dispatch_event, "g", "g")
    assert v.top == 0
    press(panel.dispatch_event, "q")
    assert not panel.has_layers


def test_viewer_sends_the_rich_renderer_the_key_it_understands(viewer):
    v, _panel = viewer
    seen = []

    class Rich:
        def handle_event(self, event):
            seen.append(event.key)

    v.mode, v._rich_widget = "rich", Rich()
    v._act("text_viewer.scroll_down", key("j", "j"))
    v._act("text_viewer.scroll_top", None)     # completed by a sequence's timeout
    assert seen == ["down", "home"]

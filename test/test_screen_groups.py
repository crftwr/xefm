"""Screens in groups, the screen strip, closing that loses nothing and the
names of AI sessions (discussion #1019).

The app's methods against a PuiKit Panel on the memory backend with stand-in
session views, as test_terminal_sessions does; the strip and the tab strip
drawn on their own."""

from types import SimpleNamespace

from puikit import Event, EventType, Panel
from puikit.backends.memory_backend import MemoryBackend

from xefm import agent_chat as C
from xefm.app import XeFMApp
from xefm.screens import FILES
from xefm.terminal_sessions import (AGENT, GROUP_AGENT, GROUP_TERMINAL, ClosedAgent, Session,
                                    ago, title_from_request, title_from_terminal)

from test_terminal_sessions import _app, _shown, _Switcher, _View


# --- names --------------------------------------------------------------------------

def test_a_title_is_the_requests_first_line_cut_at_a_word():
    assert title_from_request("Fix the login bug\n\n(Asked from XeFM...)") == "Fix the login bug"
    long = title_from_request("Please refactor the login handler so that it validates tokens")
    assert long.endswith("…") and len(long) <= 40 and " " not in long[-2:]
    assert title_from_request("  \n  spaces   run   together ") == "spaces run together"


def test_a_terminal_title_names_the_session_only_when_it_says_more_than_the_program():
    generic = {"Claude Code", "claude"}
    assert title_from_terminal("✳ Claude Code", generic) == ""
    assert title_from_terminal("⠂ Fix the login bug", generic) == "Fix the login bug"
    assert title_from_terminal("", generic) == ""


def test_ago_says_how_long_in_a_word():
    assert ago(100.0, now=130.0) == "now"
    assert ago(0.0, now=300.0) == "5m ago"
    assert ago(0.0, now=7200.0) == "2h ago"
    assert ago(0.0, now=3 * 86400.0) == "3d ago"


# --- groups -------------------------------------------------------------------------

class _ChatView(_View):
    """A drawn agent's view: busy only mid-turn."""

    @property
    def busy(self):
        return self.running and self._busy


def _agent_session(app, name="Claude Code", cwd="/w", sid="s-1", said="Fix the bug"):
    """A drawn agent session with a conversation that had a turn."""
    view = _ChatView(shell=False)
    view.entry_name = name
    conv = C.Conversation()
    conv.session_id = sid
    if said:
        conv.add_user(said)
    conv.state = C.IDLE
    view.conversation = conv
    session = app._sessions.add(Session(view=view, kind=AGENT, name=name, cwd=cwd,
                                        named=True))
    app._add_session_screen(session, view)
    return session


def test_sessions_fall_into_the_terminals_group_and_the_agents(monkeypatch):
    app = _app(monkeypatch)
    app.new_shell()
    agent = _agent_session(app)
    shell = app._sessions.for_view(app.made[0])
    assert shell.group == GROUP_TERMINAL and agent.group == GROUP_AGENT
    assert shell.screen.screen_group == GROUP_TERMINAL
    assert app._screens.files.screen_group == FILES
    assert app._screens.in_group(GROUP_AGENT) == [agent.screen]
    assert app._screens_part() == "1 shell · 1 AI"


def test_a_group_key_goes_back_to_the_screen_used_last(monkeypatch):
    app = _app(monkeypatch)
    app.new_shell()
    app.new_shell()
    first, second = app.made
    app._show_screen(app._sessions.for_view(first).screen)
    app._show_screen(app._screens.files)
    app.subshell()  # the shell used last, not the newest one
    assert first.shown and len(app.made) == 2


def test_closing_a_tab_shows_its_neighbour_in_the_group(monkeypatch):
    app = _app(monkeypatch)
    for _ in range(3):
        app.new_shell()
    a, b, c = (app._sessions.for_view(v) for v in app.made)
    _agent_session(app)  # another group: never where a shell's close goes
    app._show_screen(b.screen)
    app._close_session(b)  # the next tab
    assert app._screens.current is c.screen
    app._close_session(c)  # the last tab: the one before it
    assert app._screens.current is a.screen
    app._close_session(a)  # alone in the group: the file manager
    assert app._screens.current is app._screens.files


def test_next_and_previous_tab_wrap_within_the_group(monkeypatch):
    app = _app(monkeypatch)
    app.new_shell()
    app.new_shell()
    a, b = (app._sessions.for_view(v) for v in app.made)
    assert app._screens.current is b.screen
    app._screen_action("terminal.next_tab")
    assert app._screens.current is a.screen
    app._screen_action("terminal.prev_tab")
    assert app._screens.current is b.screen
    app._screen_action("terminal.new")  # another of the same kind
    assert len(app.made) == 3 and app._screens.current.session.view is app.made[2]


# --- the strip ----------------------------------------------------------------------

def test_the_strip_shows_with_two_screens_in_the_group_and_the_view_makes_room(monkeypatch):
    app = _app(monkeypatch)
    app.new_shell()
    [first] = app.made
    screen = app._sessions.for_view(first).screen
    assert app._screen_tabs(screen) == ([], -1)
    view_slot = app.panel._find_layer(first)
    assert view_slot.reflow(100, 40).y == 0
    app.new_shell()
    tabs, current = app._screen_tabs(screen)
    assert [t.label for t in tabs] == ["zsh", "zsh"] and current == 0
    assert all(t.icon == "$" and t.closable for t in tabs)
    assert view_slot.reflow(100, 40).y == app._strip_height() > 0


def test_a_tab_says_when_its_session_wants_you(monkeypatch):
    app = _app(monkeypatch)
    app.new_shell()
    app.new_shell()
    a, b = (app._sessions.for_view(v) for v in app.made)
    a.attention = ("attention", "zsh: asking")
    tabs, _ = app._screen_tabs(b.screen)
    assert tabs[0].mark == "⚠" and tabs[1].mark == ""


def test_a_click_on_the_strip_switches_tabs_or_opens_another(monkeypatch):
    from xefm.screen_strip import NEW_TAB
    app = _app(monkeypatch)
    app.new_shell()
    app.new_shell()
    a, b = (app._sessions.for_view(v) for v in app.made)
    hits = iter([0, NEW_TAB])
    b.screen.strip.hit = lambda x, y: next(hits)
    click = Event(type=EventType.MOUSE_CLICK, x=3.0, y=-0.5, button="left")
    from xefm.terminal import strip_event
    b.view.on_strip_event = lambda e: app._strip_event(b.screen, e)
    assert strip_event(b.view, click)
    assert app._screens.current is a.screen
    assert strip_event(b.view, click)
    assert len(app.made) == 3


class _DrawnView(_View):
    """A stand-in session view that draws: a page of dots."""

    def draw(self, ctx):
        from puikit import Style
        w, h = ctx.size_units
        for y in range(int(h)):
            ctx.draw_text(0, y, "." * int(w), Style())

    def handle_event(self, event):
        return True


def test_the_strip_is_drawn_over_a_session_view_that_covers_the_screen(monkeypatch):
    # The session view is a "cover" layer, and PuiKit draws a screen from its
    # topmost cover layer up: a strip under the view was never drawn.
    app = _app(monkeypatch)
    app._make_session_view = lambda argv, *, cwd, env, label, shell: _DrawnView(shell=shell)
    app.new_shell()
    app.new_shell()
    Panel.render(app.panel)
    rows = app.panel.backend.snapshot()
    assert "zsh" in rows[0] and "+" in rows[0]
    assert set(rows[1].strip()) == {"."}  # the view starts below the strip
    # Still the view's screen: its top layer and where its keys go.
    current = app._screens.current
    assert app._screens.top_layer() is current.session.view
    from xefm.screen_strip import top_surface
    assert top_surface(app.panel) is current.session.view


def test_a_tab_has_an_icon_a_mark_in_its_place_and_a_close_button():
    from xefm.screen_strip import CLOSE, ScreenStrip
    from xefm.tab_strip import CLOSE_GLYPH, Tab
    panel = Panel(MemoryBackend(width=60, height=10))
    strip = ScreenStrip(lambda: ([Tab("zsh", icon="$", closable=True),
                                  Tab("claude", "⚠", icon="✦", closable=True)], 0))
    panel.push_layer(strip, z=1, interactive=False, hints={"x": 0, "y": 0, "w": 60, "h": 1})
    panel.render()
    row = panel.backend.snapshot()[0]
    assert "$ zsh" in row and "⚠ claude" in row and CLOSE_GLYPH not in row
    assert "✦" not in row  # the mark stands where the icon would
    # The close button shows only while the pointer is over its tab; its room
    # is kept, so nothing moves.
    before = list(strip._strip.hits)
    tx0, tx1, _ = strip._strip.hits[1]
    panel.dispatch_event(Event(type=EventType.MOUSE_MOVE, x=tx0 + 1.0, y=0.5))
    panel.render()
    row = panel.backend.snapshot()[0]
    assert f"⚠ claude {CLOSE_GLYPH}" in row and f"$ zsh {CLOSE_GLYPH}" not in row
    assert strip._strip.hits == before
    x0, x1, _ = strip._strip.close_hits[1]
    assert strip.hit(x1 - 0.5, 0.5) == (CLOSE, 1)
    assert strip.hit(x0 - 0.5, 0.5) == 1  # the room before the × is the tab
    tx0, _, _ = strip._strip.hits[1]
    assert strip.hit(tx0 + 0.5, 0.5) == 1  # the rest of the tab shows it


class _VectorCtx:
    """Just enough of a vector DrawContext for TabStrip.draw: one unit per
    character, every call recorded."""

    vector_shapes = True
    background = (255, 255, 255)
    size_units = (60.0, 2.0)
    base_size = (8, 16)

    def __init__(self):
        from puikit.theme import DEFAULT_THEME
        self.theme = DEFAULT_THEME
        self.calls = []

    def ink(self, color, on=None, target=None):
        return color

    def measure_text(self, text, style=None):
        return float(len(text))

    def fill_rect(self, x, y, w, h, style):
        self.calls.append(("fill", x, y, w, h))

    def round_rect(self, x, y, w, h, style, radius=0.0, hints=None):
        self.calls.append(("round", x, y, w, h))

    def draw_text(self, x, y, text, style, ink=True):
        self.calls.append(("text", x, y, text))

    def pointer_in(self, x, y, w, h):
        return True  # hovering everywhere: the close button shows


def test_gui_tabs_are_taller_with_the_text_in_the_middle():
    from xefm.screen_strip import PAD_PX, TAB_HEIGHT_GUI, strip_height
    from xefm.tab_strip import Tab, TabStrip
    ctx = _VectorCtx()
    strip = TabStrip()
    strip.draw(ctx, [Tab("zsh", icon="$", closable=True)], 0, 1.0, 0.25, 50.0,
               emphasis=True, ground_height=1.85, height=TAB_HEIGHT_GUI)
    rounds = [c for c in ctx.calls if c[0] == "round"]
    assert rounds == [("round", 1.0, 0.25, rounds[0][3], TAB_HEIGHT_GUI)]
    texts = {c[3]: c[2] for c in ctx.calls if c[0] == "text"}
    assert texts["zsh"] == texts["$"] == texts["×"] == 0.25 + 0.3  # 30% above
    assert strip.row == (0.25, 0.25 + TAB_HEIGHT_GUI)
    # The strip: the tab and the inset above it; a terminal's is one row.
    gui = SimpleNamespace(capabilities=SimpleNamespace(supports=lambda c: True),
                          base_size=(8, 16))
    grid = SimpleNamespace(capabilities=SimpleNamespace(supports=lambda c: False))
    assert strip_height(gui) == TAB_HEIGHT_GUI + PAD_PX / 16
    assert strip_height(grid) == 1.0
    # A dragged tab's landing place: a 2 px line in the gap, as tall as the tabs.
    strip.drop_slot = 0
    ctx.calls.clear()
    strip._draw_drop_line(ctx, 0.25, TAB_HEIGHT_GUI, strip.GAP)
    [line] = [c for c in ctx.calls if c[0] == "fill"]
    assert line[3] == 2.0 / 8 and line[4] == TAB_HEIGHT_GUI
    assert line[1] + line[3] / 2 == 1.0 - strip.GAP / 2


def test_on_a_grid_the_close_buttons_backing_is_its_own_cell():
    # A half cell of room on each side rounded onto the cell beside the ×.
    from xefm.screen_strip import ScreenStrip
    from xefm.tab_strip import CLOSE_GLYPH, Tab
    panel = Panel(MemoryBackend(width=60, height=10))
    strip = ScreenStrip(lambda: ([Tab("zsh", icon="$", closable=True),
                                  Tab("vim", icon=">", closable=True)], 0))
    panel.push_layer(strip, z=1, interactive=False, hints={"x": 0, "y": 0, "w": 60, "h": 1})
    panel.render()
    x0, x1, _ = strip._strip.close_hits[1]
    glyph = int(x0)
    assert x1 - x0 == 1.0  # the button is the ×'s cell: what a click hits
    panel.dispatch_event(Event(type=EventType.MOUSE_MOVE, x=glyph + 0.5, y=0.5))
    panel.render()
    b = panel.backend
    assert b.snapshot()[0][glyph] == CLOSE_GLYPH
    chip = b.style_at(glyph - 2, 0).bg  # the label's cell: the chip itself
    assert b.style_at(glyph, 0).bg != chip  # the backing is under the ×...
    assert b.style_at(glyph - 1, 0).bg == chip  # ...and on no cell beside it
    assert b.style_at(glyph + 1, 0).bg == chip


def test_a_click_on_a_tabs_close_button_closes_that_session(monkeypatch):
    from xefm.screen_strip import CLOSE
    app = _app(monkeypatch)
    app.new_shell()
    app.new_shell()
    a, b = (app._sessions.for_view(v) for v in app.made)
    for s in (a, b):
        s.view.on_close_request = app._session_close_request
    b.screen.strip.hit = lambda x, y: (CLOSE, 0)
    app._strip_event(b.screen, Event(type=EventType.MOUSE_CLICK, x=3.0, y=-0.5,
                                     button="left"))
    assert app._sessions.for_view(a.view) is None and app._screens.current is b.screen


def test_the_strip_draws_its_tabs_and_tells_what_a_click_hit():
    from xefm.screen_strip import NEW_TAB, ScreenStrip
    from xefm.tab_strip import Tab
    panel = Panel(MemoryBackend(width=60, height=10))
    strip = ScreenStrip(lambda: ([Tab("zsh"), Tab("build", "✓")], 1))
    panel.push_layer(strip, z=1, interactive=False, hints={"x": 0, "y": 0, "w": 60, "h": 1})
    panel.render()
    row = panel.backend.snapshot()[0]
    assert "zsh" in row and "✓ build" in row and "+" in row
    x0, x1, _ = strip._strip.hits[0]
    assert strip.hit((x0 + x1) / 2, 0.5) == 0
    x0, x1, _ = strip._strip.hits[-1]
    assert strip.hit((x0 + x1) / 2, 0.5) == NEW_TAB
    assert strip.hit(0.0, 3.0) is None


# --- closing ------------------------------------------------------------------------

def test_an_idle_shell_closes_without_asking_and_a_busy_one_asks(monkeypatch):
    import xefm.app as app_mod
    asked = []
    monkeypatch.setattr(app_mod, "show_message_box",
                        lambda *a, **k: asked.append(k.get("on_result")))
    app = _app(monkeypatch)
    app.new_shell()
    app.new_shell()
    idle, busy = app.made
    busy._busy = True
    app._session_close_request(idle)
    assert app._sessions.for_view(idle) is None and asked == []
    app._session_close_request(busy)
    assert app._sessions.for_view(busy) is not None and len(asked) == 1
    asked[0]("Close")
    assert app._sessions.for_view(busy) is None


def test_screens_closes_every_idle_session_at_once(monkeypatch):
    app = _app(monkeypatch)
    switcher = _Switcher(monkeypatch)
    app.new_shell()
    app.new_shell()
    idle, busy = app.made
    busy._busy = True
    app.screens()
    labels = switcher.labels()
    assert "Close 1 idle session" in labels
    dialog = switcher.last
    dialog.kw["on_accept"](dialog.items[labels.index("Close 1 idle session")])
    assert [s.view for s in app._sessions] == [busy]


def test_screens_renames_a_session(monkeypatch):
    import xefm.app as app_mod
    app = _app(monkeypatch)
    switcher = _Switcher(monkeypatch)
    asked = []
    monkeypatch.setattr(app_mod, "show_input", lambda panel, **kw: asked.append(kw))
    app.new_shell()
    [view] = app.made
    session = app._sessions.for_view(view)
    app.screens()
    switcher.last.kw["on_rename"](session)
    asked[0]["on_accept"]("build server")
    assert session.title == "build server" and session.tab_label == "build server"
    assert switcher.labels()[0].startswith("build server")  # Screens again


# --- closed AI conversations ----------------------------------------------------------

class _State:
    def __init__(self):
        self.values = {}

    def get_state(self, key, default=None):
        return self.values.get(key, default)

    def set_state(self, key, value, instance_id=None):
        self.values[key] = value
        return True


def test_a_closed_conversation_is_kept_and_offered_to_resume(monkeypatch):
    from xefm import agents
    app = _app(monkeypatch)
    app.state_manager = _State()
    switcher = _Switcher(monkeypatch)
    app.config.AGENTS = [{"name": "Claude Code", "command": ["claude"],
                          "preset": "claude-code"}]
    monkeypatch.setattr(agents, "installed", lambda e: True)
    session = _agent_session(app)
    session.title = "Fix the bug"
    app._close_session(session)
    [record] = app._closed_agents()
    assert (record.agent, record.session_id, record.title) == ("Claude Code", "s-1",
                                                               "Fix the bug")
    assert record.conversation is session.view.conversation
    # Kept for the next run too, without the conversation itself.
    assert app.state_manager.values["agents.closed"][0]["session_id"] == "s-1"
    resumed = []
    app._agents_ready = lambda: True
    app._start_agent = lambda entry, prompt=None, resume=None: resumed.append(
        (entry["name"], resume))
    app.screens()
    labels = switcher.labels()
    row = next(i for i, text in enumerate(labels) if text.startswith("Resume Fix the bug"))
    switcher.last.kw["on_accept"](switcher.last.items[row])
    assert resumed == [("Claude Code", record)] and app._closed_agents() == []


def test_a_conversation_with_no_turn_is_not_kept(monkeypatch):
    app = _app(monkeypatch)
    app._close_session(_agent_session(app, said=""))
    assert app._closed_agents() == []


def test_closed_conversations_come_back_from_the_last_run(monkeypatch):
    app = _app(monkeypatch)
    app.state_manager = _State()
    app.state_manager.values["agents.closed"] = [
        {"agent": "Codex", "cwd": "/w", "session_id": "t-9", "title": "Notes",
         "closed_at": 1.0},
        {"broken": True}]
    [record] = app._closed_agents()
    assert record.agent == "Codex" and record.conversation is None


def test_resuming_brings_the_conversation_back_and_restarts_on_it(monkeypatch):
    app = _app(monkeypatch)
    restarted = []
    conv = C.Conversation()
    conv.add_user("Fix the bug")
    conv.state = C.EXITED
    record = ClosedAgent(agent="Claude Code", cwd="/w", session_id="s-1",
                         title="Fix the bug", closed_at=1.0, conversation=conv)
    view = SimpleNamespace(conversation=C.Conversation(), _source="x", _dirty=False,
                           _panel=None, protocol=SimpleNamespace(
                               restart=lambda v, resume: restarted.append(resume)))
    session = SimpleNamespace(title="")
    app._resume_into(session, view, record)
    assert view.conversation is conv and conv.state == C.STARTING
    assert restarted == [True] and session.title == "Fix the bug"
    # One from an earlier run: the id alone, and a word in the transcript.
    view.conversation = C.Conversation()
    app._resume_into(session, view, ClosedAgent("Claude Code", "/w", "s-2", "Old", 1.0))
    assert view.conversation.session_id == "s-2"
    assert "Resumed: Old" in view.conversation.items[-1].text


# --- naming AI sessions ---------------------------------------------------------------

def test_a_drawn_session_is_named_after_its_first_turn_and_keeps_the_name(monkeypatch):
    app = _app(monkeypatch)
    session = _agent_session(app, said="")
    conv = session.view.conversation
    conv.add_user("Fix the login bug\n\n(Asked from XeFM.)")
    app._name_agent_session(session)
    assert session.title == ""  # mid-turn
    conv.state = C.IDLE
    app._name_agent_session(session)
    assert session.title == "Fix the login bug"
    conv.add_user("Now write the docs")
    conv.state = C.IDLE
    app._name_agent_session(session)
    assert session.title == "Fix the login bug"  # fixed


def test_the_agents_own_title_names_the_session_first(monkeypatch):
    app = _app(monkeypatch)
    session = _agent_session(app, said="")
    session.view.conversation.title = "Login bug investigation"
    app._name_agent_session(session)
    assert session.title == "Login bug investigation"


def test_an_agent_in_the_terminal_is_named_by_its_first_telling_title(monkeypatch):
    app = _app(monkeypatch)
    app._session_title = XeFMApp._session_title.__get__(app)
    app.new_shell()
    [view] = app.made
    session = app._sessions.for_view(view)
    session.agent, session.name, session.program = True, "Claude Code", "claude"
    app._session_title(view, "✳ Claude Code")
    assert session.title == ""
    app._session_title(view, "✳ Fix the login bug")
    app._session_title(view, "✳ Write the docs")
    assert session.title == "Fix the login bug" and session.group == GROUP_AGENT


def test_acp_session_info_update_gives_the_title():
    from xefm.agent_acp import AcpClient
    conv = C.Conversation()
    client = AcpClient(["agent"], conv=conv, cwd="/w", env={}, post=lambda fn: fn(),
                       on_message=lambda m: None, on_exit=lambda c, e: None)
    client._on_notification("session/update", {"update": {
        "sessionUpdate": "session_info_update", "title": "Refactor the parser"}})
    assert conv.title == "Refactor the parser"


# --- keys -----------------------------------------------------------------------------

def test_ctrl_d_on_an_empty_message_closes_a_drawn_session(tmp_path):
    from test_agent_chat import _plain_view
    closed = []
    panel, view = _plain_view(tmp_path)
    view.on_close_request = closed.append
    view.input.set_text("draft")
    panel.dispatch_event(Event(type=EventType.KEY, key="d", modifiers=frozenset({"ctrl"})))
    assert closed == []  # a message is being typed
    view.input.set_text("")
    panel.dispatch_event(Event(type=EventType.KEY, key="d", modifiers=frozenset({"ctrl"})))
    assert closed == [view]


def test_the_rename_key_hands_the_highlighted_row_over():
    from xefm.filter_list_dialog import FilterListDialog
    renamed = []
    dialog = FilterListDialog(["a", "b"], on_rename=renamed.append)
    dialog.list.selected = 1
    dialog.handle_event(Event(type=EventType.KEY, key="f2"))
    assert renamed == ["b"] and "rename" in dialog.hint()


def test_the_new_actions_have_their_keys():
    from xefm import actions as A
    from xefm import keymap_presets as kp
    for name, context in (("new_shell", A.FILER), ("new_agent", A.FILER),
                          ("switch_screen", A.COMMON), ("terminal.switch_screen", A.TERMINAL),
                          ("terminal.new", A.TERMINAL), ("terminal.next_tab", A.TERMINAL),
                          ("terminal.prev_tab", A.TERMINAL),
                          ("rename_list_item", A.FILTER_LIST)):
        assert A.registry.resolve(context, name) is not None, name
    for preset in kp.PRESETS:
        table = kp.table(preset)
        assert table["switch_screen"] == ["Ctrl-GRAVE"], preset
        assert table["screens"] == [], preset


# --- moving tabs ----------------------------------------------------------------------

def test_a_dragged_tab_shows_where_it_would_land_and_moves_there_when_dropped():
    from xefm.tab_strip import TabStrip
    strip = TabStrip()
    strip.row = (0.0, 1.0)
    strip.hits = [(0.0, 10.0, 0), (11.0, 21.0, 1), (22.0, 32.0, 2), (33.0, 36.0, 3)]
    assert strip.press(5.0, 0.5, 3)
    assert not strip.drag(5.5, 3) and not strip.dragging  # not far enough yet
    assert not strip.drag(15.0, 3) and strip.drop_slot is None  # it would stay put
    assert strip.drag(17.0, 3) and strip.drop_slot == 2  # past tab 1's middle
    assert strip.drag(34.0, 3) and strip.drop_slot == 3  # after the last, never past +
    assert strip.release() == (0, 2)  # dropped after tab 2
    assert strip.drop_slot is None and not strip.take_click()  # its click is no click
    assert strip.press(30.0, 0.5, 3)
    strip.drag(1.0, 3)
    assert strip.drop_slot == 0 and strip.release() == (2, 0)
    strip.take_click()
    assert not strip.press(34.0, 0.5, 3)  # the + does not drag
    assert strip.release() is None and strip.take_click()


def test_the_line_where_a_tab_would_land_is_drawn_in_the_gap():
    from xefm.screen_strip import ScreenStrip
    from xefm.tab_strip import Tab
    panel = Panel(MemoryBackend(width=60, height=10))
    strip = ScreenStrip(lambda: ([Tab("one"), Tab("two"), Tab("three")], 0))
    panel.push_layer(strip, z=1, interactive=False, hints={"x": 0, "y": 0, "w": 60, "h": 1})
    panel.render()
    assert "│" not in panel.backend.snapshot()[0]
    hits = strip._strip.hits
    strip.press((hits[0][0] + hits[0][1]) / 2, 0.5)
    strip.drag(hits[2][1] - 0.5)
    panel.render()
    row = panel.backend.snapshot()[0]
    gap = int(hits[2][1])  # the gap after "three", before +
    assert row[gap] == "│" and row.count("│") == 1


def test_moving_a_screen_tab_changes_the_tabs_not_the_order_they_were_made(monkeypatch):
    app = _app(monkeypatch)
    for _ in range(3):
        app.new_shell()
    a, b, c = (app._sessions.for_view(v).screen for v in app.made)
    assert app._screens.move_tab(c, 0)
    assert app._screens.in_group(GROUP_TERMINAL) == [c, a, b]
    assert app._screens.started()[1:] == [a, b, c]  # ctx.screens(order="started")
    assert app._screens.neighbour(c) is a
    app._show_screen(a)
    app._screen_action("terminal.move_tab_right")
    assert app._screens.in_group(GROUP_TERMINAL) == [c, b, a]
    assert not app._screens.move_tab(a, 3)  # off the end: stays


def test_dragging_a_screen_tab_along_the_strip_moves_it(monkeypatch):
    from xefm.terminal import strip_event
    app = _app(monkeypatch)
    app._make_session_view = lambda argv, *, cwd, env, label, shell: _DrawnView(shell=shell)
    app.new_shell()
    app.new_shell()
    Panel.render(app.panel)
    a, b = (s.screen for s in app._sessions)
    view = b.session.view
    hits = b.strip._strip.hits
    top = app._strip_height()

    def at(kind, x, y=-0.5):
        return strip_event(view, Event(type=kind, x=x, y=y, button="left"))

    x0, x1, _ = hits[1]
    assert at(EventType.MOUSE_DOWN, (x0 + x1) / 2)
    tx0, tx1, _ = hits[0]
    # Down into the terminal and back: the drag stays the strip's.
    assert at(EventType.MOUSE_DRAG, (tx0 + tx1) / 2 - 1.0, y=3.0 - top)
    assert app._screens.in_group(GROUP_TERMINAL) == [a, b]  # only shown where
    assert b.strip._strip.drop_slot == 0                     # it would land
    assert at(EventType.MOUSE_UP, tx0 + 1.0, y=3.0 - top)
    assert app._screens.in_group(GROUP_TERMINAL) == [b, a]  # dropped: moved
    assert at(EventType.MOUSE_CLICK, tx0 + 1.0, y=3.0 - top)  # swallowed, not a switch
    assert app._screens.current is b
    assert not at(EventType.MOUSE_DOWN, 5.0, y=2.0)  # the terminal's own


def test_moving_a_pane_tab_keeps_the_current_one_current():
    from xefm.pane_manager import PaneManager
    pm = PaneManager.__new__(PaneManager)
    pm.tabs = {"left": ["a", "b", "c"]}
    pm.tab_index = {"left": 1}
    assert pm.move_tab("left", 1, 2)
    assert pm.tabs["left"] == ["a", "c", "b"] and pm.tab_index["left"] == 2
    assert pm.move_tab("left", 0, 2)
    assert pm.tabs["left"] == ["c", "b", "a"] and pm.tab_index["left"] == 1
    assert not pm.move_tab("left", 0, 5)

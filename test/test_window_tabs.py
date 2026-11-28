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
from xefm.hint_bar import hints_text


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


# --- the tabs -------------------------------------------------------------------------

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


def test_every_session_is_a_tab_after_the_file_managers(monkeypatch):
    app = _app(monkeypatch)
    app.new_shell()
    agent = _agent_session(app)
    shell = app._sessions.for_view(app.made[0])
    assert shell.group == GROUP_TERMINAL and agent.group == GROUP_AGENT  # its kind
    assert app._screens.tabs() == [app._screens.files, shell.screen, agent.screen]
    tabs, current = app._window_tabs()
    assert [(t.icon, t.label, t.closable) for t in tabs] == [
        ("▤", "Files", False), ("$", "zsh", True), ("✦", "Claude Code", True)]
    assert current == 1  # the shell, shown when it started


def test_a_group_key_goes_back_to_the_screen_used_last(monkeypatch):
    app = _app(monkeypatch)
    app.new_shell()
    app.new_shell()
    first, second = app.made
    app._show_screen(app._sessions.for_view(first).screen)
    app._show_screen(app._screens.files)
    app.subshell()  # the shell used last, not the newest one
    assert first.shown and len(app.made) == 2


def test_closing_a_tab_goes_back_to_the_screen_shown_before_it(monkeypatch):
    # As a browser or VS Code goes back to the tab used last: an editor opened
    # from the file manager closes back to it, not to the tab beside it.
    app = _app(monkeypatch)
    for _ in range(2):
        app.new_shell()
    a, b = (app._sessions.for_view(v) for v in app.made)
    c = _agent_session(app)  # another kind, the same strip
    app._show_screen(app._screens.files)
    app._show_screen(b.screen)
    app._close_session(b)  # b was opened from the file manager
    assert app._screens.current is app._screens.files
    app._show_screen(a.screen)
    app._show_screen(c.screen)
    app._close_session(c)
    assert app._screens.current is a.screen
    app._close_session(a)
    assert app._screens.current is app._screens.files


def test_closing_a_tab_out_of_view_leaves_the_screen_on_now(monkeypatch):
    app = _app(monkeypatch)
    app.new_shell()
    a = app._sessions.for_view(app.made[0])
    c = _agent_session(app)
    app._show_screen(c.screen)
    app._close_session(a)
    assert app._screens.current is c.screen


def test_next_and_previous_tab_wrap_through_the_file_manager(monkeypatch):
    app = _app(monkeypatch)
    app.new_shell()
    app.new_shell()
    a, b = (app._sessions.for_view(v) for v in app.made)
    assert app._screens.current is b.screen
    app.next_screen()
    assert app._screens.current is app._screens.files
    app.next_screen()
    assert app._screens.current is a.screen
    app.prev_screen()
    assert app._screens.current is app._screens.files


# --- the strip ----------------------------------------------------------------------

def test_the_strip_shows_with_a_session_and_the_view_sits_between_the_chrome(monkeypatch):
    app = _app(monkeypatch)
    assert not app.window_tabs.shown() and app._chrome_bands()[1] == 0
    app.new_shell()
    [first] = app.made
    assert app.window_tabs.shown()  # one session: Files and its tab
    menu_h, strip_h, status_h = app._chrome_bands()
    assert (menu_h, strip_h, status_h) == (1.0, 1.0, 1.0)  # a grid's rows
    rect = app.panel._find_layer(first).reflow(100, 40)
    assert (rect.y, rect.h) == (2.0, 37.0)  # under the menu and the tabs, over the status
    app.menu_bar.takes_activation_key = False  # the OS has the menu bar
    assert app.panel._find_layer(first).reflow(100, 40).y == 1.0


def test_a_tab_says_when_its_session_wants_you(monkeypatch):
    app = _app(monkeypatch)
    app.new_shell()
    app.new_shell()
    a, b = (app._sessions.for_view(v) for v in app.made)
    a.attention = ("attention", "zsh: asking")
    tabs, _ = app._window_tabs()
    assert tabs[1].mark == "⚠" and tabs[2].mark == ""


def test_a_click_on_the_strip_switches_tabs_or_opens_another(monkeypatch):
    from xefm.screen_strip import NEW_TAB
    app = _app(monkeypatch)
    app.new_shell()
    app.new_shell()
    a, b = (app._sessions.for_view(v) for v in app.made)
    hits = iter([1, 0, NEW_TAB])
    app.window_tabs.hit = lambda x, y: next(hits)
    click = Event(type=EventType.MOUSE_CLICK, x=3.0, y=0.5, button="left")
    assert app._tab_event(click, 3.0, 0.5)
    assert app._screens.current is a.screen
    assert app._tab_event(click, 3.0, 0.5)
    assert app._screens.current is app._screens.files  # the Files tab
    assert app._tab_event(click, 3.0, 0.5)  # +: only a shell can start here
    assert len(app.made) == 3


def test_plus_asks_what_to_start_when_there_is_more_than_one_kind(monkeypatch):
    app = _app(monkeypatch)
    asked = []
    app._user_ctx = SimpleNamespace(choose=lambda title, labels, on_result: asked.append(
        (labels, on_result)))
    started = []
    app._new_kinds = lambda: [("New Shell", lambda: started.append("shell")),
                              ("New Claude Code", lambda: started.append("claude"))]
    app._new_tab_menu()
    [(labels, answer)] = asked
    assert labels == ["New Shell", "New Claude Code"]
    answer(1)
    assert started == ["claude"]


class _DrawnView(_View):
    """A stand-in session view that draws: a page of dots."""

    def draw(self, ctx):
        from puikit import Style
        w, h = ctx.size_units
        for y in range(int(h)):
            ctx.draw_text(0, y, "." * int(w), Style())

    def handle_event(self, event):
        return True


def test_a_session_screen_draws_the_window_chrome_around_its_view(monkeypatch):
    # The session view is a "cover" layer, and PuiKit draws a screen from its
    # topmost cover layer up: the chrome is drawn by a frame over the view -
    # the very menu bar, tab strip and status bar the file manager places.
    app = _app(monkeypatch)
    app._make_session_view = lambda argv, *, cwd, env, label, shell: _DrawnView(shell=shell)
    drawn = []
    app.menu_bar.draw = lambda ctx: drawn.append(("menu", ctx.screen_rect))
    app.status.draw = lambda ctx: drawn.append(("status", ctx.screen_rect))
    app.new_shell()
    Panel.render(app.panel)
    rows = app.panel.backend.snapshot()
    assert "Files" in rows[1] and "zsh" in rows[1] and "+" in rows[1]  # the strip
    assert set(rows[2].strip()) == {"."}  # the view, below it
    assert set(rows[38].strip()) == {"."} and rows[39].strip() == ""  # above the status
    assert ("menu", (0, 0, 100, 1.0)) in drawn and ("status", (0, 39.0, 100, 1.0)) in drawn
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
    assert texts["zsh"] == texts["$"] == texts["×"] == 0.25 + 0.15  # 15% above
    assert strip.row == (0.25, 0.25 + TAB_HEIGHT_GUI)
    # The strip: the tab and the inset above it; a terminal's is one row.
    gui = SimpleNamespace(capabilities=SimpleNamespace(supports=lambda c: True),
                          base_size=(8, 16))
    grid = SimpleNamespace(capabilities=SimpleNamespace(supports=lambda c: False))
    assert strip_height(gui) == TAB_HEIGHT_GUI + 2 * PAD_PX / 16
    assert strip_height(grid) == 1.0
    # A dragged tab's landing place: a 2 px line in the gap, as tall as the tabs.
    strip.drop_slot = 0
    ctx.calls.clear()
    strip._draw_drop_line(ctx, 0.25, TAB_HEIGHT_GUI, strip.GAP)
    [line] = [c for c in ctx.calls if c[0] == "fill"]
    assert line[3] == 2.0 / 8 and line[4] == TAB_HEIGHT_GUI
    assert line[1] + line[3] / 2 == 1.0 - strip.GAP / 2


class _ProportionalCtx(_VectorCtx):
    """Bold is wider, and the lead glyphs differ in width, as in a GUI font."""

    WIDTHS = {"⚠": 1.4, "$": 0.6, "✦": 1.0}

    def measure_text(self, text, style=None):
        from puikit import TextAttribute
        w = sum(self.WIDTHS.get(ch, 1.0) for ch in text)
        bold = style is not None and style.attr is not None \
            and style.attr & TextAttribute.BOLD
        return w * 1.1 if bold else w


def test_a_tab_keeps_its_place_whichever_is_current_and_whatever_its_mark():
    # Switching tabs moved them all a little: only the current label was
    # measured bold, and a mark (⚠) took a narrower icon's place (#1019).
    from xefm.tab_strip import Tab, TabStrip
    strip = TabStrip()

    def spans(current, mark=""):
        strip.draw(_ProportionalCtx(), [Tab("Files", icon="▤"),
                                        Tab("zsh", mark, icon="$", closable=True),
                                        Tab("Claude", icon="✦", closable=True)],
                   current, 1.0, 0.0, 58.0, emphasis=True)
        return list(strip.hits)

    assert spans(0) == spans(1) == spans(2) == spans(0, mark="⚠")


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
    app.window_tabs.hit = lambda x, y: (CLOSE, 1)
    app._tab_event(Event(type=EventType.MOUSE_CLICK, x=3.0, y=0.5, button="left"), 3.0, 0.5)
    assert app._sessions.for_view(a.view) is None and app._screens.current is b.screen


def test_pointer_events_on_the_chrome_go_to_its_widgets(monkeypatch):
    app = _app(monkeypatch)
    app.new_shell()
    [view] = app.made
    screen = app._sessions.for_view(view).screen
    seen = []
    app._tab_event = lambda event, x, y: seen.append((event.type, x, y)) or True

    def at(kind, y):  # the view's own units: it starts 2 rows down
        return app._chrome_event(screen, Event(type=kind, x=4.0, y=y, button="left"))

    assert at(EventType.MOUSE_CLICK, -2.0)  # the menu bar's row
    assert app.menu_bar.events[-1].y == 0.0
    assert at(EventType.MOUSE_DOWN, -0.5)  # the strip: held from here...
    assert at(EventType.MOUSE_DRAG, 5.0)  # ...down into the terminal
    assert at(EventType.MOUSE_UP, 5.0) and at(EventType.MOUSE_CLICK, 5.0)
    assert [k for k, _x, _y in seen] == [EventType.MOUSE_DOWN, EventType.MOUSE_DRAG,
                                         EventType.MOUSE_UP, EventType.MOUSE_CLICK]
    assert seen[0][2] == 0.5  # in the strip's own units
    assert not at(EventType.MOUSE_CLICK, 5.0)  # the terminal's own
    assert at(EventType.MOUSE_CLICK, 37.2)  # the status bar
    assert app.status.clicks == [4.0]


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
    assert switcher.labels()[1].startswith("build server")  # Screens again
    assert switcher.last.kw["on_rename"](app._screens.files) is False  # not Files


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
    assert switcher.labels() == ["File manager"]  # not in Screens: its own dialog
    app.resume_agent()
    assert switcher.last.kw["title"] == "Resume AI Conversation"
    assert switcher.labels() == ["Fix the bug - /w"]
    assert switcher.last.kw["to_right"](record).startswith("Claude Code, closed")
    switcher.enter()
    assert resumed == [("Claude Code", record)] and app._closed_agents() == []
    app.resume_agent()  # nothing left: a word in the log, no dialog
    assert app.logged[-1] == "No closed AI conversation to resume"


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
    # One from an earlier run of an RPC agent: the id alone, the conversation
    # left empty, so the agent sends its history (see the protocol tests).
    view.conversation = C.Conversation()
    app._resume_into(session, view, ClosedAgent("Codex", "/w", "t-2", "Old", 1.0))
    assert view.conversation.session_id == "t-2" and view.conversation.items == []


def test_a_claude_conversation_from_an_earlier_run_is_read_from_its_file(
        monkeypatch, tmp_path):
    import json
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path))
    folder = tmp_path / "projects" / "-w-src"
    folder.mkdir(parents=True)
    lines = [
        {"type": "user", "message": {"role": "user", "content": "Fix the login bug"}},
        {"type": "user", "isMeta": True, "message": {"role": "user", "content": "meta"}},
        {"type": "assistant", "message": {"id": "m1", "role": "assistant", "content": [
            {"type": "text", "text": "Looking at it."},
            {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/w/a"}}]}},
        {"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "t1", "content": "def login(): ..."}]}},
        {"type": "assistant", "message": {"id": "m2", "role": "assistant", "content": [
            {"type": "text", "text": "Fixed."}]}},
        {"type": "summary", "summary": "Login fix"},
    ]
    (folder / "s-9.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n")
    assert C.claude_transcript("s-9", "/w/src") == str(folder / "s-9.jsonl")
    assert C.claude_transcript("s-9") == str(folder / "s-9.jsonl")  # found by its id
    assert C.claude_transcript("../etc") is None
    app = _app(monkeypatch)
    view = SimpleNamespace(conversation=C.Conversation(), _source="", _dirty=False,
                           _panel=None, protocol=C.ClaudeProtocol())
    view.protocol.restart = lambda v, resume: None
    app._resume_into(SimpleNamespace(title=""), view,
                     ClosedAgent("Claude Code", "/w/src", "s-9", "Login fix", 1.0))
    kinds = [(i.kind, i.text or i.name) for i in view.conversation.items]
    assert kinds[0] == ("user", "Fix the login bug")
    assert ("text", "Looking at it.") in kinds and ("text", "Fixed.") in kinds
    tool = next(i for i in view.conversation.items if i.kind == "tool")
    assert tool.result == "def login(): ..." and not tool.open
    assert "Resumed: Login fix" in view.conversation.items[-1].text
    assert not any(i.text == "meta" for i in view.conversation.items)


def test_codex_sends_the_history_only_into_an_empty_conversation():
    from xefm.agent_codex import CodexClient
    calls = []
    conv = C.Conversation()
    client = CodexClient.__new__(CodexClient)
    client.conv, client.resume, client.cwd = conv, "t-1", "/w"
    client.instructions, client.channel, client.skills_roots = "", None, []
    client.call = lambda method, params, *rest: calls.append((method, params))
    client._start_thread()
    resume = next(p for m, p in calls if m == "thread/resume")
    assert resume["excludeTurns"] is False  # empty: send the turns
    client._items, client._open_text = {}, None
    client._close_text = lambda: None
    client._fold_turns([{"items": [
        {"type": "userMessage", "content": [{"type": "text", "text": "Rename these"}]},
        {"type": "agentMessage", "id": "a1", "text": "Done."}]}])
    assert [(i.kind, i.text) for i in conv.items] == [("user", "Rename these"),
                                                      ("text", "Done.")]
    calls.clear()
    client._start_thread()  # a conversation on screen: no history again
    assert next(p for m, p in calls if m == "thread/resume")["excludeTurns"] is True


def test_an_acp_playback_fills_an_empty_conversation_only():
    from xefm.agent_acp import AcpClient
    conv = C.Conversation()
    client = AcpClient(["agent"], conv=conv, cwd="/w", env={}, post=lambda fn: fn(),
                       on_message=lambda m: None, on_exit=lambda c, e: None)
    client._loading, client._replay = True, True
    for update in ({"sessionUpdate": "user_message_chunk",
                    "content": {"type": "text", "text": "Sort "}},
                   {"sessionUpdate": "user_message_chunk",
                    "content": {"type": "text", "text": "these"}},
                   {"sessionUpdate": "agent_message_chunk",
                    "content": {"type": "text", "text": "Sorted."}}):
        client._on_notification("session/update", {"update": update})
    client._session({"sessionId": "x"})
    assert [(i.kind, i.text, i.open) for i in conv.items] == [
        ("user", "Sort these", False), ("text", "Sorted.", False)]
    client._loading, client._replay = True, False  # on screen already: dropped
    client._on_notification("session/update", {"update": {
        "sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": "x"}}})
    assert len(conv.items) == 2


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
    assert renamed == ["b"] and "rename" in hints_text(dialog.hint())


def test_the_new_actions_have_their_keys():
    from xefm import actions as A
    from xefm import keymap_presets as kp
    for name, context in (("new_shell", A.FILER), ("new_agent", A.FILER),
                          ("switch_screen", A.COMMON), ("terminal.switch_screen", A.TERMINAL),
                          ("terminal.new", A.TERMINAL),
                          ("agent_chat.switch_screen", A.AGENT_CHAT),
                          ("agent_chat.new", A.AGENT_CHAT), ("agent_chat.close", A.AGENT_CHAT),
                          ("agent_chat.screens", A.AGENT_CHAT),
                          ("next_screen", A.COMMON), ("prev_screen", A.COMMON),
                          ("move_screen_left", A.COMMON), ("move_screen_right", A.COMMON),
                          ("resume_agent", A.COMMON),
                          ("rename_list_item", A.FILTER_LIST)):
        assert A.registry.resolve(context, name) is not None, name
    # One name for the window's tabs on every screen: no session-only twin
    # that read as the pane's next_tab qualified for the terminal.
    for gone in ("terminal.next_tab", "terminal.prev_tab",
                 "terminal.move_tab_left", "terminal.move_tab_right"):
        assert A.registry.resolve(A.TERMINAL, gone) is None, gone
    for preset in kp.PRESETS:
        table = kp.table(preset)
        assert table["switch_screen"] == ["Ctrl-GRAVE"], preset
        assert table["screens"] == [], preset
        # Ctrl-Tab is the window's, not a pane's (#1019).
        assert "Ctrl-TAB" not in table["next_tab"], preset


def test_ctrl_tab_walks_the_windows_tabs_in_the_desktop_app(monkeypatch):
    import xefm.keymaps.common as common
    monkeypatch.setattr(common, "is_desktop_mode", lambda: True)
    for platform in ("darwin", "win32"):
        monkeypatch.setattr(common.sys, "platform", platform)
        table = common.bindings()
        assert table["next_screen"][0] == "Ctrl-TAB", platform
        assert table["prev_screen"][0] == "Ctrl-Shift-TAB", platform
        # On a Mac the session's tab keys walk them from the file manager too.
        mac = platform == "darwin"
        assert ("Command-Shift-RIGHT_BRACKET" in table["next_screen"]) == mac
        assert ("Command-Shift-LEFT_BRACKET" in table["prev_screen"]) == mac
    monkeypatch.setattr(common, "is_desktop_mode", lambda: False)
    table = common.bindings()  # a terminal never sends Ctrl-Tab
    assert table["next_screen"] == []


def test_a_session_takes_the_window_tab_keys_from_its_program():
    # next_screen is a common action a session inherits: taken only on a
    # chord no program receives - Ctrl+Tab is one (the terminal's encoding
    # sends it as Tab), Command and Ctrl+Shift were already.
    from xefm.terminal import no_program_receives
    key = lambda k, *mods: Event(type=EventType.KEY, key=k, modifiers=frozenset(mods))
    assert no_program_receives(key("tab", "ctrl"))
    assert no_program_receives(key("tab", "ctrl", "shift"))
    assert no_program_receives(key("}", "cmd"))
    assert not no_program_receives(key("tab"))
    assert not no_program_receives(key("t", "ctrl"))  # Ctrl-T stays the shell's


def test_next_screen_walks_every_tab(monkeypatch):
    app = _app(monkeypatch)
    app.new_shell()
    agent = _agent_session(app)
    shell = app._sessions.for_view(app.made[0])
    app._show_screen(app._screens.files)
    app.next_screen()
    assert app._screens.current is shell.screen
    app.next_screen()
    assert app._screens.current is agent.screen
    app.next_screen()
    assert app._screens.current is app._screens.files
    app.prev_screen()
    assert app._screens.current is agent.screen


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
    strip = ScreenStrip(lambda: ([Tab("Files"), Tab("one"), Tab("two")], 1))
    panel.push_layer(strip, z=1, interactive=False, hints={"x": 0, "y": 0, "w": 60, "h": 1})
    panel.render()
    assert "│" not in panel.backend.snapshot()[0]
    hits = strip._strip.hits
    strip.press((hits[1][0] + hits[1][1]) / 2, 0.5)
    strip.drag(hits[2][1] - 0.5)
    panel.render()
    row = panel.backend.snapshot()[0]
    gap = int(hits[2][1])  # the gap after "two", before +
    assert row[gap] == "│" and row.count("│") == 1
    strip.release()
    strip.take_click()
    assert not strip.press((hits[0][0] + hits[0][1]) / 2, 0.5)  # Files stays put


def test_moving_a_screen_tab_changes_the_tabs_not_the_order_they_were_made(monkeypatch):
    app = _app(monkeypatch)
    for _ in range(3):
        app.new_shell()
    files = app._screens.files
    a, b, c = (app._sessions.for_view(v).screen for v in app.made)
    assert app._screens.move_tab(c, 1)
    assert app._screens.tabs() == [files, c, a, b]
    assert app._screens.started()[1:] == [a, b, c]  # ctx.screens(order="started")
    assert not app._screens.move_tab(c, 0)  # nothing goes before Files
    assert not app._screens.move_tab(files, 2)  # and Files does not move
    app._show_screen(a)
    app.move_screen_right()
    assert app._screens.tabs() == [files, c, b, a]
    assert not app._screens.move_tab(a, 4)  # off the end: stays


def test_dragging_a_screen_tab_along_the_strip_moves_it(monkeypatch):
    app = _app(monkeypatch)
    app._make_session_view = lambda argv, *, cwd, env, label, shell: _DrawnView(shell=shell)
    app.new_shell()
    app.new_shell()
    Panel.render(app.panel)
    a, b = (s.screen for s in app._sessions)
    hits = app.window_tabs._strip.hits
    x0, x1, _ = hits[2]
    tx0, tx1, _ = hits[1]

    def send(kind, x):
        app._tab_event(Event(type=kind, x=x, y=0.5, button="left"), x, 0.5)

    send(EventType.MOUSE_DOWN, (x0 + x1) / 2)
    send(EventType.MOUSE_DRAG, (tx0 + tx1) / 2 - 1.0)
    assert app._screens.tabs()[1:] == [a, b]  # only shown where it would land
    assert app.window_tabs._strip.drop_slot == 1
    send(EventType.MOUSE_UP, tx0 + 1.0)
    assert app._screens.tabs()[1:] == [b, a]  # dropped: moved
    send(EventType.MOUSE_CLICK, tx0 + 1.0)  # ends the drag, no switch
    assert app._screens.current is b


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


def test_a_sessions_view_owns_the_window_menu_bar(monkeypatch):
    # PuiKit greys an OS menu bar under a layer that does not own it (a
    # dialog's guard); a session's view is a screen showing the same bar
    # (#1019), so it is registered as an owner of it.
    from puikit import Menu
    from puikit.widgets import Label
    app = _app(monkeypatch)
    app.menu_bar.menu = Menu()
    app.panel.set_menu_bar(app.menu_bar.menu)
    app.new_shell()
    assert app._screens.current.session is not None
    assert app.panel._menu_bar_active()
    dialog = Label("dialog")
    app.panel.push_layer(dialog, z=70, hints={"x": 0, "y": 0, "w": 20, "h": 5})
    assert not app.panel._menu_bar_active()


def test_on_every_theme_the_strips_and_their_tabs_can_be_told_apart():
    # Taken from a theme's colours alone, a theme whose header and page are
    # one colour (Segment LCD) gave bands and chips that could not be told
    # apart, and over a scene (Phosphor, Pelagic) the current tab vanished
    # into the translucent ground (#1019 hand check).
    from xefm._config import Config
    from xefm.app import _build_theme_list
    from xefm.tab_strip import (CURRENT_SEPARATION, GROUND_SEPARATION, _lightness as L,
                                _mix, strip_colors)
    for name, theme in _build_theme_list(Config()):
        opacity = theme.extras.get("opacity", 1.0)
        window = strip_colors(theme, opacity=opacity)
        pane = strip_colors(theme, pane=True, opacity=opacity)
        header, page = theme.surface_bg("header"), theme.surface_bg("content")
        assert window.current == pane.current == tuple(page)[:3], name
        for a, b in ((window.ground, header), (pane.ground, header),
                     (window.ground, pane.ground)):
            assert abs(L(a) - L(b)) >= GROUND_SEPARATION - 0.01, name
        for colors in (window, pane):
            seen = _mix(page, colors.ground, colors.ground_opacity)
            assert abs(L(colors.current) - L(seen)) >= CURRENT_SEPARATION - 0.01, name
            assert colors.ground_opacity >= min(1.0, max(0.8, opacity)), name

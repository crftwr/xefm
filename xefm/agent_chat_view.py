"""The screen of an AI agent session XeFM draws itself (discussion #959).

A full-window layer on a screen of its own, like a terminal session's: the
header names the agent, where it works and what it is doing; the transcript
is a ``MarkdownView`` that follows its end as the reply streams in; the
message is typed in a ``TextArea`` at the bottom. It is the same in the
desktop app and in terminal mode - nothing here needs a terminal emulator,
which is the point: in terminal mode the agent no longer takes the terminal
over, so XeFM keeps its screen and can show the agent's questions and
``xefmctl``'s confirmations.

Keys (fixed here, as a viewer's are):

- **Enter** sends; **Alt+Enter**, **Shift+Enter** or **Ctrl+J** starts a new
  line. A message sent while the agent works waits for its turn to end.
- **Escape** stops the agent while it works; otherwise goes back to the file
  manager, the session kept (the agent key or the screen switcher returns).
- **Up / Down** on the first (last) row of the message bring back earlier
  messages.
- **Page Up / Page Down** scroll the transcript; so does the wheel.
- ``/clear`` starts a new conversation; ``/exit`` ends the session.

The view owns the agent's process (:class:`xefm.agent_chat.ChatClient`) and
the conversation (:class:`xefm.agent_chat.Conversation`); the app hands it
what it cannot know - how to ask the user (a dialog on this view's screen),
how to close it or go back to the panes.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from puikit.backend import Style, TextAttribute
from puikit.event import Event, EventType
from puikit.focus import FocusContainer
from puikit.panel import Rect
from puikit.text import elide
from puikit.widgets.base import Widget
from puikit.widgets.markdown_view import MarkdownView
from puikit.widgets.text_area import TextArea

from xefm import agent_chat as C
from xefm import surface_actions
from xefm.config import find_action_for_event
from xefm.log_manager import getLogger

logger = getLogger("AgentChat")

#: The context the view takes its bindings from: the terminal's, which an
#: agent session's screen is a peer of (``terminal.close``, ``terminal.screens``,
#: actions a config put there).
CONTEXT = "terminal"

_MOUSE = (EventType.MOUSE_DOWN, EventType.MOUSE_UP, EventType.MOUSE_DRAG,
          EventType.MOUSE_CLICK, EventType.MOUSE_SCROLL, EventType.MOUSE_MOVE)

#: The footer's keys, per state.
_HINTS = {
    C.STARTING: "Enter send · Alt+Enter new line · Esc back to files",
    C.IDLE: "Enter send · Alt+Enter new line · ↑ earlier message · PgUp/PgDn scroll · Esc back to files",
    C.WORKING: "Esc stop · Enter send next · PgUp/PgDn scroll",
    C.ASKING: "Answer the question · Esc stop",
    C.EXITED: "Enter start again · /exit close · Esc back to files",
}


def _user_actions() -> set:
    from xefm.actions import registry
    return {a.name for a in registry.actions(CONTEXT) if a.is_user and a.context == CONTEXT}


class ChatView(FocusContainer, Widget):
    """One drawn agent session's screen."""

    focusable = True
    focus_stop_when_empty = True
    #: The command palette's view of this surface (as a terminal's).
    palette_context = CONTEXT

    def __init__(self, argv: list[str], *, cwd: str, env: dict, name: str,
                 post: Callable[[Callable[[], None]], None],
                 ask: Callable[["ChatView", C.Permission], None],
                 on_close_request: Callable[["ChatView"], None],
                 on_hide: Callable[["ChatView"], None],
                 on_screens_request: Callable[[], None] | None = None,
                 on_user_action: Callable[[str], bool] | None = None,
                 on_link: Callable[[str], bool] | None = None,
                 on_change: Callable[["ChatView"], None] | None = None,
                 restart_argv: Callable[[str], list[str]] | None = None) -> None:
        self.argv = list(argv)
        self.cwd = cwd
        self.env = env
        self.name = name
        self._post = post
        self._ask = ask
        self.on_close_request = on_close_request
        self.on_hide = on_hide
        self.on_screens_request = on_screens_request
        self.on_user_action = on_user_action
        self.on_change = on_change
        self._restart_argv = restart_argv
        self.conversation = C.Conversation()
        self.client: C.ChatClient | None = None
        self.transcript = MarkdownView("", selectable=True, code_copy=True, on_link=on_link)
        self.transcript.follow_end = True
        # A relative image path in a reply means the agent's folder.
        self.transcript.base_dir = cwd
        self.input = TextArea(submit_on_enter=True, min_rows=1, max_rows=10,
                              on_submit=self._submit,
                              placeholder=f"Message {name}")
        self._focused: Any = self.input
        self._source = ""
        self._dirty = True
        self._panel: Any = None
        self._transcript_rect = Rect(0, 0, 0, 0)
        self._input_rect = Rect(0, 0, 0, 0)
        self._mouse_target: Any = None
        #: Messages sent, oldest first, for Up/Down; ``_hist`` is the one shown.
        self.history: list[str] = []
        self._hist: int | None = None
        self._draft = ""
        #: Set by the screen manager while this view's screen is on.
        self.shown = False
        #: Set while it slides away; takes no input then.
        self.closing = False
        self.started_at = time.time()
        # What a terminal session's view also says, for the session list.
        self.title = ""
        self.pwd = ""

    # --- the session list's view of it ----------------------------------------

    @property
    def running(self) -> bool:
        return self.client is not None and self.client.running

    @property
    def busy(self) -> bool:
        """Whether closing it would interrupt the agent mid-turn."""
        return self.running and self.conversation.busy

    @property
    def exit_code(self) -> int | None:
        return self.client.exit_code if self.client is not None else None

    @property
    def chat_state(self) -> str:
        return self.conversation.state

    # --- the process ------------------------------------------------------------

    def start(self, panel: Any = None, argv: list[str] | None = None) -> bool:
        """Start the agent; False (with the reason in the transcript) when it
        cannot."""
        if panel is not None:
            self._panel = panel
        if self.running:
            return True
        self.conversation.state = C.STARTING
        box: dict = {}
        client = C.ChatClient(argv or self.argv, cwd=self.cwd, env=self.env,
                              post=self._post, on_message=self._message,
                              on_exit=lambda code, err: self._exited(box["c"], code, err))
        box["c"] = client
        try:
            client.start()
        except OSError as e:
            logger.error(f"Could not start {self.name}: {e}")
            self.conversation.exited(None, "")
            self.conversation.add_notice(f"Could not start {self.name}: {e}", error=True)
            self._changed()
            return False
        self.client = client
        logger.info(f"Started {self.name} (stream-json) in {self.cwd}")
        self._changed()
        return True

    def close(self) -> None:
        """End the agent's process (the session is closing)."""
        client, self.client = self.client, None
        if client is not None:
            client.close()

    def _restart(self, *, resume: bool) -> bool:
        """A new process: the same conversation (``--resume``) after the old
        one ended, or a new one (``/clear``)."""
        old = self.client
        self.client = None
        if old is not None:
            old.close()
        sid = self.conversation.session_id
        argv = self.argv
        if resume and sid and self._restart_argv is not None:
            argv = self._restart_argv(sid)
        if not resume:
            self.conversation = C.Conversation()
            self._source = ""
            self.transcript.set_source("")
        return self.start(argv=argv)

    def _message(self, msg: dict) -> None:
        conv = self.conversation
        result = conv.handle(msg)
        if isinstance(result, C.Permission):
            self._ask(self, result)
        self._changed()

    def _exited(self, client: C.ChatClient, code: int | None, err: str) -> None:
        if client is not self.client:
            return  # a process replaced or closed on purpose
        self.conversation.exited(code, err)
        logger.info(f"{self.name} exited with code {code}")
        self._changed()

    def answer(self, perm: C.Permission, response: dict) -> None:
        """Send the user's answer to ``perm`` back to the agent."""
        if self.client is not None:
            self.client.respond(perm.request_id, response)
        self.conversation.answered(perm, response.get("behavior") == "allow",
                                   response.get("updatedInput"))
        self._changed()

    def send(self, text: str) -> bool:
        """Send ``text`` as the user's message (starting the agent again
        first when it had ended)."""
        if not self.running and not self._restart(resume=True):
            return False
        if self.client is None or not self.client.send(text):
            self.conversation.add_notice("Could not reach the agent", error=True)
            self._changed()
            return False
        self.conversation.add_user(text)
        self._changed()
        return True

    def interrupt(self) -> None:
        if self.client is not None and self.conversation.busy:
            self.client.interrupt()
            self.conversation.add_notice("Stopping…")
            self._changed()

    def _changed(self) -> None:
        self._dirty = True
        if self.on_change is not None:
            self.on_change(self)
        if self._panel is not None:
            self._panel.render()

    # --- typing -------------------------------------------------------------------

    def _submit(self, text: str) -> None:
        stripped = text.strip()
        if not stripped:
            if not self.running and self.conversation.state == C.EXITED:
                self._restart(resume=True)
            return
        if stripped in ("/exit", "/quit"):
            self.input.set_text("")
            self.on_close_request(self)
            return
        if stripped == "/clear":
            self.input.set_text("")
            self._restart(resume=False)
            return
        if self.send(text.rstrip()):
            if not self.history or self.history[-1] != text.rstrip():
                self.history.append(text.rstrip())
            self._hist = None
            self.input.set_text("")

    def _recall(self, step: int) -> bool:
        """Up/Down on the message's edge: an earlier (later) sent message."""
        if not self.history:
            return False
        if self._hist is None:
            if step > 0:
                return False
            self._draft = self.input.text
            self._hist = len(self.history)
        pos = self._hist + step
        if pos < 0:
            return True
        if pos >= len(self.history):
            self._hist = None
            self.input.set_text(self._draft)
            return True
        self._hist = pos
        self.input.set_text(self.history[pos])
        return True

    # --- actions ------------------------------------------------------------------

    def _actions(self) -> dict:
        table = {"terminal.close": lambda: self.on_close_request(self)}
        if self.on_screens_request is not None:
            table["terminal.screens"] = self.on_screens_request
        table.update(surface_actions.handlers())
        return table

    def palette_actions(self) -> set:
        return set(self._actions()) | set(_user_actions())

    def run_action(self, name: str) -> bool:
        handler = self._actions().get(name)
        if handler is not None:
            handler()
            return True
        if self.on_user_action is not None and name in _user_actions():
            return bool(self.on_user_action(name))
        return False

    @staticmethod
    def _takes(event: Event, action: str) -> bool:
        """Whether a binding beats typing: one made for this context, or a
        chord a text field never types (Command, Ctrl+Shift)."""
        if action.startswith(CONTEXT + ".") or action in _user_actions():
            return True
        mods = event.modifiers or frozenset()
        return "cmd" in mods or {"ctrl", "shift"} <= mods

    # --- focus ------------------------------------------------------------------

    def focus_children(self) -> list[Any]:
        return [self.input]

    # --- drawing ----------------------------------------------------------------

    def draw(self, ctx) -> None:
        from xefm.text_viewer import _content_bg, _header_bg, draw_status_bar, viewer_pad
        self._panel = ctx.panel
        theme = ctx.theme
        wu, hu = ctx.size_units
        pad_x, pad_y = viewer_pad(ctx)
        bg = _content_bg(theme)
        if not ctx.wallpaper:
            ctx.fill_rect(0, 0, wu, hu, Style(bg=bg))
        text_fg = theme.text if theme is not None else (212, 212, 212)
        muted = theme.muted_text if theme is not None else (150, 150, 150)
        accent = theme.accent if theme is not None else (0, 122, 204)
        iw = max(4.0, wu - 2 * pad_x)

        # Header: who, where, and what it is doing.
        head_h = 1.0 + pad_y
        header_bg = _header_bg(theme)
        ctx.fill_rect(0, 0, wu, head_h, Style(bg=header_bg))
        conv = self.conversation
        right = conv.state + (f" · {conv.model}" if conv.model else "") + " "
        right_w = ctx.measure_text(right)
        title = f" {self.name}  {_short(self.cwd)}"
        # Measured in the bold it is drawn in: bold is wider, and elided by
        # the regular widths the title ran into the state on the right.
        title_style = Style(fg=accent, bg=header_bg, attr=TextAttribute.BOLD)
        ctx.draw_text(pad_x, pad_y,
                      elide(title, max(1.0, iw - right_w - 1), where="end",
                            measure=lambda t: ctx.measure_text(t, title_style)),
                      title_style)
        state_fg = accent if conv.busy else muted
        ctx.draw_text(max(pad_x, wu - pad_x - right_w), pad_y, right,
                      Style(fg=state_fg, bg=header_bg))

        # Footer: the keys for what can be done now.
        fy = hu - 1.0 - pad_y
        draw_status_bar(ctx, fy, _HINTS.get(conv.state, _HINTS[C.IDLE]),
                        pad_x=pad_x + 1, bottom_pad=pad_y)

        # The message field, as tall as what is typed (up to its max).
        lc = ctx.layout_context()
        in_w = max(4.0, iw - 2)
        in_h = self.input.measure(lc, "y", in_w).preferred
        in_y = fy - in_h - (0.5 if ctx.pixel_layout else 0.0)
        self._input_rect = Rect(pad_x + 1, in_y, in_w, in_h)
        # A line above it while the agent works or asks.
        status = ""
        if conv.state == C.WORKING:
            status = "● Working…" + (f"  ({conv.pending_turns - 1} message(s) waiting)"
                                     if conv.pending_turns > 1 else "")
        elif conv.state == C.ASKING:
            status = "● Waiting for your answer"
        elif conv.state == C.STARTING:
            status = "Starting…"
        top_of_input = in_y
        if status:
            top_of_input -= 1.0
            ctx.draw_text(pad_x + 1, top_of_input, elide(status, in_w, where="end",
                                                         measure=ctx.measure_text),
                          Style(fg=accent if conv.busy else muted, bg=bg))

        # The transcript fills the rest.
        if self._dirty:
            self._dirty = False
            source = C.to_markdown(conv.items) if conv.items else _welcome(self.name)
            if source != self._source:
                self._source = source
                self.transcript.update_source(source)
        self.transcript.style = Style(fg=text_fg, bg=bg)
        ty = head_h + (0.5 if ctx.pixel_layout else 0.0)
        th = max(1.0, top_of_input - ty - (0.5 if ctx.pixel_layout else 0.0))
        self._transcript_rect = Rect(pad_x + 1, ty, in_w, th)
        r = self._transcript_rect
        ctx.draw_child(self.transcript, r.x, r.y, r.w, r.h,
                       hints={"focused": False, "bg": bg})
        r = self._input_rect
        ctx.draw_child(self.input, r.x, r.y, r.w, r.h,
                       hints={"focused": not self.closing})

    # --- events -----------------------------------------------------------------

    def handle_event(self, event: Event) -> bool:
        if self.closing:
            return True
        if event.type is EventType.KEY:
            self._key(event)
            return True
        if event.type is EventType.IME_COMPOSITION:
            self.input.handle_event(event)
            return True
        if event.type in _MOUSE:
            self._mouse(event)
            return True
        return True  # a screen: nothing reaches the panes underneath

    def _key(self, event: Event) -> None:
        mods = event.modifiers or frozenset()
        key = event.key
        action = find_action_for_event(event, context=CONTEXT)
        if action is not None and self._takes(event, action) and self.run_action(action):
            return
        if key == "escape" and not mods:
            if self.conversation.busy:
                self.interrupt()
            elif self.transcript.selection_text():
                self.transcript.clear_selection()
            else:
                self.on_hide(self)
            return
        if key in ("pageup", "pagedown") and not mods & {"shift"}:
            page = max(1.0, self._transcript_rect.h - 1.0)
            self.transcript.scroll_by(-page if key == "pageup" else page)
            return
        if key == "c" and mods & {"ctrl", "cmd"} and not self.input.selection_text \
                and self.transcript.selection_text():
            self.transcript.handle_event(event)
            return
        if self.input.handle_event(event):
            if key not in ("up", "down"):
                self._hist = None
            return
        if key in ("up", "down") and not mods:
            self._recall(-1 if key == "up" else 1)

    def _mouse(self, event: Event) -> None:
        target = None
        if event.type in (EventType.MOUSE_DRAG, EventType.MOUSE_UP) and self._mouse_target:
            target = self._mouse_target
        elif event.x is not None and event.y is not None:
            for widget, rect in ((self.transcript, self._transcript_rect),
                                 (self.input, self._input_rect)):
                if rect.contains(event.x, event.y):
                    target = (widget, rect)
                    break
        if target is None:
            return
        widget, rect = target
        if event.type is EventType.MOUSE_DOWN:
            self._mouse_target = target
        elif event.type is EventType.MOUSE_UP:
            self._mouse_target = None
        widget.handle_event(event.translated(-rect.x, -rect.y))


def _short(path: str) -> str:
    from xefm.terminal_sessions import _short as short
    return short(path)


def _welcome(name: str) -> str:
    return (f"_{name}, in a conversation XeFM draws. Type a request below and "
            "press Enter. XeFM asks you before the agent runs a tool that "
            "needs permission._\n")

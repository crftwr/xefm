# Screen Groups, the Screen Strip and Closed Conversations: Implementation

Discussion #1019. Terminal and AI agent sessions piled up behind the panes:
starting one was one key and always made a new one, closing one was several
steps, and nothing on screen said how many there were. This is the second
layer over [TERMINAL_SESSIONS_IMPLEMENTATION.md](TERMINAL_SESSIONS_IMPLEMENTATION.md);
read that first for screens, sessions and the layer tree.

| Part | Where |
|---|---|
| Groups | `Session.group` (`xefm/terminal_sessions.py`), `Screen.screen_group`, `ScreenManager.in_group` / `last_in_group` / `neighbour` / `after_close` (`xefm/screens.py`) |
| Group keys | `XeFMApp.subshell`, `open_agent`, `_go_to_group`, `switch_screen`, `new_shell`, `new_agent` |
| In-session actions | `xefm.terminal.SCREEN_ACTIONS`, `screen_action_handlers`; `XeFMApp._screen_action`, `_new_in_group` |
| Tab strip drawing | `xefm/tab_strip.py` (`TabStrip`, `Tab`), shared with the pane's folder tabs |
| Screen strip | `xefm/screen_strip.py` (`ScreenStrip`, `strip_height`); `XeFMApp._add_session_screen`, `_screen_tabs`, `_tab_mark`, `_strip_event`; `xefm.terminal.strip_event` |
| Session count | `XeFMApp._screens_part`; `StatusBar.draw` / `handle_event` (`_screens_hit`) |
| Closing | `XeFMApp._session_close_request` (asks only on `Session.busy`), `_close_idle_sessions`; `ChatView._key` (Ctrl-D) |
| Screens | `XeFMApp.screens`, `_rename_screen`; `FilterListDialog(on_rename=)`, `rename_list_item` |
| Closed conversations | `ClosedAgent` (`xefm/terminal_sessions.py`); `XeFMApp._closed_agents`, `_remember_closed`, `_forget_closed`, `_resume_agent`, `_resume_into`; app state key `agents.closed` |
| Names | `Session.title`, `title_from_request`, `title_from_terminal`; `XeFMApp._name_agent_session`, `_session_title`; `Conversation.title` from ACP `session_info_update` |

## Groups

A session's group is `GROUP_AGENT` for a drawn agent (`kind == AGENT`) or an
agent run in the terminal (`Session.agent`, set by `_start_agent`), else
`GROUP_TERMINAL` - shells and terminal programs alike, an editor opened with
`'terminal': True` included. The file manager's screen is a group of its own
(`FILES`). `Screen.group` was already the screen's `LayerGroup`, hence
`screen_group` for the group it belongs to.

`in_group(group)` is the group's screens in tab order - the order they were
made until the user moves a tab (`ScreenManager._tabs`, `move_tab`, which
keeps the group's places in the whole order and changes who stands in them)
- or, with `order="recent"`, most recently shown first. `started()` stays
the order they were made, which `ctx.screens(order="started")` promises;
`last_in_group` is the first of that, where a group key goes. A screen whose
session is closing (`Screen.closing`, set by `_close_session` before a fade
that can outlast the call) is no longer in its group: otherwise the group
key pressed during the fade showed the screen on its way out.

`neighbour(screen)` is the tab after it, else before it; `after_close` is
that or the file manager. `ScreenManager.remove` and `_close_session` both
use it, so closing a tab never jumps to another group's screen the way the
old "screen shown before" rule did. The closing screen itself still counts in
`neighbour`, since its place decides which tab is next.

## Keys

- `subshell` and `agent` (filer) go to their group's last screen, and start a
  session only when the group is empty. `subshell` in terminal mode is
  unchanged: it hands the terminal over.
- `new_shell` and `new_agent` (filer, unbound) always start one. `new_agent`
  never reuses a drawn session in the same folder; only a request
  (`ask_agent`, `prompt` set) still goes to one (`_agent_chat_for`).
- `switch_screen` (common, so a viewer runs it through `surface_actions`):
  from the file manager to the most recently shown other screen, from any
  other back to the file manager; with no session it opens Screens. Ctrl-`
  carries it, and `terminal.switch_screen` inside a session, which wins
  over the program because it is `terminal.*`.
- `terminal.new`, `terminal.next_tab`, `terminal.prev_tab`: desktop chords
  only (macOS Cmd-T / Cmd-Shift-] / Cmd-Shift-[, Windows Ctrl-Shift-T /
  Ctrl-Tab / Ctrl-Shift-Tab), the keys of the platforms' terminals. A
  terminal cannot deliver them, and a program needs the plain keys.
- `screens` and `terminal.screens` lost Ctrl-`: Screens is reached from the
  status bar's count, the Tools menu and the palette.

Both session views (`TerminalView`, `ChatView`) take the screen actions
through one callback, `on_screen_action`, set by `_add_session_screen`, so
neither view knows about groups.

## The screen strip

Each session's screen gets a `ScreenStrip` layer in its own layer group, at
z 2 over the view (z 1; dialogs come at 70), not interactive. Over the view
because the view is a `cover` layer and PuiKit draws a screen from its
topmost cover layer up: a strip under it is never drawn (the first version
put it at z 0 and showed no tabs). Not interactive so the keys and the focus
stay the view's (`_top_interactive_slot` skips it). What looks for a screen's
topmost layer skips it through `screen_strip.top_surface`:
`ScreenManager.top_layer`, `_over_top_layer` (where an app-wide action's
dialog is parented) and `ctx.view`'s scroll to a line. Both layers
have reflows that ask the app, on every render, whether the group has two
screens: the strip's rect is the strip height or nothing, and the view's
starts below it. A third session or a closed one changes both on the next
frame with no bookkeeping.

On a vector backend (the desktop app) a tab is 1.6 rows high
(`TAB_HEIGHT_GUI`: 30% of a row above and below the text, which
`TabStrip.draw(height=)` centres), and the strip is that plus 4 px above it;
on a grid both are one row (`strip_height(backend)`, read from the backend's
capabilities because a reflow has no draw context). The tabs stand on the
strip's bottom edge, so the current one runs on into the page. The folder
tabs use the same chips, height and spacing (inset 1 unit at each end, 0.75
between icon, label and `×` on a vector backend; whole cells on a grid).

Clicks: the panel routes every mouse event to the top interactive layer, the
view, in its local coordinates - above the strip that is a negative y. Both
views call `xefm.terminal.strip_event` first, which hands such an event to
`on_strip_event` (the app's `_strip_event`) and swallows it, so the program
never sees a click outside its grid. `_strip_event` adds the strip height
back and asks `ScreenStrip.hit`: a tab's index shows that screen, `NEW_TAB`
starts another of the group (`_new_in_group`: the same agent, else a shell in
the session's current directory).

The strip moves with its screen: `_animate_session` plays
`animate_from_behind` on the view and the same fade, for the same
`BEHIND_MS`, on the strip, wherever a session's screen comes from behind the
file manager or goes back there (`_show_screen` both ways, `_close_session`).
Without it the strip popped up at once and stayed while the view faded. A
strip that went out is drawn again when its group is shown
(`Panel.set_layer_hidden` forgets what went out under it), so a switch
between two terminals, which plays nothing, shows it.

Moving a tab: `TabStrip.press` arms a drag of the tab under a press (not
its `×`, not `+`); `drag(x)`, once the pointer has travelled
`DRAG_THRESHOLD`, sets `drop_slot` - the gap before the first tab whose
middle is past the pointer, or None where the tab would stay put - and says
whether it changed, so the caller redraws; `draw` shows the slot as a line
in the accent in that gap (2 px on a vector backend, a `│` in the gap's cell
on a grid). Nothing moves while dragging: `release` returns `(from, to)`
for the caller to move, and `take_click` refuses the click the release
brings after a drag. On a screen the gesture reaches the
app through the view: `strip_event` keeps a press made on the strip
(`view._strip_held`) - its drags, its release and the click after it -
wherever the pointer goes, so a drag that dips into the terminal never
selects text there. `_strip_event` turns a drag into
`ScreenManager.move_tab`. The folder tabs do the same in
`PaneHeader.handle_event` with `PaneManager.move_tab`, which keeps the
current tab current. `terminal.move_tab_left/right` and
`move_tab_left/right` move by one place, unbound.

A tab is `Tab(label, mark, icon, closable)` (`xefm/tab_strip.py`): inset,
the lead (the mark, else the icon) and a space, the label, a space and `×`
when closable, inset. When the tabs are squeezed the lead and the close
button keep their width and only the label is elided. The `×` is drawn only while
`ctx.pointer_in` says the pointer is over its tab (which also tells the
panel to redraw when the pointer crosses the tab's edge), with a backing
under it while the pointer is on the button (a little wider than the glyph
on a vector backend, exactly its cell on a grid, and the glyph drawn on the
backing's colour - on a grid a cell's text background is what shows); its room is reserved either
way, so the tabs never shift. `TabStrip` records the close buttons' spans apart (`close_hits`): exactly
the area the backing covers, so what lights up is what a click hits; `ScreenStrip.hit`
answers `(CLOSE, index)` for one, and `_strip_event` calls that session's
view's `on_close_request` - the same path as `terminal.close`, which asks
only when the session is busy. The folder tabs pass neither, and look as
before.

The label is `Session.tab_label` (the title, a chosen name, what runs now,
the program); the icon is `$` for a shell, `>` for a terminal program, `✦`
for an AI agent (`_tab_icon`); the mark is the status bar's mark for the
session's attention (`⚠`, `✓`), `…` while it reports progress, nothing while
it is on screen.

### The tab strip lives in XeFM, by decision

"No UI-toolkit code in XeFM" has one recorded exception here. The folder tabs
were already drawn by XeFM (`PaneHeader._draw_tabs`), and the screen strip
needed the same thing: no focus, no keys, the host choosing the current tab
and how loud it is, equal shares and elided labels when they do not fit.
PuiKit's `Tabs` is a different widget - a dialog's page switcher that takes
focus and the arrow keys and holds the page under it. The user decided
(#1019) to keep this strip as XeFM's own shared drawing in `xefm/tab_strip.py`
rather than move it into PuiKit. Its one capability read, `ctx.vector_shapes`,
only rounds the chips' top corners - a pixel ornament, which
`doc/dev/CAPABILITY_BRANCHING_AUDIT.md` allows. The release review should not
raise it again.

## Closing

`_session_close_request` asks only when `Session.busy`: a program running,
a shell in a command (`TerminalView.busy`), an agent mid-turn
(`ChatView.busy`). It asked on `view.running` before, so an idle shell at
its prompt asked "still running?", unlike the quit confirmation.
`_agent_chat_close_request` (drawn sessions) already asked only mid-turn.

`_close_idle_sessions` closes every session that is not busy - which
includes drawn agents between turns, since closing one keeps its
conversation, and excludes agents run in the terminal, which are busy while
their program runs.

`ChatView` closes on Ctrl-D with an empty message and no completion menu: a
shell's end-of-input, and a key every terminal sends (terminal mode has no
`terminal.close` key).

## Closed conversations

`_close_session` calls `_remember_closed` before anything else; so does
`_close_terminal_sessions` at quit. Only a drawn agent session with an agent
session id and at least one user turn is kept, as a `ClosedAgent`: the
`AGENTS` name, the folder, the id, the title, when, and the `Conversation`
object itself. The list is newest first, one per id, at most 20, and is
written to the app state (`agents.closed`) without the conversation.
`_closed_agents` reads it back lazily on first use.

`_resume_agent(record)` finds the drawn entry by name, drops the record and
calls `_start_agent(entry, resume=record)`, which starts in the record's
folder and passes it to `_start_agent_chat`. There `_resume_into` gives the
session the record's title and either puts the old `Conversation` back (this
run: the transcript returns as it was) or sets only `session_id` on a fresh
one with a notice (an earlier run). Then `protocol.restart(view,
resume=True)` - the same path a crashed agent restarts on: Claude Code gets
`--resume <id>` through `restart_argv`, Codex `thread/resume`, ACP
`session/resume` or `session/load`, all from `conversation.session_id`.

Agents run in a terminal session are not kept: XeFM does not know their CLI's
conversation id.

## Names

`Session.title` is set once and then only by the rename key.

- Drawn: `_agent_chat_changed` calls `_name_agent_session` on every change,
  shown or not. It takes `Conversation.title` as soon as the agent gives one
  (ACP `session_info_update`, folded in `AcpClient._on_notification`), else,
  once the state is back at `IDLE` or `ASKING` after the first user item,
  `title_from_request` of that item: its first non-empty line, spaces run
  together, cut at a word to 40 characters. A request from `ask_agent` has
  the context appended after a blank line, which the first line leaves out.
- In a terminal: `_session_title` takes the first OSC title that says more
  than the program's name (`title_from_terminal`: leading marks such as
  Claude Code's `✳` and spinners stripped, the session's base name, the
  program and the known agent names refused).

What runs now (`activity`) stays separate and is shown next to the title in
Screens.

## Screens

Rows: the terminal's sessions, then the agents', each sorted waiting-on-you
first (`attention[0] == "attention"`), then `last_used_at` (set by
`make_current`); then "Close N idle sessions" when any is idle; the closed
conversations whose agent is set up and drawn; "New shell" (desktop); "New
<agent>". The file manager is not a row - `switch_screen` goes back. The
right column is the kind, the state and `ago(last_used_at)` (or "shown").
The cursor starts on the first session that is not on screen.

The remove key closes a session or forgets a closed conversation; the rename
key (`rename_list_item`, F2, a new `filter_list` action) closes the dialog,
asks for the name with `show_input` and opens Screens again.

## Tests

`test/test_screen_groups.py`: names, groups, the group key, closing to the
neighbour, tab stepping, the strip and the view's room, marks, clicks, the
strip drawn alone, the close request, close-idle, rename, closed
conversations (kept, persisted, offered, resumed), naming both ways, ACP's
title, Ctrl-D, the rename key and the new key bindings.
`test/test_terminal_sessions.py` and `test/test_agent_chat.py` hold the
rest of the screen behaviour.

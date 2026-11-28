# Window Tabs, the Shared Chrome and Closed Conversations: Implementation

Discussion #1019. Terminal and AI agent sessions piled up behind the panes:
starting one was one key and always made a new one, closing one was several
steps, and nothing on screen said how many there were. This is the second
layer over [TERMINAL_SESSIONS_IMPLEMENTATION.md](TERMINAL_SESSIONS_IMPLEMENTATION.md);
read that first for screens, sessions and the layer tree.

| Part | Where |
|---|---|
| The tabs | `ScreenManager.tabs` / `move_tab` / `after_close` (`xefm/screens.py`); `XeFMApp._window_tabs`, `_tab_icon`, `_tab_mark`, `_tab_event` |
| A session's kind | `Session.group` (`GROUP_TERMINAL`, `GROUP_AGENT`), `Screen.screen_group`, `ScreenManager.in_group` / `last_in_group` |
| Keys | `XeFMApp.subshell`, `open_agent`, `_go_to_group`, `switch_screen`, `new_shell`, `new_agent`, `_new_kinds`, `_new_tab_menu`; `xefm.terminal.SCREEN_ACTIONS`, `XeFMApp._screen_action` |
| Tab drawing | `xefm/tab_strip.py` (`TabStrip`, `Tab`), shared with the pane's folder tabs |
| The window's strip | `xefm/screen_strip.py` `ScreenStrip` (one instance, `XeFMApp.window_tabs`) |
| The chrome on a session's screen | `xefm/screen_strip.py` `SessionFrame`, `chrome_bands`; `XeFMApp._add_session_screen`, `_chrome_bands`, `_content_band`, `_chrome_event`, `_session_hints`; `StatusBar._text`, `click_at`; `xefm.terminal.strip_event` |
| Menus | `xefm.menu_when`, `XeFMApp._menu_presets`, `_share_menu_bar`; the `menu` key over a session in `on_event` |
| Closing | `XeFMApp._session_close_request` (asks only on `Session.busy`), `_close_idle_sessions`; `ChatView._key` (Ctrl-D) |
| Screens | `XeFMApp.screens`, `_rename_screen`; `FilterListDialog(on_rename=)`, `rename_list_item` |
| Closed conversations | `ClosedAgent` (`xefm/terminal_sessions.py`); `XeFMApp._closed_agents`, `_remember_closed`, `_forget_closed`, `_resume_agent`, `_resume_into`; app state key `agents.closed` |
| Names | `Session.title`, `title_from_request`, `title_from_terminal`; `XeFMApp._name_agent_session`, `_session_title`; `Conversation.title` from ACP `session_info_update` |

## The tabs

The window's screens are its tabs: the file manager's, pinned first, then
every session's - shells, terminal programs, AI agents - in one strip
(`ScreenManager.tabs`, the order they were made until the user moves one;
`ScreenManager._tabs` holds it). `move_tab` keeps the file manager first:
it does not move, and nothing goes before it. `started()` stays the order
they were made, which `ctx.screens(order="started")` promises.

`after_close(screen)` is the screen shown before it (`_recent`, most
recently shown first), else the file manager's - as a browser or VS Code goes
back to the tab used last, so an editor opened from the file manager closes
back to it rather than to whatever tab stands beside it.
`ScreenManager.remove` and `_close_session` both use it. A screen whose
session is closing (`Screen.closing`, set by `_close_session` before it tears
down) is no longer a tab.

A session's kind is still kept - `Session.group` is `GROUP_AGENT` for a
drawn agent or an agent run in the terminal (`Session.agent`, set by
`_start_agent`), else `GROUP_TERMINAL`; `Screen.screen_group` (`Screen.group`
was already its `LayerGroup`) - for the keys that go back to a kind
(`last_in_group`) and the tab's icon. An earlier version had a strip per
kind; one strip read better, and leaves room for viewers and editors to
become tabs later (with a preview-tab rule, so they do not pile up).

## Keys

- `subshell` and `agent` (filer) go to the last screen of their kind, and
  start a session only when there is none. `subshell` in terminal mode is
  unchanged: it hands the terminal over.
- `new_shell` and `new_agent` (filer, unbound) always start one. `new_agent`
  never reuses a drawn session in the same folder; only a request
  (`ask_agent`, `prompt` set) still goes to one (`_agent_chat_for`).
- `switch_screen` (common, so a viewer runs it through `surface_actions`):
  from the file manager to the most recently shown other screen, from any
  other back to the file manager. With no session it starts a terminal - a
  shell session on the desktop, the subshell in terminal mode - and never an
  agent: the key keeps meaning "terminal", the first press is not a dialog
  the second press is not, and an agent CLI (sign-in, a plan's usage) starts
  only on `agent`. Ctrl-` carries it, and `terminal.switch_screen` inside a
  session, which wins over the program because it is `terminal.*`.
- The `+` after the tabs and `terminal.new` run `_new_tab_menu`: what
  `_new_kinds` says can start (a shell where XeFM has a terminal, each agent
  installed - drawn ones only in terminal mode), at once when that is one
  thing, else picked from a `choose` list.
- `next_screen` / `prev_screen` (common) and `terminal.next_tab` / `prev_tab`
  walk all the tabs, the file manager's included: Ctrl-Tab / Ctrl-Shift-Tab,
  as in a browser or VS Code, in the desktop overrides only - a terminal
  never sends Ctrl-Tab (there: Ctrl-` and the palette). On a Mac,
  Cmd-Shift-] / Cmd-Shift-[ too, on both pairs, so the same keys walk the
  tabs from the file manager as from a session. An active macOS app never
  gets Ctrl-Tab in `keyDown:` - AppKit offers it as a key equivalent and,
  declined, spends it on the key-view loop - so PuiKit's view takes
  Ctrl-Tab / Ctrl-Shift-Tab in `performKeyEquivalent:`. The pane's tabs keep
  Ctrl-PgDn / Ctrl-PgUp; the Orthodox preset gave its Ctrl-Tab up for this,
  and its pane tabs are unbound (Ctrl-PgDn / Ctrl-PgUp are TC's open and
  parent there).
  `terminal.move_tab_left` / `right` move the current one, unbound.
- `screens` and `terminal.screens` lost Ctrl-`: Screens is reached from the
  Tools menu and the palette.

Both session views (`TerminalView`, `ChatView`) take the screen actions
through one callback, `on_screen_action`, set by `_add_session_screen`, so
neither view knows about tabs.

## The window's strip

`ScreenStrip` is one widget, `XeFMApp.window_tabs`. The file manager's
layout places it under the menu bar (`size="content"`, zero high without a
session - `measure` asks `shown()`), and a session's screen draws the same
instance at the same place (below). It lists `_window_tabs()` - **Files**
(pinned, not closable) then each session - with `+` after them; the current
one is the screen on now. Pointer events reach `_tab_event(event, x, y)` in
the strip's own units: from its layout slot directly (`on_event`), or from a
session's view through `_chrome_event`.

Tab chips: `Tab(label, mark, icon, closable)`. The icon is `▤` for the file
manager, `$` a shell, `>` a terminal program, `✦` an AI agent
(`_TAB_ICONS`); the mark (`⚠`, `✓`, `…`) takes the icon's place while a
session out of view has something to say. A chip is: inset, the lead (the
mark, else the icon) and some room, the label, room and `×` when closable,
inset; squeezed, only the label gives way. A tab keeps its width whichever
tab is current and whatever its lead shows: every label is measured as the
bold the current one is drawn in, and the lead gets the room of the widest
of `TabStrip.LEAD_SAMPLES` (the icons and the marks), centred in it - a
switch moved every tab a little when the current label alone was measured
bold and a mark replaced a narrower icon. The `×` is drawn only while
`ctx.pointer_in` says the pointer is over its tab (which also tells the
panel to redraw when the pointer crosses the tab's edge), with a backing
under it while the pointer is on the button (a little wider than the glyph
on a vector backend, exactly its cell on a grid, and the glyph drawn on the
backing's colour - on a grid a cell's text background is what shows); its
room is reserved either way, so the tabs never shift. `close_hits` are
exactly the area the backing covers, so what lights up is what a click hits.
A click there calls that session view's `on_close_request` - the same path as
`terminal.close`.

On a vector backend a tab is 1.3 rows high (`TAB_HEIGHT_GUI`: 15% of a row
above and below the text, which `TabStrip.draw(height=)` centres), and the
strip is that plus 4 px above and 4 px below it, the tabs centred in it with
all four corners rounded; on a grid both are one row. The current tab wears
the page's colour. The colours come from `tab_strip.strip_colors(theme, pane=)` for
both strips: the ground starts from the header band and is set off it - the
window's strip toward the text, a pane's toward the page - so the window's
strip, a pane's strip and the pane's path bar read as three bands. The folder tabs use the same chips, height and spacing (inset 1 unit at each end,
0.75 between icon, label and `×` on a vector backend; whole cells on a grid).

Moving a tab: `TabStrip.press` arms a drag of the tab under a press (not a
pinned one, not its `×`, not `+`); `drag(x)`, once the pointer has travelled
`DRAG_THRESHOLD`, sets `drop_slot` - the gap before the first tab whose
middle is past the pointer, never before a pinned tab, or None where the tab
would stay put - and says whether it changed, so the caller redraws; `draw`
shows the slot as a line in the accent in that gap (2 px on a vector
backend, a `│` in the gap's cell on a grid). Nothing moves while dragging:
`release` returns `(from, to)` for the caller to move, and `take_click`
refuses the click the release brings after a drag. The folder tabs do the
same in `PaneHeader.handle_event` with `PaneManager.move_tab`, which keeps the
current tab current.

## The chrome on a session's screen

A session's view is a `cover` layer (`viewer_layer_hints`), and PuiKit draws
a screen from its topmost cover layer up: the file manager's layout - its
menu bar, the strip, its status bar - is not drawn under it. So each
session's screen has a `SessionFrame` layer over the view (z 2 against its
1; dialogs come at 70), not interactive, which draws the very same widgets
with `draw_child`: `menu_bar` in the header surface (only where the menu bar
is in the window - `takes_activation_key`; the OS's otherwise), `window_tabs`,
and `status` in the status surface. One instance of each, so the two places
cannot drift apart; `MenuBar` and `StatusBar` record the rect they were last
drawn in, so a menu opened from a session's screen hangs from the right
place. The view's reflow puts it between the bands (`_content_band`), and
`chrome_bands(backend, menu_in_window=, strip=)` gives the heights the file
manager's layout measures: `CONTROL_HEIGHT` or a row for the menu, the
strip's, a row plus `BAR_PAD_PX` for the status bar. Both recompute every
render, so a first session (the strip appearing) or a closed last one
re-lays out the next frame.

Not interactive, the frame never takes the keys or the focus
(`_top_interactive_slot` skips it), and what looks for a screen's topmost
layer skips it through `screen_strip.top_surface` (`is_strip`):
`ScreenManager.top_layer`, `_over_top_layer` (where an app-wide action's
dialog is parented), `_palette_surface` (the first version of the strip
broke the command palette in sessions by answering for it) and `ctx.view`'s
scroll to a line.

Pointer events: the panel hands every pointer event to the view, in its own
units. `xefm.terminal.strip_event` passes each to `on_strip_event` - the
app's `_chrome_event` - first: by the event's place in the window it goes to
the menu bar (`handle_event`, its own units), the strip (`_tab_event`) or the
status bar (`click_at`), and True; in the content band it is the view's. A
press on a band keeps the gesture (`screen._chrome_held`: its drags, its
release and the click after it) wherever the pointer goes, so a tab dragged
down into the terminal never selects text there.

Going between screens is a tab switch: `_show_screen` makes the screen
current at once and `_close_session` tears down at once. The full-window
"from behind the file manager" transition (`animate_from_behind`, gone from
`dialog_geometry`) belonged to a terminal that covered the window; with the
chrome staying put it read as the window moving under a strip that did not.

The status bar on a session's screen says `_session_hints(session)`: a drawn
agent's `ChatView.status_hint` (which then draws no footer of its own,
`chrome_status`), or for a terminal the keys XeFM takes from the program -
`terminal.*` ones, and inherited ones only as chords. The jobs on its right
are the same as on the file manager. `StatusBar.handle_event` keeps refusing
clicks under a modal layer; `click_at` is what the frame calls.

The new-line key the agent's footer names is `newline_key()`: Shift+Enter in
the desktop app, Ctrl+J in a terminal - every terminal sends it, many cannot
send Shift+Enter, and Alt+Enter is Windows Terminal's full-screen key and
needs Option sent as Meta on a Mac. All three still work where they arrive.

## Menus and the palette on a session's screen

The menu bar is there on every screen now, so each item says where it can
act (`when`, `xefm/menu_when.py`; `doc/dev/MENU_SYSTEM.md`): the file
manager's unless it says `always`. What a session's screen offers is Command
Palette, Resume AI Conversation, Switch Screen, Screens, the configuration
and the Advanced setup (but Install Extension, which starts from the file
under the cursor), Theme, Font Size and Help. Starting a shell or an agent
from Tools (Terminal, New Shell Here, AI Agent, New AI Agent Here) is the
file manager's, since it starts in the active pane's folder; a session's
screen has the tabs' `+`. No session menu of its own: the strip and Screens
carry what one would hold.

PuiKit greys an OS menu bar while a layer that does not own it is on top
(xefm#388). A session's view is a layer too, but a screen, not a modal:
`_share_menu_bar` registers it as an owner of the window's bar
(`Panel.set_menu_bar(menu, owner=view)`), and a dialog over the session
greys the bar again. Before that, Screens and Command Palette were greyed on
a session's screen though the palette reached them.

In terminal mode the menu bar opens over a drawn agent's conversation on its
`menu` key (`on_event`, next to the palette's): the conversation owns the
keyboard, so the binding is taken before it; a terminal's program keeps the
key unless it is a chord no program receives (`takes_binding`). The command
palette opens there the same way, as it did before for viewers.

## The tab strip lives in XeFM, by decision

"No UI-toolkit code in XeFM" has one recorded exception here. The folder tabs
were already drawn by XeFM (`PaneHeader._draw_tabs`), and the screen strip
needed the same thing: no focus, no keys, the host choosing the current tab
and how loud it is, equal shares and elided labels when they do not fit.
PuiKit's `Tabs` is a different widget - a dialog's page switcher that takes
focus and the arrow keys and holds the page under it. The user decided
(#1019) to keep this strip as XeFM's own shared drawing in `xefm/tab_strip.py`
rather than move it into PuiKit. Its one capability read, `ctx.vector_shapes`,
only rounds the chips' corners - a pixel ornament, which
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
`terminal.close` key). Esc in it stops the agent or clears a selection and
no more: the conversation is a tab, which Esc leaves no more than it leaves
a shell's (it went back to the file manager before).

## Closed conversations

`_close_session` calls `_remember_closed` before anything else; so does
`_close_terminal_sessions` at quit. Only a drawn agent session with an agent
session id and at least one user turn is kept, as a `ClosedAgent`: the
`AGENTS` name, the folder, the id, the title, when, and the `Conversation`
object itself. The list is newest first, one per id, at most 20, and is
written to the app state (`agents.closed`) without the conversation.
`_closed_agents` reads it back lazily on first use.

They are offered by their own dialog, `resume_agent` (**Tools → Resume AI
Conversation…**), not Screens, which holds only the screens there are. Its
remove key forgets one, its rename key renames it (`_rename_screen(back=)`).

`_resume_agent(record)` finds the drawn entry by name, drops the record and
calls `_start_agent(entry, resume=record)`, which starts in the record's
folder and passes it to `_start_agent_chat`. There `_resume_into` gives the
session the record's title and either puts the old `Conversation` back (this
run: the transcript returns as it was) or sets only `session_id` on a fresh
one (an earlier run). Then `protocol.restart(view, resume=True)` - the same
path a crashed agent restarts on: Claude Code gets `--resume <id>` through
`restart_argv`, Codex `thread/resume`, ACP `session/resume` or
`session/load`, all from `conversation.session_id`.

The history of one from an earlier run comes from the agent, each its own
way, and only into an empty conversation - a restart after a crash keeps
what is on screen and asks for nothing:

- Claude Code's `--resume` goes on with the conversation without sending it
  again, so `agent_chat.load_claude_history` reads the file Claude Code keeps
  (`claude_transcript`: `<CLAUDE_CONFIG_DIR or ~/.claude>/projects/<the
  folder, separators made dashes>/<id>.jsonl`, else found by the id). Its
  entries are the stream-json messages XeFM folds already
  (`Conversation.handle`), plus the user's own words; meta entries, side
  chains and slash-command echoes are left out. A notice says it resumed.
- Codex: `thread/resume` with `excludeTurns` false when the conversation is
  empty; `CodexClient._fold_turns` draws the returned turns' items (a
  `userMessage`, then what `_item` already draws).
- ACP: `session/load` replays the conversation as updates; with an empty
  conversation (`AcpClient._replay`) they are folded instead of dropped,
  `user_message_chunk` included. (`session/resume` sends none: such an agent
  resumes with an empty transcript.)

Nothing goes into the conversation before the agent answers - a notice
would make it not empty and stop the history.

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

Screens holds the screens there are, nothing else: the file manager's row
first, then every session, whatever its kind, waiting-on-you first
(`attention[0] == "attention"`), then `last_used_at` (set by
`make_current`); then "Close N idle sessions" when any is idle. Starting a
session (the `+`) and resuming a closed conversation (`resume_agent`) have
places of their own: mixed in, they read as screens that were not there. The
right column is the kind, the state and `ago(last_used_at)` (or "shown").
The cursor starts on the screen shown last that is not on now.

The remove key closes a session; the rename key (`rename_list_item`, F2, a
new `filter_list` action) closes the dialog, asks for the name with
`show_input` and opens Screens again. Neither applies to the file manager's
row.

## Tests

`test/test_window_tabs.py`: names; the tabs, the kind keys, closing to the
tab beside, tab stepping; the strip, the view between the chrome, the chrome
drawn on a session's screen, pointer events routed to the chrome; marks,
icons, the close button and its cell, clicks, `+`; tall GUI tabs; dragging
and the drop line; the close request, close-idle, rename; closed
conversations (kept, persisted, offered, resumed); naming both ways, ACP's
title; Ctrl-D, the rename key and the new key bindings.
`test/test_terminal_sessions.py` and `test/test_agent_chat.py` hold the
rest of the screen behaviour.

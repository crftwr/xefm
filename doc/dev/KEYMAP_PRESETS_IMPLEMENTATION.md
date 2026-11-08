# Keymap Presets — Implementation

[#565](https://github.com/crftwr/xefm/issues/565) and
[#597](https://github.com/crftwr/xefm/issues/597), from discussion
[#343](https://github.com/crftwr/xefm/discussions/343). User-facing behavior is
in [`doc/KEYMAP_PRESETS_FEATURE.md`](../KEYMAP_PRESETS_FEATURE.md).

## Shape

`xefm/keymap_presets.py` holds `Preset` (name, label, description,
`bindings`, `type_ahead`) and the `PRESETS` table: `afx`,
`orthodox`, `native` and `vim`. Labels are bare names (`AFX style`, `Orthodox`);
what each does is the description, which the keymap dialog shows beside it. Discussion #343 asked for one mechanism with several presets on
it, not a special-cased beginner mode, and that is the reason for this shape.

Since [#597](https://github.com/crftwr/xefm/issues/597) the presets are
**peers**. Each one is a complete keymap, the first launch asks which, and
`config.py`'s `KEY_BINDINGS` is laid over whichever is in force. Before
#597, the AFX table *was* the template's `KEY_BINDINGS`, and a preset changed
only the "untouched" actions (equal to the shipped value). That made AFX the
default, and the untouched test could not tell an old shipped value from a
deliberate one.

Every preset is laid over **`xefm/keymap_common.py`**, `bindings()`: the
viewers', dialogs' and search bars' keys (the same under every preset), the
file list's keys that are not a bare letter or digit, and the desktop app's
platform keys (`quit_app`, the font size). It binds no letter or digit to a
`filer` or `common` action, and still lists every action, `[]` where a preset
has to give it a key, so none falls through to `actions._template_bindings`.
It is a function because the desktop overrides at its foot branch on
`is_desktop_mode()` and `sys.platform`, and every call returns a new dict.

The AFX preset is `xefm/keymap_afx.py`: `own_bindings()` is its letters and
digits (with the shared keys an action keeps, such as `DELETE` beside `K`),
and `bindings()` is the whole AFX keymap, the common table with those laid
over it. Until the split (in the same change as the font size keys) the AFX
table *was* the common table: it held every shared key too, and the other
presets started from it with a `free_letters` flag that stripped AFX's
letters. That made a shared key look like an AFX choice; a key for every
preset (the font size) had to be added to "the AFX file". The split kept
every preset's table identical, order included, on all three platforms in
both backends; only an emptied `{'keys': [], 'selection': …}` became `[]`.

Both presets are named for their lineage. AFX's is the single-key Japanese
filers: the X68000 file managers, then AFX (あふ), then cfiler. The preset
follows their style, not their exact keys. `FALLBACK = AFX` is the table in
force while nothing has been chosen. `ALIASES = {"default": "afx"}` and
`canonical()` keep the first name working, both in `KEY_PRESET` and in a
saved menu choice. `set_keymap_preset` compares canonical names, so
`KEY_PRESET = 'default'` does not block choosing AFX style from the menu.
A per-platform Explorer/Finder preset is one more entry.

`actions._template_bindings`, the built-in default for an action no table
mentions, reads `keymap_afx.bindings()`. Every preset's table starts from the
common table, which names every action AFX does, so only an action absent
from all of them reaches that fallback.

## `table(name)` and `apply(config, name)`

`table(name)` builds one preset's whole keymap:

1. Start from `keymap_common.bindings()`. It has no **typing keys**
   (`is_typing_key`: a bare letter or digit, or `Shift-<letter>`) on a
   `filer` or `common` action; a viewer's own actions keep their letters,
   because nothing is typed into a viewer.
2. `bindings` replaces the keys of each action it names, in place. A plain
   list drops any `selection` gate, so an orthodox `F5` copies the cursor
   item when nothing is marked, which `_transfer` already does. AFX's entries
   keep theirs: its `copy_files` is `{'keys': ['C'], 'selection':
   'required'}`.

`apply` writes the result **into `config.KEY_BINDINGS`**. The keymap is built
from that table in several places: the app's `self.keys`, the shared
`config_manager.get_key_bindings()` that help and the menus resolve through,
and `DirectoryDiffView`'s own `KeyBindings`. Rewriting the one table they all
read is what makes a preset reach every surface without touching any of them.

1. `overrides(config)` is the table `config.py` was loaded with (extension
   key suggestions included). It is stashed on the config as
   `_KEY_BINDINGS_BASE` the first time, so switching presets back and forth
   starts from it each time instead of compounding.
2. Every entry in it replaces the preset's, whatever it equals. An entry
   under an **old action name** (`rename_file`) also removes the preset's
   entry under the current one (`rename`). `KeyBindings` matches current
   names first, so the preset's entry would otherwise win.
3. **The keys an entry binds leave the preset actions it does not mention**
   (`_release_claimed_keys`, #662). Binding `Shift-T` to
   `toggle_color_scheme` takes `Shift-T` off AFX's `open_in_new_tab`, so the
   user doesn't have to find that action and empty it too. Keys are compared
   parsed (`KeyBindings._parse_key_expression`), so `shift-t` and `Shift-T`
   are the same key. A preset action keeps a key in two cases, because there
   the user's entry would not replace it:
   - **It is reached somewhere the user's entry is not.** Each name's reach is
     the set of contexts that resolve it (`_reach`). `common` actions are
     reached everywhere; a scoped rebind (`'text_viewer.quit'`) reaches only
     its own context. The key is taken only when the preset action's reach
     is a subset of the entry's. `view_file: ['Q']` does not take `Q` from
     `quit`, so the viewers still quit on it. `file_details: ['C']` does not
     take `C` from `copy_files`, which also copies in the directory diff.
   - **The two selection gates never hold together** (`required` and
     `none`). The pair splits the key the way AFX's `M` is split between
     `move_files` and `create_directory`.
4. The result lists **`config.py`'s entries first**. `KeyBindings` tries
   entries in table order, so in whatever overlap step 3 leaves, the user's
   entry is matched: `Q` opens the file in the file list, and still quits in
   a viewer.
5. `config._KEY_TYPE_AHEAD` records the flag.

Step 3 can only see where an action is reached once that action is
registered, and `config.py`'s own `ACTIONS` register after the first
`apply`. `XeFMApp._rebuild_keymap` (apply, then relabel the status bar and
the menu) therefore runs again right after `_load_user_entries`, at startup.
`reload_config` loads the user entries *before* rebuilding, for the same
reason.

`replaced(config, name)` lists the `config.py` entries whose value differs
from preset `name`'s. `set_keymap_preset` logs it when non-empty. That is the
whole migration story for a `config.py` holding the old full AFX copy. Under
AFX the copy replaces nothing and stays silent. Under Orthodox the log names
what it overrides. Nothing deletes the entries automatically: telling a
copied default from a chosen key is exactly the guess #597 removed.

The shipped `_config.py` `KEY_BINDINGS` is `{}` with commented examples, each
one meaningful under every preset.

`test_no_two_actions_share_a_key_in_the_file_list` keeps the orthodox table
free of clashes. The ones it had to resolve: `F5` was `redraw` (now unbound),
`+` was `diff_directories` (now `Shift-F2`), `-` was `reset_pane_boundary`
(now unbound), and `Home`/`End` were select all / unselect all (now `Ctrl-A` /
unbound).

## Choosing

### The Orthodox table

`_ORTHODOX.bindings` follows Total Commander's default keys wherever XeFM has
the matching action. The user asked for it to match TC as closely as possible.
The reference was TC's keyboard map, from KEYBOARD.TXT as reproduced by
softpanorama and the DefKey / devcrea lists, which agree on the keys used here.

- A TC key with no XeFM action stays unbound. Examples: Alt-F8 command-line
  history, Ctrl-L occupied space, Ctrl-U swap panels.
- An XeFM action with no TC key is unbound under this preset (`[]`) when it
  would otherwise hold a key TC uses. Examples: `reveal_in_os` (Ctrl-R),
  `cursor_prev_selected` (Ctrl-Up), `redraw` (F5), `reset_pane_boundary` (`-`),
  `index_search` (Ctrl-F). `reset_log_height` (`_`) is unbound too, so
  type-ahead can reach `__init__.py`.
- Some actions are close but not exact, and are mapped anyway:
  - `duplicate_files` for Shift-F5 (TC prompts for the name; XeFM picks one);
  - `compare_selection` for Shift-F2 (TC marks the differences in both panels);
  - `drives` for Alt-F1 / Alt-F2 (TC's are per panel; XeFM's acts on the active
    one);
  - `connect_server` for Ctrl-F / Ctrl-N (TC's FTP connect / new URL);
  - `filter` for Ctrl-S (TC's quick filter);
  - `file_details` for Alt-Enter (properties).
- `reread` is new: it relists both panes, for TC's F2 / Ctrl-R. It has no key in
  AFX style.
- `command_palette` moves to Ctrl-Shift-P, because Ctrl-T is a new tab.

The table also names actions from PRs not merged yet: tabs, quick view, flat
view, back/forward, the file clipboard, `delete_permanently`. `apply` skips an
action the registry does not resolve, so the preset is right on a build with or
without them, and a missing action never holds a key for nothing.

### The OS native table

`native` (discussion #587) is the first preset whose table depends on where
XeFM runs. That makes `Preset.bindings` either a dict or a function, and
`table()` calls the function each time it builds. `_native_bindings()` uses
the same three cases as the foot of `keymap_common.py`:

- **Any terminal** gets a table of chords a terminal can send: no `Command`,
  no `Ctrl-Shift-<letter>`, and no `Ctrl`/`Alt-Enter`.
  `test_the_terminal_case_binds_nothing_a_terminal_cannot_send` holds it to
  the same rule `TestThreeCases` holds AFX to.
- **The macOS app** and **the Windows app** update that table, with the
  platform chord first because a menu shows `keys[0]`. The terminal keys
  stay as fallbacks.

The choice is stored once (`~/.xefm`) for both apps, which is why the
terminal case is a full layout rather than an afterthought. A user who picks
Finder's keys in the app and opens the TUI still has copy, paste, rename and
a new folder.

Decisions the table encodes:

- **Enter opens, on macOS too.** Finder renames on Enter. Following it would
  leave no key to open a folder that every other preset opens with Enter.
  `F2` renames everywhere.
- **F5 / F6 copy and move to the other pane, and F3 / F4 / F7 / F8 follow.**
  Finder and Explorer have no two-pane operations; these are the keys every
  two-pane manager uses. So `redraw` loses F5, as in Orthodox.
- **Two quits.** `Ctrl-Q` is `quit`, which always asks. `Cmd-Q` (macOS app)
  and `Alt-F4` (Windows app) are `quit_app`, which quits from anywhere and
  asks only while a task runs. They are not in this table: they are the AFX
  table's desktop keys, which every preset starts from, so every preset has
  exactly the platform's key in the desktop app and none in a terminal
  (closing the terminal window is the terminal's business). They are
  defaults; `KEY_BINDINGS` still wins. Orthodox keeps Total Commander's
  `Alt-F4` on `quit`; in the Windows app, where `Alt-F4` is also `quit_app`,
  `quit_app` is matched first.
- **Quick view.** On macOS it is Space, Quick Look's key, so marking moves to
  Ctrl-Space, which every backend delivers. Elsewhere it is Alt-P, Explorer's
  preview pane, and Space marks.
- **Stand-ins for the terminal**, where nothing native exists or the native
  chord cannot arrive:
  - `F7` new folder;
  - `Alt-I` file details;
  - `Ctrl-K` command palette (Ctrl-T is a new tab, as in both apps);
  - `Ctrl-Q` quit.
- **Released AFX keys.** `index_search` gives up Ctrl-F to find files,
  `reveal_in_os` gives up Ctrl-R to reread, and `unselect_all` gives up End
  to the cursor.

`test_no_key_runs_two_file_list_actions` checks every case for clashes.

### The Vim table

`vim` (discussion #587) follows vifm 0.15's normal mode and the sample vifmrc
a new vifm install copies (F3–F8, `w`, `s`, `S`), wherever XeFM has the
action. It is the first preset whose keys are sequences (`'g g'`, `'y y'`,
`'Shift-Z Shift-Z'`, see `xefm.key_sequence`). It is also the first that
reaches past the file list: `text_viewer.*` actions and a context-qualified
`text_viewer.quit`. `table()` therefore accepts any name `_known` recognizes:
an action of any context, or `<context>.<action>` as `KEY_BINDINGS` spells a
scoped rebind. `type_ahead` stays off, since letters are commands and `/`
searches.

New actions it needed, all unbound under the other presets:

- `half_page_down` / `half_page_up`: half of `_display_height()`.
- `search_next` / `search_prev`: the last pattern the search bar closed on
  (`_last_isearch_pattern`), matched with `find_matches` as the bar does,
  wrapping.
- `toggle_select_in_place`: vifm's `t`, the context menu's toggle.

Choices worth keeping:

- **No first key is a binding of its own.** `g`, `y`, `d`, `z`, `c`, `Z` and
  `D` only begin sequences, so no key waits out `KEY_SEQUENCE_TIMEOUT`.
  `test_no_prefix_is_also_a_key_of_its_own` holds that.
- **Moved off their AFX keys:**
  - `open_with_os` from Ctrl-O (back, here) to `g x`, Vim's gx;
  - `diff_files` from `=` (the filter, here) to nothing;
  - `context_menu` from `/` (search) to Apps / Shift-F10;
  - `index_search` from Ctrl-F (page down) to nothing;
  - `jobs` from Ctrl-G (file details, vifm's) to nothing.
- **`v` is `select_range`, not a visual mode.** It fills from the nearest
  mark, which is what a visual block ends as.
- **`dd` is the Trash, and `p` pastes the file clipboard.** vifm's `P` (move a
  yank) is `x` then `p`.

In the text viewer, `_act` translates a navigation action into the key the
rich renderer understands (`_RICH_KEYS`), so `j` or `gg` move a Markdown or
JSON view too. The renderer reads keys, not actions.

`resolve(config, chosen)` returns `KEY_PRESET` from the config when it names a
preset, else the saved choice (state key `keymap.preset`), else **None**:
nothing has been chosen. Old names are mapped through `canonical`. `get(None)`
and an unknown name give `FALLBACK`; an unknown name is also logged.

### The first launch

With no preset chosen, `_keymap_preset` is None and `FALLBACK` is applied
for the moment. `run()` then calls `_ask_keymap_preset` in place of that
launch's tip of the day, so two dialogs never stack. A new install and an
upgrade from before presets are treated alike. Telling them apart was tried
first: an existing `config.py` meant AFX was kept without asking. That was
dropped because it made AFX a default after all, which #597 removes. The
cost is one question for upgrading users, and it is asked once.

The dialog is a markdown message box with one button per preset and no
Cancel. It is opened with PuiKit's `dismissable=False`, so Esc does nothing.
A preset button calls `set_keymap_preset`, which stores the choice. Quitting
with the dialog open stores nothing, so the next launch asks again.
`__init__` never opens the dialog, because tests construct the app without
`run()`.

`make keymap-reset` deletes the stored choice, for hand-checking the dialog.

`XeFMApp._apply_keymap_preset` runs right after the state manager exists,
again (as `_rebuild_keymap`) once `config.py`'s actions are registered, and in
`reload_config` after the new config and its actions replace the old ones. It
rebuilds `self.keys` and clears `config_manager._key_bindings`.
`set_keymap_preset` stores the choice, applies it, and invalidates the two
surfaces that cache key names: the status bar's hint line, and the menu
(rebuilt) — the same pair `reload_config` already refreshes for #382. It
refuses, with a log line, when `KEY_PRESET` in the config names a different
preset.

The menu is **Tools → Advanced → Keymap…**. It opens the first launch's dialog
(`_keymap_dialog`), with a Cancel, the current preset under the cursor and
marked "(current)", and a note when `KEY_PRESET` in `config.py` decides. It
used to be a submenu with one checked item per preset, but the names alone
("AFX style", "Orthodox") say little, and labels carrying "(letters)" or
"(function keys)" grew uneven as presets were added. The `choose_keymap`
action opens the same dialog, so the command palette offers it.

## Type-ahead

`on_event`: when no action matched and no menu mnemonic did,
`_type_ahead(event)` checks the flag. For a printable, non-space `char` with
no Ctrl/Alt/Cmd it calls `enter_isearch(quick=True)` and then dispatches the
same event to the panel, where the search bar is now the top layer. The key
that opened the search becomes its first character. Shift is allowed, since a
capital is typing.

`quick=True` keeps I-Search's prompt and matching, and changes only how the
search closes, which follows Total Commander's quick search. The user asked
for that much and no more: the display and the matching stay XeFM's.

- **The bar has no select, select-all or accept callbacks.**
  - `on_cancel` is `_isearch_stop`, so Esc keeps the match instead of
    restoring the origin.
  - `on_passthrough` is `_isearch_passthrough`. `ISearchBar.handle_event`
    hands it any KEY that is not typing, not one of the bar's remaining
    actions (prev/next match, cancel), and not Backspace/Delete
    (`_EDIT_KEYS`).
  - `_isearch_passthrough` closes the search and feeds the event to `on_event`,
    so Enter reaches `open_item` and F5 reaches `copy_files` on the match.
- **The status bar** shows `_quick_hints` (prev/next, close, "other keys act on
  the file") instead of the usual I-Search hint line.

The I-Search key (`enter_isearch()` with no argument) is unchanged.

## Not done

A visual mode (vifm's `v` with motions), counts (`5j`), and presets as
data packages (#543).

## Tests

`test/test_keymap_presets.py`.

The pure half covers:

- each preset as a whole table;
- the orthodox table landing, with no selection gate;
- letters freed from the file list but not from a viewer;
- `config.py` overriding every preset, even with a value equal to AFX's,
  and under an old action name;
- a rebound key leaving the preset action that had it (#662), however it is
  spelled, and the other keys of that action staying; the key staying where
  the preset action is reached beyond the user's entry (a `common` action, a
  scoped rebind, `copy_files` in the directory diff) or split by selection;
  `config.py`'s entries listed first;
- `replaced`;
- switching back and forth without compounding;
- no key clashes, `is_typing_key`, `resolve`;
- the shipped `KEY_BINDINGS` being empty.

The app half covers:

- switching relabeling the keymap;
- a typed letter opening search with it, and no type-ahead under AFX;
- the choice surviving a restart, and `KEY_PRESET` winning over the menu;
- the first launch: nothing chosen → asked with no Cancel, quit unanswered → asked again;
- the log line on switching with overriding entries.

It isolates itself from the developer's `~/.xefm/config.py` by emptying the
shared config's `_KEY_BINDINGS_BASE`. Tests elsewhere that want "the shipped
keymap" read `keymap_afx.bindings()`, not `_config.Config.KEY_BINDINGS`.

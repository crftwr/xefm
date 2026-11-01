# Editing XeFM's configuration

Read `SKILL.md` first: the ground rules there (never launch XeFM, finish with
a reload or restart) apply here too.

## 1. The file

The configuration is **`~/.xefm/config.py`**, an ordinary Python file that
XeFM executes. It must define `class Config:`, and every setting is an
UPPER_CASE attribute of that class:

```python
from xefm.external_programs import xefm_tool, xefm_python
from xefm.backend_detector import is_desktop_mode

class Config:
    TEXT_EDITOR = 'code' if is_desktop_mode() else 'vim'
    KEY_BINDINGS = {
        'reload_config': ['F12'],
    }
```

- **A setting the file leaves out keeps XeFM's default.** XeFM fills every
  missing attribute from its template, so adding one setting means adding one
  attribute — never pasting in the rest.
- **Adding a table the file does not have replaces the default whole.** A
  `FILE_ASSOCIATIONS` (or `PROGRAMS`, `FAVORITES`, `THEMES`…) written into a
  file that had none is not merged with XeFM's: its default rules are gone.
  To extend a default, copy its entries from `references/config-template.md`
  into the new attribute and add yours after them.
- **Names, defaults and shapes come from the skill**, never from the user's
  file: `references/config-template.md` is XeFM's template (every setting,
  its default, what it does) and `references/actions.md` every action with
  its default keys, both generated from the XeFM this skill shipped with. The
  user's `config.py` may carry the template's comments, but it may also have
  none — users delete them — or carry ones from an older XeFM. Do not depend
  on them; where one disagrees with the skill, trust the skill and mention the
  stale comment to the user rather than editing it.
- XeFM creates the file on first launch. If it does not exist, ask the user to
  start XeFM once rather than writing one from scratch.
- On Windows the file is `C:\Users\<name>\.xefm\config.py`.

## 2. Rules for editing

- **Change only what was asked.** Edit the one attribute (or the one entry in
  a table) the request is about. Keep every other line, the user's comments,
  and the order of the file as it is.
- **Never regenerate the file** from the template, and never "tidy" it. It is
  the user's file; it may hold settings and functions you do not recognize.
- **Edit an attribute that is already there** rather than adding a second
  one: in a class body the later assignment silently wins. Search for the name
  first. If it is not in the file, add it inside `class Config:` (indented
  like the other attributes) — after its neighbours if the file is in the
  template's order, else at the end of the class.
- If the file happens to hold what you need as a commented-out example
  (`# 'reload_config': ['F12'],`), uncommenting that line is the smallest
  edit. Put a new entry in a list or dict after its last real entry, before
  any commented-out examples.
- **`is_desktop_mode()`** (true in the desktop app, false in the terminal) is
  imported at the top of the file: `from xefm.backend_detector import
  is_desktop_mode`. A file without that line needs it added before a
  conditional can use it.
- **Keep the user's conditionals.** `TEXT_EDITOR = 'code' if is_desktop_mode()
  else 'vim'` says the desktop app and the terminal want different editors.
  When the user asks for a different editor, change the branch they mean, or
  ask which one.
- **Copy the file first** for anything beyond a one-line change
  (`config.py.bak` beside it), and say so. A broken file costs the user their
  whole configuration until it is fixed (see *Checking an edit*).
- No secrets. `NETWORK_SERVERS` has no password field on purpose; passwords go
  in the system keychain from XeFM's own connection dialog.

## 3. The main tables

### Keys: `KEY_PRESET` and `KEY_BINDINGS`

Every key comes from a **keymap preset**: `'afx'` (single letters: `C` copy,
`M` move, `K` delete …), `'orthodox'` (function keys: `F5` copy, `F6` move,
`F8` delete; letters start an incremental search), `'native'` (Finder's keys
on macOS, Explorer's elsewhere, with `F5` / `F6` for the other pane; letters
search) or `'vim'` (Vim-style keys: `hjkl`, `gg`, `yy` / `dd` / `p`, `/`, `ZZ`;
two-key commands are key sequences). The user picks one at first launch or in
**Tools ▸ Advanced ▸ Keymap…**; `KEY_PRESET = 'afx'`, `'orthodox'`, `'native'`
or `'vim'` in `config.py` overrides that choice. `None` (the default) leaves it to the menu.

`KEY_BINDINGS` holds **only the user's changes** to the preset. An entry
replaces that action's keys under every preset; an action not listed keeps the
preset's keys.

```python
KEY_BINDINGS = {
    'reload_config': ['F12'],                    # action -> list of keys
    'quit': [],                                  # an empty list unbinds it
    'delete_permanently': {'keys': ['Shift-DELETE'], 'selection': 'required'},
    'text_viewer.page_down': ['SPACE'],          # inside one viewer only
}
```

- Keys: a character (`'Q'`, `'?'` — a capital letter is *not* Shift), a name,
  or a chord of modifiers and a key: `'Ctrl-T'`, `'Shift-F'`, `'Cmd-ENTER'`.
  Names and modifiers are case-insensitive. **These are all the names**; a
  name XeFM does not know never fires and is only reported in XeFM's log —
  `xefm keys` (§4) reports it before that:
  - `'UP'` `'DOWN'` `'LEFT'` `'RIGHT'` `'HOME'` `'END'` `'PAGE_UP'` (`'PAGEUP'`)
    `'PAGE_DOWN'` (`'PAGEDOWN'`)
  - `'ENTER'` (`'RETURN'`) `'ESCAPE'` (`'ESC'`) `'TAB'` `'BACKSPACE'`
    `'DELETE'` (`'DEL'`) `'INSERT'` `'SPACE'`, `'F1'`…`'F12'`
  - `'APPS'` — the PC keyboard's Menu key; `'ALT'` alone — a bare Alt tap
    (Windows terminal only)
  - punctuation, by its glyph or by name: `'MINUS'` `'EQUAL'` (`'EQUALS'`)
    `'LEFT_BRACKET'` `'RIGHT_BRACKET'` `'BACKSLASH'` `'SEMICOLON'` `'QUOTE'`
    (`'APOSTROPHE'`) `'COMMA'` `'PERIOD'` (`'DOT'`) `'SLASH'` `'GRAVE'`
    (`'BACKTICK'`, `'BACKQUOTE'`). `Shift-` on one is the character it makes
    on a US layout (`'Shift-EQUAL'` is `'+'`).
- Modifiers, each spelling the same binding: `Shift`; `Ctrl` or `Control`;
  `Alt` or `Option`; `Cmd` or `Command` (macOS). `'Cmd-ENTER'` and
  `'Command-ENTER'` are one key, so match the spelling the user's file
  already uses. Order does not matter (`'Cmd-Shift-X'` = `'Shift-Cmd-X'`).
  A sequence is keys separated by spaces: `'g g'`.
- `'selection'`: `'any'` (default), `'required'` (only with files selected),
  `'none'` (only without).
- **Action names are in `references/actions.md`**, with each preset's
  default keys. Use those names exactly; do not guess one from a menu label,
  and do not write an action of your own to reach a built-in one. Its last
  table lists **old names** XeFM still accepts: a user's file may bind
  `drives_dialog`, which is `drives` today — edit that entry, do not add a
  second one under the new name.
- **Actions that are not XeFM's own** are not in that table:
  - the user's own, defined in this file — the keys of its `ACTIONS`;
  - an installed extension's — the keys of `[contributes.actions]` in
    `~/.xefm/extensions/<id>/xefm-extension.toml` (`xefm ext list` names the
    installed packages). They are usually prefixed with the extension's short
    name (`hello.greet`).

  Bind those names in `KEY_BINDINGS` exactly like built-in ones. A name in
  none of these places does not exist; ask rather than guess.
- **A key the user wants may already be taken.** Look it up in
  `references/actions.md`, in the column of the preset in force, and in the
  user's own `KEY_BINDINGS`. If another action has it, say which; if the user
  wants the key moved, give that action its other keys (or `[]`) explicitly,
  so nothing is left bound twice. A key bound to two actions is not an
  error — one of them silently never fires. A `KEY_BINDINGS` entry for a name
  XeFM does not know is ignored, also silently: check every name against
  `references/actions.md`.
- Keys inside a viewer, dialog or the search bar (`search.toggle_case`) are a
  separate context: the same key there does not collide with a file-list
  action.
- **Pick keys every place the user runs XeFM can send.** A terminal cannot
  deliver every chord a desktop window can:
  - `Cmd-…`: no terminal sends Command at all.
  - `Ctrl-Shift-<letter>`: a terminal on macOS or Linux sends it as plain
    `Ctrl-<letter>`, so it never fires there (and fires `Ctrl-<letter>`'s
    action instead). The Windows console does tell them apart.
  - `Shift-<character>` (`Shift-SPACE`), `Ctrl-ENTER`, `Alt-ENTER`: arrive as
    the plain key, or not at all.
  - Function keys and modified *named* keys (`F2`, `Ctrl-UP`, `Shift-DOWN`)
    reach XeFM from every backend — but the OS or the terminal can take one
    first. On a Mac keyboard the F-row sends brightness, volume and the like
    unless Fn is held, or **System Settings ▸ Keyboard ▸ Keyboard Shortcuts… ▸
    Function Keys ▸ Use F1, F2, etc. keys as standard function keys** is on; macOS itself uses some (F11 shows the
    desktop); a terminal may keep one for itself (Windows Terminal: F11 for
    full screen). When you bind a function key, tell the user which of these
    may apply on their machine.

  If the user may use the terminal version, choose such a key — or give the
  action a terminal-safe key alongside the desktop chord — and say why.
- A config from an XeFM older than the presets may hold a *full* copy of the
  old keymap in `KEY_BINDINGS`. Every entry in it overrides the preset. Do not
  delete it on your own; if the user's keys are not what the preset promises,
  point at it.


### Editor, diff tool, shell, terminal

```python
TEXT_EDITOR = ['code', '--wait']   # edit_file; a string or an argv list
TEXT_DIFF = ['code', '--diff']     # E in the diff viewers
SUBSHELL = None                    # None = $SHELL, else the platform's
TERMINAL = None                    # desktop app only: where terminal programs open
```

A string is split like a shell command line; a list is taken as argv, and is
the form to use for a Windows path with spaces or backslashes. The file paths
are appended to it.

- `TEXT_EDITOR` is the fallback: a `FILE_ASSOCIATIONS` rule with an `edit`
  command for that kind of file wins over it, and `'edit': None` means "no
  editor for this kind of file". If the user's request is about one file
  type, that is the place; if it is about every file, check no rule overrides
  it for the files they mean.
- **In the terminal XeFM waits for `TEXT_EDITOR` to exit**: that is what
  hands the editor the screen, and what makes Edit Configuration reload on
  return. **The desktop app never waits**: the editor is started in a window
  of its own and XeFM stays responsive, so a wait flag (`code --wait`,
  `subl -w`) changes nothing there — harmless, but not needed. Edit
  Configuration then asks the user to run Reload Configuration once saved,
  and Rename in Editor asks them to press Apply.
- The desktop app adds `/usr/local/bin` and `/opt/homebrew/bin` to the PATH
  it runs programs with (macOS). A program elsewhere needs its full path.

### Favorites

```python
FAVORITES = [
    {'name': 'Home', 'path': '~'},
    {'name': 'Work', 'path': '~/work'},
    {'name': 'Todo', 'path': '~/notes/todo.md'},     # a file works too
    {'name': 'Server', 'path': 'ssh://devbox/var/www'},
]
```

Append to the list; keep the user's entries and their order. A `name` is any
text (non-ASCII is fine) and need not be unique; a `path` does not have to
exist yet — nothing is checked until the user picks the row, so do not create
the directory. Favorites the
user adds inside XeFM (the **Add to Favorites** command) are kept in XeFM's own
state, not in this file — you will not find them here, and should not copy
them in. `DRIVE_LOCATIONS` (the Drives dialog's fixed rows, `None` = built-in)
and `NETWORK_SERVERS` (`{'name', 'url', 'user'}`) have the same shape.

### External programs: `PROGRAMS`

```python
PROGRAMS = [
    {'name': 'Open in VSCode', 'command': [xefm_python, xefm_tool('vscode.py')]},
    {'name': 'Disk usage', 'command': ['du', '-sh']},
    {'name': 'View with less', 'command': ['less'], 'options': {'terminal': True}},
]
```

`command` is an argv list. `options: {'terminal': True}` hands the terminal to
a full-screen program (in the desktop app it opens in `TERMINAL`). The
program gets the panes' directories and selections as `XEFM_*` environment
variables. `xefm_tool('x.py')` finds a script in `~/.xefm/tools/` first.

### File associations: `FILE_ASSOCIATIONS`

A list of rules, read top to bottom. For each action, the first rule that
matches the file name **and names that action** wins; a matching rule that
leaves an action out lets a later rule supply it.

```python
{
    'pattern': ['*.jpg', '*.png'],        # fnmatch, one or a list
    'enter': 'viewer',                    # ENTER: 'viewer', 'navigate', 'list' or None
    'open|view': ['open', '-a', 'Preview'],   # several actions, one command
    'edit': None,                         # not available
}
```

`enter` names a built-in handler, never a program. `open` (Cmd/Ctrl-Enter),
`view` (V) and `edit` take a command; `'view': None` means XeFM's own viewer.
Put a new rule above a broader one that names the same action. A rule beats
the built-in viewer: XeFM only sniffs a file when no rule names the action.

- The command gets the file paths appended, all in one launch; there is no
  placeholder.
- There is no terminal option. In the terminal XeFM hands the screen to the
  program and waits, which is what `less` or `vim` needs. In the desktop app
  the program is started detached, with no terminal — a terminal program
  there shows nothing. To make a rule terminal-only, add it conditionally:

  ```python
  FILE_ASSOCIATIONS = [
      # ... the user's rules ...
  ] + ([] if is_desktop_mode() else [
      {'pattern': '*.log', 'view': ['less']},
  ])
  ```

### Themes: `THEMES`

`THEMES` *defines* themes; it does not choose one, and there is no setting
that does. The theme in use is picked in XeFM — **View ▸ Theme** lists them
all, **View ▸ Theme ▸ Next Theme** cycles (the `toggle_color_scheme` action, which
has no key by default) — takes effect at once, and is remembered in XeFM's
own state, not in this file. So "switch to the Dracula theme" is something the
user does in XeFM: tell them how, and do not edit the file. To add or tweak a
theme (a restart applies `THEMES` changes):

```python
THEMES = {
    'Ocean': {                                  # a new theme, built on Dark+
        'accent': (38, 139, 210),               # colors are (R, G, B), 0-255
        'file_types': {'directory': (120, 200, 220)},
    },
    'Paper': {'base': 'Light+', 'file_types': {'directory': (150, 110, 0)}},
}
```

Built-ins: Dark+, Monokai, Dracula, Nord, Solarized, Gruvbox Dark, Light+,
Solarized Light. A theme with no `base` builds on the built-in of the same
name, else on Dark+. Every key a theme may set is listed in the comment
above `THEMES` in `references/config-template.md`.

### Actions: `ACTIONS` (stable API)

A short function of the user's own, bound to a key:

```python
def select_documents(ctx):                       # module level, above class Config
    """Select every Word/PDF document in the active pane."""
    n = ctx.pane.select(lambda e: e.suffix.lower() in ('.docx', '.pdf'))
    ctx.message(f"Selected {n} document(s)")

class Config:
    ACTIONS = {'select-documents': select_documents}
    KEY_BINDINGS = {'select-documents': ['Shift-Y']}
```

The function gets the same `ctx` an extension does — the API is in
`references/extensions.md`, section 3, and the same rules hold (no `print()`,
no private names, keep it quick). `EVENT_HOOKS`, `SORT_KEYS`, `FILTERS`,
`IMAGE_DECODERS`, `PATH_SCHEMES` and `LEXERS` work the same way;
`references/config-template.md` documents each. Anything longer belongs in an
extension (see `SKILL.md`).

### Everything else

Confirmations (`CONFIRM_*`), `DELETE_TO_TRASH`, `SHOW_HIDDEN_FILES`, sort
defaults, fonts (`UI_FONT_NAME`, `MONO_FONT_NAME`, `FONT_SIZE`, desktop app
only), Migemo search, caches, file monitoring: each is one attribute, named
and explained in `references/config-template.md`. Look it up there; do not
invent a name — an attribute XeFM does not know is silently ignored.

## 4. Checking an edit

What you can check:

1. **It parses.** With any Python 3 (use the full path on Windows):

   ```bash
   python3 -c "import ast, sys; ast.parse(open(sys.argv[1], encoding='utf-8').read())" ~/.xefm/config.py
   ```

   This proves the syntax only. The file imports from `xefm`, so it cannot be
   run outside XeFM.
2. **What XeFM makes of it: `xefm keys`.** It loads `config.py` and the
   installed extensions the way XeFM does — without starting it, on every OS —
   lays the keymap preset over them, and prints which key runs which action in
   each context. Give it the key or the action you bound:

   ```bash
   xefm keys F12
   ```

   ```text
   config:  /Users/me/.xefm/config.py
   keymap:  afx (chosen in XeFM), tui

   [filer]
     F12  reload_config
   ```

   An `error:` line means a binding that can never fire — a key name XeFM
   does not know, an action no context has, a malformed entry — or a
   `config.py` that does not load; the exit status is then 1. The `warning:`
   lines are the `Config warning`s XeFM would log. It uses the preset the user
   chose; `--keymap NAME` shows another, `--backend gui` the desktop app's keys
   (the OS native preset differs there). A key listed with
   `same key as …` is shared; most surfaces run the first one listed.
3. **By reading it back:** `class Config:` is still there, the attribute you
   changed appears once, its name matches `references/config-template.md`
   exactly, and the value has the shape shown there (a list where it wants a
   list, a dict entry with the keys it wants).

4. **By running it** with `xefm try` (`references/try.md`): XeFM
   loads the file in a temporary home and follows a script, for example
   pressing the key you bound:

   ```bash
   xefm try --config ~/.xefm/config.py --keys steps.json --screens out/
   ```

   Then look in `out/steps.jsonl` for an `Error loading configuration` or
   `Config warning` message, and at the screen after the key. The temporary
   home has none of the user's extensions; add `--ext` for one the edit
   depends on, or leave that part unchecked.

Tell the user what you checked and what you could not. If loading fails, XeFM
logs `Error loading configuration: …` and runs on **built-in defaults for
everything** — the user's other settings are not lost from the file, but none
of them apply until it is fixed. An out-of-range value is applied and logged
as `Config warning: …`.

## 5. Applying it

**Tools ▸ Reload Configuration** applies, without a restart: key bindings,
the keymap preset, file associations, external programs, favorites,
confirmations, the editor and diff tool, and `ACTIONS` and the other function
tables.

**A restart** is needed for: themes and their effects, fonts, the pane-split
and log-height ratios, and file-monitoring intervals.

Say which one the change needs.

# Customization

English \| [日本語](CUSTOMIZATION_FEATURE.ja.md)

> **Stable, with some parts in Preview.** The API on this page is at version
> 1 (`xefm.user_api.API_VERSION`). The stable parts keep working across XeFM
> releases. A stable API that is going away is first deprecated: it keeps
> working for at least one more minor release, XeFM logs a warning naming
> its replacement when you use it, and the release notes say so. Only then
> is it removed, with a new `API_VERSION`. Parts marked **(Preview)** may
> still change in any release.
>
> Stable: `ACTIONS`, `SORT_KEYS`, `FILTERS`, `PATH_SCHEMES` (except
> replacing a built-in scheme); the panes and entries your function is given;
> `ctx.pane` / `other` / `left` / `right`, `ctx.invoke`, `ctx.run_program`,
> `ctx.message`, `ctx.action_names`; and `xefm_tool`, `xefm_python` and
> `is_desktop_mode` for `PROGRAMS`.
>
> Preview: `EVENT_HOOKS`, `MENU_ITEMS`, `IMAGE_DECODERS`, `LEXERS`,
> `ATTRIBUTES`, `LAYOUTS`, `DEFAULT_LAYOUT`, `LAYOUT_EXTRAS`, `entry.attr`, `Cell`, the
> prompts (`ctx.input` / `choose` / `confirm`), `ctx.run_task`,
> `ctx.show_markdown`, `ctx.copy_text`, `ctx.diff`, `ctx.actions` and `pane.open_list`. A config that
> uses a Preview table gets one line in the log pane saying so, and the first
> call to a Preview function logs one line naming it.

`~/.xefm/config.py` is real Python that XeFM executes at startup, so it has
always been able to hold logic — `if sys.platform == 'win32':` blocks, computed
paths, list comprehensions. This feature takes the next step: your config can
define **functions**, bind them to keys, and run them when things happen.

Three things it lets you do:

- **Rebind any key, anywhere.** Not just the file list — the text, image, diff
  and directory-diff viewers now name every key they use, and every one of them
  can be changed.
- **Bind a key to your own function**, which reads and manipulates the panes.
- **Run your own function when something happens** — at startup, on quit, when a
  pane changes directory, when a file is opened.

Naming every key also meant correcting some names that were already there. Old
names keep working — see
[Renamed actions](KEY_BINDINGS_FEATURE.md#renamed-actions) for the list.

---

## Rebinding viewer keys

`KEY_BINDINGS` already listed most of what XeFM does. What it did not list were
the keys *inside* the viewers: `PgDn` to scroll the text viewer, `n` to jump to
the next diff block, `Tab` to switch sides in the directory diff. Those were
fixed in the code and could not be changed.

Now they are ordinary named actions. They are not listed in your `KEY_BINDINGS`
by default — they work without an entry — so add one only for a key you want to
change:

```python
KEY_BINDINGS = {
    ...
    'text_viewer.page_down': ['SPACE'],   # page with Space in the text viewer
    'text_viewer.page_up': ['B'],
    'file_diff.next_block': ['J'],
    'file_diff.prev_block': ['Shift-J'],
}
```

The name is prefixed with the viewer it belongs to. Because each surface only
ever looks at its own names, a viewer key can share a key with a file-list key
with no ambiguity — `W` toggling line wrap in the viewer and comparing panes in
the file list (as it does in AFX style) is not a conflict, and never was meant to
be. In the example above `SPACE` pages the text viewer while still doing its own
job in the file list. Which key each preset puts where is on
[Keymap Presets](KEYMAP_PRESETS_FEATURE.md#every-key-side-by-side).

An entry **replaces** the default rather than adding to it, as everywhere else
in `KEY_BINDINGS`: after that first line, PgDn no longer pages the text viewer.
List both if you want both — `['SPACE', 'PAGE_DOWN']`.

### Every viewer action

The keys they ship with are not listed here — each action declares its own in
`xefm/actions.py`, and `F1` inside a viewer shows what yours are on, which is the
only list that cannot go stale.

| Text viewer | File diff |
|---|---|
| `text_viewer.scroll_up` | `file_diff.scroll_up` |
| `text_viewer.scroll_down` | `file_diff.scroll_down` |
| `text_viewer.page_up` | `file_diff.page_up` |
| `text_viewer.page_down` | `file_diff.page_down` |
| `text_viewer.scroll_top` | `file_diff.scroll_top` |
| `text_viewer.scroll_bottom` | `file_diff.scroll_bottom` |
| `text_viewer.scroll_left` | `file_diff.scroll_left` |
| `text_viewer.scroll_right` | `file_diff.scroll_right` |
| `toggle_wrap` \* † | `file_diff.next_block` |
| `toggle_view_mode` \* † | `file_diff.prev_block` |
| `change_encoding` \* † | |

| Image viewer | Directory diff |
|---|---|
| `image_viewer.zoom_in` \* | `dir_diff.cursor_up` |
| `image_viewer.zoom_out` \* | `dir_diff.cursor_down` |
| `image_viewer.zoom_reset` \* | `dir_diff.page_up` |
| `image_viewer.next` \* | `dir_diff.page_down` |
| `image_viewer.prev` \* | `dir_diff.cursor_top` |
| `image_viewer.pan_up` \* | `dir_diff.cursor_bottom` |
| `image_viewer.pan_down` \* | `dir_diff.expand` |
| `image_viewer.pan_left` \* | `dir_diff.collapse` |
| `image_viewer.pan_right` \* | `dir_diff.activate` |
| `image_viewer.first` | `dir_diff.switch_side` |
| `image_viewer.last` | `dir_diff.next_change` |
| | `dir_diff.prev_change` |
| | `dir_diff.rescan` |
| | `dir_diff.split_left` |
| | `dir_diff.split_right` |

### The incremental search bar

The search bar (`isearch`) is a surface of its own, and its keys are named the
same way:

| Action | |
|---|---|
| `isearch.next_match` | Move to the next match |
| `isearch.prev_match` | Move to the previous match |
| `isearch.toggle_select_down` | Mark, then move to the next match |
| `isearch.toggle_select_up` | Mark, then move to the previous match (no default key) |
| `isearch.select_matches` | Mark every match (again: clear them) |
| `isearch.accept` | Stop at the current match |
| `isearch.cancel` | Cancel, restoring the cursor |

One rule applies here and nowhere else: **the key must not be one that types a
character.** Everything printable belongs to the pattern you are typing — which
is why marking a file here is `Ctrl-Space` rather than Space,
whose glyph the search reads as the separator between `report 2024` and
`report*2024*`. Bind an isearch action to `N` and it can never fire; XeFM says so
in the log pane at startup rather than leaving you to wonder. Shift is not enough
to turn a printable into a command — `Shift-Space` types a space too, so the file
list's `select_range` key does nothing here (and range selection is not one of
this surface's operations: leave the search with Enter, which keeps the cursor on
the match, and the file list's own key applies). Everything modified with Ctrl,
and every non-printable key, is free: `Ctrl-Y`, `Shift-DOWN`, `F2`, `INSERT` (on
Windows and in the terminal — macOS keyboards have no Insert key).

`isearch.select_matches` is the one default that takes a key the pattern field
would otherwise use (select-all-text). Only the Ctrl form: `Cmd-A` still selects
the text on macOS, which is where that chord is the habit.

\* These are listed as live entries in the default `KEY_BINDINGS`, so a config
generated from the template already has them. The rest work from the defaults
above with no entry at all.

† Unprefixed on purpose. These three name a *capability* rather than one
viewer's use of it, and the diff viewer — which already reads through the same
decoder — is a plausible second home for the encoding picker. Keeping the plain
name means that, if it happens, your existing binding covers both viewers with
no change: a name can live in more than one context, each with its own
behaviour, exactly as `copy_files` already does in the file list and the
directory diff.

The directory diff also understands the file-list actions it can perform on the
focused node — `copy_files`, `move_files`, `delete_files`, `view_file` and
`edit_file` — under those same names, so one rebind moves both.

### Rebinding a shared key in one place only

`quit`, `help`, `isearch` and `edit_file` mean something on every surface, which
is why rebinding `quit` changes it in the file list *and* in every viewer. To
change it in one viewer alone, prefix it with that viewer's name:

```python
KEY_BINDINGS = {
    'quit': ['Q'],            # everywhere...
    'file_diff.quit': ['X'],  # ...except in the file diff viewer
}
```

---

## Your own actions: `ACTIONS`

Define a function that takes one argument, then name it in `ACTIONS` and bind
the name in `KEY_BINDINGS`. Define the functions **above** `class Config:` —
they are ordinary module-level Python.

```python
def select_documents(ctx):
    """Select every Word/PDF document in the active pane."""
    n = ctx.pane.select(lambda e: e.suffix.lower() in ('.docx', '.pdf'))
    ctx.message(f"Selected {n} document(s)")


class Config:
    ACTIONS = {
        'select-documents': select_documents,
    }

    KEY_BINDINGS = {
        ...
        'select-documents': ['Shift-D'],
    }
```

Press Shift-D and the documents are selected. Your actions also appear in the
help dialog (`F1`), under **Your Actions**, alongside the built-in ones.

Edit the file and run `reload_config` and the new version takes effect
immediately — no restart.

### Replacing or wrapping a built-in

A name that is already a built-in action is ignored, with a warning in the log
pane, unless you say you meant it. When you do, the built-in stays reachable
through `ctx.invoke()`, so you can wrap rather than replace it:

```python
def confirm_then_quit(ctx):
    ctx.message("saving session…")
    save_session(ctx)
    ctx.invoke('quit')          # runs the *built-in* quit


class Config:
    ACTIONS = {
        'quit': {'func': confirm_then_quit, 'override': True},
    }
```

### Describing an action: the docstring

Every action of yours is in the command palette (**Tools → Command Palette…**), bound to a key or
not, so an action you run once a month needs no key at all. Its docstring is how
it is described there, split the usual Python way:

```python
def open_in_vscode(ctx):
    """Open the item under the cursor in VS Code.

    Works on directories too — VS Code opens them as a workspace.
    """
    ctx.run_program(['code', str(ctx.pane.focused.path)])
```

- The **first line** is the one-line description: the row in the Help dialog
  (F1) and the line under the palette's list.
- The **paragraphs after the blank line** are the page the palette opens when
  you press F1 on the action. Markdown works there.

Without a docstring, both show only the action's name. For a function whose
docstring you cannot write — a lambda, or one from a library — the dict form
takes a `description`, written and split exactly like a docstring. It replaces
the docstring as a whole:

```python
ACTIONS = {
    'tidy': {'func': lambda ctx: ctx.invoke('unselect_all'),
             'description': """
                 Clear the selection.

                 The same as Select ▸ Clear Selection, under a name of its own.
             """},
}
```

A one-line `description`, as configs before the command palette wrote it, is a
summary with no further page.

### What your function is given

`ctx` is the only argument. It offers:

| | |
|---|---|
| `ctx.pane` | the active pane |
| `ctx.other` | the inactive pane |
| `ctx.left`, `ctx.right` | the panes by position |
| `ctx.invoke(name)` | run another action — built-in or your own |
| `ctx.message(text)` | write one line to the log pane |
| `ctx.show_markdown(title, source)` | (Preview) show Markdown in a scrollable dialog, with a Copy button on each code block — see below |
| `ctx.copy_text(text)` | (Preview) put text on the clipboard |
| `ctx.diff(left, right)` | (Preview) compare two files as **Select → Compare Selected Files…** does, without selecting them; either may be on SSH, S3, in an archive or in a virtual folder, and `left_title=` / `right_title=` name the sides |
| `ctx.run_task(title, work, on_done=fn)` | (Preview) run slow work in the background, with a progress dialog — see below |
| `ctx.input(prompt, default, on_accept=fn)` | (Preview) ask for a line of text; `complete='path'` (or `'directory'`) adds Tab completion of paths, as Jump to Path has — relative to the active pane |
| `ctx.choose(title, items, on_result=fn)` | (Preview) pick from a list (index, or `None`); `type='filter'` for a searchable one |
| `ctx.confirm(prompt, on_result=fn)` | (Preview) yes / no |
| `ctx.run_program(command, terminal=False)` | run an external program — see below |
| `ctx.copy(items, dest, on_done=fn)` | (Preview) copy files the way **File → Copy to Other Pane** does — confirmation, conflict dialog, progress — and hear how each fared; see below |
| `ctx.move(items, dest, on_done=fn)` | (Preview) the same, moving |
| `ctx.terminal_backend_suspended()` | (Preview) a `with` block in which you run an interactive program yourself with `subprocess` — see below |
| `ctx.program_env()` | (Preview) `{'cwd': ..., 'env': ...}` for `subprocess`: what `run_program` gives its programs |
| `ctx.is_terminal_backend` | (Preview) whether XeFM is running in a terminal, so there is a terminal to hand over |
| `ctx.action_names()` | every name `invoke()` accepts |
| `ctx.actions()` | (Preview) the same actions, each with its `name`, `description`, `aliases` (names it used to have) and `keys` (bound right now, after your `KEY_BINDINGS`) |

And each pane:

| | |
|---|---|
| `pane.path` | the directory it is showing |
| `pane.name` | `'left'` or `'right'` |
| `pane.is_active` | whether the cursor is in it |
| `pane.activate()` | move the cursor into it |
| `pane.entries` | everything listed, in the pane's sort order |
| `pane.cursor` | the focused row's index (assignable; clamped) |
| `pane.focused` | the entry under the cursor, or `None` |
| `pane.selected()` | the selected entries |
| `pane.select(predicate)` | add matches to the selection; returns how many |
| `pane.unselect(predicate)` | remove matches; no predicate clears it |
| `pane.cd(path, focus_name=None)` | go somewhere |
| `pane.refresh()` | re-read the directory |
| `pane.open_list(paths, title=...)` | (Preview) open a list of paths in place of a directory — see below |

And each entry: `.name`, `.path`, `.suffix`, `.stem`, `.is_dir`, `.is_file`,
`.is_link`, `.size`, `.mtime`. `.path` is a `pathlib.Path`-alike that also
addresses files inside archives and on S3 / SFTP, so `entry.path.read_text()`
works wherever the pane does. Besides the `pathlib` methods it has
`.scheme` (`'file'`, `'s3'`, `'ssh'`, `'archive'`, …), `.is_remote()`,
`.supports(capability)` — `'write_operations'`, `'directory_rename'`,
`'file_editing'` or `'streaming_read'` — and `.target()`, the real file an
entry of a tree file stands for. Writing may raise `OSError` where the
storage is read-only, such as inside an archive.

`.size` and `.mtime` read from disk the first time you ask; the rest are free.
A predicate that only looks at names therefore costs no filesystem access at
all, which matters in a large directory.

### Showing a result (Preview)

`ctx.show_markdown` opens the dialog Help and File Details use, with your
Markdown in it. Every fenced code block gets a **Copy** button — reach it with
Tab and press Enter, or click it — and any of the text can be selected with the
mouse and copied. Put whatever the user will want to paste elsewhere in a code
block:

```python
from xefm.user_api import md_code_block, md_escape

def show_names(ctx):
    entries = ctx.pane.selected() or [ctx.pane.focused]
    names = "\n".join(e.name for e in entries if e is not None)
    ctx.show_markdown("Names",
                      f"From **{md_escape(ctx.pane.path.name)}**:\n\n"
                      + md_code_block(names))
```

`md_code_block(text, lang='')` fences `text` so that nothing in it — a name
with backticks, text that is itself Markdown — can end the block early.
`md_escape(text)` makes a file name read literally in a sentence: `a_b*.txt`
stays `a_b*.txt` rather than turning half of it italic.

To copy without showing anything, `ctx.copy_text(text)`.

### Slow work: `ctx.run_task` (Preview)

Your action runs on the UI thread, and the window waits for it. `ctx` belongs
to that thread: use it from the action and from callbacks such as `on_done`,
never from another thread. Work that takes
a while — reading whole files, a remote folder — goes to `ctx.run_task`, which
runs a function on a worker thread behind the same progress dialog a copy uses,
with **Cancel** and **Run in background**:

```python
import hashlib
from xefm.user_api import md_code_block

def sha256_selection(ctx):
    paths = [e.path for e in (ctx.pane.selected() or [ctx.pane.focused])
             if e is not None and not e.is_dir]

    def work(job):                       # on the worker thread
        lines = []
        for i, path in enumerate(paths):
            job.checkpoint()             # stops here if the user cancelled
            job.progress(i, len(paths), detail=path.name)
            digest = hashlib.sha256()
            with path.open('rb') as f:
                for block in iter(lambda: f.read(1 << 20), b''):
                    digest.update(block)
            lines.append(f"{digest.hexdigest()}  {path.name}")
        return lines

    def done(ctx, outcome):              # back on the UI thread
        if outcome.ok:
            ctx.show_markdown("SHA-256", md_code_block("\n".join(outcome.value)))
        elif outcome.status == "cancelled":
            ctx.message("SHA-256: cancelled")

    ctx.run_task("SHA-256", work, on_done=done, read_only=True)
```

- **The worker touches only `job`.** Not `ctx`, not a pane: take what it needs
  — paths, settings — before the task starts. `entry.path` works on any
  thread, and `path.open('rb')` reads a file on disk, inside an archive or on
  SSH / S3 alike.
- `job.progress(done, total, detail='')` moves the bar and shows `detail` under
  the title; before the first call the dialog shows a spinner.
  `job.item_progress(done, total)` adds a second bar for the current item, in
  bytes (`1.2 GB / 30.0 GB`), as a copy shows for a large file — call it while
  reading one file, and the next `job.progress` clears it.
  `job.checkpoint()` stops the work when the user cancels — let it pass through
  rather than catching it in an `except Exception`. `job.cancelled()` asks
  without stopping.
- `on_done(ctx, outcome)` runs once, however the work ended, with a new `ctx`.
  `outcome.status` is `'done'` (with `outcome.value`, what `work` returned),
  `'cancelled'`, or `'failed'` (with `outcome.error`; the traceback is already
  in the log). `outcome.ok` is true for `'done'`.
- `read_only=True` says the work changes nothing. Background jobs otherwise run
  one at a time, so a task started during a long background copy would wait for
  it; a read-only one runs beside it instead.

### Putting an action in a menu: `MENU_ITEMS` (Preview)

An action can sit in the **File** menu, in the **context menu** a row opens
(right-click, or the Menu key), or both:

```python
class Config:
    ACTIONS = {'sha256': sha256_selection}
    MENU_ITEMS = {
        'sha256': {'menus': ['file', 'context'], 'label': 'SHA-256…',
                   'when': 'entry'},
    }
```

`when` greys the item out unless it applies: `'entry'` needs an entry under the
cursor, `'selection'` at least one selected entry; the default is `'always'`.
Your items gather in a group of their own near the foot of each menu, in the
order written, and show the action's key when it has one. Up to three are
listed there; more go under a **Custom ▸** submenu, so the menu still fits a
terminal. A built-in action can
be named too. An entry with a mistake is skipped with a line in the log pane.

### Running an external program from a key

A `PROGRAMS` entry is launched from the **Tools → External Programs…** picker; to give a program a key
of its own, call it from an action with `ctx.run_program()`:

```python
def massren(ctx):
    ctx.run_program(['massren'], terminal=True)


class Config:
    ACTIONS = {'massren': massren}
    KEY_BINDINGS = {..., 'massren': ['Alt-R']}
```

`command` is a list, or a string that is split like a command line. It runs
the way a `PROGRAMS` entry runs — in the active pane's directory, with the same
[`XEFM_*` variables](EXTERNAL_PROGRAMS_FEATURE.md#environment-variables) in its
environment (add your own with `env={...}`, or pick a directory with `cwd=`) —
with one difference: **no file names are appended.** If the program wants the
selection, pass it yourself:

```python
def open_selection_in_vim(ctx):
    files = ctx.pane.selected() or [ctx.pane.focused]
    ctx.run_program(['vim'] + [str(e.path) for e in files if e], terminal=True)
```

- Without `terminal=True`, the program starts in the background, its output
  goes to the log pane, and XeFM carries on.
- With `terminal=True`, XeFM hands the terminal over to the program and waits
  for it — what an editor, a pager, or anything else that draws on the screen
  or reads the keyboard needs. When it exits, both panes are re-read and the
  exit code is returned. A nonzero exit waits for Enter first, so its error
  output stays readable. The desktop window has no terminal to hand over, so
  there the program opens in your [`TERMINAL`](EXTERNAL_TERMINAL_FEATURE.md)
  application instead, and XeFM does not wait for it.

Don't call `subprocess.run()` yourself for an interactive program, except
inside `ctx.terminal_backend_suspended()` (below). XeFM owns the terminal, and
a program that draws on it or reads the keyboard behind XeFM's back leaves the
screen garbled — or both of them waiting for the same key.

### Running an interactive program yourself (Preview)

`run_program` returns only the exit code. To give a program input or read what
it prints — a picker such as `fzf`, which takes its choices on stdin and prints
the one picked — run it yourself inside `ctx.terminal_backend_suspended()`.
Inside the `with` block XeFM steps aside: the screen and the keyboard belong to
the terminal, and `subprocess` works as it would in a shell.

```python
import shutil
import subprocess


def fuzzy_cd(ctx):
    fzf = shutil.which('fzf')
    if not ctx.is_terminal_backend or fzf is None:
        ctx.message('fuzzy_cd needs the terminal app and fzf')
        return
    folders = {e.name: e.path for e in ctx.pane.entries if e.is_dir}
    with ctx.terminal_backend_suspended():
        r = subprocess.run([fzf], input='\n'.join(folders), text=True,
                           stdout=subprocess.PIPE, **ctx.program_env())
    if r.returncode == 0:
        ctx.pane.cd(folders[r.stdout.strip()])
```

- When the block ends, an exception included, XeFM takes the terminal back,
  re-reads both panes and repaints.
- `ctx.program_env()` gives the program what `run_program` would: the active
  pane's directory and the [`XEFM_*` variables](EXTERNAL_PROGRAMS_FEATURE.md#environment-variables).
- Capture only the stream that carries the answer. `fzf` prints the pick on
  stdout and draws on the terminal; `dialog` and `whiptail` are the other way
  round, so capture their `stderr`.
- What `run_program` does on top is yours to do: it waits for Enter after a
  nonzero exit (a picker cancelled with Esc usually should not), and on Windows
  it finds `.cmd` programs, which `subprocess` does not — pass the path from
  `shutil.which()`, as above.
- The desktop app has no terminal to hand over, so there the block raises an
  error: check `ctx.is_terminal_backend` first.

Like everything on `ctx`, these work only on the UI thread, where your action
runs — not inside `ctx.run_task`'s work or a thread of your own.

### Copying and moving files (Preview)

`ctx.copy(items, dest)` and `ctx.move(items, dest)` run the same operation as
**File → Copy to Other Pane** and **File → Move to Other Pane**: the confirmation, the conflict dialog when
a name is taken, the progress dialog with **Cancel** and **Run in background**.
You choose the items and the destination:

```python
def backup_selection(ctx):
    def done(ctx, outcome):
        if outcome.status == 'done':
            failed = [r for r in outcome.value if r.status == 'failed']
            ctx.message(f'Backed up {len(outcome.value) - len(failed)} item(s)')

    ctx.copy(ctx.pane.selected(), '/Volumes/Backup/inbox', on_done=done)
```

- `items` takes what `ctx.pane.selected()` returns, paths, or absolute path
  strings. Nothing falls back to the item under the cursor: pass
  `[ctx.pane.focused]` yourself if that is what you want.
- `dest` is a folder, created if it is missing. It can be on SSH or S3, but
  not inside an archive, and an item cannot be copied into its own folder —
  both are errors at once.
- The call returns at once. `on_done(ctx, outcome)` runs when the operation is
  over — after a wait in the job queue or in the background, too — with a
  new `ctx`:
  - `outcome.status` is `'done'`, `'cancelled'` (at the confirmation, in the
    conflict dialog or during the run) or `'failed'` (the operation broke;
    `outcome.error` says why).
  - `outcome.value` lists one result per item, in the order given:
    `r.source`, `r.dest`, `r.status` (`'done'`, `'skipped'` in the conflict
    dialog, or `'failed'`) and `r.errors`, the `(name, message)` pairs for what
    went wrong under it. A folder whose files mostly copied is `'done'`, with
    the ones that did not in `r.errors`.

### Opening your own list of files (Preview)

`pane.open_list()` puts any list of paths in a pane, the way a search's results
land there: every file operation works on the rows, and `go_parent` returns to
the directory. It is how a search of your own — or any tool that prints paths —
gets its answer into XeFM:

```python
import subprocess


def modified_in_git(ctx):
    out = subprocess.run(['git', 'ls-files', '--modified'],
                         cwd=str(ctx.pane.path), capture_output=True,
                         text=True).stdout
    ctx.pane.open_list(out.splitlines(), title='git: modified')


class Config:
    ACTIONS = {'modified_in_git': modified_in_git}
```

Paths may be strings, `Path` objects or entries, absolute or relative to
`pane.path`, and may be `ssh://…` or `s3://…` URIs — one list can mix them.
Which of them
exist is checked on a worker thread; the ones that don't are left out and
counted in the log pane, and if none do, the pane stays as it was. Rows are
named relative to the deepest directory they all share. The
[file list feature](FILE_LIST_IMPORT_FEATURE.md) describes what the pane then
does.

Producing the list is your code's work, and it runs on the UI thread like any
action: a command that takes seconds freezes the window for those seconds.

---

## Reacting to events: `EVENT_HOOKS` (Preview)

```python
def log_visit(ctx, event):
    with open(Path.home() / '.xefm' / 'visited.log', 'a') as f:
        f.write(f"{event.new_path}\n")


def open_psd_in_gimp(ctx, event):
    if event.path.suffix.lower() != '.psd':
        return False
    subprocess.Popen(['gimp', str(event.path)])
    return True          # claimed — XeFM does nothing further


class Config:
    EVENT_HOOKS = {
        'directory_changed': [log_visit],
        'file_open': [open_psd_in_gimp],
    }
```

Every hook is `fn(ctx, event)`. `event.name` is the event's name, and what
happened is in the event's other attributes:

| Event | `event` carries | When |
|---|---|---|
| `startup` | — | once the app is up and the panes are listed |
| `quit` | — | before XeFM shuts down, panes still live |
| `directory_changed` | `pane`, `old_path`, `new_path` | a pane moves to a different directory |
| `file_open` | `path` | Enter on a file, before XeFM decides what to do with it; return `True` to claim it |

Each event maps to a list, run in order. A bare function is accepted where you
have only one.

The arguments never change: when an event has more to say in a later version,
it says it as a new attribute, and a hook that does not read it is unaffected.
(Hooks used to take the facts as separate arguments — `fn(ctx, pane,
old_path, new_path)`. Such a hook is now left out at load with a line in the
log pane naming it.)

`file_open` is how you route a file type somewhere of your own without touching
`FILE_ASSOCIATIONS`. It fires for the **open** action (Enter) — not for
directories, since entering one is navigation rather than opening, and not for
`view_file`, `open_with_os` or the viewers, which are explicit requests for
a particular way of opening something.

`directory_changed` fires on an actual change of directory. A refresh, a
re-sort, a reload after a file operation and the filesystem monitor's own
reloads all leave the pane where it is and stay quiet.

---

## Your own sort order: `SORT_KEYS`

XeFM orders names by their character codes, which is not how Explorer or Finder
order a directory: they put symbols and digits in a different place and sort
kanji by the system's own rules. Rather than pick one of those, XeFM lets you
write the order you want.

A sort key is a function that takes one entry and returns something sortable.
XeFM sorts by whatever comes back:

```python
SORT_KEYS = {
    "biggest": {"label": "Size, then name", "key": lambda e: (e.size, e.name)},
}
```

That adds a **Size, then name** row to the sort dialog (`sort`) and to the
**View → Sort By** menu, alongside the four built-in ones.

### What you get, and what you return

Your function is handed one entry, with `name`, `path`, `is_dir`, `is_link`,
`size` and `mtime`. Reading `size` or `mtime` is free — XeFM already collected
them for the listing, so your key costs nothing extra even in a huge directory on
a network drive.

`name` is the name **as the pane shows it**, which is what you want to sort by:
accented and Japanese characters come to you written one way whatever way the
disk happens to store them, and on a search-results pane it is the whole path
under the folder you searched, the same text the row displays. Use `path` when
you need to reach the file itself.

Return anything that can be compared: a string, a number, or a **tuple** for a
multi-level order — tuples are compared item by item, so `(e.size, e.name)` means
"by size, and by name within the same size". Whatever you return has to be
comparable with what you return for every *other* entry: if one entry gives a
number where another gives text, the sort cannot be done.

Two things you do **not** need to handle: directories always come first, and
ascending/descending is applied for you. Your key only decides the order inside
one group.

### Replacing a built-in

Naming one of the four built-in sorts — `filename`, `extension`, `size`,
`timestamp`, which are the dialog's own rows in lower case — replaces it. That
needs `"override": True`, so a typo cannot quietly change what Filename means:

```python
import locale, re
locale.setlocale(locale.LC_COLLATE, "")     # your system's own ordering

def by_system_order(entry):
    # digit runs as numbers, everything else through the system's ordering
    parts = re.split(r"(\d+)", entry.name)
    return [int(p) if i % 2 else locale.strxfrm(p) for i, p in enumerate(parts)]

SORT_KEYS = {"filename": {"key": by_system_order, "override": True}}
```

A replaced sort keeps its row and its label unless you give it new ones.

### The rest of the entry

| | |
|---|---|
| `label` | the row text in the dialog and the menu (defaults to the name you gave it) |
| `explain` | the example line the dialog shows under the order — say what the order looks like |
| `hotkey` | a letter that applies the sort directly in the dialog. A new row gets its label's initial when no other row has claimed it, and otherwise none — the arrow keys always work |

### If it goes wrong

A key that fails, or returns things that cannot be compared with each other,
loses the whole sort — the pane falls back to ordering by filename and says so
once in the log pane. It never fails the listing, and it never floods the log
with one message per file.

Your key may run on a background thread, so it must not do anything that expects
to be on the main one. Keep it to arithmetic and string handling over the entry
you were given.

---

## Your own filters: `FILTERS`

The pane filter (**View → Filter…**) takes wildcard patterns — one, or several separated by
spaces (`*.jpg *.png`) — which can only ask about a name. "The images", "anything I touched today", "everything over 100 MB"
are questions about the *file*, and no pattern spells them. So the filter is
yours to write too.

Each entry becomes a fixed row in the Filter dialog, straight under **clear
filter** and above the patterns you have typed there before — so a filter you
defined is always in the same place, rather than ageing down a history it was
never part of.

The simple kind is patterns, which is the case you were already writing by hand:

```python
FILTERS = {
    "images": ["*.jpg", "*.jpeg", "*.png", "*.gif"],    # any one of them matches
}
```

The other kind is a function. It takes one entry and returns whether to show it:

```python
import time

FILTERS = {
    "today": {"label": "Modified today",
              "match": lambda e: e.mtime >= time.time() - 24 * 3600},
    "big": {"label": "Over 100 MB", "match": lambda e: e.size > 100 << 20},
    "no-mates": {"label": "Files with no .txt beside them",
                 "match": lambda e: not e.path.with_suffix(".txt").exists()},
}
```

`label` is the row text and defaults to the name you gave it.

### What you get

The same entry a sort key is handed: `name`, `path`, `suffix`, `stem`, `is_dir`,
`is_file`, `is_link`, `size` and `mtime`. Reading `size` or `mtime` is free —
XeFM collected them for the listing already — so a filter over a huge directory
on a network drive costs nothing extra. `name` is the name **as the pane shows
it**; use `path` when you need to reach the file itself.

**Directories are always shown**, exactly as they are under a typed pattern: a
filter that hid them would take away the folder you were about to open. Your
function therefore only decides which *files* are visible — and "directories
only" is written `"match": lambda e: False`.

### Where the name shows up

A filter is remembered by its name, so the status bar reads `Filter: Images`
rather than the pattern behind it, and a content search (**View → Search Content…**) started while the
filter is on narrows to exactly the files the pane is showing — your `match`
function included. A name may not contain `*`, `?` or `[`: XeFM remembers a *typed* filter as the pattern itself, and one
that could be read as both would be impossible to tell apart. Put the wildcards
in `pattern` and give the filter a plain name.

Names you define never enter the filter prompt's history either — they already have
a row, and recording them would list them twice.

### If it goes wrong

A filter that fails loses the filter, not the listing: the pane shows everything
and says so once in the log pane. That direction is deliberate — a filter that
quietly hides half a directory is how a file ends up inside an operation nobody
could see it join.

Like a sort key, `match` may run on a background thread, so keep it to
arithmetic, strings and quick filesystem questions.

---

## What the file list shows: `ATTRIBUTES`, `LAYOUTS` and `LAYOUT_EXTRAS` (Preview)

`ATTRIBUTES` adds values XeFM can know about each entry — a Git status, a line
count — computed by your functions in the background. `LAYOUTS` decides how
rows are presented: which of the usual columns, in what order, written how.
`LAYOUT_EXTRAS` adds what a folder holds on top of that — marks beside a column's
text, or columns of their own — each showing where it applies and switched per
tab. They have a page of their own:
[File List Layouts](FILE_LIST_LAYOUTS_FEATURE.md).

Any of your functions can read a value XeFM already has with
`entry.attr('git')`. It never computes one and never waits — it is `None`
until the value is there — so it is as cheap in an action as in a sort key.

## Your own picture formats: `IMAGE_DECODERS` (Preview)

The image viewer already reads more than XeFM ships a decoder for, because it
asks your machine: on macOS the system decoder handles HEIC, JPEG XL and camera
RAW; on Windows, whichever imaging codecs are installed; in a terminal, Pillow
and any Pillow plugin you added. A `pillow-heif` line in
`~/.xefm/requirements.txt` and a sync ([Extra Python
Libraries](PYTHON_PACKAGES_FEATURE.md)) is the whole of adding HEIC anywhere it
is not already there.

What is left is the formats only a library XeFM does not ship can read. Write a
function from the file's bytes to a picture, and name the suffix:

```python
import io

def open_svg(data):
    import cairosvg                   # pip install cairosvg
    from PIL import Image
    return Image.open(io.BytesIO(cairosvg.svg2png(bytestring=data)))

class Config:
    IMAGE_DECODERS = {'.svg': open_svg}
```

### What you get, and what you return

Your function is handed the file's **bytes** — not a path — so one decoder
covers a picture on disk, inside a zip, and on an S3 bucket alike, with nothing
copied to a temporary file. Return a `PIL.Image`, or `None` for "I cannot read
this one". (A `puikit.image.RasterImage` is also accepted, if you already have
raw pixels and would rather not build a `PIL.Image` for XeFM to take apart
again.)

### Registering is also claiming

XeFM offers the image viewer only for formats something on the machine can
actually decode — so a file that opens in it always shows a picture, never a
"cannot show this" card. Registering a suffix adds it to that set, which is what
makes `Enter` on a `.svg` open the picture rather than the text.

Naming a suffix XeFM already reads **replaces** its decoder with yours. That is
the only way to change how a format is read, so no extra `override` flag is
asked for — writing the entry is the statement.

### If it goes wrong

A decoder that fails costs that picture and nothing else: the viewer shows the
reason on its metadata card and the log pane gets the traceback. Failing to a
card is the right direction here — unlike a filter, a picture that cannot be
decoded has no honest stand-in.

Like a sort key, a decoder may run on a background thread, so it must not touch
the UI. It is also the slowest thing in this document: a RAW decode takes
seconds.

More, including the format table per platform, in
[`doc/IMAGE_VIEWER_FEATURE.md`](IMAGE_VIEWER_FEATURE.md).

---

## Your own syntax highlighting: `LEXERS` (Preview)

The text viewer colors a file with [Pygments](https://pygments.org/), which
knows hundreds of languages and picks one from the file name. `LEXERS` is for
the files it gets wrong: a suffix it does not know, or one it gives to a
different language.

```python
from autocad_lexers import DclLexer       # ~/.xefm/extensions/autocad_lexers.py

class Config:
    LEXERS = {
        '*.dcl': DclLexer,      # your own lexer
        '*.mnl': 'newlisp',     # a lexer Pygments already has, for another suffix
    }
```

### The key: which files

A file-name pattern, as Pygments writes them: `'*.dcl'`, `'Jenkinsfile'`,
`'*.conf.in'`. A bare suffix (`'.mnl'`) means the same as `'*.mnl'`. Matching
ignores case, so `DIALOG.DCL` is a `*.dcl` file. An exact name wins over a
wildcard; between two wildcards that both match, the later entry wins.

### The value: which lexer

**A name** — any lexer Pygments has. `pygmentize -L lexers` lists them; each
line's names before the colon are the ones you can use. This is all it takes to
color another suffix as a language Pygments already reads.

**A class** — a lexer of your own. It is an ordinary Pygments lexer, written the
way [Pygments' guide](https://pygments.org/docs/lexerdevelopment/) describes,
with nothing from XeFM in it:

```python
# ~/.xefm/extensions/autocad_lexers.py
from pygments.lexer import RegexLexer
from pygments.token import Comment, Keyword, Text

class DclLexer(RegexLexer):
    name = 'DCL'
    aliases = ['dcl']
    tokens = {
        'root': [
            (r'//.*?$', Comment.Single),
            (r'\w+', Keyword),
            (r'\s+', Text),
            (r'.', Text),
        ],
    }
```

Keep it in [`~/.xefm/extensions/`](#your-own-modules-xefmextensions) so a config
reload picks up your edits. Because it is plain Pygments, asking an AI assistant
for "a Pygments lexer for <language>" gets you something that drops straight in.

The class's `filenames` attribute, if it has one, is **not** used — the key in
`LEXERS` alone decides which files it colors, so `config.py` always says the
whole of it. Its `aliases` are: once the class is in `LEXERS`, its name can be a
value too (`'*.dclx': 'dcl'`).

### Winning over Pygments

An entry is consulted before Pygments' own choice. Pygments gives `*.dcl` to the
Clean language, for instance; the entry above is what makes it AutoCAD DCL. A
lexer you installed as a Pygments plugin package needs no entry at all — Pygments
already finds it.

### If it goes wrong

An entry naming a lexer that does not exist, or a value that is not a lexer, is
skipped with a line in the log pane; the rest still load. A lexer whose output
does not reproduce the file shows that file uncolored rather than misaligned.
Without Pygments installed nothing is colored, and `LEXERS` says so once in the
log pane.

---

## Your own places: `PATH_SCHEMES`

A config can add a browsable location that is not a directory — the Windows
registry, a bookmark database, a device list, anything you can present as
folders and files. Write one class, name it, and `reg://` is somewhere a pane
can open, `jump_to_path` can jump to, and `FAVORITES` can hold.

```python
import io
from xefm.path_base import ReadOnlyPathImpl, UriStatResult

class NotesPathImpl(ReadOnlyPathImpl):
    def exists(self):  ...
    def is_dir(self):  ...
    def iterdir(self): ...      # yield self.child(name)
    def stat(self):    ...      # return UriStatResult(size=…, mtime=…, is_dir=…)
    def open(self, mode='r', buffering=-1, encoding=None,
             errors=None, newline=None): ...

class Config:
    PATH_SCHEMES = {'notes': NotesPathImpl}
```

Five methods is the whole requirement — path arithmetic, parents, names,
globbing and refusing writes come with the base class. Full walkthrough,
including a registry browser and which overrides are stable, in
[`doc/VIRTUAL_FOLDERS_FEATURE.md`](VIRTUAL_FOLDERS_FEATURE.md).

---

## Your own modules: `~/.xefm/extensions/`

`~/.xefm/extensions/` is on Python's import path, so anything the sections
above describe — a `PATH_SCHEMES` class, an archive format, a set of actions —
can live in its own file and be imported from `config.py`:

```
~/.xefm/
├── config.py
└── extensions/
    ├── box.py              # import box
    └── mail/               # import mail.eml_archive
        ├── __init__.py
        └── eml_archive.py
```

```python
import box

class Config:
    PATH_SCHEMES = {'box': box.BoxPathImpl}
```

XeFM creates the directory at startup if it is missing.

**Reloading the config re-imports them.** Edit a module, run **Tools ▸ Reload
Configuration**, and the edited code is what runs — no restart.

**Python's own modules win a name clash.** The directory is added to the *end*
of the import path, so an `email.py` or `queue.py` here cannot break the
standard library for the rest of XeFM — but it cannot be imported either.
Rename it.

**Only `extensions/` is on the path.** `~/.xefm/` itself is not (its
`config.py` would be importable as `config`, a name too common to claim), and
neither is `~/.xefm/tools/`, which holds [external programs](EXTERNAL_PROGRAMS_FEATURE.md)
XeFM runs as separate processes.

**Turning one into a package.** Give a directory here an
`xefm-extension.toml` and it becomes an [extension package](EXTENSIONS_FEATURE.md):
XeFM wires its actions, hooks and themes in for you, without any lines in
`config.py`, and it can be shared and installed with `xefm ext install`.

**Keeping them elsewhere.** If you keep your extensions in their own project
directory — under version control, say — add it to the path yourself at the top
of `config.py`:

```python
import sys
sys.path.append('/Users/me/src/xefm-extensions')
```

---

## Things to know

**Your code runs on the UI thread, and XeFM waits for it.** A slow action
freezes the window until it returns. Keep actions quick: put slow work in
`ctx.run_task()`, and launch external programs with `ctx.run_program()`.

**Prompts do not block.** XeFM never stops for a dialog, so `ctx.input`,
`ctx.choose` and `ctx.confirm` return immediately and deliver their answer to a
callback. Put the rest of the action inside it:

```python
def rename_to_lowercase(ctx):
    entry = ctx.pane.focused
    if entry is None:
        return

    def go(ok):
        if ok:
            entry.path.rename(entry.path.with_name(entry.name.lower()))
            ctx.pane.refresh()

    ctx.confirm(f"Rename {entry.name} to lowercase?", on_result=go)
```

**A long list wants the searchable picker.** `ctx.choose` opens a compact box
where typing jumps the selection and a second of quiet forgets what you typed —
right for a handful of alternatives, wrong for a list you have to search. Pass
`type='filter'` and you get the dialog the built-in Favorites and History lists
use instead: a filter field over a scrolling list, anchored over the active
pane, taking the same query the file pane's incremental search takes —
space-separated tokens, wildcards, and Migemo, so typing romaji finds Japanese
labels — and holding it until you erase it.

```python
BOOKMARKS = [("work", "/Users/me/src"), ("写真", "/Users/me/Pictures")]

def go_to_bookmark(ctx):
    def jump(index):
        if index is not None:
            ctx.pane.cd(BOOKMARKS[index][1])

    ctx.choose("Bookmarks", [f"{n}  —  {p}" for n, p in BOOKMARKS],
               type="filter", on_result=jump)
```

`pane.cd()` and `pane.refresh()` are asynchronous for the same reason — the
directory is read on a worker thread, so `pane.entries` is briefly empty right
after you call them. Read the new listing from a later action or from a
`directory_changed` hook, not from the next line.

**A mistake costs you one log line.** An exception inside your action or hook is
caught, logged with its traceback, and dropped; XeFM keeps running. A malformed
`ACTIONS` or `EVENT_HOOKS` entry is a warning that skips that one entry — the
rest of your config still loads.

**One config, both platforms.** Nothing in this API mentions a widget or a
backend, so the same config behaves identically in the terminal and in the
desktop window.

**Not in this version:** functions bound inside a *viewer* (viewer keys are
rebindable, but the function you bind must be a file-list action), custom
viewers and renderers, filter predicates as functions, and any access to the
widget tree. All are additive later.

---

## See also

- [`doc/KEY_BINDINGS_FEATURE.md`](KEY_BINDINGS_FEATURE.md) — key expression
  syntax, modifiers, selection requirements
- [`doc/CONFIGURATION_FEATURE.md`](CONFIGURATION_FEATURE.md) — everything else in
  `config.py`
- [`doc/EXTERNAL_PROGRAMS_FEATURE.md`](EXTERNAL_PROGRAMS_FEATURE.md) — running
  external programs, the other way to extend XeFM
- [`doc/VIRTUAL_FOLDERS_FEATURE.md`](VIRTUAL_FOLDERS_FEATURE.md) — `PATH_SCHEMES`
  in full, with a worked registry browser
- [`doc/TEXT_VIEWER_FEATURE.md`](TEXT_VIEWER_FEATURE.md) — where `LEXERS` colors
- [`doc/dev/CUSTOMIZATION_API_IMPLEMENTATION.md`](dev/CUSTOMIZATION_API_IMPLEMENTATION.md)
  — how it is built

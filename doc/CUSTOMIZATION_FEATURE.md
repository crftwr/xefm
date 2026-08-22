# Customization — Preview

> **Preview.** Everything on this page is subject to change. The objects your
> functions receive and the shape of the `ACTIONS` and `EVENT_HOOKS` variables
> may change in any release until `xefm.user_api.API_VERSION` reaches `1` (it is
> `0` today). XeFM writes one line to the log pane saying so whenever a config
> uses them. Nothing else in `config.py` is affected.

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
the file list is not a conflict, and never was meant to be. In the example above
`SPACE` pages the text viewer while still toggling selection in the file list.

An entry **replaces** the default rather than adding to it, as everywhere else
in `KEY_BINDINGS`: after that first line, PgDn no longer pages the text viewer.
List both if you want both — `['SPACE', 'PAGE_DOWN']`.

### Every viewer action and its default

| Text viewer | | File diff | |
|---|---|---|---|
| `text_viewer.scroll_up` | ↑ | `file_diff.scroll_up` | ↑ |
| `text_viewer.scroll_down` | ↓ | `file_diff.scroll_down` | ↓ |
| `text_viewer.page_up` | PgUp | `file_diff.page_up` | PgUp |
| `text_viewer.page_down` | PgDn | `file_diff.page_down` | PgDn |
| `text_viewer.scroll_top` | Home | `file_diff.scroll_top` | Home |
| `text_viewer.scroll_bottom` | End | `file_diff.scroll_bottom` | End |
| `text_viewer.scroll_left` | ← | `file_diff.scroll_left` | ← |
| `text_viewer.scroll_right` | → | `file_diff.scroll_right` | → |
| `text_viewer.toggle_wrap` \* | W | `file_diff.next_block` | n |
| `text_viewer.toggle_view_mode` \* | M | `file_diff.prev_block` | Shift-N |
| `text_viewer.change_encoding` \* | Shift-E | | |

| Image viewer | | Directory diff | |
|---|---|---|---|
| `image_viewer.zoom_in` \* | + = | `dir_diff.cursor_up` | ↑ |
| `image_viewer.zoom_out` \* | - _ | `dir_diff.cursor_down` | ↓ |
| `image_viewer.zoom_reset` \* | 0 | `dir_diff.page_up` | PgUp |
| `image_viewer.next` \* | ↓ | `dir_diff.page_down` | PgDn |
| `image_viewer.prev` \* | ↑ | `dir_diff.cursor_top` | Home |
| `image_viewer.pan_up` \* | Shift-↑ | `dir_diff.cursor_bottom` | End |
| `image_viewer.pan_down` \* | Shift-↓ | `dir_diff.expand` | → |
| `image_viewer.pan_left` \* | Shift-← | `dir_diff.collapse` | ← |
| `image_viewer.pan_right` \* | Shift-→ | `dir_diff.activate` | Enter |
| `image_viewer.first` | Home | `dir_diff.switch_side` | Tab |
| `image_viewer.last` | End | `dir_diff.next_change` | n |
| | | `dir_diff.prev_change` | Shift-N |
| | | `dir_diff.rescan` | r |
| | | `dir_diff.split_left` | [ |
| | | `dir_diff.split_right` | ] |

\* These are listed as live entries in the default `KEY_BINDINGS`, so a config
generated from the template already has them. The rest work from the defaults
above with no entry at all.

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
help dialog (`?`), under **Your Actions**, alongside the built-in ones.

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

The dict form also takes `description` (what the help dialog shows).

### What your function is given

`ctx` is the only argument. It offers:

| | |
|---|---|
| `ctx.pane` | the active pane |
| `ctx.other` | the inactive pane |
| `ctx.left`, `ctx.right` | the panes by position |
| `ctx.invoke(name)` | run another action — built-in or your own |
| `ctx.message(text)` | write one line to the log pane |
| `ctx.input(prompt, default, on_accept=fn)` | ask for a line of text |
| `ctx.choose(title, items, on_result=fn)` | pick from a list (index, or `None`) |
| `ctx.confirm(prompt, on_result=fn)` | yes / no |
| `ctx.action_names()` | every name `invoke()` accepts |

And each pane:

| | |
|---|---|
| `pane.path` | the directory it is showing |
| `pane.name` | `'left'` or `'right'` |
| `pane.is_active` | whether the cursor is in it |
| `pane.entries` | everything listed, in the pane's sort order |
| `pane.cursor` | the focused row's index (assignable; clamped) |
| `pane.focused` | the entry under the cursor, or `None` |
| `pane.selected()` | the selected entries |
| `pane.select(predicate)` | add matches to the selection; returns how many |
| `pane.unselect(predicate)` | remove matches; no predicate clears it |
| `pane.cd(path, focus_name=None)` | go somewhere |
| `pane.refresh()` | re-read the directory |

And each entry: `.name`, `.path`, `.suffix`, `.stem`, `.is_dir`, `.is_file`,
`.is_link`, `.size`, `.mtime`. `.path` is a `pathlib.Path`-alike that also
addresses files inside archives and on S3 / SFTP, so `entry.path.read_text()`
works wherever the pane does.

`.size` and `.mtime` read from disk the first time you ask; the rest are free.
A predicate that only looks at names therefore costs no filesystem access at
all, which matters in a large directory.

---

## Reacting to events: `EVENT_HOOKS`

```python
def log_visit(ctx, pane, old_path, new_path):
    with open(Path.home() / '.xefm' / 'visited.log', 'a') as f:
        f.write(f"{new_path}\n")


def open_psd_in_gimp(ctx, path):
    if path.suffix.lower() != '.psd':
        return False
    subprocess.Popen(['gimp', str(path)])
    return True          # claimed — XeFM does nothing further


class Config:
    EVENT_HOOKS = {
        'directory_changed': [log_visit],
        'file_open': [open_psd_in_gimp],
    }
```

| Event | Signature | When |
|---|---|---|
| `startup` | `fn(ctx)` | once the app is up and the panes are listed |
| `quit` | `fn(ctx)` | before XeFM shuts down, panes still live |
| `directory_changed` | `fn(ctx, pane, old_path, new_path)` | a pane moves to a different directory |
| `file_open` | `fn(ctx, path)` | Enter on a file, before XeFM decides what to do with it; return `True` to claim it |

Each event maps to a list, run in order. A bare function is accepted where you
have only one.

`file_open` is how you route a file type somewhere of your own without touching
`FILE_ASSOCIATIONS`. It fires for the **open** action (Enter) — not for
directories, since entering one is navigation rather than opening, and not for
`view_file` (`V`), `open_with_os` or the viewers, which are explicit requests for
a particular way of opening something.

`directory_changed` fires on an actual change of directory. A refresh, a
re-sort, a reload after a file operation and the filesystem monitor's own
reloads all leave the pane where it is and stay quiet.

---

## Things to know

**Your code runs on the UI thread, and XeFM waits for it.** A slow action
freezes the window until it returns. There is no background-work helper in this
version; keep actions quick, and launch anything long as a subprocess.

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
viewers and renderers, sort keys and filter predicates as functions, and any
access to the widget tree. All are additive later.

---

## See also

- [`doc/KEY_BINDINGS_FEATURE.md`](KEY_BINDINGS_FEATURE.md) — key expression
  syntax, modifiers, selection requirements
- [`doc/CONFIGURATION_FEATURE.md`](CONFIGURATION_FEATURE.md) — everything else in
  `config.py`
- [`doc/EXTERNAL_PROGRAMS_FEATURE.md`](EXTERNAL_PROGRAMS_FEATURE.md) — running
  external programs, the other way to extend XeFM
- [`doc/dev/CUSTOMIZATION_API_IMPLEMENTATION.md`](dev/CUSTOMIZATION_API_IMPLEMENTATION.md)
  — how it is built

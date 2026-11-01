# File List Layouts

English \| [日本語](FILE_LIST_LAYOUTS_FEATURE.ja.md)

What a row of the file list shows comes from two things that combine:

- A **layout** is how rows are presented: which of the usual columns — name,
  extension, size, date — in what order, and how each is written. That is a
  matter of taste and of how wide your panes are, so you choose it per tab and
  it stays the same from folder to folder. XeFM ships one, **Default**, and
  `config.py` can add more: dates as `13:24`, names with their extension,
  just names and sizes.
- An **extra** is what a folder adds because of what it holds: your tags,
  where the system keeps them; a Git status inside a working tree; whatever an
  extension brings. Each extra knows where it applies, puts its marks beside a
  column's text or adds a column, and several can show at once on top of
  whichever layout the tab has. XeFM has one built in, **Tags** — the colored
  dots after a name.

The values a layout or an extra shows are **attributes**: name, extension,
size (a folder's total, once calculated), date and tags are built in, and `config.py` and
extension packages can add their own.

> **Preview.** `ATTRIBUTES`, `LAYOUTS`, `DEFAULT_LAYOUT` and `LAYOUT_EXTRAS` may
> still change in any release. XeFM logs one line when your config uses them.
> See [Customization](CUSTOMIZATION_FEATURE.md).

## Choosing a layout

**View → Layout ▸** lists every layout. The choice belongs to the active
pane's current tab: each tab keeps its own, a new tab starts with the one it
was opened from, and XeFM remembers them across sessions. A tab that never
chose starts with `DEFAULT_LAYOUT`. The `choose_layout` action opens the same
choice as a dialog, and is in the command palette.

## Turning extras on and off

**View → Show ▸** has an entry for every extra, each with three states for the
active pane's tab:

- **Auto** — where every tab starts: shown in the folders it applies to (a Git
  status inside a working tree, tags where the system keeps them).
- **On** — shown everywhere in this tab.
- **Off** — not shown in this tab.

Like sort and filter, the state is the tab's: kept across sessions, and copied
by a new tab opened from it. The `choose_extras` action does the same from the
keyboard.

Installing an extension that brings an extra is enough to see it where it
applies; nothing has to be written in `config.py`.

### Where the marks go, and what they mean

- **Marks sit against the text they mark**, before or after it, on the rows
  that have one, and that text gives way on that row. No room is kept for a
  mark on the rows without one, so a name with a mark in front starts a little
  later than the names around it. Tell marks apart by their look.
- **A column of its own** is the other way to show a value, when you want it
  in one place on every row — before the name, for instance. An extra's column
  is as wide as its widest value in the folder.
- **Nothing takes room where nothing has it.** In a folder where no file has a
  Git status, there are no Git marks and no Git column, and the row is as
  tight as without the extra.

**F1** (Help) opens with a **Markers in this pane** section when the active
pane shows any: every mark the active extras can draw, its color, and what it
means.

When two extras draw the same mark in the same color — a yellow `●` for a Git
change looks exactly like a yellow tag — XeFM says so in the log pane when the
config loads.

## Resolving folder sizes and other attributes

Some attributes take too long to work out for every row on their own, so XeFM
works them out only when you ask. The size column shows `<DIR>` for a
folder, because finding out how much a folder holds means counting everything
below it; an attribute of your own may be another such value (see `compute`
below).

**View → Resolve Attribute…** (`resolve_attribute`) works one out for the
selected items, or the item under the cursor when nothing is selected. A
dialog names those items and lists, by name, the attributes that can be
resolved for them in this pane — **Size** in the default layout — even
when there is only one, so it is always clear what is about to run. To resolve
every folder here, select them all first.

It runs in the background, and each result appears as it is done.
Leaving the folder stops it. The totals stay while you are in the folder; one
whose folder changed meanwhile goes back to `<DIR>` until you resolve it
again.

## Sorting by what a pane shows

The sort dialog (`sort`) lists, after its own keys, what the pane shows that
is not already one of them — **Size with folder totals** in the default
layout (the built-in **Size** orders files only), a Git status when that extra
is showing. Sorting by such a row:

- orders **this folder only**. Go to another folder and the pane is sorted the
  way it was before; come back and choose it again.
- uses the values the pane already has. A row without one — a folder whose size
  was not calculated — goes last, whichever way the sort runs.
- is greyed out while values are still arriving, for one that is filled in
  automatically. It becomes available once every row has its value.

**View → Sort By ▸ Reverse Sort** reverses it, as it does any other sort. The status bar
shows it with "(this folder)".

## Defining your own

Open **Tools → Edit Configuration…**. The tables below are documented with
examples in the comments above them in the file itself.

### `ATTRIBUTES` — values XeFM can know about an entry

One function, `read(directory, entries)`, computes the values on a background
thread. `entries` are rows of one folder and `directory` is that folder; it
returns one value per entry, in the same order. XeFM hands it a whole folder at
once, so a source that answers a folder in one go — `git status` — is asked
once rather than once per file:

```python
import subprocess

def line_count(directory, entries):
    def count(entry):
        with open(entry.path, 'rb') as f:
            return sum(1 for _ in f)
    return [count(e) for e in entries]

def git_status(directory, entries):
    try:
        def git(*args):
            return subprocess.run(['git', *args], cwd=str(directory), check=True,
                                  capture_output=True, text=True).stdout
        prefix = git('rev-parse', '--show-prefix').strip()
        items = git('status', '--porcelain', '-z', '--', '.').split('\0')
    except (OSError, subprocess.CalledProcessError):
        return [None] * len(entries)        # not a Git working tree
    codes, skip = {}, False
    for item in items:
        if skip or len(item) < 4:
            skip = False
            continue
        code, path = item[:2], item[3:]
        skip = code[0] in 'RC'              # a rename's old path follows
        if path.startswith(prefix):
            # the entry here the change is in: a file, or the folder holding it
            name = path[len(prefix):].split('/')[0]
            codes.setdefault(name, code.strip()[:1])
    return [codes.get(e.path.name) for e in entries]

class Config:
    ATTRIBUTES = {
        'lines': {'label': 'Lines', 'type': 'count', 'read': line_count},
        'git': {
            'label': 'Git status', 'type': 'enum', 'read': git_status,
            'values': {
                'M': {'label': 'Modified',  'color': 'yellow'},
                'A': {'label': 'Added',     'color': 'green'},
                '?': {'label': 'Untracked', 'color': 'muted'},
            },
        },
    }
```

| Key | What it says |
|---|---|
| `read` | The function: `read(directory, entries)`, returning one value per entry in the order of `entries`. |
| `label` | The name shown in the sort dialog. |
| `type` | `text`, `count`, `size` (bytes), `time` (a timestamp), `duration` (seconds), `enum` (one of `values`) or `tags`. It decides how the value is written and how it sorts. |
| `values` | For an `enum`: each value's meaning, and a color to show it in. The meaning is what Help lists. |
| `where` | The storage it is asked about: `local` (the default), `archive`, `ssh`, `s3`. A call per file is cheap on a disk and a request each on S3. |
| `compute` | `auto` (the default) or `on_request`. |

Defining an attribute shows it nowhere — an extra or a layout does that. Once
something on screen shows it, it is worked out for **every row of the
folder**, in the background, so a definition should answer a folder's worth
quickly. One that cannot — it reads every file whole, say — sets
`'compute': 'on_request'`, and is then computed only when you ask, with **View →
Resolve Attribute…** (`resolve_attribute`), for the selection or the item
under the cursor.
It is then handed one entry per call, so the values appear one by one and
leaving the folder stops them.

A value is empty until it arrives. A function that fails, or returns a list of
the wrong length, costs only that call's values, and says so once in the log
pane.

**File Details** lists every attribute that applies to an item, written out
— an `enum` by its meaning, a time in full — and works out the ones it does
not have yet for the items it shows, on-request ones included.

Your own functions — a sort key, a filter, an action — can read a value XeFM
already has with `entry.attr('git')`. It never computes one and never waits:
until the value is there, it is `None`.

### `LAYOUTS` and `DEFAULT_LAYOUT` — how rows are presented

```python
class Config:
    LAYOUTS = {
        'short': {'label': 'Short time', 'columns': [
            'name', 'ext', 'size',
            {'attr': 'mtime', 'format': 'recent', 'priority': 1}]},
        'names': {'label': 'Names only', 'columns': ['name']},
    }
    DEFAULT_LAYOUT = 'short'
```

A column is an attribute's name, or a dict:

| Key | What it says |
|---|---|
| `attr` | The attribute to show. |
| `format` | How to write it: a format's name (below) or a function of your own. |
| `width` | In cells. Each format has its own. |
| `align` | `left` or `right`. Sizes, counts and durations are right-aligned; dates and text start at the left. |
| `priority` | When the pane is too narrow, columns with a priority are dropped, lowest first. A column without one stays. |

Every layout has a `name` column, and it takes the width the others leave.
Leave out `ext` and the extension stays part of the name. The built-in
`name`, `ext`, `size` (a file's size, or a folder's once it is calculated),
`mtime` and `tags` can be used in any layout. Naming a layout
`'default'` replaces the built-in one, which needs `'override': True` so that a
typo cannot.

**Formats.**

| Type | Formats (the first is the default) |
|---|---|
| `size` | `compact` (`12.3K`), `bytes` (`12,345`) |
| `time` | `short`, `full` — `DATE_FORMAT` picks between them by default — `iso`, `relative` (`5 min ago`), `recent` (`13:24` today, `10/21` this year, `2024` before) |
| `enum` | `letter` (the value itself), `word` (its label from `values`) — both in its color |
| `tags` | `dots`, `names` |
| `duration` | `clock` (`3:07`, `1:02:45`) |
| `count` | `number` |
| `text` | `text` |

A function of your own takes `(value, entry)` and returns text, or a `Cell` to
color it — or a list of them. `value` is `None` while the value is still being
worked out. A `Cell`'s `color` is `'muted'`, `'accent'`, `'accent2'`,
`'text'`, a name (`'red'`, `'green'`, `'yellow'`, `'blue'`, `'purple'`,
`'orange'`, `'gray'`) or an `(r, g, b)`; it can also be `bold` or `italic`.
The selection, the cursor and the resting pane's dimming still apply on top,
so a color never makes a row unreadable.

### `LAYOUT_EXTRAS` — what a folder adds

```python
from xefm.user_api import Cell

GIT_MARK = {'M': Cell('M', color='yellow'),
            'A': Cell('A', color='green'),
            '?': Cell('?', color='muted')}

def git_mark(value, entry):
    return GIT_MARK.get(value, '')

def in_git_tree(path):
    return any((p / '.git').exists() for p in (path, *path.parents))

class Config:
    LAYOUT_EXTRAS = {
        'git': {
            'label': 'Git status',
            'when': in_git_tree,
            'markers': [{'attr': 'git', 'format': git_mark,
                         'on': 'name', 'side': 'before'}],
            'columns': [{'attr': 'git', 'format': 'word', 'replace': 'mtime'}],
        },
    }
```

| Key | What it says |
|---|---|
| `label` | Its name under **View → Show** and in Help. |
| `when` | Where **Auto** shows it: `'always'` (the default), `'never'`, a path pattern (`'s3://*'`), or a function of the folder's path — run in the background, so it may look at the disk. |
| `markers` | Marks beside a column's text (below). |
| `columns` | Columns it adds (below). |

**A marker** is an attribute's name or a dict with `attr`, `format`, `on` —
the column whose text it marks, `'name'` by default and whenever the tab's
layout has no such column — `side` (`'before'` or `'after'`, the default) and
`limit`, the most pieces of the format's result shown (the tag dots: three).
A mark takes no room on rows without one; use one that cannot be mistaken for
the tag dots.

**A column** takes the keys of a layout's column, plus where it goes: `before`
or `after` a column, in place of one with `replace` — to save room; it takes
that column's place and, unless it says otherwise, its priority — or at the
end, also when the named column is not in the layout. A column `before` the
name keeps a value in one place on every row, where a mark before the name
moves with it. It is as wide as its widest value in
the folder, and left out of a folder where no file has a value.

**Changing an extra you did not write.** Name it in `LAYOUT_EXTRAS` with only the
keys you change; the rest stays as the built-in or the extension defined it:

```python
class Config:
    LAYOUT_EXTRAS = {
        'tags': {'when': 'never'},       # no tag dots unless turned On
        'git': {'when': 'always'},       # an extension's extra, everywhere
    }
```

### From an extension package

An extension package can bring attributes, layouts and extras
(`[contributes.attributes]`, `[contributes.layouts]`, `[contributes.layout_extras]`;
see [Extension Packages](EXTENSIONS_FEATURE.md)). Its extras come with their
own `when`, so they show where they apply as soon as the package is installed;
**View → Show** and `LAYOUT_EXTRAS` in `config.py` decide from there.

## Related

- [Sort Dialog](SORT_DIALOG_FEATURE.md)
- [File Tags](FILE_TAGS_FEATURE.md)
- [Help Dialog](HELP_DIALOG_FEATURE.md)
- [Customization](CUSTOMIZATION_FEATURE.md)
- [Menu Bar](MENU_BAR_FEATURE.md)

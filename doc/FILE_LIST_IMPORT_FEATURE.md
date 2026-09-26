# File Lists

A pane can show a **list of paths** instead of a directory: files that live
all over the disk, or on several machines, side by side in one listing, where
every file operation works on them as it does anywhere else.

The list comes from outside XeFM. Search in the tool that is best at it —
Everything, `find`, `fd`, `rg -l`, `git ls-files`, a build log, a column in a
spreadsheet — copy the paths, and bring them in.

## Import List from Clipboard

**Edit → Import List from Clipboard** (`import_list_from_clipboard`) reads the
clipboard as one path per line and shows those paths in the active pane.

```sh
find . -name '*.py' -mtime -1 | pbcopy        # macOS
rg -l TODO | clip                             # Windows
```

It is the reverse of **Copy Full Path(s)**: select files anywhere, copy their
paths, and importing them gives you the same rows back.

The action ships without a key. To give it one, add it to your config:

```python
KEY_BINDINGS['import_list_from_clipboard'] = ['Ctrl-Shift-L']
```

### What it reads

- One path per line. Blank lines are skipped.
- Spaces around a line, and one pair of quotes around it (`"C:\My Files\a.txt"`,
  as Explorer's *Copy as path* writes), are removed.
- A path listed twice appears once.
- Absolute paths and `ssh://…` / `s3://…` locations are used as they are, and
  one list can mix them.
- A **relative** path is taken relative to the directory the pane is showing,
  since the clipboard doesn't say where it came from. The log line says how
  many were read that way — check it if the list came from somewhere else.

Nothing else is interpreted: no wildcards, no CSV columns, no URLs other than
the locations XeFM can open.

### What you see

- The pane's header names the list and counts its rows:
  `List from clipboard — 42 items`.
- Paths that don't exist are left out, and the log pane says how many — and,
  separately, how many sat on a server or drive that could not be reached.
  If none exist, the pane stays as it was.
- Each row is named relative to the deepest folder the whole list shares.
  Paths from one project show as `src/main.py`; a list spanning two drives or
  two servers shares nothing, so each row shows its whole path.
- Sorting, filtering, incremental search, selection, and every file
  operation work on the rows. A file you delete or move away leaves the list.
- **Back** (`go_parent`) returns to the directory the pane showed before.
  Opening a folder from the list leaves it too.
- External programs run from the folder the rows share, or from the pane's
  previous directory when they share none.

The list is a snapshot: files that appear on disk later are not added, and the
pane is not watched for changes while it shows a list. Opening a folder from
the list, or pressing Back, returns to an ordinary live directory.

Importing changes only what the pane shows. Nothing is copied, moved, or
written.

## From your own config

A config action can show a list the same way, with
[`pane.show_list()`](CUSTOMIZATION_FEATURE.md#showing-your-own-list-of-files) —
for a search of your own, or a command whose output you use often.

# File Lists

A pane can show a **list of paths** instead of a directory: files that live
all over the disk, or on several machines, side by side in one listing, where
every file operation works on them as it does anywhere else.

The list comes from outside XeFM. Search in the tool that is best at it —
Everything, `find`, `fd`, `rg -l`, `git ls-files`, a build log, a column in a
spreadsheet — and bring the paths in, by copying them or by running the
command from XeFM.

## Import List from Clipboard

**Edit → Import List from Clipboard** (`import_list_from_clipboard`) reads the
clipboard as one path per line and shows those paths in the active pane.

```sh
find . -name '*.py' -mtime -1 | pbcopy        # macOS
rg -l TODO | clip                             # Windows
```

It is the reverse of **Copy Full Path(s)**: select files anywhere, copy their
paths, and importing them gives you the same rows back.

## Import List from Command

**Edit → Import List from Command…** (`import_list_from_command`) asks for a
command, runs it in the pane's directory, and shows the paths it prints — one
step instead of piping to the clipboard and importing.

The dialog is a command field with the commands you have run listed below it,
most recent first:

| Key | Does |
|---|---|
| typing | Edits the command, and narrows the history (Migemo included) |
| **↓** / **↑** | Move through the history, copying each command into the field |
| **Enter** | In the history: choose that command and go back to the field. In the field: run what it holds |
| **Esc** | In the history: back to what you typed. Otherwise: close |
| **Shift-Delete** | In the history: forget that command |

Enter in the field always runs the field: typing `rg -l` runs `rg -l`, even
with `rg -l TODO` in the history. To run an old command, press ↓ to it and
Enter twice — once to choose it, once to run it — or change it in between; see [Fields with a history](NAVIGATION_DIALOGS_FEATURE.md#fields-with-a-history).

```sh
rg -l TODO
git ls-files --modified
fd -e py -E tests
es.exe -path . ext:py           # Everything, under this folder
dir /s /b *.log                  # Windows, cmd
```

Everything's command-line interface, `es.exe`, is a separate download from
voidtools; put it on your `PATH`. Its query is Everything's own search syntax
(`ext:`, `dm:thisweek`, `size:>100mb`, `|`, `!`). It searches the whole index
wherever it runs, so `-path .` is what limits it to the folder the pane is
showing.

- The command runs through your shell (`/bin/sh`, or `cmd.exe` on Windows), so
  pipes and quoting work as they do at a prompt. It gets the same `XEFM_*`
  [environment variables](EXTERNAL_PROGRAMS_FEATURE.md#environment-variables)
  as a program run from the **X** picker.
- While it runs, a dialog counts the lines it has printed. **Esc** stops it,
  along with anything it started.
- The history keeps your last 100 commands, and survives a restart.
- A command that exits with an error still has its output shown — `grep` and
  `rg` exit with 1 when nothing matched, `find` when one folder could not be
  read. If it printed no paths, the log pane shows the exit code and the last
  lines it wrote to stderr.
- It runs once. Deleting or moving files removes them from the list, but the
  command is not run again; run it again from the menu to get a fresh list.
- It runs in a local directory only. A pane showing an `ssh://` or `s3://`
  location refuses rather than running on this machine.

Output is read as UTF-8. On Windows the command's console is switched to
UTF-8 before it runs, so `dir`, `es.exe` and other console tools print
Japanese and other non-English names intact whatever your system language;
output from a program that ignores the console's setting is read in the
system's code page instead. On macOS and Linux, a name that is not valid UTF-8
is kept byte for byte, so the file it names can still be opened.

## Import List from File

**Edit → Import List from File** (`import_list_from_file`), or **Open as
List** on a file's right-click menu, opens the text file under the cursor as a
list: one path per line. Select several list files first to open them as one
list.

A list file can be anything that names files: an export from Everything
(**File → Export → TXT**), a build log's list of outputs, a `.lst` or `.txt`
you keep beside a project, or the saved output of a command:

```powershell
dir -Recurse -Name *.log > logs.txt         # Windows PowerShell
```

- A **relative** path in a list file is taken relative to **the folder the
  list file is in** — so a list kept beside the files it names keeps working
  when the folder is moved, and reads the same from either pane.
- UTF-8 and UTF-16 files are both read (Windows PowerShell 5.1 and Notepad's
  "Unicode" save as UTF-16), as are files in your system's code page.
- A list file on an `ssh://` or `s3://` location is read there, and its
  relative lines name files there.
- Opening the list does not change the file, and the pane does not follow it:
  open it again to pick up an edit.

## Giving them keys

The three actions ship without a key. To give them one, add them to your
config:

```python
KEY_BINDINGS['import_list_from_clipboard'] = ['Ctrl-Shift-L']
KEY_BINDINGS['import_list_from_command'] = ['Ctrl-Shift-K']
KEY_BINDINGS['import_list_from_file'] = ['Ctrl-Shift-J']
```

## What is read

These apply to every source.

- One path per line. Blank lines are skipped.
- Spaces around a line, and one pair of quotes around it (`"C:\My Files\a.txt"`,
  as Explorer's *Copy as path* writes), are removed.
- A path listed twice appears once.
- Absolute paths and `ssh://…` / `s3://…` locations are used as they are, and
  one list can mix them.
- A **relative** path is taken relative to the folder the list file is in,
  the directory a command ran in, or — for the clipboard, which doesn't say
  where it came from — the directory the pane is showing. The log line says
  how many were read that way; check it if a copied list came from somewhere
  else.

Nothing else is interpreted: no wildcards, no CSV columns, no URLs other than
the locations XeFM can open.

## What you see

- The pane's header names the list — `Clipboard`, the command, or the list
  file — and shows the folder its rows are named from: `[Clipboard] ~/src/xefm`,
  `[rg -l TODO] ~/src/xefm`. When the header is narrow, the name is
  shortened before the folder is. The number of rows is in the footer, as for
  any directory.
- Paths that don't exist are left out, and the log pane says how many — and,
  separately, how many sat on a server or drive that could not be reached.
  If none exist, the pane stays as it was.
- Each row is named relative to the deepest folder the whole list shares —
  the one in the header. Paths from one project show as `src/main.py`; a list
  spanning two drives or two servers shares nothing, so each row shows its
  whole path and the header shows no folder.
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

A config action can open a list the same way, with
[`pane.open_list()`](CUSTOMIZATION_FEATURE.md#opening-your-own-list-of-files) —
for a search written in Python. Unlike **Import List from Command**, the
action runs on the UI thread, so keep anything slow out of it.

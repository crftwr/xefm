# xefmctl

English \| [日本語](XEFMCTL_FEATURE.ja.md)

In a shell XeFM started - the subshell, a [terminal session](TERMINAL_FEATURE.md),
a `PROGRAMS` entry, an [AI agent's session](AI_AGENT_SESSIONS_FEATURE.md) - the
`xefmctl` command talks to that XeFM: it asks for its state at the moment it
runs, and acts on its file manager.

Its first user is an AI agent working beside you: it reads what you are
looking at, searches anywhere XeFM can go, shows you what it found, and
asks you before it changes anything. It works just as well in your own
shell scripts.

## The commands

A command about a pane starts with `pane`; the rest are named after what
they do. Names follow XeFM's own: `pane cd` does what an action's
`ctx.pane.cd` does, and a command that runs a search has the name of the
action that opens it (`find-files`, `find-in-files`).

| Command | What it does |
|---|---|
| `xefmctl state` | Both panes (directory, cursor, selection, filter), the screen shown, and what is open over the panes. Start here |
| `xefmctl pane path` / `entries` / `focused` / `selected` | The pane's directory, its items, the item under the cursor, the selected items |
| `xefmctl pane cd [PATH] [--focus NAME]` | Points the pane at `PATH` (the shell's directory by default). A file: its folder, with the cursor on it |
| `xefmctl pane select PATTERN...` / `unselect` | Selects (unselects) items by name or glob; `--all` for every item |
| `xefmctl pane open-list PATH...` | Shows the paths as a [list](FILE_LIST_IMPORT_FEATURE.md) in the pane; `-` reads them from standard input |
| `xefmctl pane refresh` / `activate` | Re-reads the pane; makes it the active one |
| `xefmctl entries URL...` | What a folder holds, anywhere XeFM can go; `--recursive` for the folders below |
| `xefmctl find-files PATTERN [URL...]` | Files whose names match, below a folder |
| `xefmctl find-in-files PATTERN [URL...]` | Matching lines in the files below a folder (`--case`, `--word`, `--regex`) |
| `xefmctl index-search QUERY` | The OS index: Spotlight on macOS, Windows Search on Windows |
| `xefmctl read URL` / `fetch URL [LOCAL]` | A file's text; a copy of the file on the local disk |
| `xefmctl view FILE [--line N]` | Opens `FILE` in XeFM's viewer on the file manager's screen, in place of a viewer already open there |
| `xefmctl diff A B` | Compares two files, or two folders |
| `xefmctl show-markdown FILE` | Shows Markdown in XeFM's viewer; `-` reads it from standard input |
| `xefmctl copy SOURCE... --to DIR` / `move` | Copies (moves) through XeFM's own copy, with its conflict dialog |
| `xefmctl trash PATH...` / `delete` | Moves to the OS trash; deletes for good |
| `xefmctl confirm` / `choose` / `input` | Asks you in XeFM - yes or no, one of a list, a line of text - and prints the answer |
| `xefmctl message TEXT` | Writes a line to the log pane |
| `xefmctl action list` / `action show NAME` | Every action, with what it does and its keys; one action in full |
| `xefmctl invoke NAME` | Runs an action, as its key would on the file manager's screen |
| `xefmctl screen list` / `screen show ID` | The screens; shows one (`files` for the file manager) |
| `xefmctl terminal-session list` / `start` / `close ID` | XeFM's terminal sessions |
| `xefmctl help [COMMAND]` | Every command, or one in full |

`xefmctl help COMMAND` lists each command's options.

### Anywhere XeFM can go

`entries`, `find-files`, `find-in-files`, `read`, `fetch`, `view` and `diff`
take a path on this computer or anything XeFM can open: `ssh://host/path`,
`s3://bucket/key`, a member of an archive (`archive:///path/a.zip#inner/file`),
a [virtual folder](VIRTUAL_FOLDERS_FEATURE.md). XeFM holds the connections,
so the shell does not need its own SSH keys or cloud credentials.

### Showing what was found

Add `--show` to `entries` or a search, and what it found also appears in
the active pane (`--pane` picks another) as a list you can sort, filter and
work on, as XeFM's own search does.

### Which pane

`--pane active` (the default), `--pane other`, `--pane left` or `--pane right`.

### For scripts and agents

- `--json` on any command prints one JSON object per line. Paths with spaces
  or newlines are then never ambiguous.
- A search prints what it finds as it finds it. `--limit N` stops after `N`
  items; Ctrl-C stops it.
- Where a command takes several paths, `-` reads them from standard input,
  one per line or as the JSON lines another `xefmctl --json` printed:
  `xefmctl find-files '*.log' --json | xefmctl trash -`.
- `copy`, `move`, `trash` and `delete` return once started; `--wait` waits
  until they are done and says how they went.
- The exit status: 0 done, 1 failed (or you said no), 2 a mistake in the
  command, 3 XeFM cannot be reached, 4 XeFM is busy, 5 refused. A refusal
  says why, in words an agent can pass on to you.

```sh
cp $(xefmctl pane selected) /tmp               # names without spaces
xefmctl pane selected -0 | xargs -0 du -sh
xefmctl pane cd .                              # bring the active pane here
xefmctl find-in-files TODO ~/src --show        # the hits, as a list in the pane
xefmctl view build.log --line 120
xefmctl confirm "Delete the 3 old backups?" && xefmctl trash backup-*.zip
```

## Only what you could do by hand

A command that changes the file manager is let in when a key on its screen
would be:

- With the panes on top, anything.
- With a viewer open over them, anything but an action of the file list.
  `view` closes that viewer and opens the new one, so two are never open.
- With a dialog, a menu or the command palette open on the file manager's
  screen, nothing: the command is refused, with a message saying what is
  open. Finish it, and run the command again.

What a command opens - a viewer, a question - opens on the file manager's
screen, and XeFM takes you there. A question asked for an agent takes you
back to its terminal once you answer.

## While a subshell has the terminal

In terminal mode, XeFM waits while a subshell or terminal program runs, so
only the commands that read work there: `state`, the `pane` reads,
`entries`, the searches, `read`, `fetch`, `action list`, `screen list`,
`terminal-session list`. The others say XeFM is waiting, and work once you
are back.

If the XeFM that started the shell has quit, every command says so.

## See also

- [AI agent sessions](AI_AGENT_SESSIONS_FEATURE.md): what an agent's session may and may not do
- [Terminal](TERMINAL_FEATURE.md): the subshell, terminal sessions and screens
- [File Lists](FILE_LIST_IMPORT_FEATURE.md): lists of paths in a pane

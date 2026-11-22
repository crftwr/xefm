# xefmctl: commands

Generated from `xefm/remote_commands.py`; do not edit by hand.

`xefmctl` works in a terminal session XeFM started (`XEFM_SESSION` is set) and acts on that XeFM's file manager. Add `--json` to any command for one JSON object per line. Exit status: 0 done, 1 failed or the user said no, 2 a usage mistake, 3 XeFM cannot be reached, 4 XeFM is busy (try again), 5 refused (a dialog is open in XeFM, or this session may not do that), 6 XeFM is suspended until this shell exits (terminal mode: only commands that read work, for the rest of the session; do not retry); the message says what to tell the user.

Commands marked *Uses XeFM's screen* are the ones refused with 6. While XeFM is suspended, `--show` is ignored and the results come back to the terminal only. `xefmctl state` says whether XeFM is suspended (`suspended` in `--json`).

## Orientation

### `state`

`xefmctl state`

both panes, the screen on now and what is open over it: start here.

One call for what the user is looking at: each pane's directory, cursor, selection and filter; which pane is active; the screen shown; a viewer or dialog open over the panes.

## A pane

### `pane path`

`xefmctl pane path [--pane PANE]`

the pane's directory (or the URL it shows).
- `--pane PANE`: the pane: active (the default), other, left or right

### `pane entries`

`xefmctl pane entries [--pane PANE] [--limit N]`

every item the pane lists, in its order.
- `--pane PANE`: the pane: active (the default), other, left or right
- `--limit N`: stop after N items

### `pane focused`

`xefmctl pane focused [--pane PANE]`

the item under the cursor.
- `--pane PANE`: the pane: active (the default), other, left or right

### `pane selected`

`xefmctl pane selected [--pane PANE] [-0]`

the selected items.
- `--pane PANE`: the pane: active (the default), other, left or right
- `-0`: end each path with NUL instead of a newline

### `pane cd`

`xefmctl pane cd [PATH] [--pane PANE] [--focus NAME]`

point the pane at a folder; with --focus, put the cursor on an item there.
- `PATH`: default: this shell's directory
- `--pane PANE`: the pane: active (the default), other, left or right
- `--focus NAME`: the item to put the cursor on
- *Uses XeFM's screen.*

### `pane select`

`xefmctl pane select [PATTERN...] [--pane PANE] [--all]`

select items in the pane by name or glob.
- `PATTERN`: names or globs (*.jpg); none with --all
- `--pane PANE`: the pane: active (the default), other, left or right
- `--all`: every item
- *Uses XeFM's screen.*

### `pane unselect`

`xefmctl pane unselect [PATTERN...] [--pane PANE] [--all]`

unselect items in the pane by name or glob.
- `--pane PANE`: the pane: active (the default), other, left or right
- `--all`: every item
- *Uses XeFM's screen.*

### `pane open-list`

`xefmctl pane open-list PATH... [--pane PANE] [--title TEXT]`

show paths as a list in the pane, where every file operation works on them.
- `PATH`: paths or URLs, or - to read them from standard input
- `--pane PANE`: the pane: active (the default), other, left or right
- `--title TEXT`: the title of what is shown
- *Uses XeFM's screen.*

### `pane refresh`

`xefmctl pane refresh [--pane PANE]`

re-read the pane.
- `--pane PANE`: the pane: active (the default), other, left or right
- *Uses XeFM's screen.*

### `pane activate`

`xefmctl pane activate [--pane PANE]`

make the pane the active one.
- `--pane PANE`: the pane: active (the default), other, left or right
- *Uses XeFM's screen.*

## Places and searches

### `entries`

`xefmctl entries URL... [--recursive] [--depth N] [--limit N] [--show] [--pane PANE] [--title TEXT]`

what a folder holds, anywhere XeFM can go (ssh://, s3://, archives, virtual folders).
- `--recursive`: the folders below too
- `--depth N`: with --recursive: how deep
- `--limit N`: stop after N items
- `--show`: also show the results in a pane, as a list the user can work with
- `--pane PANE`: the pane: active (the default), other, left or right
- `--title TEXT`: the title of what is shown

### `find-files`

`xefmctl find-files PATTERN [URL...] [--case] [--no-recursive] [--limit N] [--show] [--pane PANE] [--title TEXT]`

files whose names match, below a folder anywhere XeFM can go (find_files).
- `PATTERN`: a glob (*.psd) or a part of the name
- `URL`: where to look (default: the pane's folder)
- `--case`: match capitals exactly
- `--no-recursive`: this folder only, not the ones below
- `--limit N`: stop after N items
- `--show`: also show the results in a pane, as a list the user can work with
- `--pane PANE`: the pane: active (the default), other, left or right
- `--title TEXT`: the title of what is shown

### `find-in-files`

`xefmctl find-in-files PATTERN [URL...] [--case] [--word] [--regex] [--no-recursive] [--limit N] [--show] [--pane PANE] [--title TEXT]`

lines that match, in the files below a folder anywhere XeFM can go (find_in_files).
- `URL`: where to look (default: the pane's folder)
- `--case`: match capitals exactly
- `--word`: whole words only
- `--regex`: PATTERN is a regular expression
- `--no-recursive`: this folder only, not the ones below
- `--limit N`: stop after N items
- `--show`: also show the results in a pane, as a list the user can work with
- `--pane PANE`: the pane: active (the default), other, left or right
- `--title TEXT`: the title of what is shown

### `index-search`

`xefmctl index-search QUERY [URL] [--limit N] [--show] [--pane PANE] [--title TEXT]`

the OS index (Spotlight, Windows Search) (index_search).
- `URL`: the folder to search in
- `--limit N`: stop after N items
- `--show`: also show the results in a pane, as a list the user can work with
- `--pane PANE`: the pane: active (the default), other, left or right
- `--title TEXT`: the title of what is shown

### `read`

`xefmctl read URL [--max-bytes N]`

a file's text, anywhere XeFM can go.
- `--max-bytes N`: read at most N bytes (default 1000000)

### `fetch`

`xefmctl fetch URL [LOCAL]`

copy a file from anywhere XeFM can go to a local file, and print where.
- `LOCAL`: default: a temporary file

## Showing

### `view`

`xefmctl view PATH [--line N]`

open a file in XeFM's viewer, on the file manager's screen.
- `--line N`: scroll to line N
- *Uses XeFM's screen.*

### `diff`

`xefmctl diff LEFT RIGHT`

compare two files (or two folders) in XeFM.
- *Uses XeFM's screen.*

### `show-markdown`

`xefmctl show-markdown FILE [--title TEXT]`

show Markdown in XeFM's viewer.
- `FILE`: a Markdown file, or - for standard input
- `--title TEXT`: the title of what is shown
- *Uses XeFM's screen.*

## Files

### `copy`

`xefmctl copy SOURCE... [--to DIR] [--wait]`

copy items to a folder, through XeFM's copy.
- `--to DIR`: the destination folder
- `--wait`: wait until it is done (or the user answered) and say how it went
- *Uses XeFM's screen.*

### `move`

`xefmctl move SOURCE... [--to DIR] [--wait]`

move items to a folder, through XeFM's move.
- `--to DIR`: the destination folder
- `--wait`: wait until it is done (or the user answered) and say how it went
- *Uses XeFM's screen.*

### `trash`

`xefmctl trash PATH... [--wait]`

move items to the OS trash.
- `--wait`: wait until it is done (or the user answered) and say how it went
- *Uses XeFM's screen.*

### `delete`

`xefmctl delete PATH... [--wait]`

delete items for good (refused in an agent's session).
- `--wait`: wait until it is done (or the user answered) and say how it went
- *Uses XeFM's screen.*

## Asking the user

### `confirm`

`xefmctl confirm PROMPT [--title TEXT]`

ask the user yes or no in XeFM; exit status 0 for yes, 1 for no.
- `--title TEXT`: the title of what is shown
- Waits for the user's answer.
- *Uses XeFM's screen.*

### `choose`

`xefmctl choose TITLE ITEM...`

have the user pick one item in XeFM; prints it (exit status 1 if cancelled).
- Waits for the user's answer.
- *Uses XeFM's screen.*

### `input`

`xefmctl input PROMPT [--default TEXT] [--title TEXT]`

ask the user for a line of text in XeFM; prints it (exit status 1 if cancelled).
- `--default TEXT`: the text to start with
- `--title TEXT`: the title of what is shown
- Waits for the user's answer.
- *Uses XeFM's screen.*

### `message`

`xefmctl message TEXT`

write a line to XeFM's log pane.
- *Uses XeFM's screen.*

## Actions

### `action list`

`xefmctl action list`

every action invoke takes, with what it does and its keys.

### `action show`

`xefmctl action show NAME`

what one action does, in full.

### `invoke`

`xefmctl invoke NAME [--pane PANE]`

run an action by name, as its key would on the file manager's screen.
- `--pane PANE`: the pane: active (the default), other, left or right
- *Uses XeFM's screen.*

## Screens and terminal sessions

### `screen list`

`xefmctl screen list`

the screens, the one shown first.

### `screen show`

`xefmctl screen show ID`

show a screen (files, or a terminal session's id).
- *Uses XeFM's screen.*

### `terminal-session list`

`xefmctl terminal-session list`

XeFM's terminal sessions.

### `terminal-session start`

`xefmctl terminal-session start [COMMAND...] [--cwd DIR] [--name NAME] [--hidden]`

start a terminal session (a shell by default).
- `COMMAND`: the program and its arguments
- `--cwd DIR`: 
- `--name NAME`: 
- `--hidden`: start it without showing it
- *Uses XeFM's screen.*

### `terminal-session close`

`xefmctl terminal-session close ID`

end a terminal session.
- *Uses XeFM's screen.*

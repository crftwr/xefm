# xefmctl: commands

Generated from `xefm/remote_commands.py`; do not edit by hand.

`xefmctl` works in a terminal session XeFM started (`XEFM_SESSION` is set) and acts on that XeFM's file manager. Add `--json` to any command for one JSON object per line. Exit status: 0 done, 1 failed or the user said no, 2 a usage mistake, 3 XeFM cannot be reached, 4 XeFM is busy (try again), 5 refused (a dialog is open in XeFM, or this session may not do that), 6 XeFM is suspended until this shell exits (terminal mode: only commands that read work, for the rest of the session; do not retry); the message says what to tell the user.

Commands marked *Uses XeFM's screen* are the ones refused with 6. While XeFM is suspended, `--show` is ignored and the results come back to the terminal only. `xefmctl state` says whether XeFM is suspended (`suspended` in `--json`).

## Orientation

### `state`

`xefmctl state`

both panes, the screen on now and what is open over it: start here.

One call for what the user is looking at: each pane's directory, cursor, selection and filter; which pane is active; the screen shown; a viewer or dialog open over the panes. In an AI agent's session also whether its sandbox is on, off or not known (`sandbox` in --json).

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

### `pane pick`

`xefmctl pane pick [--pane PANE] [--prompt TEXT]`

have the user select items in XeFM and press Enter; prints them (exit status 1 if cancelled with Esc).

The pane becomes the active one and every key works as usual - moving, selecting, changing folders, switching panes - until Enter, which answers the active pane's selection (or the item under its cursor), or Esc.
- `--pane PANE`: the pane: active (the default), other, left or right
- `--prompt TEXT`: what to ask for, shown in XeFM's log pane
- Waits for the user's answer.
- *Uses XeFM's screen.*

## Places and searches

### `entries`

`xefmctl entries [URL...] [--recursive] [--depth N] [--from WHAT] [--limit N] [--show] [--pane PANE] [--title TEXT]`

what a folder holds, anywhere XeFM can go (ssh://, s3://, archives, virtual folders).
- `URL`: the folders (default: the pane's folder); a file is listed as itself
- `--recursive`: the folders below too
- `--depth N`: with --recursive: how deep
- `--from WHAT`: take the items from the pane instead of the arguments: pane (its folder, or the entries of the list it shows) or selection (the selected items, or else the one under the cursor)
- `--limit N`: stop after N items
- `--show`: also show the results in a pane, as a list the user can work with
- `--pane PANE`: the pane: active (the default), other, left or right
- `--title TEXT`: the title of what is shown

### `find-files`

`xefmctl find-files PATTERN [URL...] [--case] [--no-recursive] [--from WHAT] [--limit N] [--show] [--pane PANE] [--title TEXT]`

files whose names match, below a folder anywhere XeFM can go (find_files).
- `PATTERN`: a glob (*.psd) or a part of the name
- `URL`: where to look (default: the pane's folder)
- `--case`: match capitals exactly
- `--no-recursive`: this folder only, not the ones below
- `--from WHAT`: take the items from the pane instead of the arguments: pane (its folder, or the entries of the list it shows) or selection (the selected items, or else the one under the cursor)
- `--limit N`: stop after N items
- `--show`: also show the results in a pane, as a list the user can work with
- `--pane PANE`: the pane: active (the default), other, left or right
- `--title TEXT`: the title of what is shown

### `find-in-files`

`xefmctl find-in-files PATTERN [URL...] [--case] [--word] [--regex] [--no-recursive] [--from WHAT] [--limit N] [--show] [--pane PANE] [--title TEXT]`

lines that match, in the files below a folder anywhere XeFM can go (find_in_files).

In an AI agent's session, XeFM asks the user before a file's contents are read outside the session's folder, once for each folder. Files directly in a folder the user went to in a pane are not asked about.
- `URL`: where to look (default: the pane's folder)
- `--case`: match capitals exactly
- `--word`: whole words only
- `--regex`: PATTERN is a regular expression
- `--no-recursive`: this folder only, not the ones below
- `--from WHAT`: take the items from the pane instead of the arguments: pane (its folder, or the entries of the list it shows) or selection (the selected items, or else the one under the cursor)
- `--limit N`: stop after N items
- `--show`: also show the results in a pane, as a list the user can work with
- `--pane PANE`: the pane: active (the default), other, left or right
- `--title TEXT`: the title of what is shown

### `index-search`

`xefmctl index-search QUERY [URL...] [--from WHAT] [--limit N] [--show] [--pane PANE] [--title TEXT]`

the OS index (Spotlight, Windows Search) (index_search).
- `URL`: the folders to search in (default: the pane's folder)
- `--from WHAT`: take the items from the pane instead of the arguments: pane (its folder, or the entries of the list it shows) or selection (the selected items, or else the one under the cursor)
- `--limit N`: stop after N items
- `--show`: also show the results in a pane, as a list the user can work with
- `--pane PANE`: the pane: active (the default), other, left or right
- `--title TEXT`: the title of what is shown

### `find-similar`

`xefmctl find-similar [URL...] [--method METHOD] [--threshold T] [--from WHAT] [--limit N] [--show] [--pane PANE] [--title TEXT]`

groups of similar files below local folders, found by the similar-files scan (find_similar).

One line per file: the group's number, then the path; the first file of a group is the one the others are like. The scan runs in a process of its own and shows in XeFM's jobs list; nothing is printed until it ends. With --show the groups open in the pane as a tree.
- `URL`: the folders or files to scan (default: the pane's folder)
- `--method METHOD`: what to compare (required): identical (the same content), image, video or audio
- `--threshold T`: how alike: loose, standard, strict, or a number from 0 to 1 (not for identical)
- `--from WHAT`: take the items from the pane instead of the arguments: pane (its folder, or the entries of the list it shows) or selection (the selected items, or else the one under the cursor)
- `--limit N`: stop after N items
- `--show`: also show the results in a pane, as a list the user can work with
- `--pane PANE`: the pane: active (the default), other, left or right
- `--title TEXT`: the title of what is shown

### `path-scheme list`

`xefmctl path-scheme list`

the kinds of place XeFM can open besides the local disk (ssh://, s3://, archive://, and the ones PATH_SCHEMES and extensions add).

### `read`

`xefmctl read URL [--max-bytes N]`

a file's text, anywhere XeFM can go.

In an AI agent's session, XeFM asks the user before a file's contents are read outside the session's folder, once for each folder. Files directly in a folder the user went to in a pane are not asked about.
- `--max-bytes N`: read at most N bytes (default 1000000)

### `fetch`

`xefmctl fetch URL [LOCAL]`

copy a file from anywhere XeFM can go to a local file, and print where.

In an AI agent's session, XeFM asks the user before a file's contents are read outside the session's folder, once for each folder. Files directly in a folder the user went to in a pane are not asked about. Writing to LOCAL is asked too; without it the copy goes to a new temporary folder.
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

`xefmctl copy SOURCE... [--to DIR] [--from WHAT] [--pane PANE] [--wait]`

copy items to a folder, through XeFM's copy.
- `--to DIR`: the destination folder
- `--from WHAT`: take the items from the pane instead of the arguments: pane (its folder, or the entries of the list it shows) or selection (the selected items, or else the one under the cursor)
- `--pane PANE`: the pane: active (the default), other, left or right
- `--wait`: wait until it is done (or the user answered) and say how it went
- *Uses XeFM's screen.*

### `move`

`xefmctl move SOURCE... [--to DIR] [--from WHAT] [--pane PANE] [--wait]`

move items to a folder, through XeFM's move.
- `--to DIR`: the destination folder
- `--from WHAT`: take the items from the pane instead of the arguments: pane (its folder, or the entries of the list it shows) or selection (the selected items, or else the one under the cursor)
- `--pane PANE`: the pane: active (the default), other, left or right
- `--wait`: wait until it is done (or the user answered) and say how it went
- *Uses XeFM's screen.*

### `trash`

`xefmctl trash PATH... [--from WHAT] [--pane PANE] [--wait]`

move items to the OS trash.
- `--from WHAT`: take the items from the pane instead of the arguments: pane (its folder, or the entries of the list it shows) or selection (the selected items, or else the one under the cursor)
- `--pane PANE`: the pane: active (the default), other, left or right
- `--wait`: wait until it is done (or the user answered) and say how it went
- *Uses XeFM's screen.*

### `delete`

`xefmctl delete PATH... [--from WHAT] [--pane PANE] [--wait]`

delete items for good (refused in an agent's session).
- `--from WHAT`: take the items from the pane instead of the arguments: pane (its folder, or the entries of the list it shows) or selection (the selected items, or else the one under the cursor)
- `--pane PANE`: the pane: active (the default), other, left or right
- `--wait`: wait until it is done (or the user answered) and say how it went
- *Uses XeFM's screen.*

### `rename`

`xefmctl rename [--plan FILE] [--wait]`

rename items to the names a plan gives, after the user confirms them in XeFM's rename review.

Each name is a new name in the item's own folder: rename does not move. The plan is checked as Rename in Editor checks an edited list (swaps and chains are fine; two items on one name, or a name already taken, refuse the plan) and nothing moves until the user says Rename.
- `--plan FILE`: a JSON list of {"path": ..., "name": ...}, or - for standard input
- `--wait`: wait until it is done (or the user answered) and say how it went
- *Uses XeFM's screen.*

## Tags and attributes

### `tag list`

`xefmctl tag list`

the tags XeFM knows, most recently applied first.

### `tag add`

`xefmctl tag add NAME PATH... [--tag NAME]... [--color COLOR] [--from WHAT] [--pane PANE] [--wait]`

tag items, where the OS keeps tags (Finder, user.xdg.tags, S3).
- `NAME`: the tag
- `PATH`: the items, or - to read them from standard input
- `--tag NAME`: another tag (repeat for more)
- `--color COLOR`: the color of a tag new to XeFM, where the storage keeps colors
- `--from WHAT`: take the items from the pane instead of the arguments: pane (its folder, or the entries of the list it shows) or selection (the selected items, or else the one under the cursor)
- `--pane PANE`: the pane: active (the default), other, left or right
- `--wait`: wait until it is done (or the user answered) and say how it went
- *Uses XeFM's screen.*

### `tag remove`

`xefmctl tag remove NAME PATH... [--tag NAME]... [--from WHAT] [--pane PANE] [--wait]`

take tags off items.
- `NAME`: the tag
- `PATH`: the items, or - to read them from standard input
- `--tag NAME`: another tag (repeat for more)
- `--from WHAT`: take the items from the pane instead of the arguments: pane (its folder, or the entries of the list it shows) or selection (the selected items, or else the one under the cursor)
- `--pane PANE`: the pane: active (the default), other, left or right
- `--wait`: wait until it is done (or the user answered) and say how it went
- *Uses XeFM's screen.*

### `attribute list`

`xefmctl attribute list`

every attribute XeFM knows (size, tags, ATTRIBUTES', a tree's).

### `attribute get`

`xefmctl attribute get PATH... [--attributes A,B] [--from WHAT] [--pane PANE] [--limit N]`

attribute values of items, computed now (get_attributes).

One line per item: the path, then name=value for each attribute, tab-separated. An on-request attribute is computed, and a folder's size is its total, so this can take a while. --json gives the values as they are.
- `PATH`: the items, or - to read them from standard input
- `--attributes A,B`: the attributes (default: all)
- `--from WHAT`: take the items from the pane instead of the arguments: pane (its folder, or the entries of the list it shows) or selection (the selected items, or else the one under the cursor)
- `--pane PANE`: the pane: active (the default), other, left or right
- `--limit N`: stop after N items

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

In an AI agent's session, an action that runs other programs (open_with_os, open_items_with_os, sync_python_packages), reload_config, and an action of the user's own or an extension's are asked in XeFM first.
- `--pane PANE`: the pane: active (the default), other, left or right
- *Uses XeFM's screen.*

## Skills

### `skill list`

`xefmctl skill list`

the user's own skills for agent sessions, in ~/.xefm/skills/, and whether sessions get them.

A skill that fails the check is left out of sessions. One written or changed now reaches the next session.

### `skill check`

`xefmctl skill check [NAME...]`

check skills in ~/.xefm/skills/ by name (all of them by default); exit status 1 if one fails.

Run it after writing ~/.xefm/skills/<name>/SKILL.md: it says what keeps a skill out of sessions (the frontmatter's name and description).

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

In an AI agent's session, asked in XeFM first; the new session is restricted as the agent's is.
- `COMMAND`: the program and its arguments
- `--cwd DIR`: 
- `--name NAME`: 
- `--hidden`: start it without showing it
- *Uses XeFM's screen.*

### `terminal-session close`

`xefmctl terminal-session close ID`

end a terminal session.
- *Uses XeFM's screen.*

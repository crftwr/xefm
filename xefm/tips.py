"""The Tip of the Day content (issue #261): a rotation of short feature
introductions shown by :mod:`xefm.tips_dialog`.

Each tip is a ``(title, body)`` pair. The body is Markdown (rendered by PuiKit's
``MarkdownView``), and may reference key bindings as ``{key:action}``
placeholders — :func:`render_tip` resolves those against the *live* keymap at
display time, so a tip never quotes a key the user has rebound away. Actions are
the same names the help dialog uses (``XeFMApp._HELP_SECTIONS``); an unbound
action renders as ``—``, exactly like help.

Adding a tip is appending a pair to :data:`TIPS`. The Welcome tip must stay
first (a fresh install starts the rotation at index 0), and — once a release
has shipped this list — new tips go at the **end, before the closing GitHub
tip**, rather than reordering: the app persists a position *into* this list,
so reordering makes a returning user see repeats or skips. The index is taken
modulo :func:`tip_count`, so growth itself is always safe.
"""

from __future__ import annotations

import re
from typing import Callable

from xefm.const import GITHUB_URL

#: ``{key:action}`` — the action name a placeholder carries. Dots included: an
#: action owned by one surface is qualified with it (``toggle_wrap``).
_KEY_REF = re.compile(r"\{key:([a-z0-9_.]+)\}")

#: The rotation, in display order: (title, Markdown body). The first entry is
#: the Welcome tip and must stay first — a fresh install starts the rotation at
#: index 0. Keep bodies to a few sentences; the dialog body scrolls, but a tip
#: should not need it.
TIPS: tuple[tuple[str, str], ...] = (
    ("Welcome to XeFM",
     "XeFM is a dual-pane file manager: two directory listings side by side, "
     "with operations acting from the **active** pane toward the other. The "
     "arrow keys move the cursor, {key:open_item} opens the focused item, and "
     "{key:go_parent} goes to the parent directory.\n\n"
     "Press {key:help} anytime for the **Help** dialog with every key binding "
     "— and these tips return once a day, or from **Help ▸ Tip of the Day**."),

    ("Two panes, one target",
     "Press {key:switch_pane} to switch the active pane. Copy "
     "({key:copy_files}) and move ({key:move_files}) always go from the active "
     "pane **into the other one** — set up source and destination first, then "
     "fire."),

    ("Select several files at once",
     "{key:toggle_select_down} toggles selection on the focused item and moves down; "
     "{key:toggle_select_up} toggles and moves up. {key:select_all} selects "
     "everything, and {key:unselect_all} clears the selection."),

    ("Jump to a file by typing",
     "Press {key:isearch} and just start typing — the cursor jumps to the first "
     "matching name in the pane as each character narrows the match."),

    ("Filter the listing",
     "{key:filter} narrows the pane to names matching a pattern, and "
     "{key:clear_filter} shows everything again. Handy in a directory with "
     "hundreds of entries."),

    ("Search the whole tree",
     "{key:find_files} finds files by name recursively under the current "
     "directory, and {key:find_in_files} searches *inside* files (grep). "
     "Results stream in as they are found."),

    ("Favorite directories",
     "{key:favorites} opens a searchable picker of your favorite directories "
     "for a one-keystroke jump. Define them in `FAVORITE_DIRECTORIES` in "
     "`~/.xefm/config.py` (**Tools ▸ Edit Configuration…** opens it)."),

    ("Jump to any path",
     "{key:jump_to_path} prompts for a path — with filename completion — and "
     "takes the active pane straight there. Pasting a path works too, and a "
     "path naming a *file* lands the cursor on it."),

    ("Straight to the top",
     "{key:go_root} takes the active pane to the root of wherever it is — the "
     "current drive on Windows, `/` on macOS and Linux, the bucket over S3, the "
     "host over SFTP. The cursor lands on the branch you came up through, so "
     "walking back down is one keypress away."),

    ("Revisit recent directories",
     "{key:history} lists the directories you have visited recently, "
     "most-recent first. Pick one to jump back."),

    ("Keep the panes in sync",
     "{key:sync_current_to_other} moves the active pane to the *other* pane's "
     "directory; {key:sync_other_to_current} sends this directory to the other "
     "pane. Perfect just before a copy or a compare."),

    ("Sorting, fast and slow",
     "{key:sort} opens the sort dialog. Even quicker: "
     "{key:quick_sort_name} / {key:quick_sort_size} / {key:quick_sort_date} / "
     "{key:quick_sort_ext} sort by name, size, date or extension directly — "
     "and pressing the same key again reverses the order."),

    ("Hidden files",
     "{key:toggle_hidden} shows or hides hidden files — dotfiles everywhere, "
     "and on Windows also whatever carries the hidden attribute. The setting "
     "applies to both panes."),

    ("Pick a look",
     "The **View ▸ Theme** menu picks a color theme directly, and "
     "**View ▸ Next Theme** cycles through them. Your choice is remembered "
     "across sessions."),

    ("The built-in viewer",
     "{key:view_file} opens the focused file in the built-in viewer. Text "
     "files get a scrollable view with search; images render inline — even in "
     "the terminal, on kitty, iTerm2 or WezTerm."),

    ("Hand off to the OS",
     "{key:open_with_os} opens the focused item with its default application, "
     "and {key:reveal_in_os} reveals it in the system file manager (Finder / "
     "Explorer)."),

    ("Edit in your editor",
     "{key:edit_file} opens the selected files — or the focused file when "
     "nothing is selected — in your text editor, all in one session: the "
     "`TEXT_EDITOR` command in `~/.xefm/config.py` (VS Code in desktop mode, "
     "vim in the terminal, by default). An `edit` entry in "
     "`FILE_ASSOCIATIONS` overrides it per file type."),

    ("Archives are directories",
     "Press {key:open_item} on an archive to browse *inside* it like "
     "a directory. {key:create_archive} packs the selection into a new "
     "archive; {key:extract_archive} unpacks the focused one."),

    ("Compare files and directories",
     "{key:diff_files} compares two selected files side by side in a diff "
     "viewer, and {key:diff_directories} compares the two panes' directories "
     "recursively."),

    ("Compare and select",
     "{key:compare_selection} selects files in the active pane by comparing "
     "them against the other pane — same or different size, timestamp or "
     "content. Great for spotting what changed between two snapshots."),

    ("Names and paths to the clipboard",
     "{key:copy_names} copies the selected file names to the clipboard; "
     "{key:copy_paths} copies their full paths. Ready to paste into a "
     "terminal, commit message or chat."),

    ("A shell where you are",
     "{key:subshell} opens your shell in the current directory. Exit the shell "
     "and you are right back in XeFM."),

    ("Batch rename with a regex",
     "Select more than one file and press {key:rename}: the rename prompt "
     "becomes a regex-based batch-rename dialog that renames the whole "
     "selection in one go."),

    ("Remote file systems",
     "XeFM browses remote locations too: give {key:jump_to_path} a URL like "
     "`ssh://host/path` or `s3://bucket/` and use the pane like a local "
     "directory."),

    ("Drives and locations",
     "{key:drives} opens a picker of mounted volumes, common locations, "
     "and your configured SSH hosts and S3 buckets — one list, one jump."),

    ("Rich viewers for data files",
     "{key:view_file} knows more than plain text: Markdown (`.md`) renders "
     "with headings and tables, JSON (`.json`, `.jsonl`) opens as a "
     "collapsible tree, and CSV/TSV as a table grid."),

    ("File details, with live sizes",
     "{key:file_details} shows stat details for the focused item — or an "
     "aggregate summary of the whole selection. Directories total their "
     "recursive size and item counts in the background while the dialog is "
     "open, so the numbers climb until the walk finishes."),

    ("Sync the cursor, not just the directory",
     "When both panes already show the same directory, "
     "{key:sync_current_to_other} moves the cursor onto the file the *other* "
     "pane is highlighting — press it twice to land on the same file in the "
     "same place. {key:sync_other_to_current} mirrors it the other way."),

    ("A photo tour from a search",
     "Search for images with {key:find_files} — say `*.jpg` — then open "
     "one hit with {key:view_file}: the image viewer's prev/next keys "
     "({key:image_viewer.prev} / {key:image_viewer.next}) page through every hit, across "
     "all the subdirectories the search covered."),

    ("Fix differences right in the diff",
     "The directory diff ({key:diff_directories}) is not just a report: the "
     "usual {key:copy_files} / {key:move_files} / {key:delete_files} keys "
     "work on the tree in place, and it rescans afterwards keeping your "
     "expanded folders and cursor."),

    ("Reuse a filter",
     "The Filter prompt ({key:filter}) opens with your recent patterns — "
     "kept across sessions — so a filter you use often is one pick away. "
     "The first row clears the current filter."),

    ("Complete the path",
     "Path prompts — Jump to Path ({key:jump_to_path}), Rename "
     "({key:rename}) and friends — complete filenames with **Tab**, so "
     "a deep path is a few keystrokes."),

    ("Locked archives",
     "A password-protected zip prompts for its password (masked) when you "
     "open a file inside it, then remembers it for the session. Classic "
     "ZipCrypto only — AES-encrypted zips are declined with a clear "
     "message."),

    ("Your SSH hosts, ready to go",
     "The drives picker ({key:drives}) lists the hosts from your "
     "`~/.ssh/config` automatically as `ssh://` locations — nothing to "
     "configure in XeFM to browse a machine you already SSH to."),

    ("A GUI in the browser — even over SSH",
     "`xefm --backend web` serves the full GUI to your browser. It binds "
     "`127.0.0.1` only; to reach a remote machine's XeFM, forward the port "
     "through an SSH tunnel — the startup message prints the exact command "
     "to paste."),

    ("Start where you mean to",
     "`xefm --left DIR --right DIR` opens each pane on a chosen directory, "
     "and `--backend tui|gui|web` picks the frontend — handy in a shell "
     "alias for a project you visit daily."),

    ("The log pane is a pane too",
     "The log under the file panes scrolls with {key:scroll_log_up} / "
     "{key:scroll_log_down} and resizes with {key:adjust_log_up} / "
     "{key:adjust_log_down} — older messages are never gone, just above the "
     "fold."),

    ("Take the log with you",
     "Select log text by dragging across it — the copy keys "
     "({key:copy_log_selection}) then put the highlight on the clipboard. "
     "To hand someone the whole thing — a bug report, say — "
     "**Edit ▸ Copy All Logs** takes every line, including the ones scrolled "
     "out of sight."),

    ("Make XeFM yours",
     "Every key binding and many behaviors live in `~/.xefm/config.py`. "
     "**Tools ▸ Edit Configuration…** opens it in your editor, and "
     "**Tools ▸ Reload Configuration** applies the changes without "
     "restarting."),

    ("Your own tools, one keystroke away",
     "{key:programs} runs an external program on the current selection — and "
     "the menu is yours to extend. Add entries to `PROGRAMS` in "
     "`~/.xefm/config.py` pointing at any command, and drop personal scripts "
     "in `~/.xefm/tools/`, where the `xefm_tool()` helper finds them. That "
     "folder starts you off with an editable `example_tool.py`."),

    ("Associate your favorite apps",
     "`FILE_ASSOCIATIONS` in `~/.xefm/config.py` maps filename patterns to "
     "the commands used to **open**, **view**, and **edit** them — per "
     "pattern, per verb — so a PDF can view in one app while an image edits "
     "in another."),

    ("A theme of your very own",
     "`THEMES` in `~/.xefm/config.py` defines new themes: inherit a base, "
     "override any colors — and on GUI backends add a `post_effect` "
     "(CRT-style glow and scanlines), an `animation` behind the UI "
     "(starfield, rain, wave…), or a `wallpaper` image."),

    ("Walk through your selection",
     "With several files selected, {key:cursor_next_selected} / "
     "{key:cursor_prev_selected} jump the cursor straight to the next / "
     "previous selected item, skipping everything in between — handy for "
     "double-checking a scattered selection before a copy or a delete."),

    ("Legacy text encodings",
     "The text viewer detects a file's encoding automatically — UTF-8 with or "
     "without BOM, Shift-JIS, EUC-JP, ISO-2022-JP and more — and shows what it "
     "chose in the header. When a file is detected wrong, {key:change_encoding} "
     "in the viewer picks the encoding explicitly."),

    ("Japanese search without an IME",
     "Incremental search speaks **Migemo**: typed romaji matches the Japanese "
     "it could spell, so `kensaku` in {key:isearch} also finds 検索 or ケンサク "
     "— in the file panes, the text and diff viewers, and the pickers' filter "
     "fields. It kicks in from the third character, plain matching always "
     "still applies, and `MIGEMO_SEARCH = False` in `~/.xefm/config.py` turns "
     "it off."),

    ("Select files while searching",
     "Incremental search ({key:isearch}) selects, too: "
     "{key:isearch.toggle_select_down} marks the current match and moves to the "
     "next one, and {key:isearch.select_matches} marks the whole set the counter "
     "is showing — type `.log`, press it, and every log file is selected. "
     "Space cannot do either: the search reads it as the separator between the "
     "pattern's words."),

    ("Bugs, ideas, requests",
     "XeFM is developed in the open. Found a bug, or missing a feature? "
     f"Issues and requests are very welcome at {GITHUB_URL}/issues"),
)


def tip_count() -> int:
    """How many tips are in the rotation."""
    return len(TIPS)


def referenced_actions() -> set[str]:
    """Every keymap action named by a ``{key:...}`` placeholder across all
    tips — for tests to check against the real keymap, so a typo'd action name
    can't silently render as unbound."""
    actions: set[str] = set()
    for _title, body in TIPS:
        actions.update(_KEY_REF.findall(body))
    return actions


def render_tip(index: int, resolve: Callable[[str], str] | None = None) -> str:
    """The Markdown source for tip ``index`` (taken modulo the rotation):
    a heading from the title, then the body with every ``{key:action}``
    placeholder replaced by the resolved key label as a ``code`` span.

    ``resolve`` maps an action name to its display key label (the app passes
    ``XeFMApp._keys_label``, so tips track the live keymap); ``None`` renders
    the action name itself, keeping the text legible without an app around."""
    title, body = TIPS[index % len(TIPS)]

    def sub(match: re.Match[str]) -> str:
        action = match.group(1)
        label = resolve(action) if resolve is not None else action
        return f"`{label}`"

    return f"### {title}\n\n{_KEY_REF.sub(sub, body)}"

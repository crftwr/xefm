"""The Tip of the Day content (issue #261): a rotation of short feature
introductions shown by :mod:`xefm.tips_dialog`.

Each tip is a ``(title, body)`` pair. The body is Markdown (rendered by PuiKit's
``MarkdownView``), and may reference key bindings as ``{key:action}``
placeholders — :func:`render_tip` resolves those against the *live* keymap at
display time, so a tip never quotes a key the user has rebound away. Actions are
the same names the help dialog uses (``XeFMApp._HELP_SECTIONS``); an unbound
action renders as ``—``, exactly like help.

Adding a tip is appending a pair to :data:`TIPS` — order matters only for the
first entry, the Welcome tip a brand-new user sees on first launch. The rotation
index persisted by the app is taken modulo :func:`tip_count`, so the list can
grow (or shrink) between versions without invalidating anyone's saved position.
"""

from __future__ import annotations

import re
from typing import Callable

#: ``{key:action}`` — the action name a placeholder carries.
_KEY_REF = re.compile(r"\{key:([a-z0-9_]+)\}")

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
     "{key:select_file} toggles selection on the focused item and moves down; "
     "{key:select_file_up} toggles and moves up. {key:select_all} selects "
     "everything, and {key:unselect_all} clears the selection."),

    ("Jump to a file by typing",
     "Press {key:search} and just start typing — the cursor jumps to the first "
     "matching name in the pane as each character narrows the match."),

    ("Filter the listing",
     "{key:filter} narrows the pane to names matching a pattern, and "
     "{key:clear_filter} shows everything again. Handy in a directory with "
     "hundreds of entries."),

    ("Search the whole tree",
     "{key:search_dialog} finds files by name recursively under the current "
     "directory, and {key:search_content} searches *inside* files (grep). "
     "Results stream in as they are found."),

    ("Favorite directories",
     "{key:favorites} opens a searchable picker of your favorite directories "
     "for a one-keystroke jump. Define them in `FAVORITE_DIRECTORIES` in "
     "`~/.xefm/config.py` (**Tools ▸ Edit Configuration…** opens it)."),

    ("Jump to any path",
     "{key:jump_to_path} prompts for a path — with filename completion — and "
     "takes the active pane straight there. Pasting a path works too."),

    ("Revisit recent directories",
     "{key:history} lists the directories you have visited recently, "
     "most-recent first. Pick one to jump back."),

    ("Keep the panes in sync",
     "{key:sync_current_to_other} moves the active pane to the *other* pane's "
     "directory; {key:sync_other_to_current} sends this directory to the other "
     "pane. Perfect just before a copy or a compare."),

    ("Sorting, fast and slow",
     "{key:sort_menu} opens the sort dialog. Even quicker: "
     "{key:quick_sort_name} / {key:quick_sort_size} / {key:quick_sort_date} / "
     "{key:quick_sort_ext} sort by name, size, date or extension directly — "
     "and pressing the same key again reverses the order."),

    ("Hidden files",
     "{key:toggle_hidden} shows or hides hidden files (dotfiles). The setting "
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
     "{key:edit_file} opens the focused file in the editor named by your "
     "`$EDITOR` environment variable, right from the pane."),

    ("Archives are directories",
     "Press {key:open_item} on a zip or tar archive to browse *inside* it like "
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

    ("Your own tools, one keystroke away",
     "{key:programs} runs an external program on the current selection. The "
     "menu comes from `PROGRAMS` in `~/.xefm/config.py`, so you can wire in "
     "your own scripts and tools."),

    ("Batch rename with a regex",
     "Select more than one file and press {key:rename_file}: the rename prompt "
     "becomes a regex-based batch-rename dialog that renames the whole "
     "selection in one go."),

    ("Remote file systems",
     "XeFM browses remote locations too: give {key:jump_to_path} a URL like "
     "`ssh://host/path` or `s3://bucket/` and use the pane like a local "
     "directory."),

    ("Drives and locations",
     "{key:drives_dialog} opens a picker of mounted volumes, common locations, "
     "and your configured SSH hosts and S3 buckets — one list, one jump."),

    ("Make XeFM yours",
     "Every key binding and many behaviors live in `~/.xefm/config.py`. "
     "**Tools ▸ Edit Configuration…** opens it in your editor, and "
     "**Tools ▸ Reload Configuration** applies the changes without "
     "restarting."),
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

#!/usr/bin/env python3
"""
XeFM action registry — named actions, grouped by the surface that consumes keys.

Every key-driven behavior in XeFM is a **named action**. Until this module
existed the names lived in two disconnected places: the main window resolved a
key to a name through ``KEY_BINDINGS`` and then ran it through a long ``if/elif``
chain, while each modal viewer compared raw keys inline — so a viewer's ``n``
(next diff block) or ``PAGE_DOWN`` (scroll) was invisible to the config and
could not be rebound.

The registry closes that gap. It holds, per **context**, the metadata for each
action: its name, a one-line description, the keys it is bound to out of the box
and its selection requirement. Key resolution (:mod:`xefm.config`) and the help
dialogs read those tables; the *behavior* stays with whoever owns the surface —
:class:`xefm.app.XeFMApp` and each viewer keep a ``{name: handler}`` table of
bound methods, since a bound method cannot exist at import time. ``Action.func``
is therefore ``None`` for built-ins and holds the callable only for user actions
loaded from a config's ``ACTIONS`` (see :mod:`xefm.user_api`).

Contexts
--------

A context names one key-consuming surface. ``common`` holds the handful of
actions every surface understands — ``quit``, ``help``, ``search``,
``edit_file`` — and every other context inherits it, so one rebind of ``quit``
applies in the file list and inside every viewer, exactly as before.

Names
-----

``KEY_BINDINGS`` stays one flat dictionary, so context lives in the *name*.
Every action a surface owns is dot-qualified with its context
(``file_diff.next_block``, ``image_viewer.zoom_in``), which keeps the one flat
namespace collision-free and reads properly in the help dialog. The file list's
own actions stay unqualified: ``filer`` is the namespace's incumbent, every
config in existence binds those names, and letting the dot mean "not the file
list" is worth more than uniformity.

Names that have changed keep their old spelling in ``Action.aliases``. A config
binding an alias still resolves to the action, and XeFM says so once at load —
which is what makes correcting a name possible at all. Aliases are permanent;
never reuse one for a different action.

The same dotted form also *scopes* an inherited action: a config may write
``'file_diff.quit': ['x']`` to rebind ``quit`` inside the file diff viewer only,
leaving it alone everywhere else. See ``KeyBindings._context_entries``.

Defaults
--------

``_copy_missing_fields`` fills in whole config *fields*, not missing keys inside
one — so a config written before an action existed has no entry for it, and
never will. Each action therefore carries its own default keys, used whenever the
config does not mention the name. For actions that already ship in the
``_config.py`` template the defaults are read straight from it, so the two can
never drift; the new dotted actions declare theirs here.
"""

from dataclasses import dataclass
from typing import Callable, Iterable

from xefm.log_manager import getLogger
from xefm.search_options import SEARCH_OPTIONS
from xefm.search_filters import SEARCH_FILTERS


logger = getLogger("Actions")


# --------------------------------------------------------------------------- #
# Contexts
# --------------------------------------------------------------------------- #

#: Actions every surface understands. Inherited by every context below.
COMMON = "common"
#: The main window (the two file panes).
FILER = "filer"
#: The modal text / rich-content viewer.
TEXT_VIEWER = "text_viewer"
#: The modal image viewer.
IMAGE_VIEWER = "image_viewer"
#: The modal two-file diff viewer. Named for what it diffs rather than after
#: its module, so it pairs with ``dir_diff`` — the two are symmetric surfaces
#: and reading ``diff_viewer`` next to ``dir_diff`` never made clear which was
#: which.
FILE_DIFF = "file_diff"
#: The modal recursive directory-diff viewer.
DIR_DIFF = "dir_diff"
#: The incremental-search bar — the footer overlay the file panes and the
#: viewers share (``xefm.isearch_bar.ISearchBar``). A surface like any other
#: while it is up: it is the focus root and every key goes to it first. It is
#: also the one context whose keys compete with *typing*, which is why the bar
#: resolves a key here only after the text field has had its say, and runs only
#: the actions it owns — see ``ISearchBar.handle_event``.
ISEARCH = "isearch"
#: The modal searchable-list picker (``xefm.filter_list_dialog``) behind
#: Favorites, Drives, History, External Programs and the ';' Filter prompt. Its
#: keys compete with typing for the same reason ``isearch``'s do — the query
#: field holds focus and every printable key belongs to the query — so only
#: modified or non-printable keys can reach an action here.
FILTER_LIST = "filter_list"
#: The modal live search dialog (``xefm.progressive_search_dialog``) behind
#: ``find_files`` / ``find_in_files``. A third surface whose keys compete with
#: typing, for the
#: same reason ``isearch``'s and ``filter_list``'s do — and the first one to
#: carry live options, which is why it is where the ``options`` key starts.
SEARCH = "search"

#: Every context a binding or a user action may name, most-specific first.
#: ``common`` is deliberately included: a config may bind (or a future release
#: may allow overriding) an action there.
CONTEXTS = (FILER, TEXT_VIEWER, IMAGE_VIEWER, FILE_DIFF, DIR_DIFF, ISEARCH,
            FILTER_LIST, SEARCH, COMMON)

#: The contexts whose keys compete with a text field. Every one of them is
#: subject to the printable-key rule stated on ``isearch`` below, and
#: ``xefm.config.printable_text_bindings`` reports a config that breaks it.
TEXT_SURFACES = (ISEARCH, FILTER_LIST, SEARCH)


# --------------------------------------------------------------------------- #
# Action
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Action:
    """One named action within one context.

    ``func`` is the callable for a **user** action (``source == "user"``), loaded
    from a config's ``ACTIONS``. Built-in actions leave it ``None``: their
    behavior is a bound method of the live app or viewer, looked up by name in
    that object's own handler table. What the registry stores for a built-in is
    everything that must be known *without* a running instance — the name, what
    it does, and how it is bound by default.

    ``default_keys`` of ``None`` means "read the AFX keymap table"
    (:mod:`xefm.keymap_afx`), which is where every built-in action's keys live.
    An explicit tuple (including an empty one, for a deliberately unbound
    action) overrides that lookup.
    """

    name: str
    context: str = FILER
    description: str = ""
    default_keys: tuple[str, ...] | None = None
    selection: str = "any"
    func: Callable | None = None
    source: str = "builtin"
    #: Names this action used to have. A config binding an alias still works,
    #: resolving to this action; XeFM says so once at load. Aliases are how a
    #: name can be corrected without breaking the configs that already use it,
    #: so they are permanent — never reuse one for a different action.
    aliases: tuple[str, ...] = ()
    #: What the one-line ``description`` leaves out, in Markdown: what the
    #: action needs, how it treats the selection, what else touches it. Shown
    #: on the command palette's help page (``describe_list_item``); empty where
    #: the one line says it all. The pair is a docstring's two halves — summary
    #: line and body — and a user action's are split from its docstring that
    #: way (see :func:`xefm.user_api._build_action`).
    details: str = ""

    @property
    def is_user(self) -> bool:
        return self.source == "user"

    def resolved_default_keys(self) -> tuple[str, ...]:
        """The keys this action is bound to when the config never mentions it."""
        if self.default_keys is not None:
            return self.default_keys
        keys, _selection = _template_binding(self.name)
        return keys

    def resolved_selection(self) -> str:
        """The selection requirement ('any' / 'required' / 'none') for this
        action's default binding."""
        if self.default_keys is not None:
            return self.selection
        _keys, selection = _template_binding(self.name)
        return selection or self.selection


# --------------------------------------------------------------------------- #
# Built-in defaults
# --------------------------------------------------------------------------- #

_template_cache: dict[str, tuple[tuple[str, ...], str]] | None = None


def _template_bindings() -> dict[str, tuple[tuple[str, ...], str]]:
    """``{name: (keys, selection)}`` from the AFX keymap table
    (:mod:`xefm.keymap_afx`) — what an action is bound to when the table in
    force never mentions it. Every preset's table starts from that one, so
    only an action no table names reaches this.

    Read lazily and cached: importing the table at module import would drag
    the backend-detection stack into every consumer of this module, and tests
    import the registry standalone.
    """
    global _template_cache
    if _template_cache is not None:
        return _template_cache
    table: dict[str, tuple[tuple[str, ...], str]] = {}
    try:
        from xefm.keymap_afx import bindings as _afx_bindings
        raw = _afx_bindings()
        for name, binding in raw.items():
            if isinstance(binding, dict):
                keys = tuple(binding.get("keys") or ())
                selection = binding.get("selection", "any")
            elif isinstance(binding, (list, tuple)):
                keys, selection = tuple(binding), "any"
            else:
                continue
            table[name] = (keys, selection)
    except Exception as exc:  # pragma: no cover - a broken template is fatal elsewhere
        logger.error(f"Could not read template key bindings: {exc}")
    _template_cache = table
    return table


def _template_binding(name: str) -> tuple[tuple[str, ...], str]:
    return _template_bindings().get(name, ((), "any"))


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #

class ActionRegistry:
    """Per-context action tables.

    Lookup walks the named context first and then ``common``, so an inherited
    action is visible everywhere while a context keeps the right to define its
    own action of the same name.

    ``generation`` bumps on every mutation. :class:`xefm.config.KeyBindings`
    caches a compiled per-context key table and re-derives it when the number
    changes, which is what makes a config reload — where every ``source ==
    "user"`` entry is dropped and rebuilt — take effect without a restart.
    """

    def __init__(self) -> None:
        self._tables: dict[str, dict[str, Action]] = {}
        #: Built-ins a user action has shadowed, kept so ``invoke()`` can still
        #: reach them and so dropping the user entry restores them.
        self._overridden: dict[str, dict[str, Action]] = {}
        #: ``{context: {old_name: current_name}}``, rebuilt on demand.
        self._aliases: dict[str, dict[str, str]] = {}
        self._alias_generation: int | None = None
        self.generation = 0

    # --- mutation ---------------------------------------------------------- #

    def register(self, action: Action, *, override: bool = False) -> bool:
        """Add ``action`` to its context. Returns whether it was accepted.

        A name already taken *in the same context* is refused unless ``override``
        is set — the guard that stops a user action from silently shadowing a
        built-in. Overriding does not discard the built-in: it is kept aside so
        ``ActionContext.invoke()`` can still reach it, which is what makes
        before/after decoration of a built-in possible.
        """
        table = self._tables.setdefault(action.context, {})
        existing = table.get(action.name)
        if existing is not None and not override:
            return False
        if existing is not None and existing.source == "builtin":
            self._overridden.setdefault(action.context, {})[action.name] = existing
        table[action.name] = action
        self.generation += 1
        return True

    def register_many(self, actions: Iterable[Action]) -> None:
        for action in actions:
            self.register(action)

    def unregister_source(self, source: str) -> int:
        """Drop every action with the given ``source`` (``"user"`` on reload) and
        restore any built-in they had overridden. Returns how many were removed."""
        removed = 0
        for context, table in self._tables.items():
            for name in [n for n, a in table.items() if a.source == source]:
                del table[name]
                removed += 1
                shadowed = self._overridden.get(context, {}).pop(name, None)
                if shadowed is not None:
                    table[name] = shadowed
        if removed:
            self.generation += 1
        return removed

    # --- lookup ------------------------------------------------------------ #

    def resolve(self, context: str, name: str) -> Action | None:
        """The action ``name`` means in ``context`` — its own table first, then
        ``common``. ``None`` when the context does not understand the name."""
        action = self._tables.get(context, {}).get(name)
        if action is not None:
            return action
        if context != COMMON:
            return self._tables.get(COMMON, {}).get(name)
        return None

    def builtin(self, context: str, name: str) -> Action | None:
        """The built-in ``name`` in ``context``, even when a user action has
        overridden it — what ``ActionContext.invoke()`` falls back to."""
        shadowed = self._overridden.get(context, {}).get(name)
        if shadowed is not None:
            return shadowed
        action = self.resolve(context, name)
        if action is not None and not action.is_user:
            return action
        if context != COMMON:
            return self._overridden.get(COMMON, {}).get(name)
        return None

    def _alias_table(self, context: str) -> dict[str, str]:
        """``{old_name: current_name}`` for one context, its own actions before
        the inherited ``common`` ones."""
        if self._alias_generation != self.generation:
            self._aliases.clear()
            self._alias_generation = self.generation
        table = self._aliases.get(context)
        if table is None:
            table = {}
            for action in self.actions(context):
                for alias in action.aliases:
                    table.setdefault(alias, action.name)
            self._aliases[context] = table
        return table

    def canonical(self, context: str, name: str) -> str | None:
        """The action ``name`` refers to in ``context``: itself when it is a
        current name, the current name when it is an alias, ``None`` when the
        context does not understand it at all.

        A current name always wins — a config carrying both an old and a new
        name for the same action gets the new one, not whichever it listed
        first."""
        if self.resolve(context, name) is not None:
            return name
        return self._alias_table(context).get(name)

    def aliases_in(self, context: str) -> dict[str, str]:
        """Every ``{old_name: current_name}`` pair this context understands."""
        return dict(self._alias_table(context))

    def actions(self, context: str) -> list[Action]:
        """Every action ``context`` understands, its own before the inherited
        ``common`` ones, each in registration order."""
        own = list(self._tables.get(context, {}).values())
        if context == COMMON:
            return own
        inherited = [a for a in self._tables.get(COMMON, {}).values()
                     if a.name not in self._tables.get(context, {})]
        return own + inherited

    def names(self, context: str) -> list[str]:
        return [a.name for a in self.actions(context)]

    def user_actions(self, context: str | None = None) -> list[Action]:
        contexts = [context] if context else list(self._tables)
        return [a for c in contexts
                for a in self._tables.get(c, {}).values() if a.is_user]

    def has_context(self, context: str) -> bool:
        return context in self._tables

    def contexts(self) -> list[str]:
        """Every context with an action table, ``common`` included."""
        return list(self._tables)


def _new_registry() -> ActionRegistry:
    """A registry holding only the built-in actions — the process-wide one
    below, and a clean slate for tests that need their own."""
    registry = ActionRegistry()
    registry.register_many(_BUILTIN_ACTIONS)
    return registry


# --------------------------------------------------------------------------- #
# Built-in action tables
# --------------------------------------------------------------------------- #
#
# Order matters: it is the order two actions of the same context are tried in
# when a key matches both, and the order the generated help lists them. Actions
# whose ``default_keys`` are omitted read them from the AFX keymap table.

def _a(name, context, description, **kw) -> Action:
    if context in (FILER, COMMON):
        kw.setdefault("details", _DETAILS.get(name, ""))
    return Action(name=name, context=context, description=description, **kw)


# The command palette's help page for the file list's actions (``Action.details``)
# — kept here rather than inline so the tables below stay readable as the list
# of what each surface can do. Only actions with more to say than their
# one-line description have an entry; the page shows the description, the keys
# and the selection requirement on its own. Read for the ``filer`` and
# ``common`` contexts only: ``copy_files`` in ``dir_diff`` is the same name
# doing a different thing.
#
# Written for the person running the action — what it acts on, where the
# result goes, what it refuses — never how it is built.
_DETAILS: dict[str, str] = {
    # --- common ---
    "quit": (
        "In the file list, asks for confirmation and then quits XeFM. Inside a "
        "viewer the same key closes the viewer and returns to the file list."),
    "help": (
        "Lists every key the current screen answers to, generated from your "
        "key bindings — so a key you rebound in `config.py` shows up there as "
        "you bound it. Each viewer has its own page."),
    "isearch": (
        "Opens a search bar in the active pane's footer. Type part of a name: "
        "every match is highlighted and the cursor jumps to the nearest one. "
        "Words separated by spaces must all match, and romaji also finds "
        "Japanese names (Migemo).\n\n"
        "While the bar is open, ↑/↓ move between matches, Ctrl-Space marks the "
        "current match, Ctrl-A marks every match, Enter stops at the current "
        "match and Esc puts the cursor back where it was. Those are the "
        "default keys; the Help dialog lists yours."),
    "edit_file": (
        "Opens the selected files — or the file under the cursor when nothing "
        "is selected — in your editor. An `edit` rule in `FILE_ASSOCIATIONS` "
        "picks the program per file type; otherwise `TEXT_EDITOR` is used. "
        "Files that go to the same editor open in one session.\n\n"
        "A file on a writable remote (SSH, S3) is downloaded to a local copy "
        "under `~/.xefm/edit/`, and every save of that copy is uploaded back — "
        "after a question if the remote file changed meanwhile. A failed "
        "upload keeps the copy and says where it is. Files inside archives "
        "are read-only and are skipped, with a note in the log."),
    # --- navigation ---
    "open_item": (
        "On a directory, enters it. On an archive XeFM can read, browses it "
        "like a directory (read-only; going to the parent leaves it). On any "
        "other file, opens it in the built-in viewer.\n\n"
        "An `enter` rule in `FILE_ASSOCIATIONS` can change what happens to a "
        "file type: `'viewer'`, `'navigate'` (browse as an archive), `'list'` "
        "(open as a file list) or `None` (do nothing)."),
    "open_with_os": (
        "Hands the file under the cursor to another application — the "
        "operating system's default for that type, or the `open` rule in "
        "`FILE_ASSOCIATIONS`. A rule set to `None` stops the file type from "
        "being opened this way at all."),
    "open_with": (
        "Lists the applications that can open the selected files — or the "
        "file under the cursor — and opens them in the one you pick: first "
        "the `open_with` entries of the `FILE_ASSOCIATIONS` rules the files "
        "match, then the applications the operating system offers (in the "
        "desktop app, or a terminal on this computer). With several files, "
        "only the applications that open all of them are listed, and they "
        "all go to it at once. The app you chose last for a file type is "
        "listed first.\n\n"
        "Directories are skipped, and so are files on a remote or in an "
        "archive: an application needs a file on this computer."),
    "reveal_in_os": (
        "Shows the item under the cursor in Finder or Explorer, highlighted. "
        "Elsewhere, opens its parent directory in the system file manager."),
    "go_parent": (
        "Goes up one directory and puts the cursor on the one you came from. "
        "On a search-results or file-list pane it leaves the list and returns "
        "to the directory it was opened from; inside an archive at its top, "
        "it leaves the archive."),
    "go_root": (
        "Jumps straight to the top of wherever the pane is: the drive root on "
        "Windows, `/` on macOS and Linux, the bucket root on S3, the host's "
        "root over SFTP."),
    "nav_left": (
        "In the right pane, makes the left pane active. Already in the left "
        "pane, goes to the parent directory — so the arrow always moves "
        "\"outwards\"."),
    "nav_right": (
        "In the left pane, makes the right pane active. Already in the right "
        "pane, goes to the parent directory — so the arrow always moves "
        "\"outwards\"."),
    # --- selection ---
    "toggle_select_items": (
        "Inverts the mark on every item in the pane, directories included: "
        "marked items are cleared and the rest are marked."),
    "toggle_select_files": (
        "Inverts the mark on every file in the pane, leaving directories "
        "alone: marked files are cleared and the rest are marked."),
    "select_range": (
        "Marks every item between the cursor and the nearest marked item — "
        "the keyboard's Shift-click. The nearest mark above the cursor is the "
        "anchor (below, when there is none above). Nothing outside the span is "
        "touched, so several ranges add up.\n\n"
        "In Terminal.app, iTerm2 and Linux terminals Shift-Space arrives as a "
        "plain Space; bind this to a key the terminal can send (for example "
        "`Ctrl-Y`) if you work there."),
    "select_by_pattern": (
        "Asks for a file-name pattern and adds every file it matches to the "
        "selection; what was selected already stays selected. The pattern is "
        "written as for **Filter**: several separated by spaces (`*.jpg *.png`), "
        "or the name of a filter defined in `FILTERS` in `config.py`, and the "
        "list offers the patterns you used before. Directories are never "
        "selected this way."),
    "unselect_by_pattern": (
        "The same prompt as **Select by pattern**, removing the matching files "
        "from the selection instead. Everything else stays selected."),
    "select_same_extension": (
        "Adds every file with the same extension as the one under the cursor "
        "to the selection, without asking: on `photo.JPG` it selects every "
        "`.jpg`, whatever its case. On a file with no extension it selects the "
        "other files with none."),
    "cursor_next_selected": (
        "Moves the cursor to the next marked item below it. When there is "
        "none, the cursor stays and the log says so."),
    "cursor_prev_selected": (
        "Moves the cursor to the previous marked item above it. When there "
        "is none, the cursor stays and the log says so."),
    # --- clipboard ---
    "copy_names": (
        "Copies the names of the selected items — or of the item under the "
        "cursor when nothing is selected — one per line. On a search-results "
        "pane the name includes the path below the search root, so it still "
        "says which hit it was.\n\n"
        "In a terminal the copy travels by OSC 52, which most terminals pass "
        "to the system clipboard (Terminal.app does not)."),
    "copy_paths": (
        "Copies the full paths of the selected items — or of the item under "
        "the cursor when nothing is selected — one per line. The inverse of "
        "Open List ▸ From Clipboard."),
    # --- file operations ---
    "copy_files": (
        "Copies the selected items — or the item under the cursor when "
        "nothing is selected — into the directory shown in the other pane. "
        "Directories are copied with everything in them.\n\n"
        "When a name already exists there you choose Overwrite, Skip or Keep "
        "both, once or for all. If both panes show the same directory the "
        "copy becomes a duplicate named like `report (2).txt`. The other pane "
        "cannot be a search-results view or an archive."),
    "move_files": (
        "Moves the selected items — or the item under the cursor when nothing "
        "is selected — into the directory shown in the other pane, with the "
        "same name-conflict choices as copy.\n\n"
        "Its default key is shared with `create_directory`: with something "
        "marked the key moves, with nothing marked it makes a directory. "
        "Moving out of an archive is refused — copy instead."),
    "copy_files_to": (
        "Like copy, but asks where to. The prompt starts with the other "
        "pane's directory and completes directory names with Tab; a relative "
        "path is taken from the active pane, so `.` means here and `..` its "
        "parent."),
    "move_files_to": (
        "Like move, but asks where to. The prompt starts with the other "
        "pane's directory and completes directory names with Tab; a relative "
        "path is taken from the active pane, so `.` means here and `..` its "
        "parent."),
    "duplicate_files": (
        "Copies the selected items — or the item under the cursor — into the "
        "same directory, named the way Finder does: `report (2).txt`. Also on "
        "the File menu and the context menu."),
    "delete_files": (
        "Moves the selected items — or the item under the cursor when nothing "
        "is selected — to the system's Trash (the Recycle Bin on Windows), "
        "after a confirmation (`CONFIRM_TRASH`). They can be restored from "
        "Finder, Explorer or your desktop's file manager.\n\n"
        "Where there is no Trash — SSH, S3, inside archives, and USB or "
        "network drives on Windows — the items are deleted for good instead, "
        "and the confirmation says so. `DELETE_TO_TRASH = False` makes this "
        "always delete for good."),
    "delete_permanently": (
        "Deletes the selected items — or the item under the cursor — for "
        "good, without going through the Trash, after a confirmation "
        "(`CONFIRM_DELETE`). Directories are deleted with everything in them."),
    "rename": (
        "With one item, or none selected, asks for a new name for the item "
        "under the cursor. With several items selected, opens batch rename: "
        "a regular-expression find and replace across all of them, with a "
        "preview before anything changes."),
    "rename_in_editor": (
        "Writes the selected names — or the name under the cursor — to a "
        "text file, one per line, and opens it in `TEXT_EDITOR`. Change the "
        "names in place and save; each changed line renames its file, after "
        "a confirmation listing every change. Lines cannot be added or "
        "removed, and swapped names are handled.\n\n"
        "When the editor opens in its own window, XeFM waits for you to "
        "choose Apply once the file is saved."),
    "create_file": (
        "Asks for a name and creates an empty file in the active pane's "
        "directory, with the cursor on it."),
    "create_directory": (
        "Asks for a name and creates a directory in the active pane's "
        "directory, with the cursor on it.\n\n"
        "Its default key is shared with `move_files`: the key makes a "
        "directory only while nothing is marked."),
    # --- viewing ---
    "view_file": (
        "Opens the file under the cursor in a viewer. A `view` rule in "
        "`FILE_ASSOCIATIONS` can name an external program; otherwise the "
        "built-in viewer picks by type — text with syntax highlighting, "
        "rendered Markdown, a JSON tree, a CSV grid, images. Files on remote "
        "and archive panes always use the built-in viewer."),
    "file_details": (
        "Shows size, dates, permissions and the rest for the item under the "
        "cursor, or a summary plus details for each selected item. For a "
        "directory the total size and item count are added up in the "
        "background, and the numbers climb while the dialog is open."),
    "diff_files": (
        "Compares two files side by side, differences highlighted. Mark "
        "exactly two files first — both in one pane, or one in each."),
    "diff_directories": (
        "Compares the directories shown in the two panes, recursively, as two "
        "trees side by side with the differences marked. From there you can "
        "open a file diff, and copy, move or delete across the two sides."),
    # --- archives ---
    "create_archive": (
        "Packs the selected items — or the item under the cursor — into an "
        "archive in the other pane's directory. The name you type picks the "
        "format by its extension (`.zip`, `.tar.gz`, …); a name with "
        "no recognised extension gets `.tar.gz`. Help ▸ Keyboard Shortcuts "
        "lists the formats this installation can write."),
    "extract_archive": (
        "Extracts the selected archives — or the one under the cursor — each "
        "into a directory named after it in the other pane's directory. "
        "Asks first when a destination already exists. Selected items that "
        "are not archives are skipped and reported, and a password is asked "
        "for when an archive needs one."),
    # --- search and filter ---
    "find_files": (
        "Searches for file names below the active pane's directory, showing "
        "results as you type. Tab switches to content search, and the options "
        "key (Ctrl-O by default) sets case, regular expressions and "
        "subfolders.\n\n"
        "Enter puts every result into the pane as a list you can work on like "
        "a directory, with the cursor on the hit you chose; Backspace returns "
        "to the directory."),
    "find_in_files": (
        "Searches inside the text files below the active pane's directory, "
        "showing matching lines as you type. Tab switches to file-name "
        "search, and the options key (Ctrl-O by default) sets case, whole "
        "words, regular expressions and subfolders.\n\n"
        "Enter puts the matching files into the pane, one row per file, with "
        "the cursor on the one you chose; Backspace returns to the "
        "directory."),
    "filter": (
        "Shows only the files whose names match a pattern (`*.py`, "
        "`*report*`); directories always stay visible. The list offers the "
        "filters defined in `FILTERS` in `config.py` and the patterns you used "
        "before. The pane's status bar shows the active filter."),
    "clear_filter": (
        "Removes the active pane's file-name filter, so every file shows "
        "again."),
    "sort": (
        "Opens the sort dialog for the active pane: ↑/↓ choose what to sort "
        "by, ←/→ the order, and the letters F, E, S and T pick name, "
        "extension, size and time directly. An example of the result is "
        "shown at the bottom."),
    "quick_sort_name": (
        "Sorts the active pane by name. Pressing it again while already "
        "sorted by name reverses the order."),
    "quick_sort_ext": (
        "Sorts the active pane by extension. Pressing it again while already "
        "sorted by extension reverses the order."),
    "quick_sort_size": (
        "Sorts the active pane by size. Pressing it again while already "
        "sorted by size reverses the order."),
    "quick_sort_date": (
        "Sorts the active pane by modification time. Pressing it again while "
        "already sorted by time reverses the order."),
    # --- directory navigation ---
    "favorites": (
        "Lists your favorites — those in `FAVORITES` in `config.py` and those "
        "you added — and takes the active pane to the one you pick. A "
        "favorite file opens its directory with the cursor on it. The list's "
        "remove key (Shift-Delete by default) forgets a favorite you added.\n\n"
        "Tags you have used follow the favorites. Picking one lists the files "
        "below the pane's directory that carry that tag (Spotlight answers on "
        "macOS; elsewhere the folder is searched)."),
    "add_favorite": (
        "Adds a favorite or tags files. The first rows add a favorite: the "
        "directory the pane is showing, or the item under the cursor, which "
        "may be a file. The tag rows act on the selection, or on the item "
        "under the cursor when nothing is selected: each known tag is a toggle "
        "(✓ when every item has it), and \"Edit tags…\" edits them as text.\n\n"
        "Tags are the system's own: Finder tags on macOS, `user.xdg.tags` on "
        "Linux (as in KDE), object tags on S3, and the remote system's on "
        "SSH. On Windows XeFM keeps them in an NTFS stream on the file."),
    "context_menu": (
        "Opens the menu a right-click on the item under the cursor would "
        "open, just below it. In an empty pane, opens the directory's menu "
        "instead."),
    "context_menu_dir": (
        "Opens the menu a right-click on the empty part of the pane would "
        "open — the operations on the directory itself."),
    "jump_to_path": (
        "Asks for a path and takes the active pane there. Accepts `~`, "
        "relative and absolute paths, and `s3://` / `ssh://` addresses; Tab "
        "completes names. A path to a file opens its directory with the "
        "cursor on the file."),
    "history": (
        "Lists the directories you have visited, most recent first, and takes "
        "the active pane to the one you pick. The history survives restarts. "
        "The list's remove key (Shift-Delete by default) forgets a "
        "directory."),
    "drives": (
        "Lists drives and volumes, common locations, the SSH hosts in your "
        "config and your S3 buckets, and takes the active pane to the one you "
        "pick. Buckets appear as they load.\n\n"
        "The list's remove key (Shift-Delete by default) disconnects a network "
        "share, or ejects a removable disk."),
    "connect_server": (
        "Lists the file servers on the network and the ones you have used, "
        "asks the one you pick which shares it offers, and mounts your choice "
        "through the operating system — the pane then goes there like any "
        "other directory. macOS and Windows."),
    "index_search": (
        "Searches the index your operating system keeps — Spotlight on "
        "macOS, Windows Search on Windows — in this folder and everything "
        "below it, and shows the matches as a list. Write the query as you "
        "would in Spotlight (words, kind:pdf, date:today, metadata like "
        "kMDItemPixelWidth > 4000) or in Windows Search (words; where … for "
        "a raw SQL condition). Earlier queries are offered again."),
    "find_by_tag": (
        "Lists your tags; pick one, or type a name that is not listed, and "
        "the pane shows every file under this folder that carries it. "
        "Spotlight answers on macOS; elsewhere the folders are read. The "
        "remove key drops a tag from the list without touching any file."),
    "clipboard_copy": (
        "Puts the selected files — or the one under the cursor — on the "
        "clipboard. Nothing is copied yet: paste copies them into whatever "
        "folder you are in then, in either pane, or in another application on "
        "macOS and Windows. With text selected in the log, copies that text "
        "instead. The status bar shows what the clipboard holds."),
    "clipboard_cut": (
        "Like copy, but paste moves the files instead of copying them. The "
        "cut files are shown faded until then."),
    "clipboard_paste": (
        "Copies (or, after a cut, moves) what the clipboard holds into the "
        "folder of the active pane, asking about names that already exist. "
        "On macOS and Windows, files copied in Finder or Explorer paste too. "
        "Each pane's footer says how many names a paste there would meet."),
    "quick_view": (
        "Turns the other pane into a preview of the item under the cursor, "
        "following it as the cursor moves: the start of a text file, a "
        "picture, a hex dump of a binary, or a folder's item count and size. "
        "The other pane's own folder comes back when quick view closes. On a "
        "remote location only small files are read."),
    "jobs": (
        "Lists the copy, move and delete operations running in the "
        "background, and the ones queued behind them. Choose a running one "
        "to bring its progress dialog back — where a question it is waiting "
        "on is answered, and Esc can cancel it. Choose a queued one to drop "
        "it. Send an operation to the background with the Background button "
        "when it asks to start, or with B (or Esc) in its progress dialog."),
    "find_similar": (
        "Scans the selection, or the current folder, for files with identical "
        "content, or for similar images, videos or audio, using similar-files. The scan runs as "
        "its own process and keeps going after you quit XeFM; the status bar "
        "and the jobs list show it, and its groups can be looked at while it "
        "is still running. Each group is a folder of the results tree; select "
        "files and press Shift-O to work on the real files in the other pane. "
        "Similar videos need ffmpeg, similar audio needs fpcalc (Chromaprint); "
        "similar images need nothing more."),
    "new_tab": (
        "Opens another tab in the active pane, showing the same place, and "
        "switches to it. Each pane has its own tabs, and each tab keeps its "
        "own directory, cursor, selection, sort and filter — a search result "
        "or an imported list too. The tab strip appears above the path once a "
        "pane has more than one tab."),
    "close_tab": (
        "Closes the active pane's current tab and shows the next one. A "
        "pane's only tab cannot be closed."),
    "flat_view": (
        "Shows every file below the active pane's directory as one flat list, "
        "named relative to it — sort, filter and copy work across the whole "
        "tree. With a selection, only the selected directories and files are "
        "flattened. Press it again, or Backspace, to go back."),
    "open_list_from_clipboard": (
        "Shows the paths on the clipboard, one per line, as the active pane's "
        "listing — the files can be in many directories. Nothing on disk "
        "changes; Backspace returns to the directory. Relative lines are "
        "taken from the pane's directory."),
    "open_list_from_command": (
        "Runs a command and shows the paths it prints, one per line, as the "
        "active pane's listing — `git ls-files -m`, `rg -l TODO`, `fd -e py`. "
        "The command runs in the pane's directory with the same `XEFM_*` "
        "variables external programs get. Earlier commands are offered to "
        "run again."),
    "open_list_from_file": (
        "Shows the paths listed in the file under the cursor — or in every "
        "selected file, as one list — as the active pane's listing, one path "
        "per line. Relative lines are taken from the list file's own "
        "directory, the way M3U playlists work."),
    # --- panes ---
    "sync_current_to_other": (
        "Takes the active pane to the directory the other pane shows. When "
        "both already show the same directory, moves the cursor onto the item "
        "the other pane's cursor is on. When the other pane holds search "
        "results, goes to the directory of the highlighted result."),
    "sync_other_to_current": (
        "Takes the other pane to the directory the active pane shows. When "
        "both already show the same directory, moves the other pane's cursor "
        "onto the item under this one. On a search-results pane, shows the "
        "highlighted result's directory in the other pane."),
    "compare_selection": (
        "Marks items in the active pane by comparing each with the item of "
        "the same name in the other pane, by any mix of size (equal or "
        "different), modification time (same, newer or older) and content "
        "(equal or different). Choose whether to replace the current marks or "
        "add to them. Items with no namesake on the other side are never "
        "marked."),
    "reset_pane_boundary": "Puts the divider between the two panes back in the middle.",
    "reset_log_height": "Puts the log pane back to its default height.",
    # --- log pane ---
    "copy_log_selection": (
        "Copies the text you dragged across in the log pane with the mouse, "
        "wherever the keyboard focus is. Does nothing when no log text is "
        "selected."),
    "copy_log_all": (
        "Copies every line the log pane holds, not only the ones on screen — "
        "useful for pasting into a bug report. Also on the Edit menu."),
    # --- appearance ---
    "toggle_hidden": (
        "Shows or hides hidden items — dot-files, and files with the hidden "
        "attribute on Windows."),
    "toggle_color_scheme": (
        "Switches to the next color theme. View ▸ Theme lists them all by "
        "name."),
    "choose_layout": (
        "Chooses how the active pane presents its rows — which of the usual "
        "columns it has and how they are written: short dates, names with "
        "their extension, and so on. The choice stays with the tab. "
        "`LAYOUTS` in `config.py` defines more; what a folder adds, such as "
        "a Git status, is `choose_extras`."),
    "choose_extras": (
        "Turns an extra — a Git status, your tags, anything `LAYOUT_EXTRAS` in "
        "`config.py` or an extension adds — on or off for the active pane's "
        "tab. **Auto** shows it where it applies (a Git status in a working "
        "tree); **On** and **Off** override that for this tab. Also View ▸ "
        "Show."),
    "resolve_attribute": (
        "Works out an attribute the active pane shows that is obtained only "
        "on request, because it costs time — a folder's total size, or an "
        "`ATTRIBUTES` entry in `config.py` with `'compute': 'on_request'` — "
        "for the selected items, or the item under the cursor. A dialog names "
        "the items and lists the attributes that can be resolved for them, by "
        "name. It runs in the background "
        "and stops when you leave the folder; the sort dialog can then order "
        "this folder by the results."),
    "redraw": (
        "Repaints the whole screen — for when another program or a terminal "
        "multiplexer has written over it."),
    "menu": (
        "Opens the menu bar in the window. ←/→ move between menus, Esc "
        "closes. Where the operating system shows the menu bar itself, this "
        "key is not needed."),
    "command_palette": (
        "Lists every file-list action, including the ones no key or menu "
        "reaches and the actions your `config.py` defines. Type part of a "
        "name to narrow the list — words separated by spaces must all match, "
        "in any order — and press Enter to run the highlighted action on the "
        "active pane.\n\n"
        "Each row shows the key the action is bound to, so the palette is "
        "also a way to find out what a key is."),
    # --- external programs and configuration ---
    "programs": (
        "Lists the programs in `PROGRAMS` in `config.py` and runs the one you "
        "pick on the selected files — or the file under the cursor — in the "
        "active pane's directory. Output goes to the log pane. A program "
        "marked `'terminal': True` gets the terminal (or, in the desktop app, "
        "a terminal window) for full-screen tools like `vim`."),
    "subshell": (
        "Opens a shell in the active pane's directory. In a terminal XeFM "
        "steps aside until you exit the shell; in the desktop app the shell "
        "opens in the terminal application set by `TERMINAL`. The shell is "
        "`SUBSHELL` from `config.py`, else your `$SHELL`, and it gets the "
        "`XEFM_*` variables. Local directories only."),
    "edit_config": (
        "Opens `~/.xefm/config.py` in your `TEXT_EDITOR`, creating it on first "
        "use. In a terminal the configuration reloads when the editor exits; "
        "with an editor that opens its own window, use Reload Configuration "
        "after saving."),
    "reload_config": (
        "Re-reads `~/.xefm/config.py` and applies it without restarting: key "
        "bindings, file associations, external programs, favorites and your "
        "own actions take effect at once. Theme, fonts and layout apply on the "
        "next start, and the log says so."),
    "install_extension": (
        "Asks where the extension package is — a folder holding "
        "`xefm-extension.toml`, a `.zip` of one, an `https://` zip URL, or "
        "`github:owner/repo[/path][@ref]` (paste it) — with the package under "
        "the cursor already filled in. XeFM fetches it and runs the same check "
        "as `xefm ext check`; a package that fails is refused with every "
        "finding listed. Otherwise it shows what the package adds, and installs "
        "it on Install. The same as `xefm ext install` from a shell."),
    "check_extension_updates": (
        "Asks where each installed extension package publishes its versions "
        "(its `updates` source on GitHub) whether there is a newer one, and "
        "offers to upgrade the ones that have. Each new version goes through "
        "the same check as an install, so one this XeFM cannot run is refused "
        "and the old one stays. Reaches the network, and only when you run it: "
        "XeFM never looks on its own. The same as `xefm ext outdated` and "
        "`xefm ext upgrade` from a shell."),
    "sync_python_packages": (
        "Makes `~/.xefm/site-packages` match `~/.xefm/requirements.txt`: "
        "installs what the file lists, with pip, for the Python XeFM runs on, "
        "and removes what it no longer lists. Packages XeFM already ships win — "
        "a requirement that needs a different version of one fails the sync "
        "and the log names it. Runs in the background and reaches the network; "
        "pip's output goes to the log, and the configuration reloads when it "
        "is done. The same as `xefm deps sync` from a shell."),
}


_COMMON_ACTIONS = [
    _a("quit", COMMON, "Quit XeFM — or close the open viewer"),
    # The platform's way to quit (Cmd-Q, Alt-F4, the close button): from
    # anywhere — a dialog or a viewer open too — and asking only while a task
    # runs. ``quit`` always asks, and in a viewer closes the viewer.
    _a("quit_app", COMMON, "Quit XeFM from anywhere, asking first only while a task is running"),
    _a("help", COMMON, "Show the key bindings for what is on screen"),
    _a("isearch", COMMON, "Incremental search",
       aliases=("search",)),
    _a("edit_file", COMMON, "Edit in the configured text editor"),
]

_FILER_ACTIONS = [
    # Navigation
    _a("cursor_up", FILER, "Move the cursor up one item"),
    _a("cursor_down", FILER, "Move the cursor down one item"),
    _a("page_up", FILER, "Move the cursor up one page"),
    _a("page_down", FILER, "Move the cursor down one page"),
    # Vim's Ctrl-D / Ctrl-U (#587): half of what the pane shows.
    _a("half_page_up", FILER, "Move the cursor up half a screen"),
    _a("half_page_down", FILER, "Move the cursor down half a screen"),
    _a("cursor_top", FILER, "Move the cursor to the first item"),
    _a("cursor_bottom", FILER, "Move the cursor to the last item"),
    _a("open_item", FILER, "Open the file, or enter the directory"),
    _a("open_with_os", FILER, "Open with the OS default application"),
    _a("open_with", FILER, "Choose the application that opens the selection"),
    _a("reveal_in_os", FILER, "Reveal in the OS file manager"),
    _a("go_parent", FILER, "Go to the parent directory"),
    _a("go_root", FILER, "Go to the root of the current drive or location"),
    _a("switch_pane", FILER, "Switch between the left and right panes"),
    _a("nav_left", FILER, "Focus the left pane, or go to the parent"),
    _a("nav_right", FILER, "Focus the right pane, or go to the parent"),
    _a("focus_left", FILER, "Focus the left pane"),
    _a("focus_right", FILER, "Focus the right pane"),
    # Selection
    _a("toggle_select_down", FILER, "Toggle selection and move down",
       aliases=("select_file",)),
    _a("toggle_select_up", FILER, "Toggle selection and move up",
       aliases=("select_file_up",)),
    # vifm's t (#587): mark or unmark, and stay.
    _a("toggle_select_in_place", FILER, "Toggle selection without moving the cursor"),
    _a("select_all", FILER, "Select every item"),
    _a("unselect_all", FILER, "Clear the selection"),
    _a("toggle_select_files", FILER, "Toggle selection of every file",
       aliases=("select_all_files",)),
    _a("toggle_select_items", FILER, "Toggle selection of every item",
       aliases=("select_all_items",)),
    # The keyboard's Shift-click: mark one item, move the cursor, and this fills
    # the span between them. Shift is what other applications spend on a range,
    # and Space is already "select" here, so Shift-Space is the one key both
    # halves of that sentence agree on — which is why it took the key
    # 'toggle_select_up' used to hold (see the File Selection block of
    # _config.py). A POSIX terminal cannot deliver it: it has no room for a
    # modifier on a printable, so Shift-Space arrives there as a plain Space.
    # Deliberate, and documented for rebinding — the desktop app and the Windows
    # console, where the gesture is a convention users already have, are worth
    # more than a key no surface reads as "range".
    _a("select_range", FILER, "Select from the nearest selected item to the cursor"),
    # Vim's n / N (#587): the last incremental search's pattern, again, with
    # the bar closed.
    _a("search_next", FILER, "Go to the next match of the last incremental search"),
    _a("search_prev", FILER, "Go to the previous match of the last incremental search"),
    # #544. ' and " (Shift-') are cfiler's keys for the same thing, next to the
    # filter's ; and : — see the File Selection block of _config.py.
    _a("select_by_pattern", FILER, "Select the files matching a pattern"),
    _a("unselect_by_pattern", FILER, "Unselect the files matching a pattern"),
    # Unbound: the Select menu and the palette carry it.
    _a("select_same_extension", FILER,
       "Select every file with the cursor file's extension", default_keys=()),
    _a("cursor_next_selected", FILER, "Jump to the next selected item"),
    _a("cursor_prev_selected", FILER, "Jump to the previous selected item"),
    # Clipboard
    _a("copy_names", FILER, "Copy the file name(s) to the clipboard"),
    _a("copy_paths", FILER, "Copy the full path(s) to the clipboard"),
    # File operations
    _a("copy_files", FILER, "Copy the selection to the other pane"),
    _a("move_files", FILER, "Move the selection to the other pane"),
    _a("copy_files_to", FILER, "Copy the selection to a directory typed in a prompt"),
    _a("move_files_to", FILER, "Move the selection to a directory typed in a prompt"),
    _a("duplicate_files", FILER, "Duplicate the selection in place",
       default_keys=()),
    _a("delete_files", FILER, "Move the selection to the Trash (or delete it where there is none)"),
    _a("delete_permanently", FILER, "Delete the selection for good, skipping the Trash"),
    _a("rename", FILER, "Rename the focused item, or batch-rename the selection",
       aliases=("rename_file",)),
    _a("rename_in_editor", FILER, "Rename the selection by editing its names in TEXT_EDITOR"),
    _a("create_file", FILER, "Create a new file"),
    _a("create_directory", FILER, "Create a new directory"),
    # Viewing
    _a("view_file", FILER, "View the focused file in the built-in viewer"),
    _a("file_details", FILER, "Show details for the focused item"),
    _a("diff_files", FILER, "Compare two files side by side"),
    _a("diff_directories", FILER, "Compare two directories recursively"),
    # Archives
    _a("create_archive", FILER, "Create an archive from the selection"),
    _a("extract_archive", FILER, "Extract the selected archive(s)"),
    # Search and filter
    _a("find_files", FILER, "Search for files by name",
       aliases=("search_dialog",)),
    _a("find_in_files", FILER, "Search inside files",
       aliases=("search_content",)),
    _a("filter", FILER, "Filter the listing by a filename pattern"),
    _a("clear_filter", FILER, "Clear the filename filter"),
    # Sorting
    _a("sort", FILER, "Open the sort dialog",
       aliases=("sort_menu",)),
    _a("quick_sort_name", FILER, "Sort by name"),
    _a("quick_sort_ext", FILER, "Sort by extension"),
    _a("quick_sort_size", FILER, "Sort by size"),
    _a("quick_sort_date", FILER, "Sort by modification date"),
    # Directory navigation
    _a("favorites", FILER, "Go to a favorite directory or file"),
    _a("add_favorite", FILER,
       "Add a favorite, or tag the selection"),
    # The right-click menus from the keyboard, cfiler's pair: the item's, and
    # the directory's.
    _a("context_menu", FILER, "Open the context menu for the item under the cursor"),
    _a("context_menu_dir", FILER, "Open the context menu for the current directory"),
    _a("jump_to_path", FILER, "Jump to a typed path"),
    _a("history", FILER, "Go to a recently visited directory"),
    _a("go_back", FILER, "Go back to the directory shown before"),
    _a("go_forward", FILER, "Go forward again after going back"),
    _a("drives", FILER, "Show drives and volumes",
       aliases=("drives_dialog",)),
    _a("connect_server", FILER, "Connect to a network server",
       aliases=("connect_to_server",)),
    # Every file below the directory as one list (#547). Shift-B rather than
    # Ctrl-B, which is tmux's prefix and would never reach XeFM inside it.
    _a("flat_view", FILER, "Show every file below this directory as one list"),
    # A list of paths in place of a directory (Go > Open List), "open" as
    # open_item opens an archive: the pane shows something else, and
    # go_parent leaves it. Unbound. Not "paste" -- nothing is written, and a
    # paste-like key is what #342's paste will want.
    _a("open_list_from_clipboard", FILER,
       "Open the paths on the clipboard as the pane's list", default_keys=()),
    _a("open_list_from_command", FILER,
       "Open the paths a command prints as the pane's list", default_keys=()),
    _a("open_list_from_file", FILER,
       "Open the list file under the cursor as the pane's list",
       default_keys=()),
    # The OS search index (#579): Spotlight on macOS, Windows Search on Windows.
    _a("index_search", FILER, "Search the OS index under this folder"),
    _a("find_by_tag", FILER, "Find the files with a tag under this folder"),
    # The file clipboard (#577): copy / cut now, paste wherever you go next.
    # Letters (Y, Shift-Y, G) as well as chords, so it is an expert path too.
    _a("clipboard_copy", FILER, "Copy files to the clipboard"),
    _a("clipboard_cut", FILER, "Cut files to the clipboard"),
    _a("clipboard_paste", FILER, "Paste the clipboard into this folder"),
    _a("clipboard_clear", FILER, "Empty the file clipboard", default_keys=()),
    _a("clipboard_show", FILER, "Show what the file clipboard holds", default_keys=()),
    # Quick view (#569): the other pane previews the cursor item.
    _a("quick_view", FILER, "Preview the item under the cursor in the other pane"),
    # Background jobs (#567). Ctrl-G: a plain Ctrl+letter every terminal sends
    # and nothing else uses.
    _a("jobs", FILER, "List background jobs"),
    # Similar-file scans (#571), run by similar-files as their own process.
    # Unbound: the Tools menu and the palette reach it.
    _a("find_similar", FILER, "Find identical files, or similar images, videos or audio",
       default_keys=()),
    # Folder tabs (#563), per pane. All on keys a terminal delivers: Ctrl-TAB
    # never arrives there, so next/previous are Ctrl-PAGE_DOWN / Ctrl-PAGE_UP.
    _a("new_tab", FILER, "Open a new tab in this pane, at the same place"),
    _a("open_in_new_tab", FILER, "Open the directory under the cursor in a new tab"),
    _a("close_tab", FILER, "Close this pane's current tab"),
    _a("next_tab", FILER, "Show this pane's next tab"),
    _a("prev_tab", FILER, "Show this pane's previous tab"),
    # Panes
    _a("sync_current_to_other", FILER, "Go to the other pane's directory"),
    _a("sync_other_to_current", FILER, "Send this directory to the other pane"),
    _a("compare_selection", FILER, "Select by comparison with the other pane"),
    _a("adjust_pane_left", FILER, "Make the left pane smaller"),
    _a("adjust_pane_right", FILER, "Make the left pane larger"),
    _a("reset_pane_boundary", FILER, "Reset the pane split to 50 / 50"),
    # Log pane
    _a("adjust_log_up", FILER, "Make the log pane larger"),
    _a("adjust_log_down", FILER, "Make the log pane smaller"),
    _a("reset_log_height", FILER, "Reset the log pane height"),
    _a("scroll_log_up", FILER, "Scroll the log up one line"),
    _a("scroll_log_down", FILER, "Scroll the log down one line"),
    _a("scroll_log_page_up", FILER, "Scroll the log up one page"),
    _a("scroll_log_page_down", FILER, "Scroll the log down one page"),
    # Both reach into the log without needing focus, exactly as the seven above
    # do — see XeFMApp.copy_log_selection. The selection one carries the copy
    # chord it has always answered (Cmd-C / Ctrl-C, issue #360); the whole-log
    # one ships unbound and is reached from the Edit menu.
    _a("copy_log_selection", FILER,
       "Copy the log pane's selected text to the clipboard"),
    _a("copy_log_all", FILER, "Copy the whole log to the clipboard"),
    # Appearance
    _a("toggle_hidden", FILER, "Show or hide hidden files"),
    _a("toggle_color_scheme", FILER, "Cycle to the next color theme"),
    _a("choose_layout", FILER, "Choose how the pane presents its rows", default_keys=()),
    _a("choose_extras", FILER, "Turn an extra such as Git status on or off in this tab",
       default_keys=()),
    _a("resolve_attribute", FILER,
       "Work out an attribute that takes time, such as a folder's total size",
       default_keys=()),
    _a("redraw", FILER, "Redraw the screen"),
    _a("reread", FILER, "Re-read both panes' directories", default_keys=()),
    _a("menu", FILER, "Open the menu bar"),
    # Every action of the file list, searchable and runnable — the long tail
    # the menu bar deliberately leaves out (discussion #550).
    _a("command_palette", FILER, "Search every action by name and run it"),
    _a("choose_keymap", FILER, "Choose the keymap preset"),
    # External programs and configuration
    _a("programs", FILER, "Run an external program"),
    _a("subshell", FILER, "Open a subshell in this directory"),
    _a("edit_config", FILER, "Edit config.py, then reload it"),
    _a("reload_config", FILER, "Re-read config.py and apply it live"),
    _a("install_extension", FILER,
       "Install an extension package from a folder, a .zip, a URL or GitHub"),
    _a("extensions", FILER, "List the extension packages and whether they loaded"),
    _a("check_extension_updates", FILER,
       "Look for newer versions of the installed extension packages"),
    _a("sync_python_packages", FILER,
       "Install the Python packages ~/.xefm/requirements.txt lists"),
]

_TEXT_VIEWER_ACTIONS = [
    # Unqualified on purpose. These name *capabilities*, not this viewer's use
    # of them: the diff viewer already reads through the same decoder and could
    # grow the encoding picker, and a renderer with its own wrap already takes
    # the wrap binding here. Registering one of them in a second context later
    # is then a no-op for every existing config — same name, another handler,
    # the way ``copy_files`` already works in both ``filer`` and ``dir_diff``.
    # Qualifying them would have spent the very names that makes possible.
    _a("toggle_wrap", TEXT_VIEWER, "Toggle line wrapping"),
    _a("toggle_view_mode", TEXT_VIEWER, "Toggle the rendered / raw view"),
    _a("change_encoding", TEXT_VIEWER, "Choose the text encoding"),
    _a("text_viewer.scroll_up", TEXT_VIEWER, "Scroll up one line",
       default_keys=("UP",)),
    _a("text_viewer.scroll_down", TEXT_VIEWER, "Scroll down one line",
       default_keys=("DOWN",)),
    _a("text_viewer.page_up", TEXT_VIEWER, "Scroll up one page",
       default_keys=("PAGE_UP",)),
    _a("text_viewer.page_down", TEXT_VIEWER, "Scroll down one page",
       default_keys=("PAGE_DOWN",)),
    _a("text_viewer.scroll_top", TEXT_VIEWER, "Go to the top",
       default_keys=("HOME",)),
    _a("text_viewer.scroll_bottom", TEXT_VIEWER, "Go to the bottom",
       default_keys=("END",)),
    _a("text_viewer.scroll_left", TEXT_VIEWER, "Scroll left (unwrapped only)",
       default_keys=("LEFT",)),
    _a("text_viewer.scroll_right", TEXT_VIEWER, "Scroll right (unwrapped only)",
       default_keys=("RIGHT",)),
    # Qualified, unlike the file list's 'search_next': the Vim style's 'n' is
    # that one, and the diff viewer's 'n' jumps blocks. Unbound by default;
    # the Orthodox and OS native presets give them their viewers' keys (#737).
    _a("text_viewer.search_next", TEXT_VIEWER,
       "Find the next match of the last search", default_keys=()),
    _a("text_viewer.search_prev", TEXT_VIEWER,
       "Find the previous match of the last search", default_keys=()),
]

_IMAGE_VIEWER_ACTIONS = [
    # 'pan_*', not 'scroll_*': these move the viewport over a zoomed image,
    # which the code (``_pan_by``) and the help have always called panning.
    _a("image_viewer.zoom_in", IMAGE_VIEWER, "Zoom in",
       aliases=("image_zoom_in",)),
    _a("image_viewer.zoom_out", IMAGE_VIEWER, "Zoom out",
       aliases=("image_zoom_out",)),
    _a("image_viewer.zoom_reset", IMAGE_VIEWER, "Fit the whole image to the window",
       aliases=("image_zoom_reset",)),
    _a("image_viewer.next", IMAGE_VIEWER, "Next image in the file list",
       aliases=("image_next",)),
    _a("image_viewer.prev", IMAGE_VIEWER, "Previous image in the file list",
       aliases=("image_prev",)),
    _a("image_viewer.pan_up", IMAGE_VIEWER, "Pan up (while zoomed in)",
       aliases=("image_scroll_up",)),
    _a("image_viewer.pan_down", IMAGE_VIEWER, "Pan down (while zoomed in)",
       aliases=("image_scroll_down",)),
    _a("image_viewer.pan_left", IMAGE_VIEWER, "Pan left (while zoomed in)",
       aliases=("image_scroll_left",)),
    _a("image_viewer.pan_right", IMAGE_VIEWER, "Pan right (while zoomed in)",
       aliases=("image_scroll_right",)),
    _a("image_viewer.first", IMAGE_VIEWER, "First image in the file list",
       default_keys=("HOME",)),
    _a("image_viewer.last", IMAGE_VIEWER, "Last image in the file list",
       default_keys=("END",)),
]

_FILE_DIFF_ACTIONS = [
    _a("file_diff.next_block", FILE_DIFF, "Next diff block",
       default_keys=("n",)),
    # 'Shift-N', not 'N': a bare letter token means the unshifted key (see
    # KeyBindings._parse_key_expression), so 'N' would be the same binding as
    # 'n'. The shifted form is what the raw ``event.char == "N"`` test this
    # replaced actually matched.
    _a("file_diff.prev_block", FILE_DIFF, "Previous diff block",
       default_keys=("Shift-N",)),
    _a("file_diff.scroll_up", FILE_DIFF, "Scroll up one line",
       default_keys=("UP",)),
    _a("file_diff.scroll_down", FILE_DIFF, "Scroll down one line",
       default_keys=("DOWN",)),
    _a("file_diff.page_up", FILE_DIFF, "Scroll up one page",
       default_keys=("PAGE_UP",)),
    _a("file_diff.page_down", FILE_DIFF, "Scroll down one page",
       default_keys=("PAGE_DOWN",)),
    _a("file_diff.scroll_top", FILE_DIFF, "Go to the top",
       default_keys=("HOME",)),
    _a("file_diff.scroll_bottom", FILE_DIFF, "Go to the bottom",
       default_keys=("END",)),
    _a("file_diff.scroll_left", FILE_DIFF, "Scroll left",
       default_keys=("LEFT",)),
    _a("file_diff.scroll_right", FILE_DIFF, "Scroll right",
       default_keys=("RIGHT",)),
    _a("file_diff.search_next", FILE_DIFF,
       "Find the next match of the last search", default_keys=()),
    _a("file_diff.search_prev", FILE_DIFF,
       "Find the previous match of the last search", default_keys=()),
]

_DIR_DIFF_ACTIONS = [
    # The file operations the directory-diff viewer runs on the focused node.
    # Registered here under the same names the file list uses, so one rebind of
    # 'copy_files' moves both. The focused node stands in for a selection, hence
    # the 'required' bindings still firing.
    _a("copy_files", DIR_DIFF, "Copy the focused node to the other side"),
    _a("move_files", DIR_DIFF, "Move the focused node to the other side"),
    _a("delete_files", DIR_DIFF, "Delete the focused node"),
    _a("view_file", DIR_DIFF, "Open the focused node's file diff"),
    _a("dir_diff.cursor_up", DIR_DIFF, "Move the cursor up",
       default_keys=("UP",)),
    _a("dir_diff.cursor_down", DIR_DIFF, "Move the cursor down",
       default_keys=("DOWN",)),
    _a("dir_diff.page_up", DIR_DIFF, "Move the cursor up one page",
       default_keys=("PAGE_UP",)),
    _a("dir_diff.page_down", DIR_DIFF, "Move the cursor down one page",
       default_keys=("PAGE_DOWN",)),
    _a("dir_diff.cursor_top", DIR_DIFF, "Go to the first row",
       default_keys=("HOME",)),
    _a("dir_diff.cursor_bottom", DIR_DIFF, "Go to the last row",
       default_keys=("END",)),
    _a("dir_diff.expand", DIR_DIFF, "Expand the focused directory",
       default_keys=("RIGHT",)),
    _a("dir_diff.collapse", DIR_DIFF, "Collapse it, or go to its parent",
       default_keys=("LEFT",)),
    _a("dir_diff.activate", DIR_DIFF, "Expand a directory, or diff a file",
       default_keys=("ENTER",)),
    _a("dir_diff.switch_side", DIR_DIFF, "Switch the active side",
       default_keys=("TAB",)),
    _a("dir_diff.next_change", DIR_DIFF, "Next difference",
       default_keys=("n",)),
    _a("dir_diff.prev_change", DIR_DIFF, "Previous difference",
       default_keys=("Shift-N",)),
    _a("dir_diff.rescan", DIR_DIFF, "Rescan both trees",
       default_keys=("r",)),
    _a("dir_diff.split_left", DIR_DIFF, "Move the centre split left",
       default_keys=("[",)),
    _a("dir_diff.split_right", DIR_DIFF, "Move the centre split right",
       default_keys=("]",)),
    # Sync (#560): s opens a plan from the active side and, pressed again,
    # runs it; Space changes one node's action. Not f: that is isearch, which
    # every surface inherits from common.
    _a("dir_diff.sync", DIR_DIFF, "Sync: plan from the active side, or run it",
       default_keys=("s",)),
    _a("dir_diff.cycle_sync_action", DIR_DIFF, "Change the focused node's sync action",
       default_keys=("SPACE",)),
    _a("dir_diff.toggle_identical", DIR_DIFF,
       "Show or hide the items that are the same on both sides", default_keys=("d",)),
]

_ISEARCH_ACTIONS = [
    # Every key the search bar itself answers. They were fixed in the widget
    # until now — the same gap the viewers had, and closed the same way.
    #
    # Two constraints shape the defaults, and any rebinding of them:
    #
    # 1. A printable key cannot be one. The pattern field takes every glyph
    #    (SPACE included — it is the pattern's token separator, which is exactly
    #    why the file list's SPACE cannot mark a file here, issue #347), so a
    #    binding on one would silently stop that character from being typed.
    #    ``xefm.config.printable_isearch_bindings`` reports any the config has.
    # 2. It has to survive the terminal. Ctrl/Shift+Enter do not reach a TUI
    #    (no kitty keyboard protocol on the VT input path), and macOS has no
    #    Insert key at all, so neither can carry a default.
    #
    # Ctrl+Space satisfies both and says what it does: Space is "select" in the
    # file list, and Ctrl is what turns it into a command on a surface where a
    # bare Space types. It costs a terminal nothing either — it is the NUL byte,
    # decoded since PuiKit 1.7.2.
    #
    # This was Shift+Down, which worked but read as the log pane's scroll keys,
    # since that is what the same chord does in the file list a row away. Marking
    # backwards lost its default in the move (as it did in the file list): a
    # search walks forwards, the action is still registered, and either surface
    # can have one back with a line in KEY_BINDINGS.
    #
    # There is deliberately no range key here, though the file list has one
    # ('select_range', Shift-Space). A range would have to be the *positional*
    # span to be worth anything — its anchor is an item marked before the search
    # began, so it is not a match — and a span of rows the search is not talking
    # about is a promise this surface should not make. 'isearch.accept' (Enter)
    # keeps the cursor on the current match, so the range is one keystroke away
    # in the surface that owns it.
    _a("isearch.next_match", ISEARCH, "Move to the next match",
       default_keys=("DOWN",)),
    _a("isearch.prev_match", ISEARCH, "Move to the previous match",
       default_keys=("UP",)),
    _a("isearch.toggle_select_down", ISEARCH,
       "Toggle selection and move to the next match",
       default_keys=("Ctrl-SPACE",)),
    _a("isearch.toggle_select_up", ISEARCH,
       "Toggle selection and move to the previous match",
       default_keys=()),
    # Named for what it selects: the file list's own 'select_all' means every
    # *item* in the pane, and the dotted form of a shorter name is how a config
    # scopes that same action to one context — so reusing it here would read as
    # "select_all, but in the search bar", which is not what this does.
    #
    # Ctrl-A, not Cmd-A: XeFM's own convention is Ctrl for its actions, and a
    # Command chord only where the desktop platform owns the gesture outright
    # (opening a file, copying text).
    # It costs the pattern field its select-all-text chord on Windows and in the
    # terminal — a one-line field, where Esc and retyping is the shorter move —
    # and leaves Cmd-A doing exactly that on macOS.
    _a("isearch.select_matches", ISEARCH, "Select every match (again: clear them)",
       default_keys=("Ctrl-A",)),
    _a("isearch.accept", ISEARCH, "Stop at the current match",
       default_keys=("ENTER",)),
    _a("isearch.cancel", ISEARCH, "Cancel and restore the cursor",
       default_keys=("ESCAPE",)),
]

_FILTER_LIST_ACTIONS = [
    # Named for the operation, not for the dialog that first offers it: "drop the
    # highlighted row from the list in front of you" is something other surfaces
    # will want, and the registry keeps a separate table per context — so this
    # exact name can be registered again elsewhere, each context carrying its own
    # default key while a config can still rebind them all at once by naming it
    # unqualified.
    #
    # Deliberately not "delete_*": in the file list that word means erasing files
    # from disk (``delete_files``), and a name in KEY_BINDINGS must not leave a
    # reader guessing which of the two they are binding. Nothing here touches the
    # filesystem — only the remembered list.
    _a("remove_list_item", FILTER_LIST,
       "Remove the highlighted entry from the list",
       default_keys=("Shift-DELETE",)),
    # "Tell me about the highlighted entry" — a different question from
    # ``help`` ("which keys does this screen answer to"), so a name of its own
    # rather than an overload, which would also blur what rebinding ``help``
    # means. Named for the operation like the action above, for the same
    # reason. F1 is free inside the picker: the dialog does not handle
    # ``help``, and it claims this key by action, ahead of the query field.
    # Offered only by a picker that can describe its rows (``to_help``).
    _a("describe_list_item", FILTER_LIST,
       "Show help for the highlighted entry",
       default_keys=("F1",)),
]

_SEARCH_ACTIONS = [
    # The one key that opens a surface's live options, and the reason there is
    # only one: see xefm/options.py. Named unqualified on purpose — the same
    # rationale as 'remove_list_item' above. "Open the options for the thing in
    # front of you" is an operation other surfaces will grow (the diff viewers
    # want it next), the registry keeps a table per context, so this exact name
    # can be registered again elsewhere with its own default while a config
    # naming it unqualified rebinds every one of them at once.
    #
    # Ctrl-O, and the same two constraints that shaped the isearch defaults:
    #
    # 1. Not a printable key -- the query field takes every glyph first.
    # 2. It has to survive the terminal, which rules out more than it looks
    #    like. Alt is out: macOS keyboards spend Option on glyphs and IME, and
    #    an Alt chord the VT input path does not recognize arrives as ESCAPE,
    #    which would *close the dialog* instead of opening its options.
    #    Ctrl-comma (the desktop preferences chord) cannot be encoded by a
    #    terminal at all, and on macOS Command-comma means the application's
    #    settings -- a different promise from this one. Ctrl+letter is what is
    #    left, and it arrives identically on all four backends.
    #
    # F10 already opens the menu bar, so F9 rides along as the second binding:
    # on a keyboard where it is a plain function key it reads as "the options
    # next to the menu", and where it is not (macOS ships F-keys as media keys)
    # Ctrl-O is the one that works.
    _a("options", SEARCH, "Open the search options",
       default_keys=("Ctrl-O", "F9")),
] + [
    # One unbound action per declared option, so the default keymap stays a
    # single chord while a config can still put a direct key on the option it
    # changes hourly ('search.toggle_case': ['Ctrl-A']). Generated from the
    # declarations rather than written out, because a hand-written list would be
    # the one place that silently fell behind when an option is added.
    _a(f"toggle_{option.name}", SEARCH, f"Change: {option.label}",
       default_keys=())
    for option in SEARCH_OPTIONS + SEARCH_FILTERS
]

_BUILTIN_ACTIONS = (_COMMON_ACTIONS + _FILER_ACTIONS + _TEXT_VIEWER_ACTIONS
                    + _IMAGE_VIEWER_ACTIONS + _FILE_DIFF_ACTIONS
                    + _DIR_DIFF_ACTIONS + _ISEARCH_ACTIONS
                    + _FILTER_LIST_ACTIONS + _SEARCH_ACTIONS)


#: The process-wide registry. Built-ins populate it at import; user actions are
#: loaded onto it from the config (see :func:`xefm.user_api.load_user_entries`)
#: and dropped again on every reload.
registry = _new_registry()

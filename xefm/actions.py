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

#: Every context a binding or a user action may name, most-specific first.
#: ``common`` is deliberately included: a config may bind (or a future release
#: may allow overriding) an action there.
CONTEXTS = (FILER, TEXT_VIEWER, IMAGE_VIEWER, FILE_DIFF, DIR_DIFF, COMMON)


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

    ``default_keys`` of ``None`` means "read the shipped ``_config.py``
    template", which is where every pre-registry action's defaults already live.
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
# Template defaults
# --------------------------------------------------------------------------- #

_template_cache: dict[str, tuple[tuple[str, ...], str]] | None = None


def _template_bindings() -> dict[str, tuple[tuple[str, ...], str]]:
    """``{name: (keys, selection)}`` from the shipped ``_config.py`` template.

    Read lazily and cached: importing the template at module import would drag
    the whole external-programs / backend-detection stack into every consumer of
    this module, and tests import the registry standalone.
    """
    global _template_cache
    if _template_cache is not None:
        return _template_cache
    table: dict[str, tuple[tuple[str, ...], str]] = {}
    try:
        from xefm._config import Config as _TemplateConfig
        raw = getattr(_TemplateConfig, "KEY_BINDINGS", None) or {}
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
# whose ``default_keys`` are omitted read them from the ``_config.py`` template.

def _a(name, context, description, **kw) -> Action:
    return Action(name=name, context=context, description=description, **kw)


_COMMON_ACTIONS = [
    _a("quit", COMMON, "Quit XeFM — or close the open viewer"),
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
    _a("open_item", FILER, "Open the file, or enter the directory"),
    _a("open_with_os", FILER, "Open with the OS default application"),
    _a("reveal_in_os", FILER, "Reveal in the OS file manager"),
    _a("go_parent", FILER, "Go to the parent directory"),
    _a("switch_pane", FILER, "Switch between the left and right panes"),
    _a("nav_left", FILER, "Focus the left pane, or go to the parent"),
    _a("nav_right", FILER, "Focus the right pane, or go to the parent"),
    # Selection
    _a("toggle_select_down", FILER, "Toggle selection and move down",
       aliases=("select_file",)),
    _a("toggle_select_up", FILER, "Toggle selection and move up",
       aliases=("select_file_up",)),
    _a("select_all", FILER, "Select every item"),
    _a("unselect_all", FILER, "Clear the selection"),
    _a("toggle_select_files", FILER, "Toggle selection of every file",
       aliases=("select_all_files",)),
    _a("toggle_select_items", FILER, "Toggle selection of every item",
       aliases=("select_all_items",)),
    _a("cursor_next_selected", FILER, "Jump to the next selected item"),
    _a("cursor_prev_selected", FILER, "Jump to the previous selected item"),
    # Clipboard
    _a("copy_names", FILER, "Copy the file name(s) to the clipboard"),
    _a("copy_paths", FILER, "Copy the full path(s) to the clipboard"),
    # File operations
    _a("copy_files", FILER, "Copy the selection to the other pane"),
    _a("move_files", FILER, "Move the selection to the other pane"),
    _a("duplicate_files", FILER, "Duplicate the selection in place",
       default_keys=()),
    _a("delete_files", FILER, "Delete the selected files and directories"),
    _a("rename", FILER, "Rename the focused item, or batch-rename the selection",
       aliases=("rename_file",)),
    _a("create_file", FILER, "Create a new file"),
    _a("create_directory", FILER, "Create a new directory"),
    # Viewing
    _a("view_file", FILER, "View the focused file in the built-in viewer"),
    _a("file_details", FILER, "Show details for the focused item"),
    _a("diff_files", FILER, "Compare two files side by side"),
    _a("diff_directories", FILER, "Compare two directories recursively"),
    # Archives
    _a("create_archive", FILER, "Create an archive from the selection"),
    _a("extract_archive", FILER, "Extract the focused archive"),
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
    _a("favorites", FILER, "Go to a favorite directory"),
    _a("jump_to_path", FILER, "Jump to a typed path"),
    _a("history", FILER, "Go to a recently visited directory"),
    _a("drives", FILER, "Show drives and volumes",
       aliases=("drives_dialog",)),
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
    # Appearance
    _a("toggle_hidden", FILER, "Show or hide hidden files"),
    _a("toggle_color_scheme", FILER, "Cycle to the next color theme"),
    _a("redraw", FILER, "Redraw the screen"),
    _a("menu", FILER, "Open the menu bar"),
    # External programs and configuration
    _a("programs", FILER, "Run an external program"),
    _a("subshell", FILER, "Open a subshell in this directory"),
    _a("edit_config", FILER, "Edit config.py, then reload it"),
    _a("reload_config", FILER, "Re-read config.py and apply it live"),
]

_TEXT_VIEWER_ACTIONS = [
    _a("text_viewer.toggle_wrap", TEXT_VIEWER, "Toggle line wrapping",
       aliases=("toggle_wrap",)),
    _a("text_viewer.toggle_view_mode", TEXT_VIEWER, "Toggle the rendered / raw view",
       aliases=("toggle_view_mode",)),
    _a("text_viewer.change_encoding", TEXT_VIEWER, "Choose the text encoding",
       aliases=("change_encoding",)),
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
]

_BUILTIN_ACTIONS = (_COMMON_ACTIONS + _FILER_ACTIONS + _TEXT_VIEWER_ACTIONS
                    + _IMAGE_VIEWER_ACTIONS + _FILE_DIFF_ACTIONS
                    + _DIR_DIFF_ACTIONS)


#: The process-wide registry. Built-ins populate it at import; user actions are
#: loaded onto it from the config (see :func:`xefm.user_api.load_user_entries`)
#: and dropped again on every reload.
registry = _new_registry()

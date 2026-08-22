# XeFM Menu System

## Overview

XeFM builds **one menu model** — a tree of `Menu` / `MenuItem` / `SEPARATOR`
objects from PuiKit — and hands it to the UI layer. PuiKit decides how that
single model is *realized* per backend:

- On a **`native_menus`** backend (the macOS and Windows native GUIs) the model
  becomes a real OS menu bar (`NSMenu` on macOS, an `HMENU` on Windows), and
  context menus become native popups.
- On every **other** backend (the curses TUI, and the web/memory backends) the
  same model is drawn *in-window* by PuiKit's `MenuBar` and `MenuPopup` widgets.

XeFM never branches on the backend. It describes menus as intent (labels,
callbacks, enable/checked predicates) and PuiKit resolves the rest. The menu is
not a separate command surface either: every item routes into the **same action
handlers the keymap already calls**, and shortcut hints on the labels are read
back out of the live keymap so they track user rebindings.

## Architecture

The system spans three layers.

### 1. The model — `puikit.menu` (backend-agnostic)

Source: `puikit/menu.py` in the [PuiKit](https://github.com/crftwr/puikit) repo
(installed editable from `../puikit`). XeFM imports it directly:

```python
from puikit.menu import Menu, MenuItem, SEPARATOR
```

- **`MenuItem`** — a dataclass carrying a `label`, an optional `on_select`
  callback, an optional `submenu`, a display-only `shortcut` hint, and
  `enabled` / `checked` fields that are **either a bool or a zero-arg
  predicate** (`Callable[[], bool]`):

  ```python
  @dataclass
  class MenuItem:
      label: str
      on_select: Callable[[], None] | None = None
      enabled: bool | Callable[[], bool] = True
      checked: bool | Callable[[], bool] = False
      submenu: "Menu | None" = None
      shortcut: str | None = None       # display hint only; not bound
  ```

  The predicates are **re-evaluated each time the menu opens** — through
  `validateMenuItem:` on the native backend, at draw time in the widget
  fallback — so items reflect live application state without the app rebuilding
  the tree. A `MenuItem` with a `submenu` becomes a parent that opens a nested
  menu instead of firing `on_select`.

- **`MenuSeparator`** — a divider; the shared instance `SEPARATOR` is reused
  everywhere (`Menu(item_a, SEPARATOR, item_b)`).

- **`Menu`** — an ordered list of items and separators with an optional
  `title`: `Menu(*items, title=None)`. For a menu bar, the top-level `Menu`
  holds one `MenuItem` per bar entry, each carrying its dropdown as a `submenu`.

The `shortcut` field is a **hint only** — the menu does not bind it. Key
handling stays in XeFM's keymap; the shortcut string just labels the row.

### 2. Realization — PuiKit Panel + widgets

The app hands the model to the Panel, which resolves it per backend
(`puikit/panel.py`):

- **`Panel.set_menu_bar(menu)`** — installs an app menu bar. On a
  `native_menus` backend it calls `backend.set_menu_bar(menu)` (the real OS
  bar); otherwise it is a no-op here, and the in-window `MenuBar` widget draws
  the strip. The `MenuBar` widget calls `set_menu_bar` itself once it knows the
  backend, so the app just places one widget and never branches.

- **`Panel.popup_menu(menu, x, y, on_done=None)`** — opens a context menu near
  base-unit `(x, y)`. Native backends hand it to the OS; others push a
  `MenuPopup` widget layer (kept on-screen by nudging it left/up on overflow).

The two fallback widgets live in `puikit/widgets/menu.py` (re-exported from
`puikit.widgets`):

- **`MenuBar`** — a horizontal strip of top-level titles placed in the app
  layout. On a `native_menus` backend it registers the model as the OS bar and
  collapses to zero height. Deliberately **not a focus stop** (no desktop puts
  the menu bar in the Tab order): the open entry's title highlights from the
  pulldown's open state, never from focus — taking focus on click is what left
  a title stuck inverted after an outside click dismissed its modal pulldown
  (#304). Keyboard activation is `MenuBar.open_menu(index=0)`; XeFM binds the
  `menu` action (`F10`, bare `ALT` on the Windows terminal) to it in
  `dispatch()`.
- **`MenuPopup`** — the floating list pushed as a modal Panel layer, shared by a
  bar entry dropping down and by a context menu. It handles separators,
  submenus (each opens a nested popup), the live `enabled`/`checked` predicates,
  and keyboard + mouse. A pulldown opened from the bar carries an
  `on_navigate` hook: ←/→ with no submenu to enter dismiss the chain and open
  the neighboring bar entry's pulldown (the desktop convention, #304); a
  context menu has no bar, so there ← closes and → fires like Enter.

The native builders are `puikit/backends/_macos_menu.py` (turns a `Menu` into an
`NSMenu`; a `_MenuTarget` implements `validateMenuItem:` to answer live
`is_enabled()` / `is_checked()`) and `puikit/backends/_win32_menu.py` (builds an
`HMENU` via `MenuResponder`).

The `native_menus` capability is `True` in `PROFILE_GUI_DESKTOP`
(`puikit/capability.py`) — inherited by the macOS and Windows native backends —
and `False` for the TUI and web profiles.

### 3. Application layer — `xefm/app.py`

XeFM owns the menu *content*. All of it lives in `xefm/app.py`:

- **`_build_menu()`** — builds the whole menu tree and returns the top-level
  `Menu`. Each bar entry is a `MenuItem(title, submenu=...)`. Current bar:
  **File, Go, Select, View, Tools, Help**.
- **`self.menu_bar = MenuBar(self._build_menu())`** — the widget is placed into
  the app layout as `Item(self.menu_bar, size="content", hints={"surface":
  "header"})`. `size="content"` lets it self-size: a 1-row strip on curses,
  zero height on macOS (where it installs the native bar instead), so the layout
  needs no per-backend row branch.

Two submenus are factored out because they are reused by keyboard-triggered
popups as well as the bar:

- **`_sort_menu()`** — the sort-mode menu (Name / Size / Date / Type), shared by
  the View ▸ "Sort By" submenu and the `s`-key popup (`show_sort_menu()`).
- **`_theme_menu()`** — the theme picker, shared by View ▸ "Theme". Lists every
  built-in and user-registered theme.

Both use a live `checked` predicate to mark the active choice.

#### Callbacks reuse the keymap

Menu items call the same handlers as the keyboard. Two helpers glue them:

```python
def _menu(self, action: str) -> None:
    """Run a keymap action from a menu/context-menu selection and redraw."""
    if self.dispatch(action):
        self.panel.render()

def _menu_shortcut(self, action: str) -> str | None:
    """Display-formatted first key bound to `action` (or None), so menu
    labels track the live keymap instead of hardcoded strings."""
    keys, _ = self.keys.get_keys_for_action(action)
    return self.keys.format_key_for_display(keys[0]) if keys else None
```

An item either calls `self._menu("some_action")` (dispatch through the keymap,
identical to pressing the key) or calls a bound method directly
(`on_select=self.create_directory`). Its `shortcut=` is filled from
`_menu_shortcut(...)` (aliased `sc` inside `_build_menu`) so the hint reflects
the user's actual binding.

#### Live enable / check predicates

Because `enabled` / `checked` accept predicates, menu state is expressed inline
and re-evaluated on open — no separate "update states" pass. Examples from
`_build_menu()`:

```python
def has_files() -> bool:
    return bool(self.active_pane()["files"])

MenuItem("Rename…", on_select=self.rename,
         enabled=has_files, shortcut=sc("rename_file"))

MenuItem("Show Hidden Files", on_select=lambda: self._menu("toggle_hidden"),
         checked=lambda: self.flm.show_hidden, shortcut=sc("toggle_hidden"))

MenuItem("Clear Selection", on_select=lambda: self._menu("unselect_all"),
         enabled=lambda: bool(self.active_pane()["selected_files"]),
         shortcut=sc("unselect_all"))
```

#### Context menus (right-click)

Each file pane wires a right-click handler through its `on_context` callback:

```python
self.left_view = FilePane(..., on_context=lambda i, x, y:
                          self._show_context_menu("left", i, x, y), ...)
```

`_show_context_menu(pane_name, index, x, y)` makes the clicked pane/row active,
builds a fresh `Menu(...)` (Open, View File, Select/Deselect, Rename,
Duplicate, Copy/Move to Other Pane, Delete, Copy Name(s)/Path(s), Show Hidden
Files), and calls `self.panel.popup_menu(menu, x, y)`. As with the bar, the
items reuse the same handlers and carry live `enabled` / `checked` predicates
(e.g. `enabled=entry is not None`, the Select/Deselect label chosen from the
row's current selection state).

## Adding a menu item

There are no item-id constants, no dispatch table, and no per-item state pass to
touch. To add an item to a menu in `_build_menu()`:

1. **Add a `MenuItem`** to the appropriate submenu `Menu(...)`.
2. **Point `on_select`** at either an existing bound method
   (`on_select=self.duplicate_files`) or a keymap action via the helper
   (`on_select=lambda: self._menu("some_action")`). Prefer routing through an
   existing action so the keyboard and the menu stay in sync.
3. **Add a `shortcut` hint** with `sc("action_name")` if the action has a key
   binding — the hint then tracks the live keymap automatically.
4. **Express availability inline** with `enabled=`/`checked=` — a bool for a
   static case, or a zero-arg predicate for anything that depends on live state
   (it is re-evaluated every time the menu opens).

No renderer, backend, or test-harness change is needed: the same `MenuItem`
renders natively on macOS/Windows and as a widget row on the TUI.

## Desktop vs. terminal

Whether XeFM is running a native GUI is available via
`is_desktop_mode()` (`xefm/backend_detector.py`), used for launch behavior
(e.g. detaching vs. suspending child processes). **The menu system itself does
not consult it** — the OS-bar-vs-in-window decision is made by PuiKit from the
backend's `native_menus` capability, so XeFM stays backend-agnostic.

## Code locations

### XeFM (`xefm/app.py`)
- `_build_menu()` — the full menu-bar tree (File / Go / Select / View / Tools / Help)
- `_sort_menu()`, `show_sort_menu()` — sort submenu + `s`-key popup
- `_theme_menu()` — theme-picker submenu
- `_menu(action)` — run a keymap action from a menu selection and redraw
- `_menu_shortcut(action)` — derive a label's shortcut hint from the live keymap
- `_show_context_menu(pane, index, x, y)` — right-click context menu
- `self.menu_bar = MenuBar(...)` and its `Item(...)` placement in the layout

### PuiKit (`../puikit`)
- `puikit/menu.py` — `Menu`, `MenuItem`, `MenuSeparator`, `SEPARATOR`
- `puikit/panel.py` — `Panel.set_menu_bar`, `Panel.popup_menu`
- `puikit/widgets/menu.py` — `MenuBar`, `MenuPopup` (in-window fallback)
- `puikit/backends/_macos_menu.py` — `Menu` → `NSMenu` (native macOS)
- `puikit/backends/_win32_menu.py` — `Menu` → `HMENU` (native Windows)
- `puikit/capability.py` — the `native_menus` capability
- `puikit/tests/test_menu.py` — PuiKit's menu tests

## Related documentation

- [Menu Bar Feature](../MENU_BAR_FEATURE.md) — end-user documentation
- [Desktop Mode Guide](../DESKTOP_MODE_GUIDE.md) — desktop-mode overview
- [Dialog System](DIALOG_SYSTEM.md) — the other in-window UI-layer surfaces
- [Key Bindings Implementation](KEY_BINDINGS_IMPLEMENTATION.md) — the keymap the
  menu shares its actions and shortcut hints with

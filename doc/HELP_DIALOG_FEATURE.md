# Help Dialog (? Key)

XeFM includes a scrollable help dialog listing every key binding and usage tip.
Press **?** from anywhere in XeFM to open it — no special mode or prerequisite.

## Usage

- **?** — open the help dialog
- **↑/↓** — scroll line by line
- **Page Up/Down** — scroll by page
- **Home/End** — jump to top/bottom
- **Escape** or **q** — close

## Content

The help is generated from your current key bindings, so it always reflects your
configuration (including any customizations). It is organized into sections:

- **Navigation** — arrow keys, pane switching, directory navigation
- **File Operations** — selection (Space), bulk selection (A, Shift-A), copy
  (C), move (M), delete (K), rename (R), view (V), edit (E), details (I)
- **Search & Sorting** — search (F incremental, Shift-F filename, Shift-G
  content) and sort options (S, 1–4)
- **Incremental Search** — the keys the search bar itself answers while it is
  open (match stepping, selecting matches, accept, cancel)
- **View Options** — hidden files (.), pane sync (O, Shift-O), layout
- **Log Pane** — resize (bracket keys) and scroll (Shift+Up/Down)
- **General** — help (?), quit (Q), cancel (ESC)
- **Configuration** — where config lives and tips for customizing it
- **Archive Formats** — which archive formats this copy of XeFM can browse,
  extract and create, and the libarchive it found. Built when XeFM starts rather
  than written down, because the list depends on what is installed (see
  [Archives](ARCHIVE_FEATURE.md))

## Configuration

Help is bound to **?** by default. Rebind the `help` action in `KEY_BINDINGS`
to use a different key:

```python
KEY_BINDINGS = {
    'help': ['?'],  # ? shows help
    # ... other bindings
}
```

## About dialog

Separate from the help dialog, the **About** dialog shows XeFM's logo, version
number, and GitHub repository URL over an animated Matrix-style background
(falling full-width green katakana). Open it from the menu bar in desktop mode:

- **macOS**: XeFM → About XeFM
- **Other platforms**: Help → About XeFM

Close it by pressing any key, clicking, or pressing ESC. The animation runs
while the dialog is open and adapts to window resizing.

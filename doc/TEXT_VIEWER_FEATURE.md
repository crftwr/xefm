# Text Viewer

XeFM has a built-in text viewer for source code, config files, logs, and any
other UTF-8 (or Latin-1 / CP1252) text. Put the cursor on a file and press `V`
(or `Enter` on a file with no other `enter` rule) to open it full-window,
without leaving XeFM. Binary files are detected and show a short placeholder
instead of mojibake.

For file types with a richer renderer — Markdown especially — the viewer can
switch between the rendered view and the plain source (see below and
[Markdown Viewer](MARKDOWN_VIEWER_FEATURE.md)).

## Opening & controls

| Key | Action |
|-----|--------|
| `V` | View the focused file in the text viewer |
| `Enter` | Same, for a file with no other `enter` rule |
| `↑` `↓` | Scroll one line |
| `PgUp` / `PgDn` | Scroll one page |
| `Home` / `End` | Jump to the top / bottom |
| `←` `→` | Scroll horizontally (when line wrap is off) |
| `W` | Toggle line wrapping |
| `F` | Incremental search — then `↑` / `↓` step between matches |
| `M` | Toggle rendered / raw view (Markdown and other rich types) |
| `Cmd`/`Ctrl` + `C` | Copy the current selection |
| `Cmd`/`Ctrl` + `A` | Select the whole file |
| `?` | Key help |
| `Q` / `Esc` | Close the viewer |

The view/edit keys are rebindable in your config's `KEY_BINDINGS`; the arrow /
page / home / end scroll keys are viewer-local and always active.

## Tabs & syntax highlighting

- **Tabs** are expanded to spaces automatically, aligned to 8-column tab stops.
  Expansion is column-aware, so wide (CJK / emoji) characters still line up.
- **Syntax highlighting** is applied automatically when
  [Pygments](https://pygments.org/) is installed — the language is chosen from
  the file's extension. Without Pygments the text still displays, just uncolored.
  Syntax colors follow the active theme.
- **Line wrapping** is off by default (so long lines scroll horizontally with
  `←` / `→`). Press `W` to wrap instead; a `WRAP` indicator shows in the footer.

## Selecting text & copying

You can select text with the mouse and copy it to the clipboard.

| Gesture | Selects |
|---------|---------|
| Click & drag | An arbitrary range from where you press to where you release |
| Double-click | The whole word under the pointer |
| Triple-click | The whole line under the pointer |
| Drag after a double / triple click | Extends by whole words / lines |
| Shift-click | Extends the current selection to the click |
| `Cmd`/`Ctrl` + `A` | Selects the entire document |

The highlighted range tracks the pointer as you drag, and the selection
survives scrolling — scroll away and back and it is still there.

Press `Cmd`+`C` (macOS) or `Ctrl`+`C` (Linux / Windows) to copy. The text
viewer copies the selected source text exactly, each display line on its own
line.

### On a terminal

Whether the copy reaches your **system** clipboard depends on the terminal
supporting the OSC 52 clipboard escape (most modern terminals do). The copy
always works for pasting back inside XeFM regardless.

### Rich copy from the Markdown view

When you copy from the **rendered Markdown** view (press `M` on a `.md` file),
the copy carries rich formatting — bold, italics, inline code, links, headings
and tables come across intact when you paste into a formatting-aware app, while
a plain editor gets the plain text. See
[Markdown Viewer](MARKDOWN_VIEWER_FEATURE.md) for the details.

## See also

- [Markdown Viewer](MARKDOWN_VIEWER_FEATURE.md) — the rendered view for `.md` files
- [JSON & CSV Viewers](JSON_CSV_VIEWERS_FEATURE.md) — structured views for data files
- [Image Viewer](IMAGE_VIEWER_FEATURE.md) — the viewer for images
- [File Associations](FILE_ASSOCIATIONS_FEATURE.md) — how a file type picks the raw vs. rich viewer, or an external program
- Developer notes: `doc/dev/TEXT_VIEWER_SYSTEM.md`

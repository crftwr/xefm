# Markdown Viewer

XeFM's built-in file viewer can render Markdown files (`*.md`, `*.markdown`) as
formatted rich text — headings, **bold** / *italic*, `code`, lists, tables,
block quotes, links and images — in addition to the usual raw, line-numbered
text view.

## Opening a file

Press **V** on a Markdown file (or any text file) to open the viewer. The **raw
text** view — line numbers, syntax highlighting, incremental search and line
wrapping — is the starting point, unless you've told XeFM you prefer the rendered
view for this kind of file (see *Remembering your choice* below).

## Switching to the rendered view

When the file has a rendered view available (today: Markdown), press **M** to
toggle between:

- **Raw text** — the source, with line numbers and search.
- **Rendered** — the formatted document.

Press **M** again to switch back. The two views are independent: each remembers
where you had scrolled to, so toggling back and forth returns you to where you
were in each.

## Remembering your choice

XeFM remembers the view you last chose **per file type** and reopens that type the
same way next time. Toggle a `.md` file to the rendered view and every `.md` file
you open afterwards — this session and after a restart — opens rendered; toggle
one back to raw and `.md` files open raw again. The preference is tracked
separately for each extension, and only for types that actually have a rendered
view (a `.txt` or `.py` always opens raw, since there's nothing to remember).

The footer shows which key toggles the view, and the top-right of the header
shows the current view (the line position in raw text, or the renderer's name —
e.g. *Markdown* — when rendered).

Files with no rendered view (a `.txt`, a `.py`, …) simply have nothing to toggle
to; **M** does nothing there.

## Navigating the rendered view

| Key | Action |
|-----|--------|
| ↑ / ↓ | Scroll a line |
| PgUp / PgDn | Scroll a page |
| Home / End | Jump to top / bottom |
| Mouse wheel | Scroll |
| **F** | Incremental search |
| **M** | Switch back to raw text |
| **?** | Key help |
| **Q** / Esc | Close the viewer |

### Searching the rendered view

Incremental search (**F**) works in the rendered view as well as in raw text.
Press **F**, type a pattern, and every occurrence is highlighted where it appears
in the formatted document — matches inside styled text (a heading, a **bold** run,
inline `code`, a link) keep their own color under the highlight. **↑** / **↓**
jump to the previous / next match, **Enter** keeps the current position, and
**Esc** cancels and returns to where you were. Matching is case-insensitive, and
the footer counter shows *current / total*.

Line wrap (**W**) still applies only to the raw text view (the rendered document
already wraps prose to the pane).

## Notes

- The rendered view follows the active theme and works on both the terminal and
  the native (macOS / Windows) backends — on the terminal, headings and emphasis
  render as bold/italic; on a graphical backend they render as proportional text
  at their true sizes, with real tables and images.
- Other file types have rendered views too, reached with the same **M** toggle:
  JSON / JSON Lines and CSV / TSV — see [JSON and CSV
  Viewers](JSON_CSV_VIEWERS_FEATURE.md).

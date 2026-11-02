# Documents as Text — Implementation

[#575](https://github.com/crftwr/xefm/issues/575), from discussion
[#548](https://github.com/crftwr/xefm/discussions/548). User-facing behavior is
in [`doc/DOCUMENT_VIEWER_FEATURE.md`](../DOCUMENT_VIEWER_FEATURE.md).

## Where the reading happens: doc-files

Reading the formats is a separate library,
[doc-files](https://github.com/crftwr/doc-files), not code in XeFM. It reads
`.pdf`, `.docx` `.xlsx` `.pptx`, `.odt` `.ods` `.odp` and `.epub` into a
**document model of meaning, not geometry**: headings, nested lists, tables
with merged cells, sections for pages, slides, sheets and chapters, and
speaker notes and page furniture as layers. It renders that as plain text or
Markdown. Its core is the standard library, and PDF uses pypdf.

Why a library and not code here:

- The model is meant to be rendered by a PuiKit widget with more than
  Markdown can express (spans, layers). The model is the contract between
  that widget and the readers, and neither belongs in XeFM.
- It can be tested and used without XeFM, as similar-files is.

Why not an existing library (checked October 2026): **Docling** has the
closest model but is about 230 MB even in its office-only build, needs ML
models for PDF, and reads no EPUB. **pandoc** reads no PDF and is a binary to
ship. **MarkItDown** gives Markdown only.

## `xefm/document_text.py`

The one door, used by the viewer and by content search:

| | |
|---|---|
| `handles(path)` | doc-files installed and the name has a reader. Decided by name: these are zip or PDF files, and sniffing cannot tell a `.docx` from any zip. |
| `extract(path)` | Reads the bytes (`Path.read_bytes`, so remote and archived files work), with a 256 MB cap. Returns `Extracted(text, markdown, label, problem, warnings)`. It never raises: a password, a broken file, or a missing doc-files become `problem`. |

An empty document (`Document.is_empty`, for example a scanned PDF) returns no
text at all, not even section labels, with the reader's warning as
`problem`. Otherwise "== Page 1 ==" would hide the fact that there is nothing
to read.

## The viewer

`TextViewer(..., document=Extracted)` (and `show_text_viewer(document=)`):

- `_load_document` sets `lines` from the plain text, `encoding` to the label
  shown in the header ("PDF · 12 pages"), and `highlighted` to plain rows (no
  lexer). A document with nothing to read shows `problem` as the error
  placeholder.
- `_rich` is a `RichRenderer` named after the format, building
  `MarkdownView` from `document.markdown`. `_ensure_rich_widget` takes that
  source instead of re-reading the file.
- The view mode is remembered per extension as before. With nothing stored,
  a document opens **rich**: its structure is the point.
- The encoding picker returns at once, and its hint is hidden. An extracted
  document has no bytes to re-decode.
- `_reload_text` (after an edit) extracts again.

This is #548 §3c, "an extractor registry run before the pipeline". The
renderer contract (`RichRenderer.build(source: str)`) did not have to widen,
because the source is the Markdown.

## The app

- `_enter_file`: the binary guard lets a document through
  (`document_text.handles`).
- `_open_viewer` → `_open_document`: extraction runs on a `Task` with
  `busy_label="Reading…"`, so the progress dialog shows and Esc stops it, and
  `on_done` opens the viewer. A `problem` is also logged, with the
  `open_with_os` key as the way to the application.
- `_iter_content_matches`: a document is searched through
  `extract(e).lines`. Hits name a line of the extracted text.

## Configuration

The shipped `FILE_ASSOCIATIONS` set `'view': None` for `.pdf`, `.docx`,
`.xlsx` and `.pptx`, so `V` stays in XeFM. The old binary formats keep their
application for `view`. An existing `config.py` keeps its rules, and the
feature doc says how to change them. `Enter` has no `enter` rule for these
types, so it already reaches the built-in viewer.

## Dependency

doc-files is **optional at runtime**: `handles()` is False without it, and
documents keep the binary placeholder. It is in `requirements.txt` (and so
in the desktop bundles) as plain `doc-files`: since 0.2.0 it brings pypdf
for PDF itself, with no `[pdf]` extra. For development:
`pip install -e ../doc-files`, which brings pypdf too.

## Not done

A password prompt for encrypted PDFs, OCR, the old binary Office formats,
quick view (#569) showing a document's text, and the PuiKit widget that
renders the model itself.

## Tests

`test/test_document_text.py`, skipped without doc-files. A minimal `.docx`
and PDF are built in the test. It covers `handles` by name, a Word document's
text and Markdown (heading, table), a PDF and a PDF with nothing to read, a
broken file reporting why, the viewer's raw lines, label and rich-first
mode, the problem placeholder, `Enter` opening the document through the task
into the viewer, and content search finding a word in a `.docx` with its
line. `test_file_associations.py` now expects PDF's `view` to be the
built-in viewer.

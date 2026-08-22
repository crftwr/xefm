# Text Encodings

The text viewer detects a file's character encoding automatically, so legacy
Japanese text — Shift-JIS, EUC-JP, ISO-2022-JP — displays correctly alongside
UTF-8, with or without a BOM. When detection gets a file wrong, you can pick
the encoding explicitly from inside the viewer.

## Automatic detection

Opening a file in the text viewer (`V`) just works for:

- **UTF-8** — with or without a BOM (the BOM never shows as a stray character)
- **UTF-16 / UTF-32** — when the file starts with a BOM (both byte orders)
- **Shift-JIS (CP932)** — the Windows Japanese encoding
- **EUC-JP** — the traditional Unix Japanese encoding
- **ISO-2022-JP** — the 7-bit encoding common in older Japanese mail
- **CP1252 / Latin-1** — Western single-byte text

The header's right side names the encoding in use (e.g. `Shift-JIS  12/340`),
so you always see what detection chose. Detection is content-based — no
extension lists, no locale guessing — and something always displays: a file
nothing else matches falls back to Latin-1 rather than refusing to open.

The same detection feeds the diff viewer, so comparing two Shift-JIS files
shows real text on both sides. Content search (`Shift-G`) honors BOMs too:
a UTF-16/32 file is grepped as text instead of being skipped as binary, and
a UTF-8 BOM never blocks a `^`-anchored match on the first line.

## Choosing an encoding manually

Press `Shift-E` in the viewer (the `text_viewer.change_encoding` binding) to open the
encoding picker:

- **Auto** — the default; the row also names what detection chose, so the
  picker doubles as an indicator.
- One row per encoding from your config's `TEXT_ENCODINGS` list (see below).

`↑`/`↓` choose — or just start typing (`s` jumps to Shift-JIS, `eu` to
EUC-JP; the match is shown at the dialog's bottom). `Enter` applies — the
file is re-decoded in place, keeping your scroll position — and `Esc`
cancels. The selection opens on whatever is currently in effect.

Plain `E` (`edit_file`) also works inside the viewer: it opens the viewed
file in your configured editor, exactly as it does from the file list, and
the viewer re-reads the file when a terminal editor returns.

A manual choice always shows *something*: bytes the chosen encoding can't
represent appear as replacement marks (`�`) instead of refusing. Choosing
**Auto** returns to detection.

Two situations where the override earns its place:

- **Detection guessed wrong.** Short files or unusual byte mixes can fool any
  detector; picking the right encoding fixes the view immediately.
- **BOM-less UTF-16.** Without a BOM, a UTF-16 file is indistinguishable from
  binary data (every ASCII character contains a NUL byte), so the viewer shows
  the binary placeholder. Forcing `utf-16-le` (add it to `TEXT_ENCODINGS`)
  displays it as text.

The choice is per-file and per-viewing — closing the viewer forgets it, and
reopening the file detects afresh.

## Configuring the picker

The picker's encoding list lives in `~/.xefm/config.py`:

```python
TEXT_ENCODINGS = ['utf-8', 'cp932', 'euc-jp', 'iso-2022-jp', 'latin-1']
```

Any [Python codec name](https://docs.python.org/3/library/codecs.html#standard-encodings)
works — add `'koi8-r'`, `'gb2312'`, `'utf-16-le'`, or anything else you deal
with. The list only feeds the manual picker; automatic detection is built in
and unaffected.

The `Shift-E` key is rebindable via `KEY_BINDINGS['text_viewer.change_encoding']` like any
other action (see [Key Bindings](KEY_BINDINGS_FEATURE.md)).

## See also

- [Text Viewer](TEXT_VIEWER_FEATURE.md) — the viewer itself
- [Diff Viewer](DIFF_VIEWER_FEATURE.md) — shares the same detection
- Developer notes: `doc/dev/TEXT_ENCODING_IMPLEMENTATION.md`

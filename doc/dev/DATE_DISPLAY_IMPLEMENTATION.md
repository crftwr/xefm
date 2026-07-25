# Date Display Implementation

## Overview

XeFM shows each file's modification time in the file-list panes. Two pieces
cooperate:

1. **Formatting** — turning a timestamp into a string, in one of two widths
   (`short` / `full`), selected by config.
2. **Layout** — deciding how wide the date column is and, on a narrow pane,
   whether to show it at all (the date column is dropped before the name column
   is squeezed below a legible minimum).

Source of truth:

- Formatting: `FileListManager._format_date` in
  [`xefm/file_list_manager.py`](../../xefm/file_list_manager.py).
- Column width / show-hide decision: `FilePane._date_width`, `MIN_NAME_W`, and
  the `show_date` computation in [`xefm/file_pane.py`](../../xefm/file_pane.py).
- Format identifiers: `DATE_FORMAT_SHORT` / `DATE_FORMAT_FULL` in
  [`xefm/const.py`](../../xefm/const.py).
- Default setting: `DATE_FORMAT` in the user-config template
  [`xefm/_config.py`](../../xefm/_config.py).

## Formatting

`_format_date` reads `self.config.DATE_FORMAT` and returns the string that the
listing caches per entry (`date_str`, alongside `size_str`):

```python
def _format_date(self, timestamp):
    from xefm.const import DATE_FORMAT_FULL, DATE_FORMAT_SHORT

    dt = datetime.fromtimestamp(timestamp)
    date_format = self.config.DATE_FORMAT

    if date_format == DATE_FORMAT_FULL:
        return dt.strftime("%Y-%m-%d %H:%M:%S")   # YYYY-MM-DD HH:mm:ss
    else:  # DATE_FORMAT_SHORT (default)
        return dt.strftime("%y-%m-%d %H:%M")       # YY-MM-DD HH:mm
```

Every entry in a pane is formatted with the same `DATE_FORMAT`, so all `date_str`
values in a pane share one fixed width. Both formats use ISO-8601-style hyphenated
dates for international compatibility.

### Format specifications

| Format | `strftime` pattern | Example | Description |
|--------|--------------------|---------|-------------|
| Short  | `%y-%m-%d %H:%M`    | `24-12-17 14:30`      | 2-digit year, no seconds |
| Full   | `%Y-%m-%d %H:%M:%S` | `2024-12-17 14:30:45` | 4-digit year, full timestamp |

| Format | Column width | Content |
|--------|--------------|---------|
| Short  | 14 | `YY-MM-DD HH:MM` |
| Full   | 19 | `YYYY-MM-DD HH:MM:SS` |

### Configuration

The format is a config setting, not a runtime toggle:

```python
# xefm/_config.py (copied to ~/.xefm/config.py on first run)
DATE_FORMAT = 'short'   # 'short' (YY-MM-DD HH:mm) or 'full' (YYYY-MM-DD HH:mm:ss)
```

`xefm/const.py` provides the type-safe identifiers used in the code:

```python
DATE_FORMAT_FULL  = 'full'    # YYYY-MM-DD HH:mm:ss
DATE_FORMAT_SHORT = 'short'   # YY-MM-DD HH:mm (default)
```

## Column layout and the show/hide threshold

The date column sits at the right edge of a pane, after the size column. Columns,
left to right, are: **gutter | basename | ext | size | date**. Whether the date
column is drawn depends on the space left for the name column — the date is
dropped before the name is squeezed below a legible minimum. All of this lives in
`FilePane._render_rows` in [`xefm/file_pane.py`](../../xefm/file_pane.py).

### Measuring the date width

`_date_width` samples the first dated entry from the pane's `file_info` cache.
Because every entry shares one format, a single sample gives the column width;
`0` means nothing carries a date, so the column is dropped entirely:

```python
def _date_width(self) -> int:
    for info in self.pane.get("file_info", {}).values():
        date_str = info.get("date_str")
        if date_str:
            return len(date_str)      # 14 (short) or 19 (full)
    return 0
```

### The show/hide decision

The relevant module constants:

```python
SIZE_COL   = 9    # width reserved at the right edge for the size column
COL_GAP    = 1    # gap between adjacent columns (name|size, size|date)
MIN_NAME_W = 12   # smallest name column allowed before the date column is dropped
```

The layout computes the name width that *would* remain if the date column were
shown, then keeps the date only when that width stays at or above `MIN_NAME_W`:

```python
date_w  = self._date_width()
name_if_dated = content_right - content_left - SIZE_COL - date_w - COL_GAP * 2 - ext_block
show_date = date_w > 0 and name_if_dated >= MIN_NAME_W
```

`ext_block` is the optional separate-extension column (`COL_GAP + ext_w`, or `0`
when the pane has no splittable extensions). When `show_date` is false the size
column moves to the pane's right edge and the name reclaims the freed space.

### Derived thresholds

Rearranging the condition, the date column is shown when the pane's **content
width** (the inner area after insets, in character cells on the TUI) satisfies:

```
content_width >= MIN_NAME_W + SIZE_COL + date_w + 2*COL_GAP + ext_block
              = 23 + date_w + ext_block
```

With no extension column (`ext_block = 0`):

| Format | `date_w` | Minimum content width to show date |
|--------|----------|------------------------------------|
| Short  | 14 | 37 |
| Full   | 19 | 42 |

A visible extension column raises these thresholds by `1 + ext_w`. Note this is
the pane's *content* width, evaluated live per pane, so the two panes can decide
independently — a wide pane shows the date while its narrow sibling drops it.

## Behavior notes

- **Format-aware threshold** — switching `DATE_FORMAT` from short to full widens
  the date column (14 → 19), which raises the width needed to show it, so a
  borderline pane may drop the date after the switch.
- **Narrow-pane degradation** — as a pane narrows, the date column is dropped
  first (keeping the name legible); the name only shrinks after the date is gone.
- **No date to show** — when every entry stats as inaccessible (`date_str`
  empty), `_date_width` returns `0` and the column is dropped regardless of width.

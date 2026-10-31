# Sort Dialog

English \| [日本語](SORT_DIALOG_FEATURE.ja.md)

Run `sort` to open the sort dialog over the active pane (its key depends on
your keymap preset — see [Keymap Presets](KEYMAP_PRESETS_FEATURE.md#every-key-side-by-side);
it is also in the command palette, **Tools → Command Palette…**). It replaces the old
generic sort menu with a picker made for the job: choose a **sort key**, choose
an **order**, and read what that order means before you commit.

```
┌────────────────────────────────────────────────┐
│ Sort By                                        │
├────────────────────────────────────────────────┤
│                                                │
│  Filename                                      │
│  Extension                                     │
│  Size                                          │
│  Timestamp                                     │
│                                                │
│  Ascending  Descending                         │
│  a.txt → m.txt → z.txt  (A to Z)               │
│                                                │
│ ↑/↓ key · ←/→ order · Enter apply · Esc cancel │
└────────────────────────────────────────────────┘
```

## Controls

- **Up/Down** — choose the sort key (Filename, Extension, Size, Timestamp)
- **Left/Right** — choose the order: Left is Ascending, Right is Descending
- **F / E / S / T** — the rows' initials choose that sort key directly and
  apply it immediately (the dialog closes), keeping the current order.
  With `sort` on a key, changing the sort is two keystrokes: that key, then a
  letter.
- **Enter** — apply the selected key and order
- **Escape** — cancel; the pane's sort is left untouched
- **Mouse** — clicking a key row applies it; clicking Ascending/Descending
  switches the order without closing; clicking outside the dialog cancels

The dialog opens showing the pane's current sort key and order, and is anchored
over the pane it will re-sort.

## The explanation line

Ascending/Descending is hard to picture in the abstract — does "descending
timestamp" mean newest or oldest first? The line under the order segments
answers it with three sample values in the exact order the list will use,
updated live as you move:

| Key, order | Explanation |
|------------|-------------|
| Filename, ascending | `a.txt → m.txt → z.txt  (A to Z)` |
| Size, descending | `1 GB → 1 MB → 1 KB  (largest first)` |
| Timestamp, ascending | `2024 → 2025 → 2026  (oldest first)` |

## Sorting by what a pane shows

After its own keys the dialog lists what the pane shows that is not one of
them — **Size with folder totals** in the default
[layout](FILE_LIST_LAYOUTS_FEATURE.md) (the built-in **Size** orders files
only), a Git status when that extra is
showing. Sorting by one orders this folder only, by the values the pane
already has; rows without a value go last. Going to another folder brings back
the pane's own sort. One still being filled in is greyed out until every row
has its value. See
[Sorting by what a pane shows](FILE_LIST_LAYOUTS_FEATURE.md#sorting-by-what-a-pane-shows).

## Related keys

The quick-sort actions still work without opening the dialog:
`quick_sort_name`, `quick_sort_ext`, `quick_sort_size` and `quick_sort_date`;
running the same one again reverses the order. The menu bar's
**View → Sort By** submenu offers the same four sort keys, and
**View → Sort By ▸ Reverse Sort** toggles the order.

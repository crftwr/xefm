# Sort Dialog

Press **S** to open the sort dialog over the active pane. It replaces the old
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
  Changing the sort is two keystrokes: `S` then a letter.
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

## Related keys

The quick-sort keys still work without opening the dialog: **1** (filename),
**2** (extension), **3** (size), **4** (timestamp); pressing the same key again
reverses the order. The menu bar's **View → Sort By** submenu offers the same
four keys, and **View → Reverse Sort** toggles the order.

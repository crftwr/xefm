# Filepath TAB Completion

## Overview

XeFM's text prompts complete file and directory paths as you type. Press **TAB** in
any path or name prompt to fill in the rest of a name, or to pop up a list of the
matching entries when several are possible. It works like shell path completion:
the first TAB fills in as much as is unambiguous, and a second TAB (or continued
typing) shows and narrows the choices.

## Where it works

| Prompt | Opened by | Completes |
|--------|-----------|-----------|
| **Jump to Path** | `Shift-J` | directories only |
| **New Directory** | create-directory | files + directories |
| **New File** | create-file | files + directories |
| **Rename** | `R` (single item) | files + directories |
| **Create Archive** | create-archive | files + directories |

"Jump to Path" completes directories only, because you can only navigate into a
directory. The naming prompts complete both files and directories, which helps
when typing a nested name such as `sub/dir/name`.

## Using it

1. Start typing a path or name and press **TAB**.
2. **One match** — it is filled in completely. A directory gets a trailing `/`, so
   another TAB descends into it.
3. **Several matches** — the shared leading text is filled in and a **candidate
   list** appears just below the field:
   - Keep **typing** to narrow the list (it updates live; it hides when nothing
     matches and stays up when a single match remains).
   - **↑ / ↓** (also PageUp / PageDown) move the highlight through the list; it
     wraps around at the ends.
   - **Enter** on a highlighted row inserts that entry. With **no** row
     highlighted, Enter submits the prompt as usual — so completion never gets in
     the way of just accepting what you typed.
   - **Click** a row to insert it.
   - **Esc** closes the list (a second Esc cancels the prompt).

Paths beginning with `~` (your home directory), relative paths, and absolute
paths all complete. Matching is **case-sensitive**, matching how the filesystem
names things.

## Notes and limits

- Completion reads the **local filesystem** only. In a remote (S3 / SSH) pane,
  TAB simply offers no candidates rather than stalling.
- The directory listing behind the candidates is read **in one pass** (the same
  fast enumeration the file panes use) and runs **in the background**: on a slow
  location (a network mount, a spun-down disk) the prompt keeps taking
  keystrokes and the candidates appear when the listing lands. On a local disk
  this is indistinguishable from instant.
- Completing a path that does not exist yet is harmless: TAB just offers nothing.

See also: [developer notes](dev/TAB_COMPLETION_IMPLEMENTATION.md).

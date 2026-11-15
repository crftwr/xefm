# Directory Sync

English \| [日本語](DIRECTORY_SYNC_FEATURE.ja.md)

The [directory diff](DIFF_VIEWER_FEATURE.md#directory-diff) (`diff_directories`) lets
you copy, move or delete one item at a time. Sync does the rest in one step:
it makes the other side match the active side. You see the whole plan before
anything is written.

## Running a sync

1. Open the directory diff with **Select → Compare Directories…** and wait for
   the comparison to finish.
2. Put the side you want to copy **from** on the active side. `Tab` switches
   sides, and the active side's header is highlighted.
3. Press `s` and pick a mode:

   | Mode | New and changed files | Items only on the other side |
   |------|-----------------------|------------------------------|
   | **Update** | copied over | kept |
   | **Mirror** | copied over | deleted |

4. The viewer now shows the **plan**. Identical items are hidden, and the
   centre column shows what will happen to each remaining item:

   | Mark | Meaning |
   |------|---------|
   | `→` / `←` | copied in that direction |
   | `×` | deleted on the side the arrow points to |
   | `·` | left alone |

   A directory that exists on both sides has no mark of its own. Expand it to
   see what happens inside.

5. Change anything you disagree with (see below), then press `s` again. A
   summary lists how many items will be copied, replaced, sent back and
   deleted. Choose **Sync** to run it.

`Esc` leaves the plan without doing anything, and the comparison stays open.

## Changing the plan

Press `Space` on an item to move it to its next action:

- **A new item**: copy it, or leave it alone.
- **A changed file**: copy it over, leave it alone, or copy it **back** the
  other way. This lets one sync handle a folder where each side has a few
  files the other needs.
- **An item only on the other side**: delete it, leave it alone, or copy it
  back. Update starts these at "leave alone" and Mirror at "delete".
- **A directory on both sides**: skip it and everything inside it, or decide
  item by item (the default).

While the plan is open, `Enter` still opens the file diff and `edit_files` still
opens your merge tool (its key depends on your keymap preset — see
[Keymap Presets](KEYMAP_PRESETS_FEATURE.md#every-key-side-by-side)). After a merge, the comparison updates and that item's action
is worked out again. Your other changes are kept.

`Tab` reverses the plan's direction and resets your changes.

## What sync will not do by default

- **Overwrite a newer file.** A changed file that is newer on the destination
  starts at "leave alone". Press `Space` to copy it anyway. The summary counts
  how many were left alone this way.
- **Replace a file with a folder, or a folder with a file.** When a name is a
  file on one side and a folder on the other, the comparison marks it as
  different (`!`, with the slash only on the folder's side), and sync always
  leaves it alone.
- **Delete for good without asking twice.** The summary shows deletions
  apart from the copies. When anything would be deleted for good, the dialog
  starts on **Cancel**.

## Things to know

- **Deletions go to the Trash** (the Recycle Bin on Windows) wherever there
  is one, so a Mirror's deletions can be put back. Where there is none (on
  `ssh://`, `s3://`, a removable or network drive on Windows), they are
  permanent, and the summary says so. `DELETE_TO_TRASH = False` in
  `config.py` makes them all permanent.
- **Copies run before deletions.** If you cancel a sync partway (`Esc` in the
  progress dialog), it stops wherever it is, but anything it has removed was
  removed only after every copy had finished. What was done stays done.
- **Files are compared by content.** "Changed" means the bytes differ, not
  just the date.
- **Hidden files follow the viewer.** When hidden files are not shown, they
  are not compared and the plan leaves them alone. A folder copied or deleted
  as a whole includes everything inside it, hidden files too.
- The sync runs through the same engine as `copy_files` and `delete_files`, with its progress
  dialog. It works across local folders, `ssh://`, `s3://` and mounted
  shares.

## Keys

| Key | Action |
|-----|--------|
| `s` | Open a plan, or run the open one (`dir_diff.sync`) |
| `Space` | Change the focused item's action (`dir_diff.cycle_sync_action`) |
| `d` | Show or hide the items that are the same on both sides (`dir_diff.toggle_identical`) |
| `Esc` | Leave the plan |

All of them can be rebound in `KEY_BINDINGS`. See
[Key Bindings](KEY_BINDINGS_FEATURE.md).

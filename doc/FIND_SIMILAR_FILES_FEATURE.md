# Find Similar Files

English \| [日本語](FIND_SIMILAR_FILES_FEATURE.ja.md)

**Tools → Find Similar Files…** looks through a folder for files you probably
don't need twice:

| Method | Finds | Needs |
|--------|-------|-------|
| **Identical files** | the same content under different names or in different folders | nothing more |
| **Similar images** | the same picture resized, re-encoded or lightly edited | nothing more |
| **Similar videos** | the same video re-encoded or resized, and clips cut from a longer video | [ffmpeg](https://ffmpeg.org) on your `PATH` |
| **Similar audio** | the same recording re-encoded or with its tags changed, excerpts cut from a longer recording, and tracks inside a longer mix | `fpcalc` from [Chromaprint](https://acoustid.org/chromaprint) on your `PATH` (`brew install chromaprint`, `apt install libchromaprint-tools`) |

The detection is done by [similar-files](https://github.com/crftwr/similar-files),
which XeFM runs for you. A method that is missing something shows in the menu
what to install.

## Running a scan

1. Go to the folder to scan, or select the folders and files to scan.
2. Choose **Tools → Find Similar Files…** and pick a method.

The scan starts at once and **runs as a program of its own**. A video scan can
take hours. You can keep using XeFM, or quit it: the scan carries on, and the
next time XeFM starts it tells you what finished while it was closed.

The status bar's right end shows how it is going:

```
⠋ Similar videos extract 42%
```

and says when it is done:

```
✓ Similar videos: 12 groups
```

## Looking at the results

Click that, or open **Tools → Background Jobs…**, and choose the scan. Its
results open in a **new tab** of the pane, a [tree file](TREE_FILES_FEATURE.md)
with one folder per group. The folder you were in stays in its own tab, and
closing the results tab (`Ctrl-W`) takes you back to it. In each group, the file the others were compared with comes
first.

- `Enter` on a group shows its files. View and compare them there.
- To delete or move the real files, select them (or whole groups) and run
  `sync_other_to_current` (see [Tree Files](TREE_FILES_FEATURE.md#acting-on-the-real-files)).
  The other pane shows them as one list, wherever they live.
- `Backspace` goes back up to the list of groups.

**You don't have to wait for the end.** While a scan runs, choosing it in the
jobs list offers **Look at the groups so far**. The results are rewritten
every few minutes as the scan goes, and the pane follows. Those groups are
provisional: a file the scan reads later can still join a group or start a
new one. The header says so until the scan is done. Groups of identical files
never change once they appear.

Nothing is ever deleted for you. Deciding which copy to keep is up to you.

## Stopping a scan

Choose a running scan in the jobs list, then **Stop the scan**. It stops within
a second or so, and the groups it had found are kept.

Stopping, putting the computer to sleep or restarting it doesn't waste the
work done. similar-files remembers what it has already read, so running the
same scan again picks up quickly.

## Things to know

- **Local folders only.** A mounted network share counts as local. Folders on
  `ssh://` or `s3://` can't be scanned from here yet.
- **Results are kept in `~/.xefm/scans/`**, one folder per scan, with the
  results file (`result.xft`) and the scan's log. Nothing is written beside your files. The ten most recent
  finished scans are kept.
- If a scan ends without finishing (its process was killed, for example), the
  jobs list says so, and choosing it shows its log.
- **similar-files comes with XeFM** (0.5 or later), with numpy, which lets a
  library of thousands of videos be grouped in minutes rather than an hour.
  Video and audio scans still need ffmpeg and fpcalc, as listed above.
- On a machine numpy has no ready-made package for (32-bit ARM Linux, for
  example), XeFM installs without it and groups videos more slowly; the
  scan's log says which one it used.

## See also

- [Tree Files](TREE_FILES_FEATURE.md): browsing the results, and acting on the real files
- [Background Jobs](BACKGROUND_JOBS_FEATURE.md): the jobs list

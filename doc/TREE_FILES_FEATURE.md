# Tree Files (.xft)

English \| [日本語](TREE_FILES_FEATURE.ja.md)

An `.xft` file holds **groups of references to files**: for example, the
groups of similar videos a scan found. Each group lists files that may live
in many different folders, on this computer or a server. Press `Enter` on a
`.xft` file to browse it like an archive.

```
scan.xft/
  trip.mp4 (2)/            ← a group
    trip.mp4               ← stands for /Users/me/Movies/trip.mp4
    trip-small.mp4         ← stands for /Volumes/NAS/trip-small.mp4
    trip (copy).mp4
  logo.png (1)/
    …
```

You don't write these files yourself. Programs write them: XeFM's
[Find Similar Files](FIND_SIMILAR_FILES_FEATURE.md) does, through
similar-files. The format is described in [XFT_FORMAT.md](XFT_FORMAT.md)
for anyone writing such a program.

## Browsing

- `Enter` on the file goes in. `Enter` on a group opens it. `Backspace` goes
  back up, and from the top it returns to the folder, with the cursor on the
  file.
- Each entry shows the size and date **recorded in the file**, so a group of
  files on a slow server lists instantly.
- Viewing an entry (**File → Open With ▸ Viewer**), comparing two
  (**Select → Compare Selected Files…**) and copying to the other pane work,
  all reading the real file.
- `Enter` on an entry that stands for a folder goes to that folder.

## Columns a tree adds

The program that writes a tree can record more about each file and say how
to show it. similar-files records how similar each file is to the first
file of its group, and asks for a **Similarity** column before the size.
XeFM shows such a column only inside the trees that ask for it:

- **Sort by it.** The sort dialog (`sort`) offers it by its name, for the
  group you are in.
- **Hide it** with **View → Show ▸**, the entry of the same name, set to
  **Off**.
- **Use it in your own layout.** In `config.py`, XeFM calls it `xft.` plus
  the tree's name for it: `xft.similarity`. Name it in a column of
  `LAYOUTS`, or change how the tree shows it in `LAYOUT_EXTRAS` with only
  the keys you change, such as `'xft.similarity': {'when': 'never'}`. Both
  work before you have opened any tree. See
  [File List Layouts](FILE_LIST_LAYOUTS_FEATURE.md).

Similarity is a percent rounded down, so `100%` means an exact match. A tree
of identical files does not ask for the column, since every file in it would
say `100%`.

## Acting on the real files

Entries in the tree are references. They can't be deleted or renamed there,
because the tree is a record of what was found. To work on the real files:

- **`sync_other_to_current`** opens the real location of the entry under the cursor in the
  other pane, with the cursor on the file. The tree stays where it is.
- **Select several entries (or whole groups) and run `sync_other_to_current`**. The other
  pane shows all their real files as one list, wherever they live. Delete,
  move or compare them there. This is the quick way to clean up duplicates
  spread over many folders.
- `sync_current_to_other` from the other pane goes to the real location of the entry highlighted
  in the tree.
- Whatever leaves XeFM gets the **real file**: opening an entry in its
  application (**File → Open With ▸ Default App**), revealing it in Finder or
  Explorer (**File → Reveal in File Manager**), editing it
  (**File → Open With ▸ Text Editor**), and copying its path.

The two `sync_…` actions have no menu item; run them from the command palette
(**Tools → Command Palette…**) or on their key. Keys depend on your keymap
preset — see [Keymap Presets](KEYMAP_PRESETS_FEATURE.md#every-key-side-by-side).

## Trees that are still being written

A long scan rewrites its tree file every few minutes, so you can start
looking before it finishes. While it is still running:

- the pane header says **"scanning 42% — groups may change"**;
- the pane updates by itself when the file is rewritten;
- a group may gain or lose files, or change its name. XeFM keeps you in the
  same group when it can, and returns to the top of the tree (saying so in
  the log) when the group is gone;
- `sync_other_to_current` on a selection asks before opening the files, because the groups
  you selected may still change.

Groups of identical files are final as soon as they appear. Only similar-file
groups can change.

## See also

- [Find Similar Files](FIND_SIMILAR_FILES_FEATURE.md)
- [File lists](FILE_LIST_IMPORT_FEATURE.md): flat lists of paths (`.m3u8`,
  `.lst`)

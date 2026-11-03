# The .xft Format

English \| [日本語](XFT_FORMAT.ja.md)

An `.xft` file is **a tree of references to places**: groups that hold
other groups or references, and references that point at a file or folder
somewhere (a local path, or a URI such as `ssh://…` or `s3://…`). XeFM
browses it like an archive. See [Tree Files](TREE_FILES_FEATURE.md) for what
that looks like.

The format is meant to be written by programs, such as a duplicate finder, a
search tool or a catalogue script, and read by XeFM. Its first producer is
[similar-files](https://github.com/crftwr/similar-files) (`--format tree`).
This page is the specification. Producers write it from this description and
need nothing from XeFM's code.

## The file

- UTF-8 JSON, one object. The extension is `.xft`.
- **Replace it whole.** A producer that writes the file more than once
  writes a temporary file next to it and renames it over the old one
  (`os.replace`), so a reader never sees half a file.

```json
{
  "format": "xft",
  "version": 1,
  "title": "Similar videos in /Users/me/Movies",
  "generator": {"name": "similar-files", "version": "0.2.0"},
  "final": false,
  "complete": false,
  "generation": 7,
  "written": 1760340000.5,
  "progress": {"done": 120, "total": 400},
  "attributes": {
    "similarity": {"label": "Similarity", "type": "ratio",
                   "show": {"columns": [{"before": "size"}]}}
  },
  "nodes": [
    {
      "name": "trip.mp4 (1)",
      "extra": {"method": "video", "threshold": 0.8, "members": 1},
      "children": [
        {"name": "trip.mp4", "target": "/Users/me/Movies/trip.mp4",
         "attrs": {"size": 734003200, "mtime": 1700000000.0},
         "extra": {"role": "anchor", "similarity": 1.0}},
        {"name": "trip-small.mp4", "target": "/Volumes/NAS/trip-small.mp4",
         "attrs": {"size": 120000000, "mtime": 1700100000.0},
         "extra": {"role": "member", "similarity": 0.93}}
      ]
    }
  ]
}
```

## Top level

| Key | Required | Meaning |
|---|---|---|
| `format` | yes | Always `"xft"`. |
| `version` | yes | `1`. A reader refuses a version it does not know. |
| `nodes` | yes | The top-level nodes. |
| `title` | no | What the tree is, in a few words. |
| `generator` | no | `{"name", "version"}` of the producing program. |
| `final` | no, default `true` | `false` while the producer may still rewrite the file. Every write but the last says `false`. |
| `complete` | no, default `final` | On a final file, `false` when the producer stopped before it had looked at everything, such as a cancelled scan. |
| `generation` | no | Counts the writes, starting at 1, so a reader can tell a new snapshot from the one it has. |
| `written` | no | When the file was written, in seconds since the epoch. |
| `progress` | no | `{"done", "total"}` of a producer still working. `total` is `0` when not known. |
| `attributes` | no | Values the producer records in its references' `extra`, declared so that a reader can show them. See [Attributes](#attributes). |

## Nodes

A node is an object with a `name` and **at least one of** `children` and
`target`:

| Key | Meaning |
|---|---|
| `name` | The label shown. A `/` or `\` in it reads as `_`. Names should be unique among siblings. A reader makes duplicates unique by adding ` [2]`, ` [3]`, … in order, comparing names as a case-insensitive file system does. |
| `children` | A list of nodes. A node with children is a **group**, shown as a folder. |
| `target` | An absolute path or a URI: the place this node stands for. A node with a target is a **reference**. |
| `attrs` | What the producer recorded about the target: `size` (bytes), `mtime` (seconds since the epoch), `is_dir`. A reader shows these instead of reading the target, which may be on another machine. All are optional. |
| `extra` | The producer's own data, such as a similarity or a role. A reader may show what it understands and ignores the rest. The keys declared in `attributes` are the ones it can show. |
| `final` | On a group, `true` when it cannot change any more even though the file as a whole is still provisional. Identical-file groups are final as soon as they are written. |

A node with both `children` and `target` is a group that is also a place: it
opens as a folder, and the pane-sync actions (`sync_current_to_other`,
`sync_other_to_current`) reveal its target.

`line` on a reference is **reserved** for a position in a text file (a search
hit). It is not defined yet.

## Attributes

`attributes` declares values the producer records in the `extra` of its
references, so a reader can show them and sort by them without knowing the
producer. Each key is the `extra` key that holds the value, and says what
the value is:

| Key | Meaning |
|---|---|
| `type` | `text` (the default), `count` (a whole number), `size` (bytes), `time` (seconds since the epoch), `duration` (seconds), `ratio` (a score from 0 to 1) or `enum` (one of `values`). |
| `label` | Its name for people, on a column and in the sort dialog. The key by default. |
| `values` | For an `enum`: `{value: {"label": …, "color": …}}`, what each value means and a color to show it in (`red`, `green`, `yellow`, `blue`, `purple`, `orange`, `gray`). |
| `show` | How the producer suggests showing it. Without `show`, the value is defined but shown only where the user puts it. |

`show` holds `columns`, `markers` or both, each a list of objects:

- A **column** goes `before` or `after` one of the reader's columns
  (`name`, `ext`, `size`, `mtime`), in its place with `replace`, or at the
  end when it names none. It may also give `format`, `width`, `align` and
  `priority`.
- A **marker** is drawn beside a column's text: `on` names the column
  (`name` by default) and `side` is `before` or `after`. It may also give
  `format` and `limit`.

`format` names one of the reader's formats for the type: `ratio` has
`percent` (`93%`, rounded down) and `decimal` (`0.93`). The formats of the
other types are listed in [File List Layouts](FILE_LIST_LAYOUTS_FEATURE.md).

A value of the wrong type, such as text where a `ratio` is declared, is not
shown. A declaration the reader cannot use is ignored, and the tree still
opens. `show` is a suggestion: the user can hide the column, move it, or show
the value somewhere else ([Tree Files](TREE_FILES_FEATURE.md)).

## Provisional files

While `final` is `false`, every group may still change when the file is next
written. Members can join or leave it, and its first entry can change. A
reader should:

- say that the tree is provisional, with `progress`;
- read the file again when it changes;
- find a group again by the **target of its anchor** (the reference with
  `extra.role` `"anchor"`, or else its first reference) rather than by its
  name, which can change.

Producers write identical-content groups once and mark them `"final": true`.

## Versioning

New optional keys can be added to version 1. Readers ignore keys they don't
know. Any change that would make a version 1 reader show something wrong
gets a new `version`.

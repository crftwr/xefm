# Navigation Dialogs

XeFM's directory navigation dialogs all share one searchable-list picker: a
scrollable list you filter by typing, with the same keys for moving through it
and choosing an entry. Five actions open five flavors of that picker (press `?`
for the keys yours are on, or find them in the **Go** menu):

| Action | Dialog | What it lists |
|--------|--------|---------------|
| `favorites` | Favorites | Your configured favorite directories |
| `jump_to_path` | Jump | Directories found by scanning from the current directory |
| `history` | History | Directories you have already visited in this pane |
| `drives` | Drives | Storage locations and volumes (and S3 buckets, if available) |
| `connect_server` | Connect to Server | Saved servers, plus the ones found on the network (macOS and Windows) |

Whichever one you open, pressing **Enter** navigates the current pane to the
selected location.

## Shared controls

Every navigation dialog uses the same list-picker controls:

- **Type** to filter the list, using the same search syntax as the file pane's
  incremental search: matching is case-insensitive and hits anywhere in the row,
  several keywords separated by spaces all have to match (`work src` finds
  `Projects — /home/me/work/src`), `*` and `?` wildcards work (`*.py`), and
  romaji finds Japanese entries through Migemo (`kensaku` finds `検索`)
- **Backspace** to remove filter characters
- **Up/Down** to move through results
- **Page Up/Page Down** to scroll by page
- **Home/End** to jump to the first/last result
- **Enter** to navigate to the selected entry
- The **remove** key (`remove_list_item`) to drop the highlighted entry, where
  there is something to
  remove: it forgets a directory in History or the Filter prompt, forgets a
  saved server in Connect to Server, and disconnects or ejects a volume in
  Drives. Favorites and External Programs come from your config, so there is
  nothing there to remove and the key does nothing
- **Escape** or **q** to cancel and close

A line along the bottom of each dialog names the keys that are live in it, so
the remove key shows up only where it applies — and shows the key *you* have
bound if you rebound it.

## Favorites (J)

Press **J** to open a searchable list of your favorite directories and jump to
any of them instantly.

The list opens immediately, whatever is on it. XeFM does not go and look at your
favorites before showing them — checking a network share that is asleep, offline
or behind a VPN you have not connected can take the better part of a minute per
entry, and a few of those turned opening the list into a stall (issue #430). So
nothing is contacted until you pick a row.

Pick one that is not there and **the pane does not move**. It keeps the
directory it was showing, with your cursor where you left it, and the log says
`Directory not found: …` — one line, once. The same goes for the Drives and
History pickers, which also name directories you cannot see from where you are.

That means a favorite can be anywhere: a NAS, a USB disk you plug in on
Tuesdays, an `ssh://` or `s3://` location. It sits quietly in the list whether
or not it is reachable today.

### Default favorites

XeFM ships with four — Home, Documents, Downloads and Desktop — and they are
yours to edit from the first run; your `~/.xefm/config.py` holds its own copy.

Each entry is shown with the path you wrote (with `~` expanded), e.g.:

```
Home (/Users/username)
Projects (/Users/username/dev)
Web Server (/var/www)
```

### Customizing your favorites

Edit `FAVORITE_DIRECTORIES` in your `~/.xefm/config.py`. Each entry needs a
`name` (what to call it) and a `path` (where it is; `~` expands to your home
directory):

```python
class Config:
    FAVORITE_DIRECTORIES = [
        {'name': 'Home', 'path': '~'},
        {'name': 'Work Projects', 'path': '~/work'},
        {'name': 'Scripts', 'path': '~/bin'},
        {'name': 'Web Server', 'path': '/var/www'},
        # Add your own here
    ]
```

To use a different key, rebind the `favorites` action in `KEY_BINDINGS`, e.g.
`'favorites': ['f']`.

## Jump dialog

The **Jump** dialog (`jump_to_path`) searches your filesystem for directories and
jumps to a match.
This is ideal for reaching a deeply nested directory without navigating the tree
by hand.

- Scans from the **current directory** downward and lists directory paths
  relative to that root
- Scanning runs in the background with a progress indicator, and can be
  cancelled
- The scan is bounded by an internal cap (not user-configurable) so the dialog
  stays responsive

Type to filter as results stream in. You can match a plain directory name
(`projects`), a path fragment (`work/src`), or a hidden directory (`.config`).

**Tips for large or network filesystems:** narrow the search by starting from a
more specific directory before opening the dialog (navigate into `~/Documents`
first rather than scanning all of `~`). Permission-denied directories are
skipped automatically. If an expected directory does not appear, it may be
beyond the internal scan cap — start from a closer parent, or use Favorites for
known locations.

## History (H)

Press **H** to open a searchable list of directories you have already visited in
the current pane, and jump back to any of them. Each pane keeps its own history.

The **remove** key forgets the highlighted directory. Every visit to it is
dropped, not just the most recent one, and the change is saved immediately. It
is not a blocklist: going there again puts it back at the top.

The number of remembered entries is set by `MAX_HISTORY_ENTRIES` in
`~/.xefm/config.py` (default 100).

## Drives dialog (D)

Press **D** to open a searchable list of storage locations and jump to one. On
macOS and Windows its first row is **Connect to Server…**, which opens the
[Connect to Server](CONNECT_TO_SERVER_FEATURE.md) dialog.

### Local locations

The list opens with a few fixed locations — Home (`~`), Root (`/`) on macOS and
Linux, and Desktop, Documents and Downloads when they exist — followed by
whatever the machine has mounted: drive letters on Windows, `/Volumes` on macOS,
`/media` and `/mnt` on Linux.

### Choosing your own fixed locations

The fixed part is yours to define. Set `DRIVE_LOCATIONS` in `~/.xefm/config.py`
to the list you want and it replaces the built-in one:

```python
DRIVE_LOCATIONS = [
    {'name': 'Home', 'path': '~'},
    {'name': 'Work', 'path': '~/work'},
    {'name': 'NAS', 'path': 'ssh://nas/'},
]
```

Set it to `[]` to drop the fixed rows entirely and list only the mounted
volumes. Left unset (`None`), you get the built-in set described above.

A local path that does not exist is skipped. A remote location (`ssh://`,
`s3://`) is listed exactly as written, and nothing connects until you select it.

Mounted volumes, SSH hosts and S3 buckets are not configured here — they are
read from the machine every time the dialog opens. The SSH rows come from your
`~/.ssh/config`, so a host you no longer use is removed by editing that file.

Visual indicators:

- Home directory
- Local filesystem directory
- S3 bucket

### S3 buckets

When `boto3` is installed and AWS credentials are configured, the drives dialog
also lists every S3 bucket your credentials can reach. Select a bucket and press
**Enter** to browse it in the current pane like any other filesystem.

To enable S3 listing, configure AWS credentials with any of: AWS CLI
(`aws configure`), the `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` environment
variables, or an `~/.aws/credentials` file.

If buckets do not appear, check that credentials work (`aws s3 ls`), network
connectivity, and your IAM permissions for `ListBuckets`. A "No credentials
configured" message points at the step above.

### Disconnecting and ejecting

The **remove** key disconnects the highlighted network mount, or ejects the
highlighted external volume so the device is safe to unplug. On any other row —
Home, `C:\`, an S3 bucket, an SSH host — it does nothing.

If a pane is inside the volume, XeFM moves it out first. If something else on
the machine is using the volume, the operating system refuses and XeFM says so
rather than forcing it.

## Choosing between them

- **Favorites (J)** — instant, for a handful of directories you use constantly
- **History (H)** — instant, for somewhere you were a moment ago
- **Jump** — slower (scans the disk), for finding a directory you
  don't have memorized
- **Drives (D)** — for switching between volumes, drives, or S3 buckets, and
  for disconnecting or ejecting one
- **Connect to Server** — for mounting a NAS or file server in the
  first place

## See Also

- [Connect to Server](CONNECT_TO_SERVER_FEATURE.md) — mounting a NAS or file
  server from inside XeFM
- [S3 Integration](XEFM_USER_GUIDE.md#s3-integration) (in User Guide)

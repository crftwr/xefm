# Navigation Dialogs

XeFM's directory navigation dialogs all share one searchable-list picker: a
scrollable list you filter by typing, with the same keys for moving through it
and choosing an entry. Four keys open four flavors of that picker:

| Key | Dialog | What it lists |
|-----|--------|---------------|
| **J** | Favorites | Your configured favorite directories |
| **Shift-J** | Jump | Directories found by scanning from the current directory |
| **H** | History | Directories you have already visited in this pane |
| **D** | Drives | Storage locations and volumes (and S3 buckets, if available) |

Whichever one you open, pressing **Enter** navigates the current pane to the
selected location.

## Shared controls

Every navigation dialog uses the same list-picker controls:

- **Type** any letters/numbers to filter the list (case-insensitive, matches
  anywhere)
- **Backspace** to remove filter characters
- **Up/Down** to move through results
- **Page Up/Page Down** to scroll by page
- **Home/End** to jump to the first/last result
- **Enter** to navigate to the selected entry
- **Escape** or **q** to cancel and close

## Favorites (J)

Press **J** to open a searchable list of your favorite directories and jump to
any of them instantly. Only directories that actually exist are shown.

### Default favorites

XeFM ships with these defaults: Home, Documents, Downloads, Desktop, Projects,
Root (`/`), Temp (`/tmp`), and Config (`~/.config`).

Each entry is shown with its resolved path, e.g.:

```
Home (/Users/username)
Projects (/Users/username/Projects)
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

## Jump dialog (Shift-J)

Press **Shift-J** to search your filesystem for directories and jump to a match.
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

The number of remembered entries is set by `MAX_HISTORY_ENTRIES` in
`~/.xefm/config.py` (default 100).

## Drives dialog (D)

Press **D** to open a searchable list of storage locations and jump to one.

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

## Choosing between them

- **Favorites (J)** — instant, for a handful of directories you use constantly
- **History (H)** — instant, for somewhere you were a moment ago
- **Jump (Shift-J)** — slower (scans the disk), for finding a directory you
  don't have memorized
- **Drives (D)** — for switching between volumes, drives, or S3 buckets

## See Also

- [S3 Integration](XEFM_USER_GUIDE.md#s3-integration) (in User Guide)

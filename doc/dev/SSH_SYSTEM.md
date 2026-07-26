# SSH/SFTP Subsystem

XeFM's remote browsing runs on `xefm/ssh_connection.py` (`SSHConnection` +
`SSHConnectionManager`), which drives OpenSSH's `ssh` / `sftp` CLIs in batch mode
over a shared control master. This document records the non-obvious correctness,
performance, and packaging behaviors that make SFTP browsing robust — the reasons
certain things are done a specific way, so they aren't accidentally undone.

Related code:
- `xefm/ssh_connection.py` — connections, control master, SFTP command building
- `xefm/ssh_cache.py` — `SSHCache`, the TTL cache behind `list_directory`/`stat`
- `xefm/ssh_config.py` — `SSHConfigParser` (`~/.ssh/config`, `Include`, wildcards)
- `macos_app/src/XeFMAppDelegate.m` — packaged-app `PATH` fix

Related docs:
- `PATH_POLYMORPHISM_SYSTEM.md` — the polymorphic `Path` layer that exposes remote
  paths (`ssh://host/...`) to the rest of XeFM
- `../SFTP_SUPPORT_FEATURE.md` — user-facing SFTP feature docs

---

## SFTP path handling

Every remote operation builds an `sftp` batch command as a **string**. So any
path that reaches a command must be quoted, must be normalized, and — for
directory listings — must be parsed before it is filtered. All three rules live
in `SSHConnection`.

### Path quoting — `_quote_path()`

SFTP batch mode splits each command on whitespace, so a filename containing
spaces or special characters would be mis-parsed as several arguments and the
operation would fail.

`_quote_path(path)` escapes any embedded `"` (→ `\"`) and wraps the whole path in
double quotes. Every command construction routes its paths through it —
`list_directory`, `stat`, `read_file`, `write_file`, `delete_file`,
`delete_directory`, `create_directory`, `rename`, and glob. For example a copy
becomes `get "/remote/my file.txt" "/tmp/tmpXXX"`.

This correctly handles spaces, parentheses, brackets, embedded quotes, and
runs of multiple spaces.

### Path normalization — `posixpath.normpath()`

Search and path-join operations can hand SFTP paths carrying runaway `./././…`
or `..` segments. Left as-is, these both blow up the SFTP command (a real
observed failure was a path ending in dozens of repeated `/.`) and pollute the
path cache with many equivalent-but-distinct keys.

`list_directory()` and `stat()` normalize `remote_path` with
`posixpath.normpath()` before the cache lookup and before any SFTP call. That
collapses `//`, strips `/./`, resolves `/a/../b`, and trims trailing slashes. It
is a cheap string operation; already-normal paths pass through unchanged, and
normalizing equivalent paths actually raises the cache hit rate.

### Dot-entry filtering — parse first, then filter

SFTP's `ls -la` emits `.` and `..` rows, and in that output the filename field
is a **full path** (`…/projects/xefm/.`), not a bare `.`. So filtering on the raw
line (e.g. `line.endswith(' .')`) silently misses them.

`list_directory()` instead filters **after** `_parse_ls_line()` has extracted the
basename: `if entry['name'] in ('.', '..'): continue`.

Getting this wrong is severe, not cosmetic: a surviving `.` entry re-enters the
current directory, so a recursive walk loops and every yielded entry appears
named `.`. The visible symptom is subtle — e.g. a `*.py` search returns 0
results rather than obviously hanging. The general lesson: parse structured
command output into fields first, then filter on the parsed fields.

---

## Connection establishment

XeFM shares a single OpenSSH control master per host. Establishing it reliably —
especially from a packaged macOS app — required the behaviors below.

### Control-socket location & per-process isolation

Control sockets live at `~/.xefm/ssh_sockets/xefm-ssh-{hostname_hash}-{pid}`
(created in `SSHConnection.__init__`, where `hostname_hash` is the first 8 hex
chars of an MD5 of the hostname), **not** under `tempfile.gettempdir()` / `/tmp`.

- **Why the home directory:** a DMG-mounted or otherwise sandbox-restricted app
  may have limited `/tmp` access, and socket creation there can fail silently.
  The failure surfaces as SSH's opaque `Connection closed by UNKNOWN port 65535`.
  The user's home directory is always writable in that context, and keeping
  sockets under `~/.xefm/` (next to `config.py` and `ssh_cache.json`) makes them
  easy to inspect and clean up.
- **Why the `{pid}`:** each XeFM process gets its own control socket, so one
  instance exiting and deleting its socket cannot break another instance
  connected to the same host.
- Socket paths must stay short — the Unix-domain socket path limit is ~104
  characters on most systems.

### Foreground control master (no `-f`)

`_establish_control_master()` runs `ssh -N` (no remote command) **without** the
`-f` (fork-to-background) flag, with `ControlMaster=yes`,
`ControlPath={socket}`, `ControlPersist=10m`, `BatchMode=yes`, and
`StrictHostKeyChecking=accept-new`.

With `-f`, `ssh` backgrounds immediately and the parent returns success even when
a `ProxyCommand` hangs — so a failed connection can be neither detected nor timed
out. Running in the foreground instead lets XeFM poll for the control socket to
appear, apply a timeout, and capture stderr on failure. Once the socket exists,
XeFM terminates the master process; `ControlPersist` keeps the socket alive after
XeFM (or the whole app) exits, for 10 minutes past last use.

### Default/home directory resolution

Opening an SSH drive should land in a natural location (the user's home /
current working directory), not always at `/`. `connect()` already runs a `pwd`
as its connection test, so the default directory is captured **for free** from
that same command — no extra round-trip.

SFTP's `pwd` prints `Remote working directory: /path/to/dir`; `connect()` parses
that line into `SSHConnection.default_directory`, falling back to `/` if the line
can't be parsed. The drives-dialog navigation (`xefm/filter_list_dialog.py`)
connects on demand (reusing any pooled connection) and, when
`default_directory` is set and not `/`, navigates to
`ssh://{host}{default_directory}`. Any failure falls back to root, so the dialog
never crashes on a server that doesn't support `pwd`.

### Packaged-app PATH (macOS DMG)

A DMG-mounted app does not inherit the user's shell `PATH`. SSH configs that use
a `ProxyCommand` shelling out to `aws`, `gcloud`, etc. therefore can't find those
tools and fail with the same `port 65535` error.

`macos_app/src/XeFMAppDelegate.m` fixes this in `setupEnvironmentPath`, called
before the XeFM module is imported. It prepends the common tool locations —
`/usr/local/bin`, `/opt/homebrew/bin`, `/opt/local/bin`, `~/bin`, `~/.local/bin`,
and the `~/Library/Python/3.x/bin` dirs — to `PATH` via `setenv`, and mirrors the
result into Python's `os.environ` so every subprocess (and thus the
`ProxyCommand`) can resolve those tools.

---

## Control-master sharing & connection-check caching

The control master is an SSH multiplexing feature: multiple SFTP operations share
one authenticated TCP connection instead of each paying a full TCP handshake +
key exchange + auth + teardown. The first operation pays that cost; every
subsequent `sftp` invocation connects to the local control socket and runs
essentially instantly. This is the single biggest reason remote browsing feels
responsive, so the sharing must not be broken by accident (see the
control-socket and `-f` notes above).

**Detecting a dead master.** The master can die independently of XeFM — network
drop, remote reboot, `sshd` restart, `ControlPersist` idle-timeout, or manual
kill — and there is no callback when it does. XeFM must actively check.
`_check_control_master()` runs `ssh -O check -o ControlPath={socket} {host}`
(5 s timeout) and reports whether the master is still listening; `is_connected()`
uses it to drive automatic reconnection so the user sees a working browse rather
than a cryptic SFTP hang.

**Why the check is cached.** Running `ssh -O check` on *every* operation would
add a subprocess round-trip to each list/stat and largely negate the control
master's benefit — a directory scroll or a sort over N files would fire N checks.
But the master is very stable once up: it does not randomly die, and if it *has*
died the next SFTP command fails within a second or two and triggers
reconnection anyway. So a slightly stale "connected" answer is cheap and safe.

`is_connected()` therefore caches the result:

- `_control_master_check_interval = 5.0` s. Within the interval it returns the
  cached `_cached_control_master_status` with no subprocess; past the interval it
  runs the real check, updates the cache and timestamp, and clears `_connected`
  if the check fails.
- Net effect: for a burst of operations inside 5 s, one `ssh -O check` instead of
  one per operation. Disconnection detection is delayed by at most the interval —
  imperceptible in practice, and failing operations recover on their own.

**Manager-level health check.** `SSHConnectionManager._check_connection_health()`
adds a second, coarser layer with `_health_check_interval = 60` s. Within that
window it trusts `conn._connected` directly (no call into `is_connected()` at
all); only once the 60 s window elapses does it call `conn.is_connected()`
(which itself may still hit the 5 s cache). The two layers keep pooled
connections cheap to reuse in `get_connection()`.

---

## Bulk stat caching during `list_directory`

Browsing a directory needs an `ls`-style listing *and* per-file stat data (size,
mtime, permissions) for display and sorting. Fetching those separately would be
one `ls -la` plus one `ls -l` per file — N+1 network round-trips for N files, the
dominant cost on a high-latency link.

`list_directory()` already gets everything it needs from the single `ls -la`, so
while parsing each row it also writes that row into the cache under the same key
`stat()` would use — `_cache.put(operation='stat', hostname=…, path=…, data=entry)`
for `posixpath.join(remote_path, entry['name'])`. A subsequent `stat()` on any
listed file is a pure cache hit with no network call, turning the common
"open directory, then sort/inspect its files" flow into a single round-trip.

Details worth preserving:
- `stat()` and `list_directory()` share an identical cache-key format, so the
  entries populated here are exactly what `stat()` looks up.
- Entries are cached under the normal data TTL of `SSHCache` (default 30 s,
  configurable via `config.SSH_CACHE_TTL`; cached *errors* use the longer
  `error_ttl`, default 300 s). `stat()` still falls back to `ls -l` on a miss.
- No API changes were needed — `stat()`, `SSHCache`, and the `Path` layer already
  supported this; only `list_directory()`'s parse loop grew the `put` call.

## Byte-level transfer progress & cancellation

Issue #131. A remote copy showed no byte-level progress and could not be
cancelled: `read_file()`/`write_file()` fired the progress callback exactly
twice, at 0% and 100%, with one uninterruptible `sftp -b` subprocess in between.

### Why the sftp progress meter is not the answer

`sftp` has a progress meter, and even an interactive `progress` command to
toggle it, but it never reaches us:

- With stdout on a pipe — which is how `_execute_sftp_command()` invokes it —
  no meter is emitted at all.
- The `progress` command *toggles*, so sending it unconditionally turns the
  meter **off** on a terminal, where it would otherwise have been on.
- It could not be coaxed into emitting even on a real pty with a deliberately
  throttled transfer.

So the byte count is obtained by watching the file being written instead.

### `_TransferMonitor`

A sampling thread runs alongside the `sftp` subprocess and pushes updates to the
caller's progress callback. The byte count comes from a `probe` supplied per
direction:

- **Download** — `os.path.getsize(tmp_path)`. `sftp get` is filling that local
  temp file, so its size on disk *is* the progress. Free, exact, and needs
  nothing remote. Sampled every `_DOWNLOAD_POLL` (0.25 s).
- **Upload** — `_remote_size(remote_path)`. The source file is already complete,
  so there is nothing local that grows; the destination is measured instead.
  Sampled every `_UPLOAD_POLL` (0.5 s), less often because each sample costs a
  command.

`_remote_size()` runs `stat -c %s` with a `stat -f %z` fallback (GNU vs BSD) and
a final `echo 0` for the window before the file exists. It runs over the
**existing ControlMaster**, so it is a channel on the connection already open —
not a second SSH session and no re-auth. Deliberately one command per sample
rather than a long-lived remote polling loop: a remote `while :; do … done`
would outlive an XeFM crash and never be cleaned up.

The path is interpolated into a remote *shell* command, so it is escaped with
`shlex.quote()` — not `_quote_path()`, which produces double quotes for sftp's
own parser and would leave `$(…)` live.

A probe that raises (file not yet created, remote hiccup) is logged at debug and
skipped. It must never take down a transfer that is otherwise healthy.

### Cancellation

The progress callback doubles as the cancel checkpoint — mid-file it is the only
thread of control that returns to the caller often enough to notice. Anything it
raises is recorded in `_TransferMonitor.error`, the `sftp` process is killed, and
the exception is re-raised unchanged by `read_file()`/`write_file()`.

Re-raising it *unchanged* is the fiddly part. A killed subprocess returns a
non-zero code, and both methods wrap unexpected exceptions in `SSHError`, so the
cancel is checked **before** the return code and **outside** the error-wrapping
`try`. Otherwise a cancel surfaces as "Failed to read file: …".

The same contract is carried through `Path.copy_to()` by `_CallbackAbort` (see
`xefm/path.py`), which tags whatever the caller's callback raised so the generic
`except Exception → OSError` in the cross-storage copy helpers does not relabel a
cancel as a copy failure. `FileOperationService._remote_progress()` is what
supplies a callback that calls `task.checkpoint()`.

### Cost of the S3 side

For S3 the equivalent hook is boto3's transfer `Callback`. Raising from it aborts
the transfer and the exception reaches the caller intact — verified against a
real HTTP endpoint, since a stubbed client never reads the request body and so
never fires the callback at all. A cancelled multipart upload issues its own
`AbortMultipartUpload`, so no orphaned parts are left accruing storage charges.

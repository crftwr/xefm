# Network Mount System

XeFM mounts network shares through the operating system's own mount machinery
rather than speaking SMB itself. This document records the design decision
behind that, the platform bindings it rests on, and the behaviors that are easy
to undo by accident.

Related code:
- `xefm/netmount.py` — the platform-neutral API and the `MountInfo` record
- `xefm/netmount_macos.py` — NetFS.framework, `getmntinfo`, Bonjour browsing,
  `smbutil view`, `diskutil eject`
- `xefm/netmount_windows.py` — `mpr.dll` (WNet\*), volume eject IOCTLs
- `xefm/server_list.py` — the saved-server list and the credential store
- `xefm/connect_dialog.py` — the server picker and the connection form
- `xefm/app.py` — `show_connect_server`, `show_drives`, `_drive_remove`

Related docs:
- `../CONNECT_TO_SERVER_FEATURE.md` — user-facing feature docs
- `PATH_POLYMORPHISM_SYSTEM.md` — the `Path` facade this subsystem deliberately
  does **not** extend
- `DRIVES_DIALOG_SYSTEM.md` — the picker the disconnect/eject key lives in

---

## Why a mount and not a `PathImpl`

XeFM already has three remote backends behind `Path` (`archive://`, `s3://`,
`ssh://`), so a fourth — `smb://` on top of a Python SMB client — would have
been the obvious shape. It was rejected:

- **Everything downstream keeps working for free.** A mounted share is an
  ordinary local path, so viewers, archive reading, the file operations engine,
  external programs, drag and drop and the file monitor need no new cases. A
  `PathImpl` would have needed the download-to-temp treatment `ssh://` gets, in
  every one of those places.
- **No new dependency.** Both platform bindings are `ctypes`/`pyobjc-core`
  against libraries already on the machine. An SMB client would have meant
  `smbprotocol` and its `cryptography` / `pyspnego` chain, on every install,
  for one feature.
- **Credentials and Kerberos are the OS's problem.** The Keychain, Credential
  Manager and domain SSO all apply because it is the OS doing the mount.
- **Precedent.** `xefm/ssh_connection.py` drives OpenSSH's `ssh`/`sftp` CLIs
  rather than embedding paramiko, for the same reasons.

The cost is that Linux gets nothing (`is_supported()` is False there) and that
the mount is machine-global state rather than something XeFM owns. Both were
accepted knowingly. The second one is why XeFM does not unmount on exit and does
not reconnect at startup: a mount XeFM made is the machine's, the same as one
Finder made, and a file manager that tore down the user's shares when it closed
— or that waited on an unreachable NAS before it would open — would be worse
than one that leaves them alone.

**The `Path` facade is not involved.** `Path._create_implementation` does not
learn an `smb://` scheme, and nothing in `xefm/path.py` changes. Mounting is a
side effect with a network round trip and a password prompt attached, and
`Path("smb://…")` is constructed in places that must never do either — the
favorites picker builds one per row and is required to touch nothing
(`get_favorite_directories`, issue #430). Resolution happens one layer up, in
the dialog that asked for it, and what reaches the rest of XeFM is the local
path the mount landed on.

## The neutral layer — `xefm/netmount.py`

```python
is_supported() -> bool
parse_address(text) -> MountTarget | None
list_mounts() -> list[MountInfo]
mount(target, user, password, *, drive_letter="", cancel=None) -> str
unmount(path) -> None
eject(path) -> None
```

`mount()` returns **the path the volume actually landed on**, which is not
always derivable from the address: macOS appends a disambiguating suffix when
`/Volumes/photo` is taken, so a second mount of a different `photo` share
becomes `/Volumes/photo-1`. Callers navigate to the returned path, never to a
path they built themselves.

Platform selection is one lazy import inside this module. Nothing else in XeFM
branches on `platform.system()` for this feature, and the dialogs are written
against this API alone.

`MountInfo` carries `path`, `kind` (`"network"` / `"removable"` / `"other"`) and
`source` (the address it came from, where the OS reports one). `kind` is what
the Drives dialog switches on to decide between disconnect, eject and nothing.

### Addresses

`parse_address` accepts a URL (`smb://me@nas/photo`) or a UNC path
(`\\nas\photo`, and the `//nas/photo` spelling macOS writes), and returns
the scheme, host, share, and any embedded user name. It returns `None` for anything that is not plausibly an address, which is
how the picker's filter line decides whether **Enter** on unmatched text means
"connect to this" or "nothing matched" — so it must stay strict. A bare word is
not an address.

`MountTarget` then offers the address in **two forms, and the distinction is
load-bearing**:

- `url` keeps the case the user typed. It is what the picker shows, what a
  saved row stores, and what goes into a log line or a message.
- `key` folds the host to lower case. It is what two addresses are compared
  by: deduplicating saved servers, and naming a stored password.

`key` is built on `canonical_host`, which folds **two** things, both of them
one machine wearing several names:

- **case**, because DNS, mDNS and NetBIOS all ignore it; and
- **a trailing `.local`**, because Bonjour answers with the mDNS name
  (`SynologyNas.local`) where a hand-typed address and the mount table both say
  `synologynas`.

The share does **not** fold: SMB share names preserve case, and the mount path
is built from them.

The `.local` half was missed first time round and cost three separate things at
once: the same NAS reached two ways got two rows in the picker, a password
saved under one spelling was not found under the other, and a share mounted
through a discovered row showed as *not* mounted because the mount table
reports it without the suffix. One rule, applied in `key`, in the keychain
arguments and in both mount-table matches, is what keeps those three honest.

Folding in `url` as well, which is how this first shipped, meant someone who
typed `SynologyNAS` saw `smb://synologynas/Videos` in the list and in the log.
Nothing broke; it just put XeFM's bookkeeping on their screen. So: anything
that compares two addresses uses `key`, anything that shows one uses `url`.

## macOS — `xefm/netmount_macos.py`

### Binding NetFS without a new dependency

`NetFSMountURLSync` and friends live in NetFS.framework, for which PyObjC
publishes a binding (`pyobjc-framework-NetFS`) XeFM does not install. They are
bound instead from the framework directly with `objc.loadBundleFunctions`, which
needs only `pyobjc-core` — already present on macOS as one of PuiKit's platform
requirements:

```python
bundle = NSBundle.bundleWithPath_('/System/Library/Frameworks/NetFS.framework')
objc.loadBundleFunctions(bundle, ns, [('NetFSMountURLSync', b'i@@@@@@o^@')])
```

The signature is worth reading closely. The six inputs are declared as plain
object types (`@`) rather than as their CoreFoundation struct spellings, because
`CFURLRef`, `CFStringRef` and `CFDictionaryRef` are toll-free bridged and PyObjC
will hand an `NSURL` / `str` / `NSMutableDictionary` straight through. The
trailing **`o`** is the load-bearing character: it marks the last argument as an
*out* pointer, so PyObjC returns the mountpoint array alongside the status —
`status, mountpoints = NetFSMountURLSync(...)` — instead of demanding a pointer
be passed in. Without it the call cannot be made at all. That array is where the
real mount path comes from.

One API covers `smb:`, `afp:`, `http(s):` (WebDAV), `nfs:` and `ftp:` — Finder's
*Connect to Server* is the same call. Adding a protocol is a line in the scheme
whitelist, not new code.

If the bundle or the symbols cannot be loaded, `is_supported()` returns False
and the feature disappears from the UI rather than failing at the point of use.

### Options passed to the mount

- `kNAUIOptionKey = kNAUIOptionNoUI` — **XeFM collects the credentials itself.**
  With `AllowUI` the system would draw its own authentication sheet, which
  cannot work in the TUI backend (no window server session, and nothing the
  keyboard can reach). One code path for both backends is worth more than the
  system sheet's polish.
- `kNetFSAllowSubMountsKey = True` — permits mounting a directory below the
  share point, so `smb://nas/photo/2026` works.
- `kNetFSSoftMountKey` is left at its default (true), so I/O on a server that
  disappears fails instead of hanging the process in the kernel.

### Cancellation

`NetFSMountURLSync` blocks for as long as the network takes to give up, which
for a switched-off NAS is tens of seconds.

The obvious answer — `NetFSMountURLAsync` plus `NetFSMountURLCancel`, which is a
real cancel — was tried and dropped. The async call takes a completion **block**
(`NetFSMountURLBlock`) and a `dispatch_queue_t`, and a block argument needs
PyObjC metadata that `objc.loadBundleFunctions`' signature string cannot
express. Getting it would mean depending on `pyobjc-framework-NetFS` after all,
which is the dependency this whole approach exists to avoid.

So **both platforms cancel the same way**, and the semantics are stated plainly
rather than pretended away: Esc releases the UI immediately, and if the mount
lands afterwards it is **undone** — `xefm.netmount.mount` unmounts what the
backend just mounted and raises instead. Nobody is left holding a share they
cancelled, and no thread is killed. What Esc does not do is shorten the
network's own timeout; the worker thread runs to its end in the background.

### Listing mounts — one syscall, not one subprocess per row

The Drives dialog needs to know, for every row, whether it is a network mount, a
removable volume or neither. Shelling out to `diskutil info` per row would put a
subprocess per volume on the dialog's opening path.

`getmntinfo` (libSystem, via `ctypes`) returns the whole mount table in one
call, and each `statfs` record carries both fields needed:

The symbol is asked for by three names in order — `getmntinfo$INODE64`,
`getmntinfo64`, `getmntinfo`. On Apple silicon there is one `getmntinfo` and it
is the 64-bit-inode one, but on x86_64 the plain name is the *legacy* entry
point with a different struct layout, and binding that one would decode every
field at the wrong offset.

- `f_fstypename` — `smbfs`, `webdav`, `afpfs`, `nfs` mark a network mount
- `f_flags` — `MNT_LOCAL` (`0x1000`) absent is the general test for "not a local
  filesystem"; `MNT_REMOVABLE` (`0x200`) is set for removable media

`kind` is decided as:

1. `f_fstypename` in an explicit network list (`smbfs`, `webdav`, `afpfs`,
   `nfs`, …) → `"network"`. **Not** "anything without `MNT_LOCAL`": `autofs` and
   `devfs` are not local either, and `umount /dev` is not something to put on a
   keystroke.
2. `MNT_LOCAL`, directly under `/Volumes`, and not `MNT_DONTBROWSE` →
   `"removable"`. The `/Volumes` test rather than `MNT_REMOVABLE` is deliberate:
   an external USB SSD with an APFS container does not always have the removable
   flag set, but Finder still offers to eject it, and so should XeFM. The
   `MNT_DONTBROWSE` exclusion is what keeps the Recovery volume off the list.
3. Everything else → `"other"`, which the Drives picker treats as "nothing to
   do here".

### Unmount and eject

`unmount()` runs `/sbin/umount`; `eject()` runs `/usr/sbin/diskutil eject`,
which also spins down and powers off the device, which is what makes it safe to
unplug. Both are subprocesses on purpose: the failure text they print is the
text worth showing the user (`Resource busy` naming the offending process),
and neither is on a hot path.

## Windows — `xefm/netmount_windows.py`

### Connecting

`WNetAddConnection2W` (`mpr.dll`) with a `NETRESOURCEW` describing the remote
name. `lpLocalName` is `NULL` by default — a **deviceless** connection, so the
UNC path works everywhere without consuming a drive letter. A letter is only
used when the form asks for one, in which case `CONNECT_UPDATE_PROFILE` is *not*
passed: XeFM does not restore connections at startup, so persisting them in the
user's profile would make Windows do it behind XeFM's back.

`CONNECT_INTERACTIVE` and `CONNECT_PROMPT` are likewise not passed. As on macOS,
XeFM collects the credentials, for the same TUI reason.

The error codes are mapped to sentences rather than shown raw:
`ERROR_LOGON_FAILURE` / `ERROR_ACCESS_DENIED` reopen the form,
`ERROR_BAD_NETPATH` / `ERROR_BAD_NET_NAME` name the address,
`ERROR_ALREADY_ASSIGNED` and `ERROR_DEVICE_ALREADY_REMEMBERED` are treated as
success for a *deviceless* connection — there is nothing to collide over but the
share itself, and being connected to it is the state the caller wanted. With a
drive letter asked for they stay errors, because the letter is the thing that
was refused.

WebDAV goes through the same call and depends on the **WebClient** service
running; when it is stopped the error is `ERROR_BAD_NET_NAME`, which is
indistinguishable from a bad address, so the message mentions both.

### Cancellation

`WNetAddConnection2W` has no cancel. **Esc** therefore releases the UI and
marks the request abandoned; if the call later succeeds, the worker immediately
disconnects what it just connected and logs it. The user never ends up with a
mount they cancelled, and no thread is killed.

### Listing connections

Deviceless connections do not appear in `os.listdrives()`, so the Drives dialog
would have no row to disconnect. `WNetOpenEnum(RESOURCE_CONNECTED, …)` /
`WNetEnumResource` list them, and each becomes a row whose path is the UNC.
Lettered connections are recognised by asking `WNetGetConnection` for each
letter the drive scan found.

### Eject

The Explorer sequence, on a handle to `\\.\X:`:

1. `FSCTL_LOCK_VOLUME` — fails if anything has the volume open, which is the
   check that makes the rest safe
2. `FSCTL_DISMOUNT_VOLUME`
3. `IOCTL_STORAGE_EJECT_MEDIA` — best effort

Step 3 is not supported by every USB flash device, and a failure there is *not*
reported as a failure: after step 2 the volume is flushed and dismounted, which
is what "safe to remove" means. Only a failure in step 1 or 2 is an error.

`GetDriveTypeW` classifies most rows — `DRIVE_REMOTE` is a share,
`DRIVE_REMOVABLE` and `DRIVE_CDROM` are ejectable — and it answers from the
mount table without touching the device, so an empty card reader cannot stall
the dialog.

`DRIVE_FIXED` needs one more question, because an external USB disk reports
itself fixed and Explorer still ejects it. `IOCTL_STORAGE_GET_HOTPLUG_INFO`
answers it from the storage stack's cached device information, over a handle
opened with **no access rights** — a property query, not I/O, so it neither
reads nor spins up the device and stays safe on the UI thread.

## Finding servers, and asking one what it offers

Two separate capabilities, and they degrade differently, which is why they are
separate calls: `discover_servers` (what is out there) and `list_shares` (what
one of them offers).

### macOS discovery is Bonjour, through Foundation

`NSNetServiceBrowser` browsing `_smb._tcp.` and `_afpovertcp._tcp.` — the two
service types Finder's Network view is built on, so XeFM finds what Finder
finds.

**Not `dns-sd`.** The command-line tool was the obvious choice and does not
work: it full-buffers stdout when it is talking to a pipe rather than a
terminal, so a browse delivers its first line and then nothing until 4 KB have
accumulated, which for a handful of servers is never. That is a property of the
tool, not of the network, and no amount of reading harder fixes it.

The browser runs on **the picker's loader thread**, run loop and all:
`discover_servers` is a generator that turns `NSRunLoop` in 200 ms slices,
checks the cancel flag between them, and yields whatever the delegate has
collected. Browsing has no natural end — a NAS that wakes up ten seconds later
is a new row — so it runs until the dialog closes, with a 300-second cap so a
window left open overnight does not keep a run loop turning until morning.

**Each service is resolved before it is reported.** The advertised name is not
a host name: a Mac announces "Anna's MacBook Pro" and answers to
`Annas-MacBook-Pro.local`. Resolving on the same run loop, as each service
arrives, is what keeps every `NSNetService` on one thread — resolving later,
from whichever worker the user's choice lands on, would mean two threads
sharing an object Apple does not document as thread-safe. It also means every
row in the list is a row that can actually be opened: a service that will not
resolve is dropped rather than shown.

The found services are held in a list on the delegate. The browser does not
retain them, and a resolution in flight against a collected object is a crash
rather than a failure.

### Windows discovery is the weak half, knowingly

`WNetEnumResource` over `RESOURCE_GLOBALNET`, walked three levels — provider,
domain/workgroup, server. What comes back on a modern Windows is whatever
WS-Discovery has collected, which is frequently nothing at all for machines
that are perfectly reachable by name; Microsoft retired the browser service
that used to answer this. So an empty result is not an error, the picker simply
shows no discovered rows, and typing the address still works. The walk checks
the cancel flag between containers, because a domain that is not answering
takes seconds and the picker has to stay closable.

### Listing shares

macOS runs `smbutil view`, twice at most, because two things work and a third
does not:

- **`-g`, as a guest.** Right for an open share; a Synology refuses it
  outright with `Authentication error`, which is the common case.
- **`//user@host`**, which makes `smbutil` look the account up in the **login
  Keychain** and connect with what it finds. This is what works against a real
  NAS, and it needs no password from XeFM at all.

What does not work is handing `smbutil` a password. It takes one only on its
command line, where the process list carries it to every user on the machine
(verified: a normal user can read root's `argv` here), and it does **not** read
one from stdin — measured, not assumed. A deliberately wrong password piped to
a known account was ignored and the Keychain entry used instead; an unknown
account failed in 0.3 s without ever reading the pipe.

So **the account is the thing XeFM has to supply**, not the password, and
`list_shares` takes a user and no password at all. A server found on the
network arrives without one, so it is looked for in three places, in order:
what the user typed, `server_list.user_for_host` (the account last used for
that machine), and finally `find_account`, which asks the Keychain.

That last one is what makes a freshly-discovered server work on a machine
with no saved servers at all, and it has a spelling trap in it. Finder files
a Bonjour-discovered server under its **service** name —
`SynologyNas._smb._tcp.local`, not `SynologyNas.local` and not `synologynas` —
so a lookup by host name finds nothing on exactly the machines the user has
already connected to. `_keychain_servers` tries the service form first, then
the host as written, then the canonical host. The lookup reads attributes
only (no `-w`), so nothing is decrypted and no access prompt can appear for a
server the user has merely highlighted.

Ticking *Save password* also makes a locked-down server browsable next time,
for the same underlying reason: the password lands in the Keychain, which is
where the tool looks.

The first version of this asked as a guest and nothing else, and looked
correct because it was tested while a share from that very NAS was still
mounted — an authenticated session `smbutil` quietly reused. Unmounted, the
same call failed. Two checks in this subsystem have now been wrong for that
kind of reason (the other being `security` and the controlling terminal), so:
**test these against the state the user will be in, not the state the last
experiment left behind.**

Its output is a fixed-width table, and the header says where the columns start,
so the share name is **sliced at that offset rather than split**: a share name
may contain spaces, and the Comments column beside it certainly does.
Administrative shares (`IPC$`, `C$`) are dropped, as they are in Finder.

Windows has it easier: the same `WNetEnumResource`, one level below a server,
using the credentials the session already has. No separate authentication, and
no anonymous-query problem — which makes it the reliable half on the platform
whose discovery is the unreliable one.

### What the flow does with them

`smb://nas` — an address with a server and no share — **parses**, and
`parse_address` no longer rejects it. It is not mountable (`mount` refuses it,
naming the missing share), but it is meaningful: it is a server to browse. That
one change is what lets the form double as the way in for a server typed by
hand, since `connect()` sends any share-less address to `browse_shares` and
everything converges on the same path.

## Saved servers and credentials — `xefm/server_list.py`

The list the picker shows is the **merge** of two sources, in this order:

1. `NETWORK_SERVERS` from `~/.xefm/config.py` — hand-written, not removable
   from the UI (`origin="config"`)
2. Entries saved from the connection form — kept in the state DB under
   `network_servers` (`origin="state"`)

Deduplication is by normalised URL, config winning, which is what lets a user
promote a server they first saved from the dialog into their config without
ending up with two rows.

Passwords are never in either store. They go to the OS:

| | Store | Mechanism |
|-|-------|-----------|
| macOS | login Keychain | `/usr/bin/security add-internet-password` / `find-internet-password`, keyed by protocol + host + account |
| Windows | Credential Manager | `CredWriteW` / `CredReadW`, `CRED_TYPE_GENERIC`, target name `XeFM:<url>#<user>` |

`security` is invoked with the password on **stdin** — `-w` with no value
prompts for it, and then asks a second time to confirm, so it is written twice.
Passing it as an argument instead would put it in the process list for every
user on the machine to read, which is what makes the odd double-write worth it.

**Every system tool here runs with `start_new_session=True`**, and that is not
hygiene, it is the fix for a real failure. `security -w` does not read the
stdin it is handed if it can open `/dev/tty` instead — and in the TUI
`/dev/tty` is the terminal XeFM is drawing on. Saving a password printed
`password data for new item:` over the file pane, waited for keystrokes that
were going to XeFM, and timed out twenty seconds later. With no controlling
terminal, `readpassphrase(3)` cannot open `/dev/tty` and falls back to stdin,
which is where the password already was. The same reasoning covers `smbutil`,
`umount` and `diskutil`, so they are all detached through the same wrapper —
the invariant is "nothing in this module may reach for a terminal", and
`test_netmount` asserts it for every call rather than for the one that was
caught.
Reading it back has its own wrinkle: `security -w` prints a password that is not
plain ASCII as hex, and `123456` is also valid hex, so the hex is only undone
when it decodes to printable text containing a non-ASCII character.

Windows uses a **generic** credential rather than a domain password because
Windows will not return a domain password's blob to the program that wrote it —
it could be saved but never read, and reading it back to prefill the form is the
whole point.

Forgetting a server deletes its credential too; a failure to delete is logged
and does not block the removal of the row.

## Drives dialog integration

`show_filter_list`'s `on_remove` hook already has exactly the right contract:
the caller decides *whether* a row is removable and does the work, and the row
disappears only if the callback returns True (`filter_list_dialog.py`). So
disconnect/eject needed no new key plumbing:

- `on_remove` is now passed by the Drives picker (`XeFMApp._drive_remove`). It
  looks the highlighted row up in `list_mounts()` and dispatches on `kind`:
  `network` → unmount, `removable` → eject, anything else → nothing.
- The hint line's verb is a parameter (`remove_label`), since "remove" is wrong
  for this picker. Drives says *disconnect*.
- `_drive_remove` **always returns False**, for two different reasons, and the
  distinction is worth keeping straight. A row with nothing to disconnect
  declines and therefore stays, which is the hook's normal contract. A row that
  *does* have something to disconnect returns False as well, and the picker is
  closed instead: the work runs on a worker thread, and a row that disappeared
  before the unmount answered would be claiming an outcome nobody knew yet. The
  log line reports what happened.

Before unmounting, `_release_volume()` moves any pane sitting inside the volume
to a path outside it and stops the file monitor for that directory. XeFM's own
watcher holding the directory open is the most likely reason for a spurious
`Resource busy`, and it is the one reason XeFM can do something about.

The Connect to Server picker passes `on_remove` too, with the opposite meaning —
forget the saved server — which is why the two actions are in two dialogs
instead of competing for keys in one.

## Threading

Every network call in this subsystem runs on a worker thread through
`connect_dialog.run_connecting`, which is a smaller sibling of `xefm.task`: a
busy modal, a daemon worker, and an animation tick that delivers the result on
the UI thread, with the same inline fallback on a backend that drives no ticks.
`ProgressDialog` was not reused because there is nothing to count here, and its
words ("Preparing…") and its cancel-confirm step both describe a file operation.
The rules that matter:

- `mount()` may block for tens of seconds. It is never called from the UI
  thread, and the progress dialog it runs under is cancellable.
- `list_mounts()` is cheap and local (one syscall on macOS, the mount table on
  Windows) and *is* called on the UI thread, when the Drives dialog opens and
  when a row is acted on. It must stay that way: no `diskutil`, no `net use`,
  no per-row subprocess may creep into it.
- `unmount()` / `eject()` run a subprocess or an IOCTL and can block — on a
  server that has gone away, for a long time, which is exactly when someone
  reaches for them. They go behind the same busy modal.

## Testing

What is unit-tested (`test/test_netmount.py`, `test/test_server_list.py`,
`test/test_connect_dialog.py`):

- `parse_address` — URL and UNC forms, embedded user names, and the rejections
  that keep the filter line from treating a search word as an address
- `_kind` against a table of filesystem types and `MNT_*` flags, and
  `sizeof(_statfs)` against the number the SDK declares — get that wrong and
  mount paths come back as garbage rather than as an error
- The config/state merge, deduplication, origin rules, and what "forget" takes
  with it
- The flow: a mounted row costs no round trip, a rejected password reopens the
  form with what was typed, a stored password is read on the worker and not
  before it, and a cancelled connection is silent

What cannot be: the mounts themselves. `make test` never touches the network.
Connecting, disconnecting and ejecting are hand-checked against a real server
and a real USB device, on both platforms; the checklist is in the issue.

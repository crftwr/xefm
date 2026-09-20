# Connect to Server

XeFM connects to a NAS or file server by itself. On macOS you no longer need to
open Finder, walk into **Network** and open a share to get it into `/Volumes`;
on Windows you no longer need Explorer's *Map network drive*. Press **Shift-D**,
pick the server, and the pane lands in it.

The connection is a real mount made by the operating system, not a private
XeFM channel. Once it is up, the share is an ordinary directory —
`/Volumes/photo` on macOS, `\\nas\photo` on Windows — so everything else in XeFM
works on it unchanged: viewers, archives, copy and move, external programs,
drag and drop, and automatic reloading.

**Available on macOS and Windows.** On Linux the dialog is not offered; mount
your shares with the tools your distribution provides and reach them through the
Drives dialog like any other directory.

## Opening the dialog

| How | |
|-----|--|
| **Shift-D** | Opens Connect to Server directly |
| **D** | The Drives dialog, whose first row is **Connect to Server…** |
| Menu | **Go → Connect to Server…** |

## The server list

The dialog is the same searchable picker as Favorites and Drives — type to
filter, **Up/Down** to move, **Enter** to choose, **Esc** to close.

```
┌ Connect to Server ────────────────────────────────────────────┐
│ NAS Photo  —  smb://nas/photo  →  /Volumes/photo              │
│ NAS Backup  —  smb://nas/backup                               │
│ Documents  —  https://dav.example.com/files                   │
│ New connection…                                               │
│ SynologyNas  —  on the network                                │
│ Anna's iMac  —  on the network                                │
└───────────────────────────────────────────────────────────────┘
```

Each row says what it is, and **Enter** does the obvious thing with it:

| Row ends with | |
|-|-|
| `→ /Volumes/photo` | Mounted right now. **Enter** just moves the pane there — no network, no password, no waiting. |
| an address | Saved, not mounted. **Enter** connects, then moves the pane. |
| `— on the network` | Found just now (see below). **Enter** asks it which shares it offers. |

**Shift-Delete** forgets the highlighted server. It does not disconnect
anything — it removes the entry from the list, along with any password saved for
it. Servers written into your config file cannot be forgotten this way; edit the
config instead.

## Servers found on the network

XeFM looks for file servers while the dialog is open, the same way Finder's
**Network** view does, and they appear at the bottom of the list as they are
found — named as the server announces itself, and marked *on the network*
because there is no saved address for them yet. Nothing is contacted until you
choose one.

Choosing one asks it what it offers and shows a second list:

```
┌ Shares on SynologyNas ─────────────────────────┐
│ home                                           │
│ Videos                                         │
│ Documents                                      │
│ PlexMediaServer                                │
└────────────────────────────────────────────────┘
```

Pick a share and it mounts. That is the whole path from "the NAS is on" to "the
pane is in it", without typing anything.

This works best on **macOS**, where discovery is Bonjour — the same mechanism
Finder uses, so XeFM finds what Finder finds. On **Windows** it asks the
network providers, and modern Windows often answers with nothing even when the
machines are reachable by name; there the address is still typed or saved.

A server you have already saved as a *server* is not listed twice. A saved
*share* does not hide its server, because the two rows do different things: one
goes straight to that share, the other browses the machine.

### Which account the share list is asked under

A NAS will not tell a guest what it offers, so the question has to be asked
under an account. XeFM finds one without asking you:

1. As a **guest** first, which is enough for an open share.
2. Otherwise under the **account you last used for that machine** — from your
   saved servers, or failing that from the keychain itself, which remembers
   the account for every server you have ever connected to, including the ones
   you opened in Finder. The password never leaves the keychain; XeFM only
   needs to know which account to ask under.

If neither works, the connection form opens with the server filled in and the
share left for you to add — `smb://nas/` becomes `smb://nas/Videos`. Filling in
the account there and ticking **Save password** also fixes it for next time:
the password goes into the keychain, which is where the share list looks.

### Connecting to an address you have not saved

Type the address into the filter line and press **Enter**. If it looks like a
server address rather than a filter, the connection form opens with it already
filled in, so all that is left is the password. If it looks like neither — a
word that matched no row — nothing happens, because it was a search.

## New connection

**＋ New connection…** opens a small form:

| Field | |
|-------|--|
| **Address** | `smb://nas/photo`, `\\nas\photo`, `https://dav.example.com/files`, … |
| **User name** | Leave empty to connect as a guest |
| **Password** | Typed characters show as bullets |
| **Save password** | Off by default. See [Passwords](#passwords) |
| **Save this server** | On by default — adds it to the list for next time |
| **Drive letter** (Windows) | Empty by default. See [Drive letters](#drive-letters-windows) |

**Tab** moves between fields, **Space** ticks the checkbox you are standing on,
**Enter** connects from anywhere in the form, and **Esc** cancels.

Leaving both **User name** and **Password** empty connects as a guest, which is
how a share that needs no account is reached.

While XeFM is connecting, a progress dialog
names the server and **Esc** gives up on it — worth knowing, because a server
that is switched off does not refuse the connection, it simply never answers,
and without a way out you would be waiting for the network's own timeout.

### Addresses you can use

| | macOS | Windows |
|-|-------|---------|
| SMB / Windows file sharing | `smb://server/share` | `\\server\share` or `smb://server/share` |
| WebDAV | `https://server/path`, `http://server/path` | `https://server/path` |
| Apple File Protocol | `afp://server/share` | — |
| NFS | `nfs://server/export` | — |

A user name can be written into the address (`smb://me@nas/photo`) instead of
into the **User name** field; XeFM splits it out and fills the field for you.

A short server name that your network does not resolve is also tried as
`name.local`, which is how Macs and many NAS boxes announce themselves. So
`smb://nas/photo` finds the machine whether it answers to plain `nas` or only
to `nas.local`, and the volume is named after whichever one worked.

Leaving the share off the end (`smb://nas`) is not an error: an address that
names a server and no share is a request to **browse** it, and you get the share
list described above.

## Saved servers

Two kinds of entry appear in the list, and they are merged into one:

**Servers you save from the dialog** are remembered by XeFM and can be removed
with **Shift-Delete**.

**Servers written into `~/.xefm/config.py`** come from `NETWORK_SERVERS`:

```python
NETWORK_SERVERS = [
    {'name': 'NAS Photo',  'url': 'smb://nas/photo', 'user': 'crftwr'},
    {'name': 'NAS Backup', 'url': 'smb://nas/backup'},
    {'name': 'Docs',       'url': 'https://dav.example.com/files'},
]
```

`name` is what the list shows, `url` is the address, and `user` is optional. A
config entry cannot be removed with **Shift-Delete** — the config is the source
of truth for it, the same way it is for Favorites.

**Never put a password in the config file.** There is no field for one, and
XeFM will not read one from there.

## Passwords

**Save password** is off by default, so by default XeFM asks every time you
connect. Tick it and the password goes into the operating system's own store —
the login **Keychain** on macOS, **Credential Manager** on Windows — never into
the config file or XeFM's own state. On the next connection the field comes up
already filled.

To remove a saved password, either forget the server with **Shift-Delete** (the
password goes with it) or delete the entry in Keychain Access / Credential
Manager directly.

Saving happens after the connection succeeds, so a failure to save is reported
in the log and costs you the saved password, not the connection.

If the server rejects the credentials, XeFM says so and reopens the form with
the address and account you typed — the password field comes back empty, ready
for another attempt. Any other failure (no such server, no such share) is
reported on its own, because retyping a password would not help.

## No reconnecting at startup

XeFM does not restore connections when it launches. Windows offers this for
mapped drives and it is deliberately not copied here: an unreachable server
turns startup into a network wait, and a file manager that will not open because
a NAS is off is worse than one extra keypress. A saved server is one **Shift-D**
and one **Enter** away.

## Disconnecting and ejecting

Both live in the **Drives** dialog (**D**), on **Shift-Delete**:

- On a **network mount**, it disconnects.
- On an **external volume** — a USB stick, an SD card, an external disk — it
  ejects, so the device is safe to unplug.
- On anything else (Home, `C:\`, an S3 bucket, an SSH host) it does nothing, and
  the dialog's key hint says so by naming the key only where it applies.

If a pane is sitting inside the volume, XeFM moves it out to the volume's parent
first and stops watching the directory, so the unmount is not refused by XeFM's
own activity. If something *else* is using the volume — a file open in another
application, a shell sitting in it — the operating system refuses, and XeFM
reports that rather than forcing it. Close whatever is using the volume and try
again.

The Drives dialog closes as the disconnect starts, and the log line says what
happened. Disconnecting a server that has gone away can take a moment, and a row
that vanished from the list before the answer came back would be claiming
something nobody knew yet.

Disconnecting is not the same as forgetting. A disconnected server stays in the
Connect to Server list, ready to be connected again.

## Drive letters (Windows)

By default a connection is *deviceless*: it is made to `\\server\share` with no
drive letter, which is all XeFM needs, and it keeps your letters free. The
connection still shows up in the Drives dialog and still disconnects from there.

Type a letter into **Drive letter** to map one anyway — useful for programs that
cannot take a UNC path. The field only appears where there is a free letter to
use, and the mapping is not remembered across sign-ins (see
[No reconnecting at startup](#no-reconnecting-at-startup)).

## When it does not work

**"The server may not exist, or it is not responding"** — the name did not
resolve or nothing answered. Check the spelling, and check that the machine is
awake; a NAS that has spun down can take a few seconds.

**A server you can see in Finder is not in XeFM's list** — on macOS both use
Bonjour, so this usually means it had not announced itself yet; the list fills
as answers arrive, so give it a few seconds. A server that advertises nothing
(some Windows machines, and NAS boxes with Bonjour switched off) will not
appear in either, and is reached by typing its address.

**"<server> needs a user name and password"** — XeFM tried to connect as a
guest, because no account was given and none was saved, and the server does not
allow that. Most NAS boxes do not. Fill in the account and try again.

**Authentication keeps failing on a Windows server** — try the user name
qualified with the domain or the machine name (`WORKGROUP\me`, `nas\admin`).

**The share mounts but is empty** — some servers publish a share whose contents
need a second level of permission. Check the same share in Finder or Explorer
once; if it is empty there too, it is the server's doing, not XeFM's.

**macOS: "Connect to Server is not available"** — XeFM could not load the
system framework it mounts through. This should not happen on a supported macOS;
the log pane names the reason.

## See Also

- [Navigation Dialogs](NAVIGATION_DIALOGS_FEATURE.md) — the Drives dialog and
  the picker controls shared by all of these lists
- [SFTP Support](SFTP_SUPPORT_FEATURE.md) — browsing a server over SSH instead,
  which needs no mount at all
- [S3 Support](S3_SUPPORT_FEATURE.md)

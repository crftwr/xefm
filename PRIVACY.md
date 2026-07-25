# XeFM Privacy Policy

**Last updated: July 25, 2026**

XeFM is a dual-pane file manager that runs entirely on your own computer. It has no
user accounts, no advertising, and no analytics or telemetry of any kind.

**The developer of XeFM does not collect, receive, store, or transmit any of your
personal information.**

---

## What XeFM stores on your device

XeFM keeps its settings and session state in a `.xefm` folder inside your home
directory. These files never leave your computer.

| Location | Contents |
|----------|----------|
| `~/.xefm/config.py` | Your settings: key bindings, fonts, colors, favorite directories, file associations, and configured external programs. |
| `~/.xefm/state.db` | Session state so XeFM reopens the way you left it: the directories shown in each pane, recently visited directories, search and filter history, window layout, and the selected theme. It also records running XeFM instances (process ID, start time, and your computer's hostname) so that multiple open windows do not overwrite each other's state. |
| `~/.xefm/ssh_sockets/` | Temporary connection sockets, created only while you are connected to a remote host over SSH. |
| `~/.xefm/tools/` | Optional helper programs that you choose to place there yourself. |

Some of this information — directory paths, filenames, and search terms — can be
personal in nature, because it reflects the files on your own machine. It is stored
locally, in files you own, and is readable only by you. You can delete any of it at
any time by removing the corresponding file or the entire `~/.xefm` folder.

A log file is written **only** when you explicitly start XeFM with the `--log-file`
option. It is off by default.

## Your files

XeFM reads, writes, copies, moves, renames, compares, and deletes files at your
direction — that is what a file manager does. All of this happens locally through your
operating system. The contents of your files are never uploaded, indexed by a remote
service, or sent to the developer.

## Network connections

XeFM does not connect to the internet on its own. It never checks for updates, never
phones home, and never contacts any server operated by the developer.

XeFM makes a network connection **only when you explicitly ask it to browse a remote
location**, and only to the destination you specify:

- **SSH / SFTP** — When you open a remote path, XeFM runs your operating system's own
  `ssh` and `sftp` programs to connect to the host you named. Authentication uses your
  existing SSH configuration and keys (`~/.ssh`). XeFM does not store your passwords or
  private keys.
- **Amazon S3** — When you open an S3 path, XeFM uses the AWS SDK (`boto3`) to contact
  Amazon S3. Credentials come from your existing AWS configuration or environment
  variables. XeFM does not store your AWS credentials.

In both cases the connection is directly between your computer and the service you
chose, and any data transferred is governed by that service's own terms and privacy
policy. The developer of XeFM has no access to these connections or their contents.

## External programs

XeFM can launch other applications — an editor, a viewer, a terminal — according to
the file associations and programs you configure. When it does, it passes the relevant
file paths to that program. Anything that program then does with your data is covered
by its own privacy policy, not this one.

## Sharing and selling of data

The developer of XeFM receives no data from the application, and therefore has nothing
to share, sell, or disclose to anyone, including advertisers, data brokers, and law
enforcement.

## Children's privacy

XeFM is a general-purpose utility. It collects no information from anyone, including
children under 13.

## Changes to this policy

If this policy changes, the updated version will be published at this address and the
"Last updated" date above will be revised.

## Contact

Questions about this policy can be raised as an issue at
<https://github.com/shimomut/xefm/issues>, or sent to craftware@gmail.com.

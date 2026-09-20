# Virtual folders — Preview

> **Preview.** Everything on this page is subject to change until
> `xefm.user_api.API_VERSION` reaches `1` (it is `0` today). XeFM writes one
> line to the log pane saying so whenever a config defines a virtual folder.
> Nothing else in `config.py` is affected.

XeFM browses the local disk, archives, S3 and SSH. A **virtual folder** lets
your `config.py` add a fifth kind: anything you can present as directories and
files — the Windows registry, a bookmark database, a device list, a REST API —
opens in a pane like a directory, with the cursor, sorting, filtering,
incremental search and Jump to Path all working as usual.

You write one class and name it. Everything else follows.

```python
PATH_SCHEMES = {'notes': NotesPathImpl}
```

After that, `notes://` is a place: you can open it in a pane, jump to it with
Ctrl-J, put it in `FAVORITE_DIRECTORIES`, and walk into it and back out.

---

## The five methods

Inherit `ReadOnlyPathImpl` and write five methods. That is the whole
requirement — path arithmetic, parents, names, suffixes, globbing, refusing
writes, and everything the pane and status bar need come with it.

```python
import io
from xefm.path_base import ReadOnlyPathImpl, UriStatResult

NOTES = {
    '':           ['work', 'home'],
    'work':       ['standup.md', 'roadmap.md'],
    'home':       ['shopping.md'],
}
BODIES = {
    'work/standup.md':  '- shipped the thing\n',
    'work/roadmap.md':  '# Q3\n',
    'home/shopping.md': 'milk\n',
}


class NotesPathImpl(ReadOnlyPathImpl):

    def exists(self):
        return self._key in NOTES or self._key in BODIES

    def is_dir(self):
        return self._key in NOTES

    def iterdir(self):
        for name in NOTES.get(self._key, []):
            yield self._child(name)

    def stat(self):
        return UriStatResult(size=len(BODIES.get(self._key, '')),
                             mtime=0.0, is_dir=self.is_dir())

    def open(self, mode='r', buffering=-1, encoding=None,
             errors=None, newline=None):
        return io.StringIO(BODIES.get(self._key, ''))


class Config:
    PATH_SCHEMES = {'notes': NotesPathImpl}
```

| method | returns |
|---|---|
| `exists()` | whether there is anything at this path |
| `is_dir()` | whether it can be listed |
| `iterdir()` | the entries, as `self._child(name)` |
| `stat()` | size, time and kind, via `UriStatResult` |
| `open(mode=…)` | a file object for the content |

### `self._key`

The part of the URI after `notes://`, with no leading or trailing slash:

| path | `self._key` |
|---|---|
| `notes://` | `''` — the root |
| `notes://work` | `'work'` |
| `notes://work/standup.md` | `'work/standup.md'` |

`self._child(name)` builds a child of the current path. You never build a URI
by hand, and you never work out a parent, a name or a suffix — XeFM does that
from the key.

### `UriStatResult`

`UriStatResult(size=…, mtime=…, is_dir=…)` is enough for the file list, the
sort orders and the details panel. `mtime` is a Unix timestamp; pass `0.0` if
the thing has no time.

---

## Writing is refused for you

A `ReadOnlyPathImpl` refuses every write — create, rename, delete, copy into,
`touch`, `chmod` — with a clear message, and tells the rest of XeFM in advance
so operations that cannot work are not offered. Say why in your own words:

```python
class RegistryPathImpl(ReadOnlyPathImpl):
    READ_ONLY_MESSAGE = 'the registry is edited with regedit'
```

Copying *out* of a virtual folder works as soon as `open()` does: the file is
read through it like any other remote file.

---

## A worked example: browsing the Windows registry

This is the case the feature was built for — look through the registry in a
pane, and hand the actual editing to `regedit`. Values are shown as files whose
content is the value; keys are directories.

```python
# ~/.xefm/config.py
import io
import winreg

from xefm.path_base import ReadOnlyPathImpl, UriStatResult

HIVES = {
    'HKEY_CLASSES_ROOT':   winreg.HKEY_CLASSES_ROOT,
    'HKEY_CURRENT_USER':   winreg.HKEY_CURRENT_USER,
    'HKEY_LOCAL_MACHINE':  winreg.HKEY_LOCAL_MACHINE,
    'HKEY_USERS':          winreg.HKEY_USERS,
}


class RegistryPathImpl(ReadOnlyPathImpl):
    """reg://HKEY_CURRENT_USER/Software/... — keys as folders, values as files."""

    READ_ONLY_MESSAGE = 'the registry is browsed here and edited with regedit'

    def _open_key(self):
        """The open registry key for this path, or None if it is not one."""
        hive, _, subkey = self._key.partition('/')
        if hive not in HIVES:
            return None
        try:
            return winreg.OpenKey(HIVES[hive], subkey)
        except OSError:
            return None

    def _value(self):
        """This path read as a *value* under its parent key, or None."""
        parent, _, name = self._key.rpartition('/')
        hive, _, subkey = parent.partition('/')
        if hive not in HIVES:
            return None
        try:
            with winreg.OpenKey(HIVES[hive], subkey) as key:
                return winreg.QueryValueEx(key, name)[0]
        except OSError:
            return None

    # --- the five ---------------------------------------------------------

    def exists(self):
        return self.is_dir() or self._value() is not None

    def is_dir(self):
        if not self._key:
            return True                      # reg:// lists the hives
        key = self._open_key()
        if key is None:
            return False
        key.Close()
        return True

    def iterdir(self):
        if not self._key:
            for name in HIVES:
                yield self._child(name)
            return
        key = self._open_key()
        if key is None:
            return
        with key:
            n_subkeys, n_values, _ = winreg.QueryInfoKey(key)
            for i in range(n_subkeys):
                yield self._child(winreg.EnumKey(key, i))
            for i in range(n_values):
                name = winreg.EnumValue(key, i)[0]
                yield self._child(name or '(Default)')

    def stat(self):
        if self.is_dir():
            return UriStatResult(is_dir=True)
        return UriStatResult(size=len(str(self._value() or '')), is_dir=False)

    def open(self, mode='r', buffering=-1, encoding=None,
             errors=None, newline=None):
        return io.StringIO(str(self._value() or ''))


class Config:
    PATH_SCHEMES = {'reg': RegistryPathImpl}

    FAVORITE_DIRECTORIES = [
        {'name': 'Registry',  'path': 'reg://'},
        {'name': 'Run keys',  'path': 'reg://HKEY_CURRENT_USER/Software/'
                                      'Microsoft/Windows/CurrentVersion/Run'},
    ]
```

Ctrl-J and `reg://HKEY_CURRENT_USER` now open the registry in a pane. Enter
walks into a key, Backspace walks back out, `;` filters, and the viewer shows a
value's content.

To hand a key to `regedit`, bind an action — see
[Customization](CUSTOMIZATION_FEATURE.md#your-own-actions-actions):

```python
import subprocess

def edit_in_regedit(ctx):
    entry = ctx.pane.focused
    if entry is not None and str(entry.path).startswith('reg://'):
        subprocess.Popen(['regedit', '/m'])

class Config:
    ACTIONS = {'edit-in-regedit': edit_in_regedit}
    KEY_BINDINGS = {'edit-in-regedit': ['Ctrl-E']}
```

---

## Naming the scheme

The key in `PATH_SCHEMES` is the scheme, written without `://`. It must start
with a letter and hold only lowercase letters, digits, `+`, `-` and `.` —
`reg`, `notes`, `ms-appx` are all fine; `Reg`, `reg://` and `1reg` are not.

You do not have to repeat it inside the class: XeFM fills in `SCHEME` from the
key. If you do set it, it has to match the key it is registered under.

`archive`, `s3`, `ssh`, `scp` and `ftp` are taken. Replacing one is possible
but has to be asked for, so a typo cannot quietly take S3 away:

```python
PATH_SCHEMES = {'s3': {'class': MyS3PathImpl, 'override': True}}
```

---

## If it goes wrong

A bad entry costs you that entry and one line in the log pane; the rest of your
config still loads. The messages name the problem:

```
Config warning: PATH_SCHEMES['reg'] cannot be used: RegistryPathImpl does not
implement open, stat
Config warning: PATH_SCHEMES['Reg'] keys must be schemes: scheme 'Reg' must be
lowercase
Config warning: PATH_SCHEMES['s3'] would replace the built-in 's3://' backend
and was ignored — pass {'class': ..., 'override': True} if that is intended
```

An exception raised *inside* your methods is reported the way any other
listing failure is: the pane says it could not read the directory, and the log
pane has the detail. It never takes XeFM down.

Virtual folders reload with the rest of the config (**Reload Configuration**),
so iterating on one is edit-then-reload with no restart. A scheme you remove
from `PATH_SCHEMES` stops resolving on the next reload.

---

## Things to know

**Your methods run wherever XeFM lists directories** — which is a worker
thread for a pane listing, and the UI thread for smaller questions. Treat them
as you would a sort key: no UI access, and no unbounded waiting.

**It is read-only in this version.** `ReadOnlyPathImpl` is what `PATH_SCHEMES`
is designed around. A writable virtual folder means implementing the nine write
operations on `UriPathImpl` instead, which is possible but not what this
preview promises.

**One config, both platforms.** Nothing here mentions a widget or a backend, so
a virtual folder behaves identically in the terminal and in the desktop window.

**Not in this version:** custom icons or colours for your entries, a
virtual-folder-specific details panel, and background loading with a progress
bar. All are additive later.

---

## See also

- [`doc/CUSTOMIZATION_FEATURE.md`](CUSTOMIZATION_FEATURE.md) — actions, event
  hooks, sort keys and filters, the rest of the same API
- [`doc/CONFIGURATION_FEATURE.md`](CONFIGURATION_FEATURE.md) — everything else
  in `config.py`
- [`doc/dev/VIRTUAL_FOLDERS_IMPLEMENTATION.md`](dev/VIRTUAL_FOLDERS_IMPLEMENTATION.md)
- [`doc/dev/PATH_POLYMORPHISM_SYSTEM.md`](dev/PATH_POLYMORPHISM_SYSTEM.md) — the
  storage layer underneath

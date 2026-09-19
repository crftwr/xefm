"""Network mounts — the Windows backend.

Connecting is ``WNetAddConnection2W`` from ``mpr.dll``, the call behind
Explorer's *Map network drive* and behind ``net use``. It is used **deviceless**
by default — ``lpLocalName`` left null — so ``\\\\nas\\photo`` works without
consuming a drive letter, which is all XeFM needs. A letter is mapped only when
the connection form asks for one.

WebDAV goes through the same call, via the ``\\\\host@SSL\\path`` form the
WebDAV redirector understands, and needs the **WebClient** service to be
running.

Everything here is ``ctypes`` against libraries that ship with Windows, so this
file adds no dependency. Only :mod:`xefm.netmount` imports it.
"""

from __future__ import annotations

import ctypes
import string
from ctypes import wintypes

from xefm.log_manager import getLogger
from xefm.netmount import NETWORK, OTHER, REMOVABLE, MountError, MountInfo

logger = getLogger("NetMountWin")

#: What the Windows redirectors can mount. ``afp`` and ``nfs`` are not here:
#: NFS needs an optional Windows feature XeFM cannot assume, and AFP has no
#: Windows client at all. :func:`xefm.netmount.mount` reports the difference.
SCHEMES = ("smb", "http", "https")

_mpr = ctypes.WinDLL("mpr", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

RESOURCE_CONNECTED = 0x00000001
RESOURCETYPE_DISK = 0x00000001
CONNECT_UPDATE_PROFILE = 0x00000001

DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3
DRIVE_REMOTE = 4
DRIVE_CDROM = 5

ERROR_SUCCESS = 0
ERROR_MORE_DATA = 234
ERROR_NO_MORE_ITEMS = 259

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

FSCTL_LOCK_VOLUME = 0x00090018
FSCTL_UNLOCK_VOLUME = 0x0009001C
FSCTL_DISMOUNT_VOLUME = 0x00090020
IOCTL_STORAGE_EJECT_MEDIA = 0x002D4808
IOCTL_STORAGE_GET_HOTPLUG_INFO = 0x002D0C14

CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2


class NETRESOURCEW(ctypes.Structure):
    _fields_ = [
        ("dwScope", wintypes.DWORD),
        ("dwType", wintypes.DWORD),
        ("dwDisplayType", wintypes.DWORD),
        ("dwUsage", wintypes.DWORD),
        ("lpLocalName", wintypes.LPWSTR),
        ("lpRemoteName", wintypes.LPWSTR),
        ("lpComment", wintypes.LPWSTR),
        ("lpProvider", wintypes.LPWSTR),
    ]


class STORAGE_HOTPLUG_INFO(ctypes.Structure):
    _fields_ = [
        ("Size", wintypes.DWORD),
        ("MediaRemovable", ctypes.c_ubyte),
        ("MediaHotplug", ctypes.c_ubyte),
        ("DeviceHotplug", ctypes.c_ubyte),
        ("WriteCacheEnableOverride", ctypes.c_ubyte),
    ]


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD),
                ("dwHighDateTime", wintypes.DWORD)]


class CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


_mpr.WNetAddConnection2W.argtypes = [ctypes.POINTER(NETRESOURCEW), wintypes.LPCWSTR,
                                     wintypes.LPCWSTR, wintypes.DWORD]
_mpr.WNetAddConnection2W.restype = wintypes.DWORD
_mpr.WNetCancelConnection2W.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.BOOL]
_mpr.WNetCancelConnection2W.restype = wintypes.DWORD
_mpr.WNetOpenEnumW.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                               ctypes.POINTER(NETRESOURCEW),
                               ctypes.POINTER(wintypes.HANDLE)]
_mpr.WNetOpenEnumW.restype = wintypes.DWORD
_mpr.WNetEnumResourceW.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD),
                                   ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
_mpr.WNetEnumResourceW.restype = wintypes.DWORD
_mpr.WNetCloseEnum.argtypes = [wintypes.HANDLE]
_mpr.WNetCloseEnum.restype = wintypes.DWORD
_mpr.WNetGetConnectionW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR,
                                    ctypes.POINTER(wintypes.DWORD)]
_mpr.WNetGetConnectionW.restype = wintypes.DWORD

_kernel32.GetLogicalDriveStringsW.argtypes = [wintypes.DWORD, wintypes.LPWSTR]
_kernel32.GetLogicalDriveStringsW.restype = wintypes.DWORD
_kernel32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
_kernel32.GetDriveTypeW.restype = wintypes.UINT
# Explicit types matter most here: with ctypes' default restype (a 32-bit int) a
# 64-bit HANDLE comes back truncated, and every call made with it then fails in
# a way that looks like a permissions problem.
_kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.HANDLE]
_kernel32.CreateFileW.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                      ctypes.c_void_p, wintypes.DWORD,
                                      ctypes.c_void_p, wintypes.DWORD,
                                      ctypes.POINTER(wintypes.DWORD),
                                      ctypes.c_void_p]
_kernel32.DeviceIoControl.restype = wintypes.BOOL

_advapi32.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIALW), wintypes.DWORD]
_advapi32.CredWriteW.restype = wintypes.BOOL
_advapi32.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                ctypes.POINTER(ctypes.POINTER(CREDENTIALW))]
_advapi32.CredReadW.restype = wintypes.BOOL
_advapi32.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
_advapi32.CredDeleteW.restype = wintypes.BOOL
_advapi32.CredFree.argtypes = [ctypes.c_void_p]
_advapi32.CredFree.restype = None


def is_available() -> bool:
    """``mpr.dll`` loaded, so the calls exist. It ships with every Windows, so
    this is a formality — but a formality that turns a missing DLL into a hidden
    menu item instead of an exception."""
    return True


# --- addresses ---------------------------------------------------------------

def _remote_name(target) -> str:
    """The remote name ``WNetAddConnection2W`` wants.

    SMB is the plain UNC path. WebDAV uses the redirector's own spelling —
    ``\\\\host@SSL\\path`` for https, with the port as a second ``@`` component
    when one is given — because the ``https://…`` form only works through
    ``net use``'s own translation, not through this call.
    """
    if target.scheme == "smb":
        return target.unc
    host = target.host
    if target.scheme == "https":
        host += "@SSL"
    if target.port:
        host += f"@{target.port}"
    tail = "".join("\\" + part for part in target.share.split("/") if part)
    return f"\\\\{host}{tail}"


# --- mount -------------------------------------------------------------------

_AUTH_ERRORS = {
    5,     # ERROR_ACCESS_DENIED
    86,    # ERROR_INVALID_PASSWORD
    1326,  # ERROR_LOGON_FAILURE
    1327,  # ERROR_ACCOUNT_RESTRICTION
    1330,  # ERROR_PASSWORD_EXPIRED
    1331,  # ERROR_ACCOUNT_DISABLED
    1385,  # ERROR_LOGON_TYPE_NOT_GRANTED
}

_MESSAGES = {
    5: "The server rejected the user name or password.",
    53: "The server could not be found on the network.",
    55: "The share is not available.",
    64: "The connection to the server was dropped.",
    85: "That drive letter is already in use.",
    86: "The server rejected the user name or password.",
    1202: "That drive letter is already remembered for another share.",
    1203: "No network provider recognised that address.",
    1219: ("Windows already holds a connection to that server under a "
           "different account. Disconnect it first."),
    1222: "The network is not available.",
    1326: "The server rejected the user name or password.",
    1327: "That account is not allowed to connect.",
    1330: "That password has expired.",
    1331: "That account is disabled.",
    1385: "That account is not allowed to connect this way.",
}


def mount(target, user: str = "", password: str = "",
          drive_letter: str = "") -> str:
    """Connect to ``target`` and return the path to browse it at — the UNC path
    for a deviceless connection, ``X:\\`` for a lettered one."""
    remote = _remote_name(target)
    local = ""
    if drive_letter:
        local = drive_letter.rstrip(":\\/").upper() + ":"

    resource = NETRESOURCEW()
    resource.dwType = RESOURCETYPE_DISK
    resource.lpLocalName = local or None
    resource.lpRemoteName = remote
    resource.lpProvider = None

    # CONNECT_UPDATE_PROFILE is deliberately not passed: XeFM does not restore
    # connections at startup, and persisting one in the user's profile would
    # have Windows reconnect it behind XeFM's back at every sign-in.
    # CONNECT_INTERACTIVE / CONNECT_PROMPT are likewise omitted — XeFM collects
    # the credentials itself so the TUI backend behaves the same as the GUI.
    result = _mpr.WNetAddConnection2W(ctypes.byref(resource),
                                      password or None, user or None, 0)

    if result != ERROR_SUCCESS:
        # Already connected to exactly this share is not a failure; it is the
        # state the caller wanted. (Windows reports it on the lettered path;
        # a deviceless repeat usually just succeeds.)
        if result in (85, 1202) and not drive_letter:
            return remote
        if result == 67:  # ERROR_BAD_NET_NAME
            # The WebDAV redirector reports a stopped WebClient service the same
            # way it reports a misspelled share, so the message names both.
            raise MountError(
                f"{remote} was not found. If this is a WebDAV address, check "
                "that the WebClient service is running.")
        message = _MESSAGES.get(result)
        if message is None:
            message = f"Could not connect to {target.host} (error {result})."
        elif result in (53, 55, 64):
            message = f"{target.host}: {message}"
        raise MountError(message, auth=result in _AUTH_ERRORS)

    return f"{local}\\" if local else remote


def unmount(path: str) -> None:
    """Disconnect a mapped drive or a deviceless UNC connection."""
    result = _mpr.WNetCancelConnection2W(path.rstrip("\\/"), 0, False)
    if result != ERROR_SUCCESS:
        if result == 2404:  # ERROR_DEVICE_IN_USE
            raise MountError(f"{path} is still in use by another program.")
        if result == 2250:  # ERROR_NOT_CONNECTED
            return  # already gone; nothing to report
        raise MountError(f"Could not disconnect {path} (error {result}).")


# --- the mount table ---------------------------------------------------------

def list_mounts() -> list[MountInfo]:
    """Network connections (lettered and deviceless) plus the local volumes,
    classified. Runs on the UI thread, so nothing here opens a data handle to a
    disk — see :func:`_is_hotplug` for the one probe that does and why it is
    limited to fixed drives."""
    mounts: list[MountInfo] = []
    seen: set[str] = set()

    for local, remote in _connections():
        # A deviceless connection has no drive letter, so the UNC path *is* the
        # path to browse — and it is the only handle the Drives dialog has on it.
        path = f"{local}\\" if local else remote
        key = path.rstrip("\\/").lower()
        if key in seen:
            continue
        seen.add(key)
        mounts.append(MountInfo(path=path, kind=NETWORK, source=remote,
                                fstype="smb"))

    for root in _logical_drives():
        key = root.rstrip("\\/").lower()
        if key in seen:
            continue
        seen.add(key)
        kind, source = _classify_drive(root)
        mounts.append(MountInfo(path=root, kind=kind, source=source))

    return mounts


def _connections() -> list[tuple[str, str]]:
    """``(local name, remote name)`` for every current network connection.
    ``local`` is empty for a deviceless one — which is exactly why this
    enumeration is needed: those appear in no drive-letter listing."""
    handle = wintypes.HANDLE()
    result = _mpr.WNetOpenEnumW(RESOURCE_CONNECTED, RESOURCETYPE_DISK, 0,
                                None, ctypes.byref(handle))
    if result != ERROR_SUCCESS:
        return []

    found: list[tuple[str, str]] = []
    size = 16384
    buf = ctypes.create_string_buffer(size)
    try:
        while True:
            count = wintypes.DWORD(0xFFFFFFFF)
            length = wintypes.DWORD(size)
            result = _mpr.WNetEnumResourceW(handle, ctypes.byref(count),
                                            ctypes.cast(buf, ctypes.c_void_p),
                                            ctypes.byref(length))
            if result == ERROR_MORE_DATA:
                size = length.value or size * 2
                buf = ctypes.create_string_buffer(size)
                continue
            if result != ERROR_SUCCESS:
                break  # ERROR_NO_MORE_ITEMS, or an error we can only stop on
            if not count.value:
                break  # success with nothing in it: stop rather than spin
            entries = ctypes.cast(buf, ctypes.POINTER(NETRESOURCEW))
            for i in range(count.value):
                entry = entries[i]
                remote = entry.lpRemoteName or ""
                if not remote:
                    continue
                found.append(((entry.lpLocalName or "").rstrip("\\/"), remote))
    finally:
        _mpr.WNetCloseEnum(handle)
    return found


def _logical_drives() -> list[str]:
    """``['C:\\\\', 'D:\\\\', …]`` — which letters exist, asked of the OS only,
    so an unready removable drive cannot stall the listing."""
    need = _kernel32.GetLogicalDriveStringsW(0, None)
    if not need:
        return []
    buf = ctypes.create_unicode_buffer(need)
    written = _kernel32.GetLogicalDriveStringsW(need, buf)
    if not written:
        return []
    return [s for s in buf[:written].split("\0") if s]


def _classify_drive(root: str) -> tuple[str, str]:
    """``(kind, source)`` for one drive letter."""
    drive_type = _kernel32.GetDriveTypeW(root)
    if drive_type == DRIVE_REMOTE:
        return NETWORK, _connection_of(root)
    if drive_type in (DRIVE_REMOVABLE, DRIVE_CDROM):
        return REMOVABLE, ""
    if drive_type == DRIVE_FIXED and _is_hotplug(root):
        # An external USB disk reports DRIVE_FIXED, yet Explorer offers to
        # eject it and so should XeFM.
        return REMOVABLE, ""
    return OTHER, ""


def _connection_of(root: str) -> str:
    """The UNC path a mapped letter points at, or ``""``."""
    length = wintypes.DWORD(1024)
    buf = ctypes.create_unicode_buffer(length.value)
    result = _mpr.WNetGetConnectionW(root.rstrip("\\/"), buf, ctypes.byref(length))
    return buf.value if result == ERROR_SUCCESS else ""


def _is_hotplug(root: str) -> bool:
    """Whether a fixed drive is really a hot-pluggable device (a USB disk).

    ``IOCTL_STORAGE_GET_HOTPLUG_INFO`` answers from the storage stack's cached
    device information. The handle is opened with **no access rights**, which is
    what keeps this from reading, spinning up or waking the device — it is a
    property query, not I/O, so it is safe on the UI thread.
    """
    handle = _open_volume(root, access=0)
    if handle is None:
        return False
    try:
        info = STORAGE_HOTPLUG_INFO()
        info.Size = ctypes.sizeof(info)
        returned = wintypes.DWORD()
        ok = _kernel32.DeviceIoControl(
            handle, IOCTL_STORAGE_GET_HOTPLUG_INFO, None, 0,
            ctypes.byref(info), ctypes.sizeof(info),
            ctypes.byref(returned), None)
        return bool(ok) and bool(info.DeviceHotplug)
    except Exception:
        return False
    finally:
        _kernel32.CloseHandle(handle)


# --- eject -------------------------------------------------------------------

def _open_volume(root: str, access: int):
    """A handle to ``\\\\.\\X:``, or ``None``."""
    letter = root.rstrip("\\/")
    handle = _kernel32.CreateFileW(
        f"\\\\.\\{letter}", access, FILE_SHARE_READ | FILE_SHARE_WRITE,
        None, OPEN_EXISTING, 0, None)
    if handle == INVALID_HANDLE_VALUE or not handle:
        return None
    return handle


def eject(path: str) -> None:
    """Eject a removable volume, the way Explorer does it.

    Lock, dismount, then ask the device to eject. The **lock** is the step that
    makes this safe: it fails outright if anything still has the volume open,
    which is the case worth reporting. The final eject is best effort — a USB
    flash drive commonly has no ejectable media and refuses it, but by then the
    volume is flushed and dismounted, which is what "safe to remove" means.
    """
    handle = _open_volume(path, GENERIC_READ | GENERIC_WRITE)
    if handle is None:
        raise MountError(f"Could not open {path}.")
    returned = wintypes.DWORD()
    try:
        if not _kernel32.DeviceIoControl(handle, FSCTL_LOCK_VOLUME, None, 0,
                                         None, 0, ctypes.byref(returned), None):
            raise MountError(f"{path} is still in use by another program.")
        if not _kernel32.DeviceIoControl(handle, FSCTL_DISMOUNT_VOLUME, None, 0,
                                         None, 0, ctypes.byref(returned), None):
            _kernel32.DeviceIoControl(handle, FSCTL_UNLOCK_VOLUME, None, 0,
                                      None, 0, ctypes.byref(returned), None)
            raise MountError(f"Could not dismount {path}.")
        if not _kernel32.DeviceIoControl(handle, IOCTL_STORAGE_EJECT_MEDIA, None, 0,
                                         None, 0, ctypes.byref(returned), None):
            logger.info(f"{path} dismounted; the device does not support eject")
    finally:
        _kernel32.CloseHandle(handle)


# --- stored passwords --------------------------------------------------------

def _credential_target(target, user: str) -> str:
    """The Credential Manager entry name.

    Namespaced with ``XeFM:`` and stored as a **generic** credential rather than
    as a domain password. Windows will not hand a domain password's blob back to
    the program that wrote it, so a credential of that type could be saved but
    never read — and reading it back to prefill the form is the whole point.
    """
    return f"XeFM:{target.key}#{user}" if user else f"XeFM:{target.key}"


def save_password(target, user: str, password: str) -> None:
    blob = password.encode("utf-16-le")
    # Held in a named local until after the call: the structure points into
    # this buffer, and a temporary created inline in the assignment would be
    # relying on ctypes' ownership tracking to keep it alive through a call
    # into another DLL.
    buffer = ctypes.create_string_buffer(blob, len(blob))
    cred = CREDENTIALW()
    cred.Type = CRED_TYPE_GENERIC
    cred.TargetName = _credential_target(target, user)
    cred.CredentialBlobSize = len(blob)
    cred.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))
    cred.Persist = CRED_PERSIST_LOCAL_MACHINE
    cred.UserName = user or None
    if not _advapi32.CredWriteW(ctypes.byref(cred), 0):
        raise MountError(
            f"Credential Manager refused the entry (error "
            f"{ctypes.get_last_error()}).")


def load_password(target, user: str) -> str:
    pointer = ctypes.POINTER(CREDENTIALW)()
    if not _advapi32.CredReadW(_credential_target(target, user),
                               CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
        return ""
    try:
        cred = pointer.contents
        if not cred.CredentialBlobSize:
            return ""
        raw = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
        return raw.decode("utf-16-le", "replace")
    finally:
        _advapi32.CredFree(pointer)


def forget_password(target, user: str) -> None:
    # A missing entry is the ordinary case when a server never saved one.
    _advapi32.CredDeleteW(_credential_target(target, user), CRED_TYPE_GENERIC, 0)


def free_drive_letters() -> list[str]:
    """Letters not currently in use, for the form's drive-letter choice. ``A``
    and ``B`` are left out — they are floppy letters, and mapping a share onto
    one confuses more software than it helps."""
    taken = {root[0].upper() for root in _logical_drives() if root}
    return [c for c in string.ascii_uppercase[2:] if c not in taken]

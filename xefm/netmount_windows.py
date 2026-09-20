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
import queue
import string
import time
from ctypes import wintypes
from typing import NamedTuple

from xefm.log_manager import getLogger
from xefm.netmount import (NETWORK, OTHER, REMOVABLE, DiscoveredServer,
                           MountError, MountInfo, canonical_host)

logger = getLogger("NetMountWin")

#: What the Windows redirectors can mount. ``afp`` and ``nfs`` are not here:
#: NFS needs an optional Windows feature XeFM cannot assume, and AFP has no
#: Windows client at all. :func:`xefm.netmount.mount` reports the difference.
SCHEMES = ("smb", "http", "https")

_mpr = ctypes.WinDLL("mpr", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
#: The DNS client, for the DNS-SD browse behind :class:`_ServiceBrowse`. Its
#: DNS-SD entry points arrived in Windows 10 1703, so they are looked up when
#: the browse starts rather than bound here — an older Windows must still
#: import this module and mount shares.
_dnsapi = ctypes.WinDLL("dnsapi", use_last_error=True)

RESOURCE_CONNECTED = 0x00000001
RESOURCE_GLOBALNET = 0x00000002
RESOURCETYPE_DISK = 0x00000001
RESOURCEUSAGE_CONTAINER = 0x00000002
RESOURCEDISPLAYTYPE_SERVER = 0x00000002
CONNECT_UPDATE_PROFILE = 0x00000001

#: The DNS-SD service type file servers advertise themselves with, and the one
#: the macOS backend browses through Bonjour. ``_afpovertcp._tcp`` is browsed
#: there too and is not here: Windows has no AFP client to offer the row to.
_SMB_SERVICE = "_smb._tcp.local"

#: How long the first pass waits for multicast answers before the provider
#: walk begins. Long enough for a NAS on the same switch, short enough that a
#: network with nothing on it does not feel like a stall.
_MDNS_SETTLE = 1.5

#: How often the browse queue is looked at, which is also how quickly the
#: generator notices the picker has closed.
_MDNS_POLL = 0.25

DNS_QUERY_REQUEST_VERSION1 = 1
DNS_REQUEST_PENDING = 9506
DNS_TYPE_SRV = 33
DnsFreeRecordList = 1

#: How deep the network walk goes: provider -> domain/workgroup -> server.
#: Deeper levels are shares, which :func:`list_shares` asks for by name.
_DISCOVERY_DEPTH = 3

DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3
DRIVE_REMOTE = 4
DRIVE_CDROM = 5

ERROR_SUCCESS = 0
ERROR_EXTENDED_ERROR = 1208
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


class DNS_SRV_DATAW(ctypes.Structure):
    _fields_ = [
        ("pNameTarget", wintypes.LPWSTR),
        ("wPriority", wintypes.WORD),
        ("wWeight", wintypes.WORD),
        ("wPort", wintypes.WORD),
        ("Pad", wintypes.WORD),
    ]


class DNS_RECORD_DATA(ctypes.Union):
    """Only the arm this module reads is declared.

    A ``DNS_RECORD``'s payload is a union of some forty record types, and the
    union is as large as its largest arm. Declaring one arm is safe because
    nothing here *writes* it and the record is read through ``wType``: an
    answer that is not an SRV is stepped over by the list walk. What must be
    right is the offset the union starts at, which is fixed by the fields
    ahead of it, not by what is declared inside it.
    """

    _fields_ = [("Srv", DNS_SRV_DATAW)]


class DNS_RECORDW(ctypes.Structure):
    pass


DNS_RECORDW._fields_ = [
    ("pNext", ctypes.POINTER(DNS_RECORDW)),
    ("pName", wintypes.LPWSTR),
    ("wType", wintypes.WORD),
    ("wDataLength", wintypes.WORD),
    ("Flags", wintypes.DWORD),
    ("dwTtl", wintypes.DWORD),
    ("dwReserved", wintypes.DWORD),
    ("Data", DNS_RECORD_DATA),
]

#: ``VOID (DWORD Status, PVOID pQueryContext, PDNS_RECORD pDnsRecord)``, called
#: on a thread pool thread of the DNS client's choosing.
_BROWSE_CALLBACK = ctypes.WINFUNCTYPE(None, wintypes.DWORD, ctypes.c_void_p,
                                      ctypes.POINTER(DNS_RECORDW))


class DNS_SERVICE_BROWSE_REQUEST(ctypes.Structure):
    _fields_ = [
        ("Version", wintypes.DWORD),
        ("InterfaceIndex", wintypes.DWORD),
        ("QueryName", wintypes.LPCWSTR),
        ("pBrowseCallback", _BROWSE_CALLBACK),
        ("pQueryContext", ctypes.c_void_p),
    ]


class DNS_SERVICE_CANCEL(ctypes.Structure):
    _fields_ = [("reserved", ctypes.c_void_p)]


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
_mpr.WNetGetLastErrorW.argtypes = [ctypes.POINTER(wintypes.DWORD),
                                   wintypes.LPWSTR, wintypes.DWORD,
                                   wintypes.LPWSTR, wintypes.DWORD]
_mpr.WNetGetLastErrorW.restype = wintypes.DWORD
_mpr.WNetGetConnectionW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR,
                                    ctypes.POINTER(wintypes.DWORD)]
_mpr.WNetGetConnectionW.restype = wintypes.DWORD

_dnsapi.DnsFree.argtypes = [ctypes.c_void_p, ctypes.c_int]
_dnsapi.DnsFree.restype = None
if hasattr(_dnsapi, "DnsServiceBrowse"):
    _dnsapi.DnsServiceBrowse.argtypes = [
        ctypes.POINTER(DNS_SERVICE_BROWSE_REQUEST),
        ctypes.POINTER(DNS_SERVICE_CANCEL)]
    _dnsapi.DnsServiceBrowse.restype = wintypes.DWORD
    _dnsapi.DnsServiceBrowseCancel.argtypes = [ctypes.POINTER(DNS_SERVICE_CANCEL)]
    _dnsapi.DnsServiceBrowseCancel.restype = wintypes.DWORD

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


class _Resource(NamedTuple):
    """One row of a network enumeration, copied out of the buffer.

    ``WNetEnumResourceW`` writes an array of structures *plus the strings they
    point at* into a single caller-supplied buffer and reuses it on the next
    call, so everything has to be taken out before the loop turns — which is
    what this record is.

    It keeps **the whole row, not just the name**, because opening the level
    below a container needs the NETRESOURCE the enumeration handed back. See
    :func:`_container`.
    """

    local: str
    remote: str
    provider: str
    usage: int
    display: int
    type: int


def _net_error(result: int) -> str:
    """A network error code as text, unwrapping ``ERROR_EXTENDED_ERROR``.

    1208 does not say what went wrong, it says *the provider knows*; without
    asking, the only thing in the log is a number that means nothing. This is
    what turns a silently empty server list into "the list of servers for this
    workgroup is not currently available" — the answer a machine with no
    browser service gives, and the reason discovery finds nothing there.
    """
    if result != ERROR_EXTENDED_ERROR:
        return f"error {result}"
    code = wintypes.DWORD()
    description = ctypes.create_unicode_buffer(512)
    provider = ctypes.create_unicode_buffer(512)
    if _mpr.WNetGetLastErrorW(ctypes.byref(code), description, 512,
                              provider, 512) != ERROR_SUCCESS:
        return f"error {result}"
    return f"{provider.value} error {code.value}: {description.value}"


def _enum(scope: int, resource=None) -> list[_Resource]:
    """One level of a network enumeration, as :class:`_Resource` rows.

    One helper for three callers — current connections, the servers on the
    network, and one server's shares — because the fiddly part is the same
    every time (see :class:`_Resource`).
    """
    handle = wintypes.HANDLE()
    result = _mpr.WNetOpenEnumW(scope, RESOURCETYPE_DISK, 0,
                                ctypes.byref(resource) if resource else None,
                                ctypes.byref(handle))
    if result != ERROR_SUCCESS:
        # Returning [] and saying nothing is what let a walk that was refused
        # at every level look exactly like a network with nothing on it. An
        # empty list is still the right answer — this is best effort — but
        # which container refused, and why, belongs in the log.
        if resource is not None:
            where = resource.lpRemoteName or "?"
        else:
            where = ("the current connections" if scope == RESOURCE_CONNECTED
                     else "the network")
        logger.info(f"Could not enumerate {where}: {_net_error(result)}")
        return []

    found: list[_Resource] = []
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
                found.append(_Resource(
                    local=(entry.lpLocalName or "").rstrip("\\/"),
                    remote=entry.lpRemoteName or "",
                    provider=entry.lpProvider or "",
                    usage=int(entry.dwUsage),
                    display=int(entry.dwDisplayType),
                    type=int(entry.dwType)))
    finally:
        _mpr.WNetCloseEnum(handle)
    return found


def _connections() -> list[tuple[str, str]]:
    """``(local name, remote name)`` for every current network connection.
    ``local`` is empty for a deviceless one — which is exactly why this
    enumeration is needed: those appear in no drive-letter listing."""
    return [(row.local, row.remote) for row in _enum(RESOURCE_CONNECTED)
            if row.remote]


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


# --- finding servers and shares ----------------------------------------------

def discover_servers(cancel):
    """Servers on the local network, from the two sources Windows offers.

    **mDNS first, and it is the one that works.** ``_smb._tcp`` over multicast
    DNS is what a NAS, a Mac and a Samba box all advertise themselves with, and
    it is the same protocol the macOS backend browses through Bonjour — so the
    two platforms now find the same machines by the same means, rather than
    Windows having a weaker idea of what discovery is.

    The ``WNetEnumResource`` walk is kept behind it because it answers where
    mDNS does not: a domain, and a Windows box that shares files without
    advertising the service. On a workgroup machine it reliably answers *the
    list of servers for this workgroup is not currently available* — Microsoft
    retired the browser service that used to know — so it is no longer what
    this feature rests on. Anything it does find that mDNS already reported is
    dropped, host names being folded by :func:`~xefm.netmount.canonical_host`
    because the two sources spell the same machine ``SYNOLOGYNAS`` and
    ``SynologyNas.local``.

    Order is about latency, not preference: mDNS answers in well under a
    second and the walk can take twenty, so what the multicast brought back is
    yielded before the walk starts and the picker fills immediately.

    Discovery has no natural end — a NAS that wakes up ten seconds later is a
    new row — so this runs until ``cancel``, which the picker sets when it
    closes.
    """
    seen: set = set()
    browse = _ServiceBrowse(_SMB_SERVICE)
    try:
        browsing = browse.start()
        if browsing:
            yield from _found_so_far(browse, seen, cancel, _MDNS_SETTLE)
        yield from _walk_the_providers(cancel, seen)
        # Where there is no browse to wait on there is nothing left to do:
        # the walk has run once and has no second answer in it.
        while browsing and not cancel.is_set():
            yield from _found_so_far(browse, seen, cancel, _MDNS_POLL)
    finally:
        browse.stop()


def _found_so_far(browse, seen: set, cancel, timeout: float):
    """Whatever the browse has collected within ``timeout``, each server once.

    The callback runs on a thread pool thread of the DNS client's choosing, so
    what crosses into the generator is a queue and nothing else.
    """
    deadline = time.monotonic() + timeout
    while not cancel.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        try:
            name, host = browse.queue.get(timeout=min(remaining, _MDNS_POLL))
        except queue.Empty:
            continue
        key = canonical_host(host)
        if not key or key in seen:
            continue
        seen.add(key)
        logger.info(f"Found {name} at {host} over mDNS")
        yield DiscoveredServer(name=name, host=host, scheme="smb")


def _walk_the_providers(cancel, seen: set):
    """The ``WNetEnumResource`` half: provider, domain/workgroup, server.

    Walked breadth-first with the cancel flag checked between containers,
    because a domain that is not answering can take seconds and the picker
    must stay closable.
    """
    level = [None]
    for _depth in range(_DISCOVERY_DEPTH):
        if cancel.is_set():
            return
        below = []
        for container in level:
            if cancel.is_set():
                return
            for row in _enum(RESOURCE_GLOBALNET, container):
                if not row.remote:
                    continue
                if row.display == RESOURCEDISPLAYTYPE_SERVER:
                    host = row.remote.lstrip("\\\\")
                    key = canonical_host(host)
                    if key and key not in seen:
                        seen.add(key)
                        yield DiscoveredServer(name=host, host=host,
                                               scheme="smb")
                elif row.usage & RESOURCEUSAGE_CONTAINER:
                    below.append(_container(row))
        level = below
        if not level:
            return


class _ServiceBrowse:
    """A running mDNS browse for one service type, feeding :attr:`queue`.

    ``DnsServiceBrowse`` is the DNS-SD client that has shipped in the Windows
    DNS client since Windows 10 1703. It is used rather than a multicast
    socket of XeFM's own for the reason the whole subsystem exists: the
    machinery is the operating system's, so the firewall, the interface
    selection, the retry schedule and the record cache are not XeFM's problem.

    The call returns immediately with ``DNS_REQUEST_PENDING`` and the answers
    arrive on a thread pool thread, repeatedly — a browse is a subscription,
    and every re-announcement calls back again with the same records. So the
    callback puts ``(name, host)`` on a queue and the caller does the
    de-duplication; the callback itself does as little as it can and raises
    nothing, because it is returning into C.

    A batch carries the whole answer — PTR, SRV, TXT and the addresses — so
    the **SRV record alone is read** and ``DnsServiceResolve`` is never
    needed. That matters beyond saving a call: SRV is where the host lives,
    and an instance name is a label, not a host. A Mac announces "Anna's
    MacBook Pro" and answers to ``Annas-MacBook-Pro.local``, so a row built
    from the PTR name alone would be a row that cannot be opened.
    """

    def __init__(self, service: str):
        self.service = service
        self.queue: queue.Queue = queue.Queue()
        self._callback = None
        self._cancel = None

    def start(self) -> bool:
        """Begin browsing. False where the DNS client has no DNS-SD in it,
        which is every Windows before 10 1703 — the caller carries on with
        the provider walk alone."""
        browse = getattr(_dnsapi, "DnsServiceBrowse", None)
        if browse is None:
            return False
        # Held on the instance because the DNS client keeps pointers to both:
        # a callback collected while the browse is live is a crash, not a
        # missed row.
        self._callback = _BROWSE_CALLBACK(self._on_records)
        self._cancel = DNS_SERVICE_CANCEL()
        request = DNS_SERVICE_BROWSE_REQUEST()
        request.Version = DNS_QUERY_REQUEST_VERSION1
        request.InterfaceIndex = 0
        request.QueryName = self.service
        request.pBrowseCallback = self._callback
        request.pQueryContext = None
        result = browse(ctypes.byref(request), ctypes.byref(self._cancel))
        if result != DNS_REQUEST_PENDING:
            logger.info(f"Browsing {self.service} did not start: error {result}")
            self._callback = self._cancel = None
            return False
        return True

    def stop(self) -> None:
        if self._cancel is None:
            return
        cancel, self._cancel = self._cancel, None
        try:
            _dnsapi.DnsServiceBrowseCancel(ctypes.byref(cancel))
        except Exception as e:
            logger.error(f"Could not stop browsing {self.service}: {e}")
        finally:
            # Only now: the callback cannot be called again once the browse is
            # cancelled, and not before.
            self._callback = None

    def _on_records(self, status, context, records) -> None:
        try:
            if status != ERROR_SUCCESS or not records:
                return
            try:
                for name, host in self._servers(records):
                    self.queue.put((name, host))
            finally:
                _dnsapi.DnsFree(records, DnsFreeRecordList)
        except Exception as e:  # noqa: BLE001 — this returns into C
            logger.error(f"Browsing {self.service} raised: {e}")

    def _servers(self, records):
        node = records
        while node:
            record = node.contents
            if record.wType == DNS_TYPE_SRV:
                host = (record.Data.Srv.pNameTarget or "").rstrip(".")
                label = _instance_label(record.pName or "", self.service)
                if host:
                    yield label or host, host
            node = record.pNext


def _instance_label(instance: str, service: str) -> str:
    """``SynologyNas`` out of ``SynologyNas._smb._tcp.local``.

    The label is what the machine calls itself and is all the picker shows;
    the host comes from the SRV record, never from here.
    """
    suffix = "." + service
    name = instance.rstrip(".")
    if name.lower().endswith(suffix.lower()):
        name = name[:-len(suffix)]
    return name


def _container(row: _Resource) -> NETRESOURCEW:
    """The NETRESOURCE that opens the level below ``row``.

    **Copied from the row the enumeration returned, not rebuilt from its
    name.** The top level of the network is the installed providers, and a
    provider's ``lpRemoteName`` is a display name — "Microsoft Windows
    Network" — not a path. A NETRESOURCE carrying only that, which is what
    this used to build, belongs to no provider and is refused with
    ERROR_NO_NET_OR_BAD_PATH every time. The walk therefore ended one level
    in, silently, and discovery found nothing on any Windows machine at all.

    ``lpProvider`` is the field that was missing and is the reason; the type,
    usage and display type are copied for the same reason, so that what is
    handed back is the row as it was given.
    """
    resource = NETRESOURCEW()
    resource.dwScope = RESOURCE_GLOBALNET
    resource.dwType = row.type
    resource.dwDisplayType = row.display
    resource.dwUsage = row.usage
    resource.lpRemoteName = row.remote
    # A server named by hand has no provider, and NULL is how that is said —
    # an empty string is a provider whose name is "".
    resource.lpProvider = row.provider or None
    return resource


def list_shares(target, user: str = "") -> list[str]:
    """The disk shares a server offers.

    The same enumeration, one level down from a server — so it uses whatever
    credentials the session already has, and needs none of its own. That makes
    it the reliable half on Windows, where discovery is the unreliable one.

    Administrative shares (``C$``, ``ADMIN$``, ``IPC$``) are left out, as they
    are in Explorer.

    ``user`` is accepted and deliberately unused. The macOS backend needs it —
    it has to name an account for ``smbutil`` to look up in the Keychain —
    and :func:`xefm.netmount.list_shares` passes it to whichever backend is
    loaded. Windows has no use for it, but it must still be *taken*: without
    this parameter every attempt to browse a server on Windows died on a
    TypeError inside the worker thread, which the picker reported as the
    server refusing to list its shares.
    """
    if target.scheme != "smb":
        raise MountError(f"XeFM cannot list shares over {target.scheme}.")
    for host in _spellings(target.host):
        shares = _shares_of(host)
        if shares:
            return shares
    # An empty answer here is far more likely to be a refused query than a
    # server with no shares, and the caller's fallback (type the name) is the
    # right response to both.
    raise MountError(f"{target.host} did not list any shares.", auth=True)


def _spellings(host: str) -> list[str]:
    """The names to try for one machine, in order.

    The enumeration runs on **the session's own credentials**, and the
    redirector keys a session on the server name as written: with
    ``\\\\SynologyNas`` already connected and authenticated, the very same NAS
    asked for as ``\\\\SynologyNas.local`` is a server it has never heard of,
    answers anonymously, and is refused with ``ERROR_ACCESS_DENIED``.

    That is not a corner case now that discovery is mDNS, because mDNS is
    where the ``.local`` spelling comes from: every discovered row carries it,
    while the session the user already has — from Explorer, or from XeFM's own
    last mount — is almost always under the short name. So the short name is
    tried as well. :func:`~xefm.netmount.canonical_host` already declares the
    two to be one machine; this is the same rule, applied to the one place
    that talks to the redirector rather than to a key.
    """
    spellings = [host]
    if host.lower().endswith(".local"):
        short = host[:-len(".local")]
        if short:
            spellings.append(short)
    return spellings


def _shares_of(host: str) -> list[str]:
    """One enumeration of one spelling of a server, admin shares dropped."""
    server = _Resource(local="", remote=f"\\\\{host}", provider="",
                       usage=RESOURCEUSAGE_CONTAINER,
                       display=RESOURCEDISPLAYTYPE_SERVER,
                       type=RESOURCETYPE_DISK)
    shares = []
    for row in _enum(RESOURCE_GLOBALNET, _container(server)):
        remote = row.remote
        name = remote.rsplit("\\", 1)[-1] if "\\" in remote else remote
        if not name or name.endswith("$"):
            continue
        shares.append(name)
    return shares


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

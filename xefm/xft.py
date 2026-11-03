"""Tree files of references — ``.xft`` (#573, discussion #549).

An ``.xft`` file is a tree whose interior nodes are groups and whose leaves
point at places: a duplicate scan's groups, and later search results or a
catalogue. XeFM browses it the way it browses an archive, through the
read-only ``xft://<file>#<path>`` scheme; ``doc/XFT_FORMAT.md`` is the
format.

Every entry inside is a **proxy**. It is named by the label in the file,
shows the size and date the producer recorded (no ``stat`` of a remote
target), and reads its target's bytes, so view, compare and copy-out work.
It cannot be deleted or renamed — the tree is a snapshot. The real file is
reached through :meth:`XftPathImpl.target`, which the pane-sync keys use.

A producer may also **declare attributes**: values it records in each
reference's ``extra`` (a similarity), with their type and how to show them.
Reading the tree registers each as the attribute ``xft.<name>`` and, when it
says how to show it, the extra of the same name, so XeFM knows nothing of what
a producer records.

A producer may rewrite the file while it is open (similar-files does, every
few minutes during a long scan). Documents are cached by the file's size and
modification time, looked at no more than once a second, so a listing that
asks about every entry reads the file once, and a rewrite is picked up on
the next look.
"""

from __future__ import annotations

import errno
import json
import os
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Optional

from xefm import attributes, layouts
from xefm.log_manager import getLogger
from xefm.path import Path
from xefm.path_base import ReadOnlyPathImpl, UriStatResult

logger = getLogger("Xft")

FORMAT = "xft"
VERSION = 1
SUFFIX = ".xft"
SCHEME = "xft"


def is_tree_file(path) -> bool:
    """Whether ``path`` names a tree file by its extension."""
    return str(path).lower().endswith(SUFFIX)

#: How long a document is trusted before its file is looked at again.
_RECHECK_S = 1.0


@dataclass
class Node:
    name: str
    target: Optional[str] = None
    attrs: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)
    children: Optional[list] = None
    final: bool = False
    index: dict = field(default_factory=dict)

    @property
    def is_group(self) -> bool:
        return self.children is not None

    def child(self, name: str) -> Optional["Node"]:
        return self.index.get(name)

    def anchor_target(self) -> Optional[str]:
        """The target a group is known by across rewrites: its anchor's, or
        its first reference's."""
        for c in self.children or ():
            if c.extra.get("role") == "anchor" and c.target:
                return c.target
        for c in self.children or ():
            if c.target:
                return c.target
        return None


@dataclass
class Document:
    title: str
    final: bool
    complete: bool
    generation: int
    done: int
    total: int
    root: Node
    stamp: tuple = ()
    #: ``{name: spec}`` of the ``attributes`` the file declares, as written.
    attributes: dict = field(default_factory=dict)

    @property
    def provisional(self) -> bool:
        return not self.final

    def progress_text(self) -> str:
        if self.total:
            return f"{int(100 * self.done / self.total)}%"
        return ""


def _label(raw) -> str:
    """A node's name as a path segment: no slashes, never empty."""
    name = str(raw or "").replace("/", "_").replace("\\", "_").strip()
    return name or "_"


def _build(raw: dict) -> Node:
    children = raw.get("children")
    node = Node(
        name=_label(raw.get("name")),
        target=raw.get("target") if isinstance(raw.get("target"), str) else None,
        attrs=raw.get("attrs") if isinstance(raw.get("attrs"), dict) else {},
        extra=raw.get("extra") if isinstance(raw.get("extra"), dict) else {},
        final=bool(raw.get("final")),
    )
    if isinstance(children, list):
        node.children = []
        _adopt(node, [_build(c) for c in children if isinstance(c, dict)])
    return node


def _adopt(parent: Node, kids: list) -> None:
    """Give ``parent`` its children, making names unique the way the format
    asks a reader to: `` [2]``, `` [3]``…, compared as a case-insensitive
    filesystem would."""
    taken: set = set()
    for kid in kids:
        name, n = kid.name, 2
        while unicodedata.normalize("NFC", name).casefold() in taken:
            name = f"{kid.name} [{n}]"
            n += 1
        taken.add(unicodedata.normalize("NFC", name).casefold())
        kid.name = name
        parent.children.append(kid)
        parent.index[name] = kid


def parse(data: dict) -> Document:
    """A document from the JSON object of an ``.xft`` file. Raises
    ``ValueError`` for anything that is not one this version reads."""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("not an .xft file")
    if data.get("version") != VERSION:
        raise ValueError(f".xft version {data.get('version')!r}; this XeFM reads {VERSION}")
    root = Node(name="", children=[])
    nodes = data.get("nodes")
    _adopt(root, [_build(n) for n in nodes if isinstance(n, dict)] if isinstance(nodes, list) else [])
    progress = data.get("progress") if isinstance(data.get("progress"), dict) else {}
    declared = data.get("attributes") if isinstance(data.get("attributes"), dict) else {}
    final = bool(data.get("final", True))
    return Document(
        title=str(data.get("title") or ""),
        final=final,
        complete=bool(data.get("complete", final)),
        generation=int(data.get("generation") or 0),
        done=int(progress.get("done") or 0),
        total=int(progress.get("total") or 0),
        root=root,
        attributes={k: v for k, v in declared.items()
                    if isinstance(k, str) and k and isinstance(v, dict)},
    )


# --- declared attributes ------------------------------------------------------------

#: What XeFM calls a declared attribute, and the extra that shows it.
ATTR_PREFIX = "xft."
#: The column and marker keys a file may give; the rest of a LAYOUT_EXTRAS
#: entry (a 'when', a function) is XeFM's or the user's.
_COLUMN_KEYS = ("format", "width", "align", "priority", "before", "after", "replace")
_MARKER_KEYS = ("format", "on", "side", "limit")
_NUMBERS = ("count", "size", "time", "duration", "ratio")
_declare_lock = threading.Lock()
#: One reader and one condition per name, so declaring the same thing again
#: compares equal and changes nothing.
_readers: dict = {}
_whens: dict = {}


def attr_name(name: str) -> str:
    return ATTR_PREFIX + name


def _typed(kind: str, value):
    """``value`` when it is one of ``kind``, else None — a file is data."""
    if isinstance(value, bool) or value is None:
        return None
    if kind in _NUMBERS:
        return value if isinstance(value, (int, float)) else None
    if kind == "enum":
        return value if isinstance(value, (str, int)) else None
    return str(value) if isinstance(value, (str, int, float)) else None


def _reader(name: str):
    def read(path, record):
        attr = attributes.get(attr_name(name))
        node = XftPathImpl(str(path))._node() if is_xft_path(path) else None
        if node is None or attr is None:
            return None
        return _typed(attr.type, node.extra.get(name))
    return _readers.setdefault(name, read)


def _when(name: str):
    def when(path) -> bool:
        """A folder of a tree that shows ``name``."""
        if not is_xft_path(path):
            return False
        try:
            spec = load(split(path)[0]).attributes.get(name)
        except OSError:
            return False
        return bool(spec and spec.get("show"))
    return _whens.setdefault(name, when)


def _shown(name: str, show) -> tuple[Optional[dict], Optional[str]]:
    """The ``LAYOUT_EXTRAS`` spec for a declaration's ``show``, or a problem."""
    if not isinstance(show, dict):
        return None, "'show' must be an object with 'columns' and/or 'markers'"
    spec: dict = {"when": _when(name)}
    for key, allowed in (("columns", _COLUMN_KEYS), ("markers", _MARKER_KEYS)):
        items = show.get(key)
        if items is None:
            continue
        if not isinstance(items, list):
            return None, f"'show.{key}' must be a list"
        out = []
        for item in items:
            item = {} if item is True else item
            if not isinstance(item, dict):
                return None, f"each of 'show.{key}' must be an object"
            unknown = sorted(set(item) - set(allowed))
            if unknown:
                return None, f"'show.{key}' does not take {', '.join(unknown)}"
            out.append({**item, "attr": attr_name(name)})
        spec[key] = out
    return spec, None


def _declare(doc: Document, file: str) -> None:
    """Register what ``doc`` declares. A name declared again by another tree
    takes that tree's declaration; one a tree declares no longer stays
    registered, shown only in trees that show it (``_when``)."""
    for name, spec in doc.attributes.items():
        kind = spec.get("type", "text")
        problem = None
        if kind not in attributes.TYPES or kind == "tags":
            problem = f"type {kind!r} is not one a tree file can hold"
        values = spec.get("values") or {}
        if not problem and not (isinstance(values, dict)
                                and all(isinstance(v, dict) for v in values.values())):
            problem = "'values' must map each value to its label and color"
        shown = None
        if not problem and spec.get("show") is not None:
            shown, problem = _shown(name, spec["show"])
        if problem:
            logger.warning(f"{os.path.basename(file)}: attribute {name!r} ignored: {problem}")
            continue
        label = str(spec.get("label") or name)
        attr = attributes.Attribute(attr_name(name), label, kind, values=dict(values),
                                    where=(SCHEME,), sync=_reader(name), source="file")
        with _declare_lock:
            attributes.declare(attr)
            if shown is not None:
                problem = layouts.declare_extra(attr_name(name), {"label": label, **shown})
        if problem:
            logger.warning(f"{os.path.basename(file)}: how to show {name!r} ignored: {problem}")


_cache: dict = {}
_lock = threading.Lock()


def load(file: str) -> Document:
    """The document in ``file`` (a path or URI), cached by its size and
    modification time. Raises ``OSError`` when it cannot be read as one."""
    now = time.monotonic()
    with _lock:
        hit = _cache.get(file)
        if hit is not None and now - hit[0] < _RECHECK_S:
            return hit[1]
    path = Path(file)
    st = path.stat()
    stamp = (st.st_size, st.st_mtime)
    with _lock:
        hit = _cache.get(file)
        if hit is not None and hit[1].stamp == stamp:
            _cache[file] = (now, hit[1])
            return hit[1]
    try:
        doc = parse(json.loads(path.read_bytes().decode("utf-8")))
    except ValueError as e:
        raise OSError(errno.EIO, f"{path.name}: {e}", file) from None
    doc.stamp = stamp
    _declare(doc, file)
    with _lock:
        _cache[file] = (now, doc)
    return doc


def forget(file: Optional[str] = None) -> None:
    """Drop a cached document (all of them with no argument)."""
    with _lock:
        if file is None:
            _cache.clear()
        else:
            _cache.pop(file, None)


def is_xft_path(path) -> bool:
    return str(path).startswith(f"{SCHEME}://")


def uri_for(file) -> str:
    """The URI of the top of ``file``'s tree."""
    return f"{SCHEME}://{file}#"


def split(path) -> tuple[str, str]:
    """``(file, key)`` of an ``xft://`` path."""
    rest = str(path)[len(SCHEME) + 3:]
    file, _sep, key = rest.partition("#")
    return file, key


def find_group(doc: Document, anchor: str) -> Optional[str]:
    """The name of the top-level group whose anchor target is ``anchor`` —
    how a group is found again after a rewrite renamed it."""
    for node in doc.root.children or ():
        if node.is_group and node.anchor_target() == anchor:
            return node.name
    return None


class XftPathImpl(ReadOnlyPathImpl):
    """``xft://<file>#<group>/<entry>`` — a node of an ``.xft`` tree."""

    SCHEME = SCHEME
    READ_ONLY_MESSAGE = ("a .xft tree is a snapshot — reveal the real file "
                         "with the pane-sync key (Shift-O) and act on it there")
    CAPABILITIES = frozenset({"extraction_for_reading"})

    def parse_uri(self, uri: str) -> str:
        prefix = f"{SCHEME}://"
        if not uri.startswith(prefix):
            raise ValueError(f"not a {prefix} URI: {uri!r}")
        self._file, _sep, key = uri[len(prefix):].partition("#")
        return key

    def root_prefix(self) -> str:
        return f"{SCHEME}://{self._file}#"

    # -- where the tree sits ---------------------------------------------- #

    @property
    def file(self) -> Path:
        return Path(self._file)

    @property
    def parent(self) -> Path:
        """At the top, the directory holding the file — the way out, landing
        on the file, as leaving an archive does."""
        if not self._segments:
            return self.file.parent
        return self.at("/".join(self._segments[:-1]))

    @property
    def name(self) -> str:
        return self._segments[-1] if self._segments else self.file.name

    def document(self) -> Document:
        return load(self._file)

    def _node(self) -> Optional[Node]:
        try:
            node = self.document().root
        except OSError:
            return None
        for seg in self._segments:
            node = node.child(seg) if node.is_group else None
            if node is None:
                return None
        return node

    # -- what UriPathImpl asks for ---------------------------------------- #

    def exists(self) -> bool:
        return self._node() is not None

    def is_dir(self) -> bool:
        node = self._node()
        return node is not None and node.is_group

    def iterdir(self):
        node = self._node()
        if node is None:
            # Say why: the file is unreadable, or a rewrite took this group.
            self.document()
            raise FileNotFoundError(errno.ENOENT, "no such group in the tree", str(self))
        if not node.is_group:
            raise NotADirectoryError(errno.ENOTDIR, "not a group", str(self))
        for child in node.children:
            yield self.child(child.name)

    def stat(self):
        node = self._node()
        if node is None:
            raise FileNotFoundError(errno.ENOENT, "no such entry in the tree", str(self))
        attrs = node.attrs
        if node.is_group:
            try:
                written = self.file.stat().st_mtime if not self._segments else 0.0
            except OSError:
                written = 0.0
            return UriStatResult(size=0, mtime=float(attrs.get("mtime") or written), is_dir=True)
        if "size" in attrs or "mtime" in attrs:
            return UriStatResult(size=int(attrs.get("size") or 0),
                                 mtime=float(attrs.get("mtime") or 0.0),
                                 is_dir=bool(attrs.get("is_dir")))
        target = self.target()
        if target is not None:
            return target.stat()
        return UriStatResult()

    def open(self, mode="r", buffering=-1, encoding=None, errors=None, newline=None):
        if any(c in mode for c in "wax+"):
            self._refuse()
        target = self.target()
        if target is None:
            raise IsADirectoryError(errno.EISDIR, "a group has no content", str(self))
        return target.open(mode, buffering, encoding, errors, newline)

    def target(self) -> Optional[Path]:
        node = self._node()
        if node is None or not node.target:
            return None
        return Path(node.target)

    def get_extended_metadata(self) -> dict:
        node = self._node()
        details = []
        if node is not None:
            if node.target:
                details.append(("Points at", node.target))
            try:
                declared = self.document().attributes
            except OSError:
                declared = {}
            for key, value in sorted(node.extra.items()):
                attr = attributes.get(attr_name(key)) if key in declared else None
                if attr is not None:
                    value = _typed(attr.type, value)
                    if value is not None:
                        details.append((attr.label, layouts.words(attr, value)))
                elif isinstance(value, (str, int, float, bool)):
                    details.append((key.replace("_", " ").capitalize(), str(value)))
        return {"type": "xft", "details": details, "format_hint": "standard"}


def _factory(uri: str):
    return XftPathImpl(uri)

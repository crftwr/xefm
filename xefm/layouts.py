"""File list layouts and extras — which attributes a row shows, and how (#756).

The display side of :mod:`xefm.attributes`, in two parts that combine:

- A **layout** (``LAYOUTS``) is presentation: for one *kind* of list
  (``details`` today; ``tree`` and ``thumbnails`` later), which **columns** a
  row has, their formats, widths and order. It is a matter of taste and screen
  width, chosen per tab by hand (``DEFAULT_LAYOUT`` for a new one).
- An **extra** (``LAYOUT_EXTRAS``) is content: an attribute shown because of what the
  folder holds — Git status, tags — as **markers** beside a column's text
  and/or **columns** placed after or in place of a layout's. Each has a
  ``when`` deciding where it applies by default, which an extension may
  propose and the user overrides; each tab holds Auto / On / Off per extra.

The row a pane draws is :func:`compose` of its layout and its active extras.

A **format** turns a value into what is drawn: a built-in one named by a
string (``'relative'``), or a function ``fn(value, entry)`` returning a ``str``,
a :class:`Cell` or a list of cells. Formats only choose text, a color role and
bold/italic; selection, the cursor and the resting pane's dimming are applied
by the pane on top, so nothing a format returns can make a row unreadable.

"""

from __future__ import annotations

import fnmatch
import time
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Callable, Optional, Union

from xefm import attributes
from xefm.log_manager import getLogger
from xefm.str_format import format_size

logger = getLogger("Layouts")

#: The kinds of layout. Only ``details`` is drawn today.
KINDS = ("details",)
#: Where a marker sits relative to the text it decorates.
SIDES = ("after", "before")
ALIGNS = ("left", "right")
#: The name of the layout every pane falls back to.
DEFAULT = "default"
#: The keys a column / marker dict accepts; an extra's take one more each.
COLUMN_KEYS = ("attr", "format", "width", "align", "priority", "refresh", "markers")
MARKER_KEYS = ("attr", "format", "side", "limit")
EXTRA_COLUMN_KEYS = COLUMN_KEYS[:-1] + ("before", "after", "replace")
EXTRA_MARKER_KEYS = MARKER_KEYS + ("on",)
LAYOUT_KEYS = ("label", "kind", "columns", "override")
EXTRA_KEYS = ("label", "when", "markers", "columns")
#: The per-tab states of an extra; a tab with no entry for one is on auto.
EXTRA_STATES = ("auto", "on", "off")


@dataclass(frozen=True)
class Cell:
    """A piece of formatted text with its look.

    ``color`` is a role — ``'muted'``, ``'accent'``, ``'accent2'``, ``'text'``
    — a color name (``'red'``, ``'green'``, ``'yellow'``, ``'blue'``,
    ``'purple'``, ``'orange'``, ``'gray'``) or an ``(r, g, b)`` tuple. ``None``
    keeps the column's own ink."""
    text: str
    color: Union[str, tuple, None] = None
    bold: bool = False
    italic: bool = False


FormatResult = Union[str, Cell, list, None]


# --- built-in formats -------------------------------------------------------------

@dataclass(frozen=True)
class Row:
    """What a built-in format knows about the row it formats. A format of the
    user's own is handed the :class:`~xefm.user_api.EntryInfo` instead."""
    is_dir: bool = False
    ok: bool = True
    attr: Any = None


def _fmt_text(value, entry):
    return "" if value is None else str(value)


def _fmt_count(value, entry):
    return "" if value is None else f"{value:,}" if isinstance(value, int) else str(value)


def _size_placeholder(row) -> str:
    if not row.ok:
        return "---"
    return "<DIR>" if row.is_dir else ""


def _fmt_compact(value, entry):
    if value is None:
        return _size_placeholder(entry)
    return format_size(value, compact=True)


def _fmt_bytes(value, entry):
    if value is None:
        return _size_placeholder(entry)
    return f"{value:,}"


def _time_formatter(pattern: str):
    def fmt(value, entry):
        if value is None:
            return "" if entry.ok else "---"
        try:
            return datetime.fromtimestamp(value).strftime(pattern)
        except (OverflowError, OSError, ValueError):
            return "---"
    return fmt


def _fmt_relative(value, entry):
    if value is None:
        return ""
    seconds = time.time() - value
    if seconds < 60:
        return "just now"
    minutes = seconds / 60
    if minutes < 60:
        return f"{int(minutes)} min ago"
    hours = minutes / 60
    if hours < 24:
        return f"{int(hours)} h ago"
    days = hours / 24
    if days < 14:
        return f"{int(days)} days ago"
    if days < 60:
        return f"{int(days // 7)} wk ago"
    if days < 365:
        return f"{int(days // 30)} mo ago"
    return f"{int(days // 365)} yr ago"


def _fmt_recent(value, entry):
    """As short as the age allows: the time for today, the day for this year,
    the year before that — ``13:24``, ``10/21``, ``2024``."""
    if value is None:
        return "" if entry.ok else "---"
    try:
        when = datetime.fromtimestamp(value)
    except (OverflowError, OSError, ValueError):
        return "---"
    now = datetime.now()
    if when.date() == now.date():
        return when.strftime("%H:%M")
    if when.year == now.year:
        return when.strftime("%m/%d")
    return str(when.year)


def _fmt_clock(value, entry):
    """A length of time as a clock reads it: ``3:07``, ``1:02:45``."""
    if value is None:
        return ""
    try:
        total = int(round(float(value)))
    except (TypeError, ValueError, OverflowError):
        return "---"
    hours, rest = divmod(max(total, 0), 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes}:{seconds:02}"


def _enum_spec(row, value) -> dict:
    attr = row.attr
    return (attr.values.get(value) if attr is not None else None) or {}


def _fmt_letter(value, entry):
    if value is None or value == "":
        return ""
    return Cell(str(value), color=_enum_spec(entry, value).get("color"))


def _fmt_word(value, entry):
    if value is None or value == "":
        return ""
    spec = _enum_spec(entry, value)
    return Cell(str(spec.get("label", value)), color=spec.get("color"))


TAG_DOT = "●"


def _fmt_dots(value, entry):
    return [Cell(TAG_DOT, color=getattr(tag, "color_name", None)) for tag in value or []]


def _fmt_names(value, entry):
    return ", ".join(getattr(tag, "name", str(tag)) for tag in value or [])


@dataclass(frozen=True)
class Format:
    func: Callable
    width: int = 10
    align: str = "left"
    mono: bool = False
    refresh: Optional[float] = None


#: ``{type: {name: Format}}``, the first of each type its default.
FORMATS: dict[str, dict[str, Format]] = {
    "text": {"text": Format(_fmt_text, 12)},
    "count": {"number": Format(_fmt_count, 7, "right", True)},
    "size": {"compact": Format(_fmt_compact, 9, "right", True),
             "bytes": Format(_fmt_bytes, 15, "right", True)},
    "time": {"short": Format(_time_formatter("%y-%m-%d %H:%M"), 14, "right", True),
             "full": Format(_time_formatter("%Y-%m-%d %H:%M:%S"), 19, "right", True),
             "iso": Format(_time_formatter("%Y-%m-%d %H:%M"), 16, "right", True),
             "relative": Format(_fmt_relative, 10, "right", True, refresh=60.0),
             "recent": Format(_fmt_recent, 5, "right", True, refresh=60.0)},
    "duration": {"clock": Format(_fmt_clock, 8, "right", True)},
    "enum": {"letter": Format(_fmt_letter, 1), "word": Format(_fmt_word, 10)},
    "tags": {"dots": Format(_fmt_dots, 3),
             "names": Format(_fmt_names, 16)},
}


def format_names(kind: str) -> list[str]:
    return list(FORMATS.get(kind, {}))


def default_format(kind: str, config=None) -> str:
    if kind == "time" and config is not None:
        if getattr(config, "DATE_FORMAT", "short") == "full":
            return "full"
        return "short"
    return next(iter(FORMATS.get(kind, FORMATS["text"])))


def enum_width(attr, fmt: str) -> int:
    if not attr.values:
        return 1 if fmt == "letter" else 10
    if fmt == "letter":
        return max(len(str(k)) for k in attr.values)
    return max(len(str(v.get("label", k))) for k, v in attr.values.items())


#: Value types drawn right-aligned in a fixed-advance face when the format
#: does not say otherwise.
NUMERIC = ("count", "size", "time", "duration")


def words(attr, value) -> str:
    """``value`` written out for File Details (#789): an ``enum`` by its
    label, tags by their names, a size in both units, a time in full — what
    a column would say, without the glyphs a column is narrow enough to want."""
    kind = attr.type if attr is not None else "text"
    if kind == "enum":
        spec = attr.values.get(value) or {}
        return str(spec.get("label", value))
    if kind == "tags":
        return _fmt_names(value, None)
    if kind == "size":
        return f"{format_size(value)} ({value:,} bytes)" if isinstance(value, int) \
            else str(value)
    row = Row(attr=attr)
    if kind == "time":
        return _time_formatter("%Y-%m-%d %H:%M:%S")(value, row)
    if kind == "duration":
        return _fmt_clock(value, row)
    if kind == "count":
        return _fmt_count(value, row)
    return _fmt_text(value, row)


@dataclass(frozen=True)
class Resolved:
    """A column's or marker's format, resolved against its attribute: the
    function to call, whether it is one of ours, and how it is laid out."""
    func: Callable
    builtin: bool
    width: int
    align: str
    mono: bool
    refresh: Optional[float]


def resolve_format(fmt, attr, config=None, *, width=None, align=None,
                   refresh=None) -> Resolved:
    kind = attr.type if attr is not None else "text"
    numeric = kind in NUMERIC
    if callable(fmt):
        return Resolved(fmt, False, width or 10, align or ("right" if numeric else "left"),
                        numeric, refresh)
    table = FORMATS.get(kind, FORMATS["text"])
    name = fmt if isinstance(fmt, str) and fmt in table else default_format(kind, config)
    spec = table[name]
    default_width = enum_width(attr, name) if kind == "enum" and attr is not None else spec.width
    return Resolved(spec.func, True, width or default_width, align or spec.align,
                    spec.mono, refresh if refresh is not None else spec.refresh)


_failed_formats: set = set()


def render(resolved: Resolved, value, row: Row, entry_factory) -> list[Cell]:
    """Run a format and normalize what it returned to a list of cells. A
    format of the user's own that raises draws nothing, logged once."""
    try:
        if resolved.builtin:
            out = resolved.func(value, row)
        else:
            out = resolved.func(value, entry_factory())
    except Exception as exc:  # noqa: BLE001 — a format's failure costs its cell
        key = getattr(resolved.func, "__qualname__", repr(resolved.func))
        if key not in _failed_formats:
            _failed_formats.add(key)
            logger.error(f"Format {key} failed: {exc}")
        return []
    if out is None or out == "":
        return []
    if isinstance(out, (str, Cell)):
        out = [out]
    cells = []
    for item in out:
        if isinstance(item, Cell):
            if item.text:
                cells.append(item)
        elif item is not None and str(item):
            cells.append(Cell(str(item)))
    return cells


# --- the model --------------------------------------------------------------------

@dataclass(frozen=True)
class Marker:
    attr: str
    format: Union[str, Callable, None] = None
    side: str = "after"
    #: The most cells of the format's result drawn (None: all of them). A count,
    #: not a width, so it means the same in a proportional font.
    limit: Optional[int] = None
    #: The extra it came from: a row draws one extra's markers together.
    slot: Optional[str] = None


@dataclass(frozen=True)
class Column:
    attr: str
    format: Union[str, Callable, None] = None
    width: Optional[int] = None
    align: Optional[str] = None
    #: Columns with a priority are dropped, lowest first, when the pane is too
    #: narrow for the name; one without stays.
    priority: Optional[int] = None
    refresh: Optional[float] = None
    markers: tuple = ()
    #: The extra that placed it: as wide as its widest value in the listing,
    #: and left out when it has none.
    extra: Optional[str] = None


@dataclass(frozen=True)
class Layout:
    name: str
    label: str
    kind: str = "details"
    columns: tuple = ()
    source: str = "builtin"

    def attributes(self) -> set[str]:
        """Every attribute this layout draws — a column or a marker."""
        out = set()
        for col in self.columns:
            out.add(col.attr)
            out.update(m.attr for m in col.markers)
        return out


@dataclass(frozen=True)
class ExtraMarker:
    marker: Marker
    on: str = "name"


@dataclass(frozen=True)
class ExtraColumn:
    column: Column
    after: Optional[str] = None
    replace: Optional[str] = None
    before: Optional[str] = None


@dataclass(frozen=True)
class Extra:
    name: str
    label: str
    #: Where it applies on Auto: ``'always'``, ``'never'``, a path pattern, or
    #: a function of the folder's path (run on the listing worker).
    when: Union[str, Callable] = "always"
    markers: tuple = ()
    columns: tuple = ()
    source: str = "builtin"

    def attributes(self) -> set[str]:
        return ({m.marker.attr for m in self.markers}
                | {c.column.attr for c in self.columns})


BUILTIN_DEFAULT = Layout(DEFAULT, "Default", "details", (
    Column("name"),
    Column("ext"),
    Column("size"),
    Column("mtime", priority=1),
))


def _tags_when(path) -> bool:
    from xefm import tags
    store = tags.store_for(path)
    return store is not None and store.cheap


#: Built-in extras as the specs ``LAYOUT_EXTRAS`` takes, so a config entry of the
#: same name overrides them key by key, as it does an extension's.
BUILTIN_EXTRA_SPECS: dict[str, dict] = {
    "tags": {"label": "Tags", "when": _tags_when,
             "markers": [{"attr": "tags", "on": "name", "side": "after", "limit": 3}]},
}

_user: dict[str, Layout] = {}
_extras: dict[str, Extra] = {}
_default_name = DEFAULT
_composed: dict = {}


def register(layout: Layout) -> None:
    _user[layout.name] = layout
    _composed.clear()


def register_extra(extra: Extra) -> None:
    _extras[extra.name] = extra
    _composed.clear()


def set_default(name: str) -> None:
    global _default_name
    _default_name = name
    _composed.clear()


def clear() -> None:
    _user.clear()
    _extras.clear()
    _composed.clear()
    set_default(DEFAULT)
    for name, spec in BUILTIN_EXTRA_SPECS.items():
        extra, _problem = build_extra(name, spec, source="builtin")
        _extras[name] = extra


def get(name: Optional[str]) -> Optional[Layout]:
    if name is None:
        return None
    if name in _user:
        return _user[name]
    return BUILTIN_DEFAULT if name == DEFAULT else None


def all_layouts() -> list[Layout]:
    """Every layout, ``default`` first."""
    out = [get(DEFAULT)]
    out.extend(l for n, l in _user.items() if n != DEFAULT)
    return out


def get_extra(name: str) -> Optional[Extra]:
    return _extras.get(name)


def all_extras() -> list[Extra]:
    """Every extra, in definition order — the order they are placed in."""
    return list(_extras.values())


# --- building from config -----------------------------------------------------------

def _build_format(where: str, attr, fmt) -> Optional[str]:
    if fmt is None or callable(fmt):
        return None
    if not isinstance(fmt, str):
        return f"{where}: 'format' must be a format name or a function"
    if attr is not None and fmt not in FORMATS.get(attr.type, {}):
        known = ", ".join(format_names(attr.type))
        return f"{where}: '{fmt}' is not a format for a {attr.type} value — known: {known}"
    return None


def _check_keys(where: str, spec: dict, keys) -> Optional[str]:
    unknown = sorted(set(spec) - set(keys))
    if not unknown:
        return None
    hint = " ('max_width' is now 'limit', a count of cells)" if "max_width" in unknown else ""
    return f"{where}: unknown keys {', '.join(unknown)} — known: {', '.join(keys)}{hint}"


def _build_marker(where: str, spec, keys=MARKER_KEYS, slot=None) -> tuple[Optional[Marker], Optional[str]]:
    if isinstance(spec, str):
        spec = {"attr": spec}
    if not isinstance(spec, dict):
        return None, f"{where} must be an attribute name or a dict"
    problem = _check_keys(where, spec, keys)
    if problem:
        return None, problem
    name = spec.get("attr")
    if not isinstance(name, str):
        return None, f"{where} needs 'attr'"
    problem = _build_format(where, attributes.get(name), spec.get("format"))
    if problem:
        return None, problem
    side = spec.get("side", "after")
    if side not in SIDES:
        return None, f"{where}: side '{side}' is not one of {', '.join(SIDES)}"
    limit = spec.get("limit")
    if limit is not None and (not isinstance(limit, int) or limit < 1):
        return None, f"{where}: 'limit' must be a positive whole number"
    return Marker(name, spec.get("format"), side, limit, slot), None


def _build_column(where: str, spec, keys=COLUMN_KEYS, extra=None) -> tuple[Optional[Column], Optional[str]]:
    if isinstance(spec, str):
        spec = {"attr": spec}
    if not isinstance(spec, dict):
        return None, f"{where} must be an attribute name or a dict"
    problem = _check_keys(where, spec, keys)
    if problem:
        return None, problem
    name = spec.get("attr")
    if not isinstance(name, str):
        return None, f"{where} needs 'attr'"
    problem = _build_format(where, attributes.get(name), spec.get("format"))
    if problem:
        return None, problem
    width = spec.get("width")
    if width is not None and (not isinstance(width, int) or width < 1):
        return None, f"{where}: 'width' must be a positive whole number of cells"
    align = spec.get("align")
    if align is not None and align not in ALIGNS:
        return None, f"{where}: align '{align}' is not one of {', '.join(ALIGNS)}"
    priority = spec.get("priority")
    if priority is not None and not isinstance(priority, int):
        return None, f"{where}: 'priority' must be a whole number"
    refresh = spec.get("refresh")
    if refresh is not None and (not isinstance(refresh, (int, float)) or refresh <= 0):
        return None, f"{where}: 'refresh' must be a number of seconds"
    markers = []
    for i, m in enumerate(spec.get("markers") or ()):
        marker, problem = _build_marker(f"{where}['markers'][{i}]", m)
        if problem:
            return None, problem
        markers.append(marker)
    return Column(name, spec.get("format"), width, align, priority, refresh,
                  tuple(markers), extra), None


def build(name: str, spec) -> tuple[Optional[Layout], Optional[str]]:
    """Validate one ``LAYOUTS`` entry: a :class:`Layout`, or a problem."""
    where = f"LAYOUTS['{name}']"
    if not isinstance(name, str) or not name:
        return None, f"{where}: the name must be a non-empty string"
    if not isinstance(spec, dict):
        return None, f"{where} must be a dict with 'columns'"
    problem = _check_keys(where, spec, LAYOUT_KEYS)
    if problem:
        return None, problem
    if name == DEFAULT and not spec.get("override"):
        return None, (f"{where} would replace the built-in layout and was ignored — "
                      f"add 'override': True if that is intended")
    kind = spec.get("kind", "details")
    if kind not in KINDS:
        return None, f"{where}: kind '{kind}' is not one of {', '.join(KINDS)}"
    specs = spec.get("columns")
    if not isinstance(specs, (list, tuple)) or not specs:
        return None, f"{where} needs 'columns', a list"
    columns = []
    for i, c in enumerate(specs):
        column, problem = _build_column(f"{where}['columns'][{i}]", c)
        if problem:
            return None, problem
        columns.append(column)
    if not any(c.attr == "name" for c in columns):
        return None, f"{where} has no 'name' column — every layout shows the name"
    label = spec.get("label") or name
    return Layout(name, str(label), kind, tuple(columns), source="user"), None


def build_extra(name: str, spec, source: str = "user") -> tuple[Optional[Extra], Optional[str]]:
    """Validate one ``LAYOUT_EXTRAS`` entry — already merged over the built-in or the
    extension's entry of the same name — as an :class:`Extra`, or a problem."""
    where = f"LAYOUT_EXTRAS['{name}']"
    if not isinstance(name, str) or not name:
        return None, f"{where}: the name must be a non-empty string"
    if not isinstance(spec, dict):
        return None, f"{where} must be a dict with 'markers' and/or 'columns'"
    problem = _check_keys(where, spec, EXTRA_KEYS)
    if problem:
        return None, problem
    when = spec.get("when", "always")
    if not (isinstance(when, str) or callable(when)):
        return None, (f"{where}: 'when' must be 'always', 'never', a path pattern "
                      f"or a function of the folder's path")
    markers = []
    for i, m in enumerate(spec.get("markers") or ()):
        at = f"{where}['markers'][{i}]"
        marker, problem = _build_marker(at, m, EXTRA_MARKER_KEYS, slot=name)
        if problem:
            return None, problem
        on = m.get("on", "name") if isinstance(m, dict) else "name"
        if not isinstance(on, str):
            return None, f"{at}: 'on' must be the attribute of a column"
        markers.append(ExtraMarker(marker, on))
    columns = []
    for i, c in enumerate(spec.get("columns") or ()):
        at = f"{where}['columns'][{i}]"
        column, problem = _build_column(at, c, EXTRA_COLUMN_KEYS, extra=name)
        if problem:
            return None, problem
        where = {k: c.get(k) for k in ("before", "after", "replace")
                 if isinstance(c, dict) and c.get(k) is not None}
        if len(where) > 1:
            return None, f"{at}: give one of 'before', 'after' and 'replace'"
        columns.append(ExtraColumn(column, where.get("after"), where.get("replace"),
                                   where.get("before")))
    if not markers and not columns:
        return None, f"{where} shows nothing — give it 'markers' or 'columns'"
    label = spec.get("label") or name
    return Extra(name, str(label), when, tuple(markers), tuple(columns), source), None


def unknown_attributes(layout) -> list[str]:
    """Attributes a layout or an extra names that nothing registered (checked
    after every table has loaded, since an attribute may come from an
    extension)."""
    return sorted(n for n in layout.attributes() if not attributes.is_known(n))


# --- where extras apply ---------------------------------------------------------------

def applies(extra: Extra, path) -> bool:
    """Whether ``extra``'s ``when`` holds for the folder ``path``. Called on
    the listing worker, so a ``when`` may touch the filesystem; one that raises
    does not apply, logged."""
    when = extra.when
    try:
        if when == "always":
            return True
        if when == "never":
            return False
        if isinstance(when, str):
            return fnmatch.fnmatch(str(path), when)
        return bool(when(path))
    except Exception as exc:  # noqa: BLE001 — a broken condition shows nothing
        logger.error(f"LAYOUT_EXTRAS['{extra.name}'] 'when' failed: {exc}")
        return False


def extras_for(path) -> frozenset:
    """The extras whose ``when`` holds for ``path`` — what Auto shows."""
    return frozenset(e.name for e in all_extras() if applies(e, path))


def extra_state(pane: dict, name: str) -> str:
    return (pane.get("extras") or {}).get(name, "auto")


def active_extras(pane: dict) -> list[Extra]:
    """The extras ``pane`` draws, in definition order: On, or Auto and
    applying to its folder."""
    auto = pane.get("_extras_auto") or frozenset()
    out = []
    for extra in all_extras():
        state = extra_state(pane, extra.name)
        if state == "on" or (state == "auto" and extra.name in auto):
            out.append(extra)
    return out


# --- composing a row -----------------------------------------------------------------

def compose(layout: Layout, extras: list) -> Layout:
    """``layout`` with ``extras`` placed in it, in order.

    A column with ``replace`` takes the named column's place (and its priority,
    unless it gives its own); one with ``before`` or ``after`` goes beside it;
    any goes at the end when the named column is absent or already replaced.
    Columns placed beside the same one keep their definition order. A marker goes on the named column, or on the
    name when that column is absent."""
    key = (layout, tuple(e.name for e in extras))
    found = _composed.get(key)
    if found is not None:
        return found
    cols = [list((c, list(c.markers))) for c in layout.columns]

    def index_of(attr):
        return next((i for i, (c, _m) in enumerate(cols) if c.attr == attr), None)

    replaced = set()
    for extra in extras:
        for ec in extra.columns:
            col = ec.column
            target = ec.replace or ec.after or ec.before
            i = index_of(target) if target else None
            if ec.replace and i is not None and i not in replaced and cols[i][0].extra is None:
                if col.priority is None and cols[i][0].priority is not None:
                    col = replace(col, priority=cols[i][0].priority)
                cols[i] = [col, cols[i][1]]
                replaced.add(i)
            elif ec.before and i is not None:
                cols.insert(i, [col, []])
                replaced = {k + (k >= i) for k in replaced}
            elif ec.after and i is not None:
                j = i + 1
                while j < len(cols) and cols[j][0].extra is not None:
                    j += 1
                cols.insert(j, [col, []])
                replaced = {k + (k >= j) for k in replaced}
            else:
                cols.append([col, []])
        for em in extra.markers:
            i = index_of(em.on)
            if i is None:
                i = index_of("name")
            cols[i][1].append(em.marker)
    out = Layout(layout.name, layout.label, layout.kind,
                 tuple(replace(c, markers=tuple(m)) for c, m in cols), layout.source)
    _composed[key] = out
    return out


def layout_of(pane: dict) -> Layout:
    """The tab's own layout: chosen by hand, else ``DEFAULT_LAYOUT``."""
    return get(pane.get("layout")) or get(_default_name) or get(DEFAULT)


def effective(pane: dict) -> Layout:
    """What ``pane`` draws: its layout with its active extras placed in it."""
    return compose(layout_of(pane), active_extras(pane))


# --- reading the extras back -------------------------------------------------------------

#: Colors a tag dot can take — for the collision check.
_TAG_COLORS = (None, "gray", "green", "purple", "blue", "yellow", "red", "orange")


def glyphs(extra: Extra, entry_factory=lambda: None, *,
           by_color: bool = False) -> list[tuple[list, str]]:
    """``[(cells, meaning)]`` for each value ``extra``'s markers can draw —
    what the Help dialog's legend lists and the collision check compares. An
    ``enum`` attribute's values are run through the marker's own format. Tag
    dots are one row, or one per color with ``by_color`` (the check)."""
    out = []
    for em in extra.markers:
        marker = em.marker
        attr = attributes.get(marker.attr)
        if attr is None:
            continue
        resolved = resolve_format(marker.format, attr)
        if attr.type == "enum":
            for value, spec in attr.values.items():
                cells = render(resolved, value, Row(attr=attr), entry_factory)
                if marker.limit:
                    cells = cells[:marker.limit]
                if cells:
                    out.append((cells, str(spec.get("label", value))))
        elif attr.type == "tags" and resolved.builtin and marker.format in (None, "dots"):
            if not by_color:
                out.append(([Cell(TAG_DOT)], "a tag, in the tag's color"))
                continue
            for color in _TAG_COLORS:
                out.append(([Cell(TAG_DOT, color=color)],
                             f"a tag{'' if color is None else ' colored ' + color}"))
    return out


def collisions(extras: list, entry_factory=lambda: None) -> list[str]:
    """One line per glyph two extras both draw in the same color."""
    seen: dict = {}
    lines = []
    for extra in extras:
        for cells, meaning in glyphs(extra, entry_factory, by_color=True):
            if len(cells) != 1:
                continue
            key = (cells[0].text, cells[0].color)
            other = seen.get(key)
            if other is not None and other[0] != extra.name:
                color = f" in {key[1]}" if key[1] else ""
                lines.append(f"LAYOUT_EXTRAS '{other[0]}' ({other[1]}) and '{extra.name}' "
                             f"({meaning}) both draw {key[0]}{color} — tell them "
                             f"apart with another glyph or color")
            else:
                seen.setdefault(key, (extra.name, meaning))
    return lines


clear()

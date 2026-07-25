"""Rich-viewer registry — maps a file's type to an optional *rich* (formatted)
rendering widget the modal file viewer can switch to, alongside its always-
available raw plain-text view.

Registered today: Markdown (``*.md`` / ``*.markdown`` → PuiKit's ``MarkdownView``),
JSON / JSON Lines (``*.json`` / ``*.jsonl`` / ``*.ndjson`` → a collapsible
``JsonView`` tree), and CSV / TSV (``*.csv`` / ``*.tsv`` → a ``TableView`` grid).
Each type registers a :class:`RichRenderer` for its extensions and the viewer's
*toggle view mode* action picks it up with no other change. The raw text view is
the universal fallback, so an unregistered file type simply has nothing to toggle
to (:func:`rich_renderer_for` returns ``None``).

A renderer's ``build`` turns the file's raw source text into a scrollable PuiKit
:class:`~puikit.widgets.base.Widget`, styled onto the viewer's content surface so
the rendered document follows the active theme like the rest of XeFM. A ``build``
may raise on malformed input (an unparseable ``.json`` / ``.csv``); the viewer
catches that and stays in raw text mode, so the toggle never crashes.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from typing import Any, Callable

from puikit.backend import Style
from puikit.widgets.base import Widget

from xefm.log_manager import getLogger

logger = getLogger("ViewerReg")


@dataclass(frozen=True)
class RichRenderer:
    """A named formatted renderer for one family of file types.

    ``name`` is the short label shown in the viewer chrome (e.g. ``"Markdown"``);
    ``build(source, *, style)`` turns the file's raw source text into a scrollable
    PuiKit widget drawn on ``style`` (the viewer's content surface)."""

    name: str
    build: Callable[..., Widget]


#: Extension (lower-cased, with leading dot) → the rich renderer for that type.
_REGISTRY: dict[str, RichRenderer] = {}


def register(renderer: RichRenderer, *suffixes: str) -> None:
    """Associate ``renderer`` with each lower-cased file ``suffix`` (``".md"`` …).
    Later registrations for the same suffix win, so a config could override a
    built-in renderer in the future."""
    for suffix in suffixes:
        _REGISTRY[suffix.lower()] = renderer


def rich_renderer_for(path: Any) -> RichRenderer | None:
    """The rich renderer registered for ``path``'s extension, or ``None`` when the
    type has only the raw text view (nothing to toggle to). ``path`` is any object
    exposing a ``suffix`` (``xefm.path.Path`` / ``pathlib.Path``)."""
    try:
        suffix = path.suffix.lower()
    except AttributeError:
        return None
    return _REGISTRY.get(suffix)


def _build_markdown(source: str, *, style: Style) -> Widget:
    """Build a PuiKit ``MarkdownView`` for ``source`` on the viewer's surface.
    Imported here (not at module load) so the registry stays cheap to import and
    free of any widget-import ordering concerns."""
    from puikit.widgets import MarkdownView

    # ``selectable`` turns on mouse text-selection + Cmd/Ctrl+C copy (plain text
    # plus rich HTML) in the file viewer; help / message popups build their own
    # MarkdownView without it, so those stay inert.
    return MarkdownView(source, style=style, selectable=True)


def _parse_json(source: str) -> Any:
    """Parse ``source`` as a single JSON document, falling back to JSON Lines /
    NDJSON (one JSON value per non-blank line) when the whole-file parse fails —
    so ``*.json`` and ``*.jsonl`` / ``*.ndjson`` share one builder. Raises
    ``json.JSONDecodeError`` when neither form parses (the viewer then stays raw)."""
    text = source.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        records = []
        for line in text.splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))  # propagates on a bad line
        if not records:
            raise
        return records


def _build_json(source: str, *, style: Style) -> Widget:
    """Build a collapsible ``JsonView`` tree for ``source`` (JSON or JSON Lines).
    Imported lazily, like :func:`_build_markdown`, so the registry stays cheap to
    import."""
    from puikit.widgets import JsonView

    return JsonView(_parse_json(source), style=style)


def _make_table_builder(delimiter: str) -> Callable[..., Widget]:
    """A ``build`` for a delimited-text table with the given ``delimiter`` (``","``
    for CSV, ``"\\t"`` for TSV — the suffix picks which, since ``build`` itself is
    not handed the path). The first row is the header; the rest are body rows."""

    def build(source: str, *, style: Style) -> Widget:
        from puikit.widgets import TableView

        rows = list(csv.reader(io.StringIO(source), delimiter=delimiter))
        header = rows[0] if rows else []
        body = rows[1:] if rows else []
        return TableView(header, body, style=style)

    return build


register(RichRenderer("Markdown", _build_markdown), ".md", ".markdown")
register(RichRenderer("JSON", _build_json), ".json", ".jsonl", ".ndjson")
register(RichRenderer("Table", _make_table_builder(",")), ".csv")
register(RichRenderer("Table", _make_table_builder("\t")), ".tsv")

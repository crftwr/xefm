"""A filter picker that also takes typed text says so.

Ask AI Agent's field takes a request of your own as well as filtering the
saved ones, but with a magnifier beside an empty field it read as a search
box only. A picker can name its field (``field_label``, drawn in place of the
magnifier) and put muted text in it while it is empty (``placeholder``).

Run with: python -m pytest test/test_filter_list_field_label.py -v
"""

from puikit import Event, EventType, Panel
from puikit.backends.memory_backend import MemoryBackend

from xefm.filter_list_dialog import show_filter_list


def _text(backend, panel):
    for _ in range(40):
        backend.run_animation_ticks()
    panel.render()
    return "\n".join("".join(row) for row in backend.snapshot())


def _open(**kwargs):
    b = MemoryBackend(width=80, height=24)
    b.open()
    panel = Panel(b)
    dialog = show_filter_list(panel, ["Summarize", "Find duplicates"],
                              title="Ask AI Agent", **kwargs)
    return b, panel, dialog


def test_label_replaces_the_magnifier_and_placeholder_fills_the_empty_field():
    b, panel, dialog = _open(field_label="Prompt:", placeholder="Type a request")
    try:
        text = _text(b, panel)
        assert "Prompt:" in text
        assert "\U0001F50D" not in text
        assert "Type a request" in text
        assert dialog.filter_edit.text == ""

        panel.dispatch_event(Event(type=EventType.KEY, key="s", char="s"))
        text = _text(b, panel)
        assert "Type a request" not in text, "typing replaces the placeholder"
        assert "Prompt:" in text
    finally:
        b.close()


def test_without_them_the_magnifier_stays():
    b, panel, _dialog = _open()
    try:
        assert "\U0001F50D" in _text(b, panel)
    finally:
        b.close()

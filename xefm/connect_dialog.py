"""Connect to Server — the picker, the connection form, and the wait.

Three surfaces, in the order a connection goes through them:

- :func:`open_connect_server` — the picker. The saved servers (config +
  remembered, merged by :mod:`xefm.server_list`), each marked with whether it is
  mounted right now, plus a row that opens the form. It is the shared
  :func:`~xefm.filter_list_dialog.show_filter_list`, so filtering, Migemo and
  the remove key come for free — and so does typing an address that is not in
  the list, through ``on_accept_text``.
- :class:`ConnectFormDialog` — address, account, password and the two save
  choices on one surface. One form rather than three stacked prompts, and the
  password field is masked the same way the archive-password prompt is.
- :func:`run_connecting` — the wait. The mount runs on a worker thread and
  **Esc** gives up on it, which matters because a server that is switched off
  does not refuse a connection, it simply never answers.

The credential lookup happens **inside the worker**, never on the UI thread: it
is a call into the system keychain, which can take a beat and can, after an app
update, put up a system prompt of its own. So the first attempt at a saved
server is made with whatever is stored, and only if that is rejected does the
form open — which is also why a share that allows guests connects with no
prompt at all.

This module owns no navigation. It reports the path it mounted through
``on_connected`` and :mod:`xefm.app` decides what to do with it.
"""

from __future__ import annotations

import platform
import queue
import threading
from dataclasses import dataclass
from typing import Any, Callable, Optional

from puikit.backend import Style, TextAttribute
from puikit.event import Event, EventType
from puikit.focus import FocusContainer, focus_on_click, move_focus
from puikit.panel import Rect
from puikit.theme import DEFAULT_THEME
from puikit.widgets import BusyIndicator, show_message_box
from puikit.widgets.base import Widget
from puikit.widgets.checkbox import Checkbox
from puikit.widgets.text_edit import TextEdit

from xefm import netmount, server_list
from xefm.dialog_geometry import (HINT_ROWS, OPEN_MS_DIALOG, animate_open,
                                  draw_hint_row, draw_title_bar,
                                  pane_anchored_box)
from xefm.log_manager import getLogger

logger = getLogger("Connect")

#: The picker row that opens the form. A module-level sentinel so the row can be
#: compared by identity rather than sniffed out of a label.
NEW_CONNECTION = object()

_MOUNTED_MARK = "●"
_UNMOUNTED_MARK = "○"
#: A server found on the network, which is neither of the above: nothing is
#: mounted and nothing was saved, so it reads as the faintest of the three.
_FOUND_MARK = "·"


# --- the form ----------------------------------------------------------------

@dataclass
class ConnectRequest:
    """What the form collected, and what :func:`run_connecting` acts on."""

    address: str
    user: str = ""
    password: str = ""
    save_password: bool = False
    save_server: bool = True
    drive_letter: str = ""
    #: Name for the saved-server row. The address when the user did not pick
    #: one, which is what a row typed straight into the picker gets.
    name: str = ""


class ConnectFormDialog(FocusContainer, Widget):
    """The connection form: three text fields and two or three checkboxes.

    Focus moves with Tab / Shift-Tab and the arrow keys, Space toggles the
    checkbox under focus, Enter connects from anywhere in the form, and Esc
    cancels. Enter is *not* routed to the focused widget — a form where Enter
    means different things depending on which row you are standing on is a form
    people press Enter on by accident.
    """

    focusable = True
    focus_stop_when_empty = True

    def __init__(self, request: ConnectRequest, *, error: str = "",
                 with_drive_letter: bool = False,
                 on_accept: Callable[[ConnectRequest], None] | None = None,
                 on_cancel: Callable[[], None] | None = None):
        self.title = "Connect to Server"
        self.on_accept = on_accept
        self.on_cancel = on_cancel
        self._error = error
        self._panel: Any = None
        self._size: tuple[float, float] = (0.0, 0.0)

        self.address = TextEdit(text=request.address)
        self.user = TextEdit(text=request.user)
        self.password = TextEdit(text=request.password, mask="•")
        self.save_password = Checkbox("Save password", request.save_password)
        self.save_server = Checkbox("Save this server", request.save_server)
        self.drive_letter = TextEdit(text=request.drive_letter) if with_drive_letter else None
        self._name = request.name

        #: ``(label, widget)`` in focus and draw order. One list drives both, so
        #: a row cannot be drawn in one place and focused in another.
        self.rows: list[tuple[str, Any]] = [
            ("Address", self.address),
            ("User name", self.user),
            ("Password", self.password),
            ("", self.save_password),
            ("", self.save_server),
        ]
        if self.drive_letter is not None:
            self.rows.append(("Drive letter", self.drive_letter))

        for _label, widget in self.rows:
            if isinstance(widget, TextEdit):
                widget.cursor = len(widget.text)
                widget._anchor = len(widget.text)
        # Land on the first empty field: reconnecting a saved server means
        # typing only the password, and starting on the address would mean
        # tabbing past two filled fields every time.
        self._focused = self._first_empty()
        self._row_rects: list[tuple[int, Rect]] = []

    def _first_empty(self) -> Any:
        for _label, widget in self.rows:
            if isinstance(widget, TextEdit) and not widget.text:
                return widget
        return self.rows[0][1]

    # --- focus ---------------------------------------------------------------

    def focus_children(self) -> list[Any]:
        return [widget for _label, widget in self.rows]

    # --- drawing -------------------------------------------------------------

    def draw(self, ctx) -> None:
        self._panel = ctx.panel
        self._size = ctx.size_units
        theme = ctx.theme or DEFAULT_THEME
        surface_bg = theme.popup_bg
        border = theme.popup_border
        box_w, box_h = ctx.size_units
        ctx.draw_box(0, 0, box_w, box_h, Style(bg=surface_bg, fg=border),
                     hints={"fill": True})
        y = draw_title_bar(ctx, self.title, surface_bg=surface_bg, border=border,
                           y=1.0)

        label_w = max(ctx.measure_text(label + " ")
                      for label, _w in self.rows if label) + 2.0
        self._row_rects = []
        for index, (label, widget) in enumerate(self.rows):
            focused = widget is self._focused
            if label:
                ctx.draw_text(2.0, y, label, Style(bg=surface_bg, fg=theme.text))
                x = 2.0 + label_w
            else:
                x = 2.0 + label_w
            w = max(1.0, box_w - x - 2.0)
            if isinstance(widget, TextEdit):
                widget.width = w
            ctx.draw_child(widget, x, y, w, 1.0, hints={"focused": focused})
            self._row_rects.append((index, Rect(x, y, w, 1.0)))
            y += 1.0

        if self._error:
            ctx.draw_text(2.0, y, self._error,
                          Style(bg=surface_bg, fg=(229, 110, 110),
                                attr=TextAttribute.DIM))

        draw_hint_row(ctx, self.hint(), surface_bg=surface_bg, border=border)

    def hint(self) -> str:
        return " · ".join(["Tab next field", "Space toggle",
                           "Enter connect", "Esc cancel"])

    # --- events --------------------------------------------------------------

    def handle_event(self, event: Event) -> bool:
        if event.type is EventType.IME_COMPOSITION:
            if isinstance(self._focused, TextEdit):
                self._focused.handle_event(event)
            return True
        if event.type is EventType.KEY:
            self._on_key(event)
            return True
        if event.type in (EventType.MOUSE_DOWN, EventType.MOUSE_UP,
                          EventType.MOUSE_CLICK, EventType.MOUSE_DRAG):
            self._on_mouse(event)
            return True
        return True  # modal: swallow the rest

    def _on_key(self, event: Event) -> None:
        key = event.key
        if key == "escape":
            self._close()
            if self.on_cancel is not None:
                self.on_cancel()
            return
        if key == "enter":
            self._accept()
            return
        if key == "tab":
            move_focus(self, -1 if "shift" in event.modifiers else 1, wrap=True)
        elif key in ("up", "down") and not isinstance(self._focused, TextEdit):
            # Inside a text field the arrows belong to the caret; on a checkbox
            # there is nothing else for them to do, so they step rows.
            move_focus(self, -1 if key == "up" else 1, wrap=True)
        elif key == "space" and isinstance(self._focused, Checkbox):
            self._toggle(self._focused)
        elif isinstance(self._focused, TextEdit):
            self._focused.handle_event(event)
        self._render()

    def _on_mouse(self, event: Event) -> None:
        if event.x is None or event.y is None:
            return
        w, h = self._size
        if event.type is EventType.MOUSE_CLICK and not (
                0 <= event.x < w and 0 <= event.y < h):
            self._close()
            if self.on_cancel is not None:
                self.on_cancel()
            return
        for index, rect in self._row_rects:
            if not rect.contains(event.x, event.y):
                continue
            widget = self.rows[index][1]
            if event.type is EventType.MOUSE_DOWN:
                focus_on_click(self, widget)
            if isinstance(widget, Checkbox):
                if event.type is EventType.MOUSE_CLICK:
                    self._toggle(widget)
            else:
                widget.handle_event(event.translated(-rect.x, -rect.y))
            self._render()
            return

    def _toggle(self, box: Checkbox) -> None:
        box.checked = not box.checked
        if box.on_change is not None:
            box.on_change(box.checked)

    # --- outcome -------------------------------------------------------------

    def _accept(self) -> None:
        address = self.address.text.strip()
        target = netmount.parse_address(address)
        if target is None:
            # Kept open with the message inline: a mistyped address is one
            # character away from a good one, and closing would lose the rest.
            self._error = ("That is not an address XeFM can connect to — "
                           "try smb://server/share.")
            self._render()
            return
        if target.scheme not in netmount.supported_schemes():
            self._error = f"{target.scheme}:// cannot be mounted on this system."
            self._render()
            return
        request = ConnectRequest(
            address=address,
            user=self.user.text.strip() or target.user,
            password=self.password.text,
            save_password=self.save_password.checked,
            save_server=self.save_server.checked,
            drive_letter=(self.drive_letter.text.strip()
                          if self.drive_letter is not None else ""),
            name=self._name,
        )
        self._close()
        if self.on_accept is not None:
            self.on_accept(request)

    def _close(self) -> None:
        if self._panel is not None:
            self._panel.remove_layer(self)

    def _render(self) -> None:
        if self._panel is not None:
            self._panel.render()


def show_connect_form(panel: Any, request: ConnectRequest, *, error: str = "",
                      on_accept: Callable[[ConnectRequest], None] | None = None,
                      on_cancel: Callable[[], None] | None = None,
                      region: tuple[float, float] | None = None,
                      z: int = 70) -> ConnectFormDialog:
    """Push the connection form over ``panel``."""
    with_letter = bool(_free_drive_letters())
    dialog = ConnectFormDialog(request, error=error,
                               with_drive_letter=with_letter,
                               on_accept=on_accept, on_cancel=on_cancel)
    sw, sh = panel.backend.size_units
    w = max(40.0, min(sw * 0.7, 66.0))
    # One row per field, plus the same chrome the single-field input prompt
    # reserves: pad, title band, the error line under the last field, and the
    # hint band. The compact GUI title bar pulls everything up a row, which is
    # why the constant differs by backend exactly as it does there.
    chrome = 4.0 if panel.backend.capabilities.supports("vector_shapes") else 5.0
    h = len(dialog.rows) + chrome
    hints: dict[str, Any] = {"shadow": True, "w": w, "h": h}
    if region is not None:
        w, x = pane_anchored_box(w, sw, region)
        hints["w"], hints["x"] = w, x
    dialog._panel = panel
    panel.push_layer(dialog, z=z, hints=hints)
    animate_open(panel, dialog, OPEN_MS_DIALOG)
    return dialog


def _free_drive_letters() -> list[str]:
    """The drive letters a connection could be mapped onto — Windows only, and
    empty everywhere else, which is what keeps the field off the form on a Mac
    rather than showing one that cannot mean anything."""
    backend_letters = getattr(_windows_backend(), "free_drive_letters", None)
    if backend_letters is None:
        return []
    try:
        return backend_letters()
    except Exception as e:
        logger.warning(f"Could not list free drive letters: {e}")
        return []


def _windows_backend():
    if platform.system() != "Windows":
        return None
    try:
        from xefm import netmount_windows
        return netmount_windows
    except Exception:
        return None


# --- the wait ----------------------------------------------------------------

class _BusyDialog(Widget):
    """A small modal that says what is being waited for and offers Esc.

    Deliberately not :class:`xefm.task.ProgressDialog`: there is nothing to
    count here, and that dialog's words ("Preparing…") and its cancel-confirm
    step both describe a file operation rather than a connection attempt.
    """

    focusable = True

    def __init__(self, title: str, message: str, on_cancel: Callable[[], None]):
        self.title = title
        self.message = message
        self.on_cancel = on_cancel
        self.busy = BusyIndicator(label="")
        self._panel: Any = None
        self._size: tuple[float, float] = (0.0, 0.0)

    def draw(self, ctx) -> None:
        self._panel = ctx.panel
        self._size = ctx.size_units
        theme = ctx.theme or DEFAULT_THEME
        surface_bg = theme.popup_bg
        box_w, box_h = ctx.size_units
        ctx.draw_box(0, 0, box_w, box_h,
                     Style(bg=surface_bg, fg=theme.popup_border),
                     hints={"fill": True})
        y = draw_title_bar(ctx, self.title, surface_bg=surface_bg,
                           border=theme.popup_border, y=1.0)
        ctx.draw_child(self.busy, 2.0, y, 2.0, 1.0)
        ctx.draw_text(4.5, y, self.message, Style(bg=surface_bg, fg=theme.text))
        draw_hint_row(ctx, "Esc stop waiting", surface_bg=surface_bg,
                      border=theme.popup_border)

    def handle_event(self, event: Event) -> bool:
        if event.type is EventType.KEY and event.key == "escape":
            self.on_cancel()
        return True  # modal

    def close(self) -> None:
        if self._panel is not None:
            self._panel.remove_layer(self)


def run_connecting(panel: Any, message: str, work: Callable[[threading.Event], Any],
                   on_done: Callable[[Any, Optional[BaseException], bool], None],
                   *, title: str = "Connect to Server", z: int = 75) -> None:
    """Run ``work(cancel)`` on a worker thread behind a busy modal.

    ``on_done(result, error, cancelled)`` is called on the **UI thread** once
    the worker ends. ``cancel`` is set when the user presses Esc; the worker is
    expected to notice it where it can and, where it cannot, to undo what it
    did (:func:`xefm.netmount.mount` does exactly that).

    On a backend that drives no animation ticks — the still backend the tests
    use — there is nothing to pump the dialog or service Esc, so the work runs
    inline instead, the same fallback :class:`xefm.task.TaskManager` makes.
    """
    cancel = threading.Event()
    results: queue.Queue = queue.Queue()

    def worker() -> None:
        try:
            results.put((work(cancel), None))
        except BaseException as exc:  # noqa: BLE001 — handed to on_done
            results.put((None, exc))

    dialog = _BusyDialog(title, message, on_cancel=cancel.set)
    sw, sh = panel.backend.size_units
    w = max(36.0, min(sw * 0.6, 60.0))
    dialog._panel = panel
    panel.push_layer(dialog, z=z, hints={"shadow": True, "w": w,
                                         "h": 2.0 + 1.0 + HINT_ROWS})

    def finish(result: Any, error: Optional[BaseException]) -> None:
        dialog.close()
        panel.render()
        on_done(result, error, cancel.is_set())

    def tick() -> bool:
        try:
            result, error = results.get_nowait()
        except queue.Empty:
            return True
        finish(result, error)
        return False

    if not panel.request_animation_ticks(tick):
        dialog.close()
        try:
            finish(work(cancel), None)
        except BaseException as exc:  # noqa: BLE001
            finish(None, exc)
        return

    animate_open(panel, dialog, OPEN_MS_DIALOG)
    threading.Thread(target=worker, daemon=True,
                     name="xefm-connect").start()
    panel.render()


# --- the picker and the flow -------------------------------------------------

class ConnectFlow:
    """Drives one Connect to Server interaction, from the picker to the mount.

    Held together in one object because the steps hand values to each other: a
    rejected password reopens the form with what the user typed, and a
    successful connection has a server to remember and a path to navigate to.
    """

    def __init__(self, panel: Any, *,
                 on_connected: Callable[[str, str], None],
                 region: tuple[float, float] | None = None):
        self.panel = panel
        #: ``on_connected(path, label)`` — the mounted path and what to call it
        #: in the log line. Navigation is the app's business, not this module's.
        self.on_connected = on_connected
        self.region = region
        #: Hosts already represented in the list, so discovery does not add a
        #: second row for one. Filled by :meth:`open`, added to by the loader.
        self._known: set[str] = set()

    # --- the picker ---------------------------------------------------------

    def open(self) -> None:
        from xefm.filter_list_dialog import show_filter_list

        mounts = netmount.list_mounts()
        entries = server_list.get_servers()
        rows: list[Any] = [_PickerRow(entry, server_list.mounted_at(entry, mounts))
                           for entry in entries]
        rows.append(NEW_CONNECTION)
        # Servers already in the list as a *server* (not as one of its shares)
        # are not worth a second row. A saved share is different: the row goes
        # to that share, the discovered row browses the whole machine.
        self._known = {_host_key(entry.url) for entry in entries
                       if (entry.target is not None and not entry.target.share)}

        show_filter_list(
            self.panel, rows, title="Connect to Server",
            to_label=_row_label,
            on_accept=self._chosen,
            on_accept_text=self._typed,
            on_remove=_forget_row,
            remove_label="forget",
            region=self.region,
            elide_where="middle",
            load_more=self._discover if netmount.can_discover() else None,
        )
        self.panel.render()

    def _discover(self, cancel: threading.Event):
        """Servers found on the network, streamed into the open picker.

        The same background-loader seam the drives picker uses for S3 buckets:
        the dialog is up before this starts, rows arrive underneath it, and
        closing the dialog sets ``cancel`` and stops the browse.
        """
        for server in netmount.discover_servers(cancel):
            if _host_key(server.host) in self._known:
                continue
            self._known.add(_host_key(server.host))
            yield _DiscoveredRow(server)

    def _chosen(self, row: Any) -> None:
        if row is NEW_CONNECTION:
            self.show_form(ConnectRequest(address=""))
            return
        if isinstance(row, _DiscoveredRow):
            # A server, not a share: ask it what it offers.
            self.browse_shares(row.server.target, name=row.server.name)
            return
        if row.mounted_at:
            # Already there: no network, no password, no waiting.
            self.on_connected(row.mounted_at, row.entry.name)
            return
        self.connect(ConnectRequest(address=row.entry.url, user=row.entry.user,
                                    name=row.entry.name, save_server=False),
                     stored_password=True)

    def _typed(self, text: str) -> None:
        """Enter on filter text that matched no row. An address opens the form
        with it filled in; anything else was a search that found nothing, and
        the picker has already closed on it."""
        target = netmount.parse_address(text)
        if target is None:
            return
        self.show_form(ConnectRequest(address=text, user=target.user))

    # --- the form -----------------------------------------------------------

    def show_form(self, request: ConnectRequest, error: str = "") -> None:
        show_connect_form(self.panel, request, error=error,
                          on_accept=lambda req: self.connect(req),
                          region=self.region)
        self.panel.render()

    # --- the connection -----------------------------------------------------

    def connect(self, request: ConnectRequest, *, stored_password: bool = False) -> None:
        """Mount what ``request`` describes, behind the busy modal.

        ``stored_password`` means "no password was typed — look one up". That
        lookup is a keychain call, so it happens on the worker thread with the
        mount, never here.
        """
        target = netmount.parse_address(request.address)
        if target is None:
            show_message_box(self.panel,
                             f"{request.address} is not an address XeFM "
                             "can connect to.",
                             title="Connect to Server", icon="error")
            self.panel.render()
            return

        user = request.user or target.user
        if not target.share and target.scheme in ("smb", "afp", "nfs"):
            # An address that names a server and no share is a request to
            # browse it. This is also what makes the form double as the way in
            # for a server typed by hand: it comes back here either way.
            self.browse_shares(target, name=request.name, user=user,
                               password=request.password)
            return

        def work(cancel: threading.Event) -> str:
            password = request.password
            if stored_password and not password:
                password = netmount.load_password(target, user)
            path = netmount.mount(target, user=user, password=password,
                                  drive_letter=request.drive_letter,
                                  cancel=cancel)
            if request.save_password and request.password:
                netmount.save_password(target, user, request.password)
            if request.save_server:
                server_list.save_server(request.name or target.url,
                                        target.url, user)
            return path

        def done(path: Any, error: Optional[BaseException], cancelled: bool) -> None:
            if cancelled:
                logger.info(f"Connection to {target.url} cancelled")
                return
            if error is None and path:
                self.on_connected(str(path), request.name or target.url)
                return
            self._failed(request, target, user, error)

        run_connecting(self.panel, f"Connecting to {target.host}…", work, done)

    # --- browsing a server --------------------------------------------------

    def browse_shares(self, target, *, name: str = "", user: str = "",
                      password: str = "") -> None:
        """Ask a server what it offers and let the user pick one.

        Finder's flow, and for the same reason: a server is not something to
        open, it is a list of shares, and nobody remembers the spelling of the
        third one. The listing is anonymous (see
        :func:`xefm.netmount.list_shares`), so a server that will not answer a
        guest query ends up back at the form — where the address can simply be
        finished by hand.
        """
        def work(cancel: threading.Event) -> list:
            return netmount.list_shares(target)

        def done(shares: Any, error: Optional[BaseException],
                 cancelled: bool) -> None:
            if cancelled:
                return
            if error is not None or not shares:
                self._cannot_browse(target, name, user, error)
                return
            self._show_shares(target, shares, name=name, user=user,
                              password=password)

        run_connecting(self.panel, f"Asking {target.host} for its shares…",
                       work, done, title="Connect to Server")

    def _show_shares(self, target, shares: list, *, name: str, user: str,
                     password: str) -> None:
        from xefm.filter_list_dialog import show_filter_list

        def chosen(share: str) -> None:
            self.connect(ConnectRequest(
                address=f"{target.url}/{share}", user=user, password=password,
                name=f"{name or target.host} — {share}"))

        show_filter_list(
            self.panel, list(shares),
            title=f"Shares on {name or target.host}",
            on_accept=chosen, region=self.region, elide_where="middle")
        self.panel.render()

    def _cannot_browse(self, target, name: str, user: str,
                       error: Optional[BaseException]) -> None:
        """A server that would not list its shares. The form reopens with the
        server address, and the message says what to add to it — which is the
        one thing the user can do that XeFM cannot."""
        detail = str(error) if error else f"{target.host} listed no shares."
        logger.info(f"Could not list shares on {target.host}: {detail}")
        self.show_form(
            ConnectRequest(address=target.url + "/", user=user, name=name),
            error=f"{detail} Add the share name after the server.")

    def _failed(self, request: ConnectRequest, target, user: str,
                error: Optional[BaseException]) -> None:
        message = str(error) if error else "The connection did not happen."
        auth = isinstance(error, netmount.MountError) and error.auth
        logger.error(f"Could not connect to {target.url}: {message}")
        if auth or not error:
            # Reopened with what was typed, so the password can be corrected
            # without retyping the address — and so that a saved server whose
            # stored password has gone stale has somewhere to enter a new one.
            self.show_form(ConnectRequest(address=request.address, user=user,
                                          save_password=request.save_password,
                                          save_server=request.save_server,
                                          drive_letter=request.drive_letter,
                                          name=request.name),
                           error=message)
            return
        show_message_box(self.panel, message, title="Connect to Server",
                         icon="error")
        self.panel.render()


@dataclass(frozen=True)
class _PickerRow:
    entry: server_list.ServerEntry
    mounted_at: str


@dataclass(frozen=True)
class _DiscoveredRow:
    """A server found on the network rather than saved. It has no share yet,
    so choosing it browses instead of connecting."""

    server: netmount.DiscoveredServer


def _host_key(text: str) -> str:
    """A host as an identity, for telling a discovered server apart from one
    already in the list. The rule lives in :func:`xefm.netmount.canonical_host`
    — the same one the keychain and the mount table are matched by."""
    target = netmount.parse_address(text)
    return netmount.canonical_host(target.host if target is not None else text)


def _row_label(row: Any) -> str:
    if row is NEW_CONNECTION:
        return "＋  New connection…"
    if isinstance(row, _DiscoveredRow):
        return f"{_FOUND_MARK}  {row.server.name}  —  on the network"
    mark = _MOUNTED_MARK if row.mounted_at else _UNMOUNTED_MARK
    label = f"{mark}  {row.entry.name}"
    if row.entry.name != row.entry.url:
        label += f"  —  {row.entry.url}"
    if row.mounted_at:
        label += f"  →  {row.mounted_at}"
    return label


def _forget_row(row: Any) -> bool:
    """The picker's remove hook. The form row and the discovered rows decline
    it — nothing was remembered about them to forget — and so do config rows;
    declining is what leaves all three in the list."""
    if row is NEW_CONNECTION or isinstance(row, _DiscoveredRow):
        return False
    return server_list.forget_server(row.entry)


def open_connect_server(panel: Any, *,
                        on_connected: Callable[[str, str], None],
                        region: tuple[float, float] | None = None) -> None:
    """Open the Connect to Server picker. ``on_connected(path, label)`` fires
    once a share is mounted (or found already mounted)."""
    ConnectFlow(panel, on_connected=on_connected, region=region).open()

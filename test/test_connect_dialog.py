"""Connect to Server — the routing between picker, form and mount.

The surfaces are not drawn here; what is checked is which one each choice leads
to, and what is handed to the mount when it gets there. A share that is already
mounted must not cost a round trip, a rejected password must reopen the form
with what was typed, and an address typed into the filter line must not be
mistaken for a search.
"""

import threading
import time
import unittest
from unittest.mock import patch

from puikit.event import Event, EventType

from xefm import connect_dialog as cd
from xefm import netmount
from xefm import server_list
from xefm.server_list import CONFIG, ServerEntry


class _Panel:
    """Enough panel for the flow: it records nothing and draws nothing."""

    def render(self):
        pass

    def remove_layer(self, widget):
        return True

    def push_layer(self, widget, **kwargs):
        pass

    def request_animation_ticks(self, tick):
        return False  # the still-backend path: work runs inline

    class backend:
        size_units = (120.0, 40.0)


class RowLabels(unittest.TestCase):
    def test_a_mounted_row_says_where(self):
        row = cd._PickerRow(ServerEntry("NAS Photo", "smb://nas/photo"),
                            "/Volumes/photo")
        self.assertIn("/Volumes/photo", cd._row_label(row))

    def test_an_unmounted_row_does_not(self):
        row = cd._PickerRow(ServerEntry("NAS Photo", "smb://nas/photo"), "")
        self.assertNotIn("→", cd._row_label(row))

    def test_no_row_starts_with_a_glyph_of_its_own(self):
        """Marks like ``●``/``○``/``·``/``＋`` do not line up. The circles and
        the middle dot are East Asian Width *ambiguous* — one cell in a Latin
        terminal, two in a CJK one — while the fullwidth plus is always two, so
        the labels began at three different columns; and in the GUI's
        proportional font at three different offsets again. No other picker in
        XeFM puts a glyph in front of a row either."""
        rows = [
            cd._PickerRow(ServerEntry("A", "smb://a/x"), "/Volumes/x"),
            cd._PickerRow(ServerEntry("B", "smb://b/x"), ""),
            cd.NEW_CONNECTION,
            self._row(),
        ]
        for row in rows:
            label = cd._row_label(row)
            with self.subTest(label=label):
                self.assertTrue(label[0].isalnum(),
                                f"row starts with {label[0]!r}")

    def _row(self, name="SynologyNas", host="SynologyNas.local"):
        return cd._DiscoveredRow(netmount.DiscoveredServer(name, host))

    def test_an_unnamed_row_does_not_print_its_address_twice(self):
        row = cd._PickerRow(ServerEntry("smb://nas/x", "smb://nas/x"), "")
        self.assertEqual(cd._row_label(row).count("smb://nas/x"), 1)

    def test_the_action_row_has_its_own_label(self):
        self.assertIn("New connection", cd._row_label(cd.NEW_CONNECTION))

    def test_the_action_row_declines_the_remove_key(self):
        self.assertFalse(cd._forget_row(cd.NEW_CONNECTION))


class DiscoveredRows(unittest.TestCase):
    def _row(self, name="SynologyNas", host="SynologyNas.local"):
        return cd._DiscoveredRow(netmount.DiscoveredServer(name, host))

    def test_a_discovered_row_says_where_it_came_from(self):
        label = cd._row_label(self._row())
        self.assertIn("SynologyNas", label)
        self.assertIn("on the network", label)

    def test_a_discovered_row_declines_the_remove_key(self):
        """Nothing was remembered about it, so there is nothing to forget."""
        self.assertFalse(cd._forget_row(self._row()))

    def test_local_comes_off_when_matching_a_host(self):
        """Bonjour answers `SynologyNas.local`; a saved row says
        `synologynas`. One machine, one row."""
        self.assertEqual(cd._host_key("smb://synologynas/Videos"),
                         cd._host_key("SynologyNas.local"))

    def test_different_servers_do_not_collide(self):
        self.assertNotEqual(cd._host_key("smb://nas-a/x"),
                            cd._host_key("smb://nas-b/x"))


class _FakeState:
    """The two ``StateManager`` methods the server list uses, over a dict.

    Every test that lets a connection succeed goes through ``save_server``, and
    ``ConnectRequest.save_server`` defaults to True — so without this the suite
    writes test servers into the developer's own ``~/.xefm/state.db``. It did,
    once.
    """

    def __init__(self):
        self.store = {}

    def get_state(self, key, default=None):
        return self.store.get(key, default)

    def set_state(self, key, value):
        self.store[key] = value
        return True


class Flow(unittest.TestCase):
    def setUp(self):
        state = _FakeState()
        patcher = patch("xefm.server_list.get_state_manager", lambda: state)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.panel = _Panel()
        self.connected = []
        self.flow = cd.ConnectFlow(
            self.panel, on_connected=lambda p, n: self.connected.append((p, n)))
        self.forms = []
        patcher = patch.object(
            cd, "show_connect_form",
            lambda panel, request, **kw: self.forms.append((request, kw.get("error", ""))))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_mounted_row_needs_no_connection_at_all(self):
        row = cd._PickerRow(ServerEntry("NAS", "smb://nas/photo"), "/Volumes/photo")
        with patch.object(cd, "run_connecting") as run:
            self.flow._chosen(row)
        run.assert_not_called()
        self.assertEqual(self.connected, [("/Volumes/photo", "NAS")])

    def test_an_unmounted_row_connects_with_its_stored_password(self):
        row = cd._PickerRow(ServerEntry("NAS", "smb://nas/photo", "me"), "")
        with patch.object(netmount, "load_password", return_value="stored") as load, \
             patch.object(netmount, "mount", return_value="/Volumes/photo") as mount:
            self.flow._chosen(row)
        load.assert_called_once()
        self.assertEqual(mount.call_args.kwargs["password"], "stored")
        self.assertEqual(mount.call_args.kwargs["user"], "me")
        self.assertEqual(self.connected, [("/Volumes/photo", "NAS")])

    def test_the_stored_password_is_read_on_the_worker_not_before_it(self):
        """The keychain can take a beat, and can put up a prompt of its own; it
        must not be asked on the UI thread."""
        seen = {}

        def work_recording_mount(*a, **kw):
            seen["thread"] = threading.current_thread().name
            return "/Volumes/photo"

        row = cd._PickerRow(ServerEntry("NAS", "smb://nas/photo", "me"), "")
        calls = []
        with patch.object(netmount, "load_password",
                          side_effect=lambda t, u: calls.append("load") or ""), \
             patch.object(netmount, "mount", side_effect=work_recording_mount), \
             patch.object(cd, "run_connecting") as run:
            self.flow._chosen(row)
            # Nothing was read while the choice was being handled...
            self.assertEqual(calls, [])
            # ...it happens inside the callable handed to run_connecting, which
            # is called here *under the patches* — outside them this line would
            # be a real mount attempt against a real network.
            run.assert_called_once()
            run.call_args.args[2](threading.Event())
        self.assertEqual(calls, ["load"])
        self.assertTrue(seen["thread"])

    def test_the_new_connection_row_opens_an_empty_form(self):
        self.flow._chosen(cd.NEW_CONNECTION)
        self.assertEqual(self.forms[0][0].address, "")

    def test_a_typed_address_opens_the_form_filled_in(self):
        self.flow._typed("smb://me@nas/photo")
        request, _error = self.forms[0]
        self.assertEqual(request.address, "smb://me@nas/photo")
        self.assertEqual(request.user, "me")

    def test_typed_text_that_is_not_an_address_does_nothing(self):
        """It was a filter that matched nothing, not a server."""
        self.flow._typed("kensaku")
        self.assertEqual(self.forms, [])

    def test_a_rejected_password_reopens_the_form_with_what_was_typed(self):
        request = cd.ConnectRequest(address="smb://nas/photo", user="me",
                                    password="wrong", save_password=True)
        error = netmount.MountError("The server rejected the user name or "
                                    "password.", auth=True)
        with patch.object(netmount, "mount", side_effect=error):
            self.flow.connect(request)
        self.assertEqual(len(self.forms), 1)
        reopened, message = self.forms[0]
        self.assertEqual(reopened.address, "smb://nas/photo")
        self.assertEqual(reopened.user, "me")
        self.assertTrue(reopened.save_password)
        self.assertIn("rejected", message)
        # The password itself is not carried back into the form.
        self.assertEqual(reopened.password, "")

    def test_an_unreachable_server_reports_rather_than_reopening(self):
        error = netmount.MountError("nas: The server cannot be reached.")
        with patch.object(netmount, "mount", side_effect=error), \
             patch.object(cd, "show_message_box") as box:
            self.flow.connect(cd.ConnectRequest(address="smb://nas/photo"))
        self.assertEqual(self.forms, [])
        box.assert_called_once()

    def test_a_cancelled_connection_is_silent(self):
        def cancelling(panel, message, work, on_done, **kw):
            on_done(None, netmount.MountError("Cancelled."), True)

        with patch.object(cd, "run_connecting", cancelling), \
             patch.object(cd, "show_message_box") as box:
            self.flow.connect(cd.ConnectRequest(address="smb://nas/photo"))
        box.assert_not_called()
        self.assertEqual(self.forms, [])
        self.assertEqual(self.connected, [])

    def test_a_successful_connection_saves_what_it_was_told_to(self):
        request = cd.ConnectRequest(address="smb://nas/photo", user="me",
                                    password="secret", save_password=True,
                                    save_server=True, name="NAS")
        with patch.object(netmount, "mount", return_value="/Volumes/photo"), \
             patch.object(netmount, "save_password") as save_pw, \
             patch("xefm.server_list.save_server") as save_server:
            self.flow.connect(request)
        save_pw.assert_called_once()
        self.assertEqual(save_pw.call_args.args[2], "secret")
        save_server.assert_called_once_with("NAS", "smb://nas/photo", "me")
        self.assertEqual(self.connected, [("/Volumes/photo", "NAS")])

    def test_nothing_is_saved_when_the_boxes_are_unticked(self):
        request = cd.ConnectRequest(address="smb://nas/photo", password="secret",
                                    save_password=False, save_server=False)
        with patch.object(netmount, "mount", return_value="/Volumes/photo"), \
             patch.object(netmount, "save_password") as save_pw, \
             patch("xefm.server_list.save_server") as save_server:
            self.flow.connect(request)
        save_pw.assert_not_called()
        save_server.assert_not_called()

    def test_a_password_typed_into_the_form_reaches_the_mount(self):
        """The whole chain, since an authentication failure looks identical
        whether the server refused the password or XeFM never sent it."""
        with patch.object(netmount, "supported_schemes", return_value=("smb",)), \
             patch.object(netmount, "mount", return_value="/Volumes/Videos") as mount:
            form = cd.ConnectFormDialog(
                cd.ConnectRequest(address="smb://synologynas/Videos"),
                on_accept=self.flow.connect)
            form.user.text = "crftwr"
            form.password.text = "hunter2"
            form._accept()
        self.assertEqual(mount.call_args.kwargs["user"], "crftwr")
        self.assertEqual(mount.call_args.kwargs["password"], "hunter2")

    def test_a_refused_guest_connection_reopens_the_form(self):
        """Choosing a saved server with no stored password tries guest first;
        a NAS refuses that, and the next thing the user sees has to be the
        password field, not a dead end (EAUTH, error 80)."""
        row = cd._PickerRow(ServerEntry("NAS", "smb://synologynas/Videos"), "")
        error = netmount.MountError("synologynas needs a user name and "
                                    "password.", auth=True)
        with patch.object(netmount, "load_password", return_value=""), \
             patch.object(netmount, "mount", side_effect=error), \
             patch.object(cd, "show_message_box") as box:
            self.flow._chosen(row)
        box.assert_not_called()
        self.assertEqual(len(self.forms), 1)
        self.assertEqual(self.forms[0][0].address, "smb://synologynas/Videos")

    def test_an_address_the_form_could_not_have_produced_is_refused(self):
        with patch.object(cd, "show_message_box") as box, \
             patch.object(netmount, "mount") as mount:
            self.flow.connect(cd.ConnectRequest(address="nonsense"))
        mount.assert_not_called()
        box.assert_called_once()

    def test_choosing_a_discovered_server_browses_it(self):
        row = cd._DiscoveredRow(
            netmount.DiscoveredServer("SynologyNas", "SynologyNas.local"))
        with patch.object(netmount, "list_shares",
                          return_value=["Videos", "Documents"]) as shares, \
             patch("xefm.filter_list_dialog.show_filter_list") as show, \
             patch.object(netmount, "mount") as mount:
            self.flow._chosen(row)
        mount.assert_not_called()          # a server is not something to mount
        shares.assert_called_once()
        self.assertEqual(shares.call_args.args[0].url,
                         "smb://SynologyNas.local")
        self.assertEqual(list(show.call_args.args[1]), ["Videos", "Documents"])

    def test_picking_a_share_mounts_that_share(self):
        target = netmount.parse_address("smb://SynologyNas.local")
        with patch("xefm.filter_list_dialog.show_filter_list") as show:
            self.flow._show_shares(target, ["Videos"], name="SynologyNas",
                                   user="me", password="secret")
        chosen = show.call_args.kwargs["on_accept"]
        with patch.object(netmount, "mount",
                          return_value="/Volumes/Videos") as mount:
            chosen("Videos")
        self.assertEqual(mount.call_args.args[0].url,
                         "smb://SynologyNas.local/Videos")
        self.assertEqual(mount.call_args.kwargs["password"], "secret")
        self.assertEqual(self.connected[0][0], "/Volumes/Videos")

    def test_browsing_uses_the_account_already_saved_for_that_machine(self):
        """The screenshot case: a discovered server has no account, the guest
        query is refused, and the account the user connected with before is
        what makes the listing work."""
        row = cd._DiscoveredRow(
            netmount.DiscoveredServer("SynologyNas", "SynologyNas.local"))
        with patch("xefm.server_list.user_for_host", return_value="crftwr"), \
             patch.object(netmount, "list_shares",
                          return_value=["Videos"]) as shares, \
             patch("xefm.filter_list_dialog.show_filter_list"):
            self.flow._chosen(row)
        self.assertEqual(shares.call_args.args[1], "crftwr")

    def test_the_keychain_supplies_the_account_when_nothing_is_saved(self):
        """With the saved servers forgotten there is no account to remember —
        but the machine has been connected to before, and the system credential
        store knows under what name. That is what Finder uses too."""
        row = cd._DiscoveredRow(
            netmount.DiscoveredServer("SynologyNas", "SynologyNas.local"))
        with patch("xefm.server_list.user_for_host", return_value=""), \
             patch.object(netmount, "find_account", return_value="crftwr"), \
             patch.object(netmount, "list_shares",
                          return_value=["Videos"]) as shares, \
             patch("xefm.filter_list_dialog.show_filter_list"):
            self.flow._chosen(row)
        self.assertEqual(shares.call_args.args[1], "crftwr")

    def test_a_typed_account_beats_both_lookups(self):
        with patch("xefm.server_list.user_for_host", return_value="saved") as saved, \
             patch.object(netmount, "find_account", return_value="keychain") as kc, \
             patch.object(netmount, "list_shares",
                          return_value=["Videos"]) as shares, \
             patch("xefm.filter_list_dialog.show_filter_list"):
            self.flow.connect(cd.ConnectRequest(address="smb://nas", user="typed"))
        self.assertEqual(shares.call_args.args[1], "typed")
        saved.assert_not_called()
        kc.assert_not_called()

    def test_a_saved_account_beats_the_keychain(self):
        with patch("xefm.server_list.user_for_host", return_value="saved"), \
             patch.object(netmount, "find_account", return_value="keychain") as kc, \
             patch.object(netmount, "list_shares",
                          return_value=["Videos"]) as shares, \
             patch("xefm.filter_list_dialog.show_filter_list"):
            self.flow.connect(cd.ConnectRequest(address="smb://nas"))
        self.assertEqual(shares.call_args.args[1], "saved")
        kc.assert_not_called()

    def test_a_password_to_be_saved_is_saved_before_the_listing(self):
        """`smbutil` authenticates out of the Keychain, so storing the password
        is what makes it usable — the order is the point."""
        order = []
        with patch.object(netmount, "save_password",
                          side_effect=lambda *a: order.append("save")), \
             patch.object(netmount, "list_shares",
                          side_effect=lambda *a: order.append("list") or ["Videos"]), \
             patch("xefm.filter_list_dialog.show_filter_list"):
            self.flow.connect(cd.ConnectRequest(
                address="smb://nas", user="me", password="secret",
                save_password=True))
        self.assertEqual(order, ["save", "list"])

    def test_a_password_not_to_be_saved_is_not_saved(self):
        with patch.object(netmount, "save_password") as save, \
             patch.object(netmount, "list_shares", return_value=["Videos"]), \
             patch("xefm.filter_list_dialog.show_filter_list"):
            self.flow.connect(cd.ConnectRequest(
                address="smb://nas", user="me", password="secret",
                save_password=False))
        save.assert_not_called()

    def test_a_server_that_will_not_list_sends_you_to_the_form(self):
        """The listing is anonymous, so a locked-down server refuses it. The
        share name is then the one thing the user can supply and XeFM cannot."""
        row = cd._DiscoveredRow(
            netmount.DiscoveredServer("SynologyNas", "SynologyNas.local"))
        error = netmount.MountError("SynologyNas.local: refused", auth=True)
        with patch.object(netmount, "list_shares", side_effect=error), \
             patch.object(cd, "show_message_box") as box:
            self.flow._chosen(row)
        box.assert_not_called()
        request, message = self.forms[0]
        self.assertEqual(request.address, "smb://SynologyNas.local/")
        self.assertIn("Add the share name", message)

    def test_a_server_typed_by_hand_is_browsed_not_mounted(self):
        with patch.object(netmount, "list_shares",
                          return_value=["Videos"]) as shares, \
             patch("xefm.filter_list_dialog.show_filter_list"), \
             patch.object(netmount, "mount") as mount:
            self.flow.connect(cd.ConnectRequest(address="smb://nas"))
        mount.assert_not_called()
        shares.assert_called_once()

    def test_discovery_skips_a_server_already_in_the_list(self):
        entries = [server_list.ServerEntry("NAS", "smb://synologynas")]
        found = [netmount.DiscoveredServer("SynologyNas", "SynologyNas.local"),
                 netmount.DiscoveredServer("Other", "other.local")]
        with patch("xefm.server_list.get_servers", return_value=entries), \
             patch.object(netmount, "list_mounts", return_value=[]), \
             patch.object(netmount, "can_discover", return_value=True), \
             patch.object(netmount, "discover_servers", return_value=iter(found)), \
             patch("xefm.filter_list_dialog.show_filter_list"):
            self.flow.open()
            streamed = list(self.flow._discover(threading.Event()))
        self.assertEqual([r.server.name for r in streamed], ["Other"])

    def test_a_saved_share_does_not_hide_its_server(self):
        """Saving one share is not a reason to stop offering the machine: the
        rows do different things."""
        entries = [server_list.ServerEntry("Videos", "smb://synologynas/Videos")]
        found = [netmount.DiscoveredServer("SynologyNas", "SynologyNas.local")]
        with patch("xefm.server_list.get_servers", return_value=entries), \
             patch.object(netmount, "list_mounts", return_value=[]), \
             patch.object(netmount, "can_discover", return_value=True), \
             patch.object(netmount, "discover_servers", return_value=iter(found)), \
             patch("xefm.filter_list_dialog.show_filter_list"):
            self.flow.open()
            streamed = list(self.flow._discover(threading.Event()))
        self.assertEqual([r.server.name for r in streamed], ["SynologyNas"])

    def test_the_picker_lists_saved_servers_and_the_action_row(self):
        entries = [ServerEntry("Work", "smb://work/share", origin=CONFIG)]
        with patch("xefm.server_list.get_servers", return_value=entries), \
             patch.object(netmount, "list_mounts", return_value=[]), \
             patch("xefm.filter_list_dialog.show_filter_list") as show:
            self.flow.open()
        rows = show.call_args.args[1]
        self.assertIs(rows[-1], cd.NEW_CONNECTION)
        self.assertEqual(rows[0].entry.name, "Work")
        self.assertEqual(show.call_args.kwargs["remove_label"], "forget")


class FormValidation(unittest.TestCase):
    def _form(self, address, **kw):
        accepted = []
        dialog = cd.ConnectFormDialog(
            cd.ConnectRequest(address=address, **kw),
            on_accept=accepted.append)
        return dialog, accepted

    def test_a_good_address_is_accepted(self):
        with patch.object(netmount, "supported_schemes", return_value=("smb",)):
            dialog, accepted = self._form("smb://nas/photo")
            dialog._accept()
        self.assertEqual(accepted[0].address, "smb://nas/photo")

    def test_a_bad_address_keeps_the_form_open(self):
        dialog, accepted = self._form("nonsense")
        dialog._accept()
        self.assertEqual(accepted, [])
        self.assertIn("smb://server/share", dialog._error)

    def test_a_scheme_this_platform_cannot_mount_is_named(self):
        with patch.object(netmount, "supported_schemes", return_value=("smb",)):
            dialog, accepted = self._form("nfs://server/export")
            dialog._accept()
        self.assertEqual(accepted, [])
        self.assertIn("nfs://", dialog._error)

    def test_the_user_from_the_address_fills_the_field(self):
        with patch.object(netmount, "supported_schemes", return_value=("smb",)):
            dialog, accepted = self._form("smb://me@nas/photo")
            dialog._accept()
        self.assertEqual(accepted[0].user, "me")

    def test_focus_starts_on_the_first_empty_field(self):
        dialog, _ = self._form("smb://nas/photo", user="me")
        self.assertIs(dialog._focused, dialog.password)

    def test_there_is_no_drive_letter_field_without_letters_to_offer(self):
        dialog, _ = self._form("smb://nas/photo")
        self.assertIsNone(dialog.drive_letter)
        self.assertEqual(len(dialog.rows), 5)


class FormKeys(unittest.TestCase):
    """The form's own keyboard: Tab walks the rows, Space toggles a checkbox,
    Enter connects from wherever you are standing."""

    def setUp(self):
        self.accepted = []
        self.cancelled = []
        self.dialog = cd.ConnectFormDialog(
            cd.ConnectRequest(address="smb://nas/photo", user="me"),
            on_accept=self.accepted.append,
            on_cancel=lambda: self.cancelled.append(True))

    def _key(self, name, char=None, mods=()):
        self.dialog.handle_event(Event(type=EventType.KEY, key=name, char=char,
                                       modifiers=frozenset(mods)))

    def test_tab_walks_forward_and_wraps(self):
        order = [w for _label, w in self.dialog.rows]
        self.dialog._focused = order[0]
        for expected in order[1:] + order[:1]:
            self._key("tab")
            self.assertIs(self.dialog._focused, expected)

    def test_shift_tab_walks_back(self):
        order = [w for _label, w in self.dialog.rows]
        self.dialog._focused = order[0]
        self._key("tab", mods=("shift",))
        self.assertIs(self.dialog._focused, order[-1])

    def test_space_toggles_the_checkbox_under_focus(self):
        self.dialog._focused = self.dialog.save_password
        self.assertFalse(self.dialog.save_password.checked)
        self._key("space", char=" ")
        self.assertTrue(self.dialog.save_password.checked)

    def test_space_in_a_text_field_is_a_space(self):
        self.dialog._focused = self.dialog.user
        before = self.dialog.save_password.checked
        self._key("space", char=" ")
        self.assertEqual(self.dialog.save_password.checked, before)

    def test_the_arrows_step_rows_everywhere_in_the_form(self):
        """Including inside the text fields: they are single-line, so up and
        down mean nothing to the caret and would otherwise be dead keys on
        three of the five rows."""
        order = [w for _label, w in self.dialog.rows]
        self.dialog._focused = order[0]
        for expected in order[1:] + order[:1]:
            self._key("down")
            self.assertIs(self.dialog._focused, expected)

    def test_up_steps_back_and_wraps(self):
        order = [w for _label, w in self.dialog.rows]
        self.dialog._focused = order[0]
        self._key("up")
        self.assertIs(self.dialog._focused, order[-1])

    def test_typing_still_reaches_the_focused_field(self):
        """The arrows were the only keys taken away from the fields."""
        self.dialog._focused = self.dialog.user
        self._key("a", char="a")
        self.assertEqual(self.dialog.user.text, "mea")  # caret was at the end

    def test_enter_connects_from_a_checkbox_too(self):
        self.dialog._focused = self.dialog.save_server
        with patch.object(netmount, "supported_schemes", return_value=("smb",)):
            self._key("enter")
        self.assertEqual(len(self.accepted), 1)

    def test_escape_cancels(self):
        self._key("escape")
        self.assertEqual(self.cancelled, [True])
        self.assertEqual(self.accepted, [])


class Drawing(unittest.TestCase):
    """The surfaces draw. Layout bugs in a dialog are invisible to the routing
    tests above and show up only when something actually renders it."""

    def setUp(self):
        from puikit.backends import create_backend
        from puikit.panel import Panel

        self.backend = create_backend("memory", width=100, height=30)
        self.backend.open()
        self.panel = Panel(self.backend)
        self.panel.set_text_effect(False)
        # Off for the same reason the text effect is: the entrance scales the
        # box to 92% on its first frames, so a dialog measured mid-animation
        # is a dialog measured at the wrong size — which is how a row that
        # does not fit went unnoticed once already.
        self.panel.set_reduced_motion(True)
        self.addCleanup(self.backend.close)

    def _shows(self, needle):
        self.panel.render()
        lines = self.backend.snapshot()
        return any(needle in line for line in lines), lines

    def test_the_form_draws_with_an_error_and_a_filled_address(self):
        cd.show_connect_form(
            self.panel, cd.ConnectRequest(address="smb://nas/photo", user="me"),
            error="The server rejected the user name or password.")
        self.panel.render()

    def test_the_form_draws_empty(self):
        cd.show_connect_form(self.panel, cd.ConnectRequest(address=""))
        self.panel.render()

    def test_the_form_error_is_on_screen(self):
        """Asserted by reading the screen, not by comparing coordinates. The
        first version of this compared the error's row against
        ``hint_content_bottom`` and passed while the line was invisible —
        content has to end one row *above* that, since the hint band's rule is
        drawn on it."""
        cd.show_connect_form(
            self.panel, cd.ConnectRequest(address="smb://nas/x"),
            error="DISTINCTIVE-ERROR-TEXT")
        shown, lines = self._shows("DISTINCTIVE-ERROR-TEXT")
        self.assertTrue(shown, "\n".join(lines))

    def test_a_long_error_does_not_run_off_the_edge(self):
        """A server's message is as long as the server felt like making it."""
        cd.show_connect_form(
            self.panel, cd.ConnectRequest(address="smb://SynologyNas/"),
            error="SynologyNas: smbutil: server connection failed: "
                  "Authentication error. Add the share name after the server.")
        self.panel.render()
        for line in self.backend.snapshot():
            self.assertLessEqual(len(line.rstrip()), 100)

    def test_the_busy_modal_sits_on_the_dialog_surface(self):
        """Including the spinner. A child that names no background draws on
        the terminal's default, which showed as a black cell beside the
        message."""
        cd.run_connecting(self.panel, "Asking SynologyNas for its shares…",
                          lambda cancel: "x", lambda *a: None)
        self.panel.render()
        rows = [(y, line) for y, line in enumerate(self.backend.snapshot())
                if "Asking SynologyNas" in line]
        self.assertEqual(len(rows), 1)
        y, line = rows[0]
        start = line.index("│") + 1
        backgrounds = {self.backend._styles[y][x].bg
                       for x in range(start, start + 24)}
        self.assertNotIn(None, backgrounds, f"a hole in {line!r}")
        self.assertEqual(len(backgrounds), 1, f"not one surface: {line!r}")

    def test_the_busy_modal_shows_what_it_is_waiting_for(self):
        """It showed a title, a blank line and "Esc stop waiting": the box was
        one row short, so the spinner and the message were painted over by the
        hint band's rule (issue #406)."""
        cd.run_connecting(self.panel, "Asking SynologyNas for its shares…",
                          lambda cancel: "x", lambda *a: None)
        shown, lines = self._shows("Asking SynologyNas")
        self.assertTrue(shown, "\n".join(lines))

    def test_the_checkboxes_sit_on_the_dialog_surface(self):
        """A control drawn with no background takes the terminal's default on
        a grid backend, which on this dialog read as a black bar behind each
        checkbox label. The widget is told what it sits on; this checks it
        arrived."""
        cd.show_connect_form(self.panel, cd.ConnectRequest(address="smb://nas/x"))
        self.panel.render()
        rows = [(y, line) for y, line in enumerate(self.backend.snapshot())
                if "Save password" in line or "Save this server" in line]
        self.assertEqual(len(rows), 2)
        for y, line in rows:
            start = line.index("[")
            backgrounds = {self.backend._styles[y][x].bg
                           for x in range(start, start + len("[x] Save password"))}
            self.assertNotIn(None, backgrounds, f"a hole in row {y}: {line!r}")
            self.assertEqual(len(backgrounds), 1, "the row is not one surface")

    def test_the_picker_draws(self):
        entries = [ServerEntry("NAS Photo", "smb://nas/photo", "me"),
                   ServerEntry("Work", "smb://work/share", origin=CONFIG)]
        mounts = [netmount.MountInfo("/Volumes/photo", netmount.NETWORK,
                                     "//me@nas/photo", "smbfs")]
        with patch("xefm.server_list.get_servers", return_value=entries), \
             patch.object(netmount, "list_mounts", return_value=mounts):
            cd.ConnectFlow(self.panel, on_connected=lambda p, n: None).open()
        self.panel.render()


class BusyModalOnARealPanel(unittest.TestCase):
    """The threaded path, on the memory backend: the modal goes up, the worker
    runs beside it, and the result is delivered on the main thread by the
    animation tick — the same shape ``xefm.task`` uses."""

    def setUp(self):
        from puikit.backends import create_backend
        from puikit.panel import Panel

        self.backend = create_backend("memory")
        self.backend.open()
        self.panel = Panel(self.backend)
        self.panel.set_text_effect(False)
        self.addCleanup(self.backend.close)

    def _pump(self, seen, timeout=3.0):
        deadline = time.monotonic() + timeout
        while not seen and time.monotonic() < deadline:
            self.backend.run_animation_ticks()
            time.sleep(0.005)

    def test_the_modal_is_up_while_the_work_runs_and_gone_after(self):
        started, release, seen = threading.Event(), threading.Event(), []

        def work(cancel):
            started.set()
            release.wait(2.0)
            return "/Volumes/photo"

        cd.run_connecting(self.panel, "Connecting to nas…", work,
                          lambda r, e, c: seen.append((r, e, c)))
        self.assertTrue(started.wait(2.0))
        self.panel.render()  # the modal draws without a live app around it
        self.assertEqual(len(self.panel._layers), 1)
        release.set()
        self._pump(seen)
        self.assertEqual(seen, [("/Volumes/photo", None, False)])
        self.assertEqual(len(self.panel._layers), 0)

    def test_escape_cancels_the_wait(self):
        seen = []

        def work(cancel):
            cancel.wait(2.0)
            raise netmount.MountError("Cancelled.")

        cd.run_connecting(self.panel, "Connecting to nas…", work,
                          lambda r, e, c: seen.append(c))
        self.panel.render()
        layer = self.panel._layers[0]
        layer.widget.handle_event(Event(type=EventType.KEY, key="escape"))
        self._pump(seen)
        self.assertEqual(seen, [True])


class InlineFallback(unittest.TestCase):
    """A backend that drives no animation ticks — the still backend the tests
    use — has nothing to pump the busy dialog or service Esc, so the work runs
    inline instead of behind a modal that could never close."""

    def test_the_work_runs_and_reports(self):
        seen = []
        cd.run_connecting(_Panel(), "Connecting…",
                          lambda cancel: "/Volumes/photo",
                          lambda result, error, cancelled: seen.append(
                              (result, error, cancelled)))
        self.assertEqual(seen, [("/Volumes/photo", None, False)])

    def test_a_failure_is_reported_rather_than_raised(self):
        seen = []
        boom = netmount.MountError("nope")
        cd.run_connecting(_Panel(), "Connecting…",
                          lambda cancel: (_ for _ in ()).throw(boom),
                          lambda result, error, cancelled: seen.append(error))
        self.assertEqual(seen, [boom])


if __name__ == "__main__":
    unittest.main()

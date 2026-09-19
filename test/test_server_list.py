"""The saved-server list: the config/state merge, and what "forget" means.

No state database and no keychain are involved — both are faked — so these run
as fast as the rest of the suite and leave nothing behind on the machine.
"""

import unittest
from unittest.mock import patch

from xefm import netmount, server_list


class _FakeState:
    """The two ``StateManager`` methods this module uses, over a dict."""

    def __init__(self, rows=None):
        self.store = {server_list._STATE_KEY: list(rows or [])}

    def get_state(self, key, default=None):
        return self.store.get(key, default)

    def set_state(self, key, value):
        self.store[key] = value
        return True


class ServerListTest(unittest.TestCase):
    def setUp(self):
        self.state = _FakeState()
        self.config_rows = []
        self.forgotten = []
        for target, value in (
                ("get_state_manager", lambda: self.state),
                ("get_network_servers", lambda: self.config_rows)):
            patcher = patch.object(server_list, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(netmount, "forget_password",
                               lambda t, u: self.forgotten.append((t.url, u)))
        patcher.start()
        self.addCleanup(patcher.stop)

    # --- the merge ----------------------------------------------------------

    def test_an_empty_list_is_empty(self):
        self.assertEqual(server_list.get_servers(), [])

    def test_config_rows_come_first(self):
        self.config_rows = [{"name": "Work", "url": "smb://work/share", "user": ""}]
        server_list.save_server("Home NAS", "smb://nas/photo", "me")
        names = [e.name for e in server_list.get_servers()]
        self.assertEqual(names, ["Work", "Home NAS"])

    def test_a_config_row_cannot_be_forgotten(self):
        self.config_rows = [{"name": "Work", "url": "smb://work/share", "user": ""}]
        entry = server_list.get_servers()[0]
        self.assertFalse(entry.removable)
        self.assertFalse(server_list.forget_server(entry))
        self.assertEqual(len(server_list.get_servers()), 1)

    def test_a_saved_row_can_be_forgotten_along_with_its_password(self):
        server_list.save_server("NAS", "smb://nas/photo", "me")
        entry = server_list.get_servers()[0]
        self.assertTrue(entry.removable)
        self.assertTrue(server_list.forget_server(entry))
        self.assertEqual(server_list.get_servers(), [])
        self.assertEqual(self.forgotten, [("smb://nas/photo", "me")])

    def test_the_same_server_in_both_places_appears_once(self):
        server_list.save_server("NAS", "smb://nas/photo", "me")
        self.config_rows = [{"name": "Promoted", "url": "smb://NAS/photo/",
                             "user": "me"}]
        entries = server_list.get_servers()
        self.assertEqual([e.name for e in entries], ["Promoted"])
        self.assertEqual(entries[0].origin, server_list.CONFIG)

    def test_the_same_server_typed_in_two_cases_is_one_row(self):
        server_list.save_server("NAS", "smb://SynologyNAS/Videos", "me")
        server_list.save_server("NAS again", "smb://synologynas/Videos", "me")
        entries = server_list.get_servers()
        self.assertEqual(len(entries), 1)
        # ...and the row shows the address as most recently typed, not folded.
        self.assertEqual(entries[0].url, "smb://synologynas/Videos")

    def test_the_case_the_user_typed_survives_being_saved(self):
        server_list.save_server("NAS", "smb://SynologyNAS/Videos", "me")
        self.assertEqual(server_list.get_servers()[0].url,
                         "smb://SynologyNAS/Videos")

    def test_saving_something_the_config_already_has_is_declined(self):
        """Otherwise the state DB keeps a shadow copy that outlives the config
        entry it was hiding behind."""
        self.config_rows = [{"name": "Work", "url": "smb://work/share", "user": ""}]
        self.assertFalse(server_list.save_server("Work", "smb://work/share"))
        self.assertEqual(self.state.store[server_list._STATE_KEY], [])

    def test_saving_again_moves_a_server_to_the_top(self):
        server_list.save_server("A", "smb://nas/a")
        server_list.save_server("B", "smb://nas/b")
        server_list.save_server("A", "smb://nas/a", "me")
        entries = server_list.get_servers()
        self.assertEqual([e.name for e in entries], ["A", "B"])
        self.assertEqual(entries[0].user, "me")

    def test_a_row_without_a_url_is_ignored(self):
        self.state.store[server_list._STATE_KEY] = [
            {"name": "broken"}, "nonsense", {"url": "smb://nas/ok"}]
        entries = server_list.get_servers()
        self.assertEqual([e.url for e in entries], ["smb://nas/ok"])
        # No name given -> named after the address rather than hidden.
        self.assertEqual(entries[0].name, "smb://nas/ok")

    def test_an_unparseable_address_is_still_listed(self):
        """A typo in the config is something the user has to be able to see in
        order to fix."""
        self.config_rows = [{"name": "Typo", "url": "smb:/nas/photo", "user": ""}]
        entry = server_list.get_servers()[0]
        self.assertIsNone(entry.target)
        self.assertEqual(entry.name, "Typo")

    # --- matching a row to a live mount --------------------------------------

    def test_a_mounted_share_is_matched_through_the_macos_source(self):
        entry = server_list.ServerEntry("NAS", "smb://nas/photo")
        mounts = [netmount.MountInfo("/Volumes/photo", netmount.NETWORK,
                                     "//me@NAS/Photo", "smbfs")]
        self.assertEqual(server_list.mounted_at(entry, mounts), "/Volumes/photo")

    def test_a_mounted_share_is_matched_through_the_windows_source(self):
        entry = server_list.ServerEntry("NAS", "smb://nas/photo")
        mounts = [netmount.MountInfo("\\\\nas\\photo", netmount.NETWORK,
                                     "\\\\nas\\photo", "smb")]
        self.assertEqual(server_list.mounted_at(entry, mounts), "\\\\nas\\photo")

    def test_a_bonjour_address_matches_a_mount_reported_without_local(self):
        entry = server_list.ServerEntry("NAS", "smb://SynologyNas.local/Videos")
        mounts = [netmount.MountInfo("/Volumes/Videos", netmount.NETWORK,
                                     "//crftwr@synologynas/Videos", "smbfs")]
        self.assertEqual(server_list.mounted_at(entry, mounts), "/Volumes/Videos")

    def test_another_share_on_the_same_server_is_not_a_match(self):
        entry = server_list.ServerEntry("NAS", "smb://nas/backup")
        mounts = [netmount.MountInfo("/Volumes/photo", netmount.NETWORK,
                                     "//me@nas/photo", "smbfs")]
        self.assertEqual(server_list.mounted_at(entry, mounts), "")

    def test_a_local_volume_is_never_a_match(self):
        entry = server_list.ServerEntry("NAS", "smb://nas/photo")
        mounts = [netmount.MountInfo("/Volumes/photo", netmount.REMOVABLE,
                                     "/dev/disk4s1", "apfs")]
        self.assertEqual(server_list.mounted_at(entry, mounts), "")


class ConfigReading(unittest.TestCase):
    """``NETWORK_SERVERS`` as ``xefm.config`` validates it."""

    def _servers(self, value):
        from xefm import config as config_module

        class _Cfg:
            NETWORK_SERVERS = value

        with patch.object(config_module, "get_config", return_value=_Cfg()):
            return config_module.get_network_servers()

    def test_a_full_entry(self):
        rows = self._servers([{"name": "NAS", "url": "smb://nas/photo",
                               "user": "me"}])
        self.assertEqual(rows, [{"name": "NAS", "url": "smb://nas/photo",
                                 "user": "me"}])

    def test_the_url_names_a_row_that_has_no_name(self):
        rows = self._servers([{"url": "smb://nas/photo"}])
        self.assertEqual(rows[0]["name"], "smb://nas/photo")

    def test_entries_without_a_url_are_dropped(self):
        self.assertEqual(self._servers([{"name": "nope"}, 42, None]), [])

    def test_a_password_in_the_config_is_ignored(self):
        """There is no field for one, and honouring it quietly would make the
        config file a place people keep passwords."""
        rows = self._servers([{"name": "NAS", "url": "smb://nas/photo",
                               "password": "hunter2"}])
        self.assertEqual(set(rows[0]), {"name", "url", "user"})

    def test_an_unset_setting_is_an_empty_list(self):
        self.assertEqual(self._servers(None), [])


if __name__ == "__main__":
    unittest.main()

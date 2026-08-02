"""
Tests for the --backend web startup notice (SSH tunneling instructions).

Run with: python -m pytest test/test_web_tunnel_message.py -v
"""

import unittest
from unittest import mock

from xefm.app import _web_access_message


class TestWebAccessMessage(unittest.TestCase):
    URL = "http://127.0.0.1:54321/"

    def test_mentions_served_url(self):
        self.assertIn(self.URL, _web_access_message(self.URL))

    def test_tunnel_command_uses_served_port(self):
        # Both ends of the forward carry the real port, so the printed URL
        # works unchanged in the remote machine's browser.
        self.assertIn("ssh -N -L 54321:127.0.0.1:54321 ",
                      _web_access_message(self.URL))

    def test_tunnel_command_targets_current_user_and_host(self):
        with mock.patch("xefm.app.getpass.getuser", return_value="alice"), \
             mock.patch("xefm.app.socket.gethostname", return_value="devbox"):
            self.assertIn("alice@devbox", _web_access_message(self.URL))

    def test_placeholder_when_user_unknown(self):
        # getpass.getuser() raises when the environment names no user; the
        # notice must still print, with a placeholder to edit.
        with mock.patch("xefm.app.getpass.getuser", side_effect=OSError):
            self.assertIn("USER@HOST", _web_access_message(self.URL))


if __name__ == "__main__":
    unittest.main()

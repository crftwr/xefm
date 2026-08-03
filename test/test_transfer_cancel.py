"""
Test cancelling an in-flight remote transfer (GitHub issue #131).

A remote copy is a single call into S3 or SFTP, so the byte-progress callback is
the only thread of control that comes back often enough to notice a cancel.
Raising from it has to unwind the transfer and reach the caller unchanged,
rather than being relabelled as a copy failure.

Run with: python -m pytest test/test_transfer_cancel.py -v
"""

import tempfile
import unittest
from unittest.mock import Mock, patch

from xefm.path import Path
from xefm.s3 import clear_s3_cache
from xefm.ssh_connection import (SSHConnection, SSHPermissionDeniedError,
                                 _TransferMonitor)
from xefm.task import Cancelled, Task


class TestS3TransferCancel(unittest.TestCase):
    """Cancelling a local <-> S3 copy from the progress callback"""

    def setUp(self):
        clear_s3_cache()
        self.temp_dir = tempfile.mkdtemp()
        self.content = b"x" * 4096
        self.local_file = Path(self.temp_dir) / "payload.bin"
        self.local_file.write_bytes(self.content)

        self.client = Mock()
        self.client.list_objects_v2.return_value = {'KeyCount': 0}
        self.client.head_object.return_value = {'ContentLength': len(self.content)}

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        clear_s3_cache()

    @patch('xefm.s3.boto3')
    def test_download_cancel_reaches_caller_unchanged(self, mock_boto3):
        """Cancelled from the callback is not folded into OSError"""
        mock_boto3.client.return_value = self.client

        def fake_download(Bucket, Key, Fileobj, Callback=None, **kwargs):
            for offset in range(0, len(self.content), 1024):
                Fileobj.write(self.content[offset:offset + 1024])
                Callback(1024)

        self.client.download_fileobj.side_effect = fake_download

        def cancel_after_one_chunk(copied, total):
            if copied > 0:
                raise Cancelled()

        dest = Path(self.temp_dir) / "downloaded.bin"
        with self.assertRaises(Cancelled):
            Path("s3://bucket/payload.bin").copy_to(
                dest, overwrite=True, progress_callback=cancel_after_one_chunk)

    @patch('xefm.s3.boto3')
    def test_cancelled_download_leaves_no_partial_file(self, mock_boto3):
        """A cancelled download does not leave a stub on disk"""
        mock_boto3.client.return_value = self.client

        def fake_download(Bucket, Key, Fileobj, Callback=None, **kwargs):
            Fileobj.write(self.content[:1024])
            Callback(1024)
            Fileobj.write(self.content[1024:])

        self.client.download_fileobj.side_effect = fake_download

        def cancel_after_one_chunk(copied, total):
            if copied > 0:
                raise Cancelled()

        dest = Path(self.temp_dir) / "downloaded.bin"
        with self.assertRaises(Cancelled):
            Path("s3://bucket/payload.bin").copy_to(
                dest, overwrite=True, progress_callback=cancel_after_one_chunk)

        self.assertFalse(dest.exists(),
                         "cancelled download should not be left on disk")

    @patch('xefm.s3.boto3')
    def test_upload_cancel_reaches_caller_unchanged(self, mock_boto3):
        """Same for the upload direction"""
        mock_boto3.client.return_value = self.client

        def fake_upload(Fileobj, Bucket, Key, Callback=None, **kwargs):
            Fileobj.read()
            Callback(1024)
            Callback(1024)

        self.client.upload_fileobj.side_effect = fake_upload

        def cancel_after_one_chunk(copied, total):
            if copied > 0:
                raise Cancelled()

        with self.assertRaises(Cancelled):
            self.local_file.copy_to(Path("s3://bucket/payload.bin"), overwrite=True,
                                    progress_callback=cancel_after_one_chunk)

    @patch('xefm.s3.boto3')
    def test_genuine_failure_is_still_an_oserror(self, mock_boto3):
        """Guarding the callback must not stop real errors becoming OSError"""
        mock_boto3.client.return_value = self.client
        self.client.upload_fileobj.side_effect = ValueError("bad bucket")

        with self.assertRaises(OSError):
            self.local_file.copy_to(Path("s3://bucket/payload.bin"), overwrite=True,
                                    progress_callback=lambda copied, total: None)


class _FakeProcess:
    """Stands in for the sftp subprocess"""

    def __init__(self, alive=True):
        self._alive = alive
        self.killed = False

    def poll(self):
        return None if self._alive else 0

    def kill(self):
        self.killed = True
        self._alive = False


class TestTransferMonitor(unittest.TestCase):
    """The SFTP transfer monitor: reporting, cancelling, and probe failures"""

    def setUp(self):
        self.logger = Mock()

    def test_reports_empty_bar_on_start(self):
        updates = []
        monitor = _TransferMonitor(lambda: 0, 2048, lambda c, t: updates.append((c, t)),
                                   0.01, self.logger)
        monitor.start(_FakeProcess())
        monitor.stop()
        self.assertEqual(updates[0], (0, 2048))

    def test_reports_probe_values_while_running(self):
        sizes = iter([512, 1024, 1536, 2048])
        updates = []

        def probe():
            try:
                return next(sizes)
            except StopIteration:
                return 2048

        monitor = _TransferMonitor(probe, 2048, lambda c, t: updates.append((c, t)),
                                   0.01, self.logger)
        process = _FakeProcess()
        monitor.start(process)
        while len(updates) < 4:
            pass
        monitor.stop()
        self.assertEqual(updates[:4], [(0, 2048), (512, 2048), (1024, 2048), (1536, 2048)])

    def test_probe_overshoot_is_clamped(self):
        """A remote size larger than expected must not push the bar past full"""
        updates = []
        monitor = _TransferMonitor(lambda: 999999, 2048,
                                   lambda c, t: updates.append((c, t)), 0.01, self.logger)
        monitor.start(_FakeProcess())
        while len(updates) < 2:
            pass
        monitor.stop()
        self.assertEqual(updates[1], (2048, 2048))

    def test_callback_exception_kills_the_transfer(self):
        """Cancelling stops sftp instead of letting it run to completion"""
        def callback(copied, total):
            if copied > 0:
                raise Cancelled()

        monitor = _TransferMonitor(lambda: 512, 2048, callback, 0.01, self.logger)
        process = _FakeProcess()
        monitor.start(process)
        while not process.killed:  # let the sampling thread reach its first probe
            pass
        monitor.stop()

        self.assertTrue(process.killed, "cancelling should stop the sftp process")
        self.assertIsInstance(monitor.error, Cancelled)

    def test_cancel_at_the_very_start_never_starts_sampling(self):
        """A task already cancelled when the transfer begins stops immediately"""
        def callback(copied, total):
            raise Cancelled()

        monitor = _TransferMonitor(lambda: 0, 2048, callback, 0.01, self.logger)
        process = _FakeProcess()
        monitor.start(process)
        monitor.stop()

        self.assertTrue(process.killed)
        self.assertIsInstance(monitor.error, Cancelled)

    def test_failing_probe_does_not_kill_a_healthy_transfer(self):
        """A remote hiccup while sampling must not abort the copy"""
        def probe():
            raise OSError("stat failed")

        updates = []
        monitor = _TransferMonitor(probe, 2048, lambda c, t: updates.append((c, t)),
                                   0.01, self.logger)
        process = _FakeProcess()
        monitor.start(process)
        monitor.stop()

        self.assertFalse(process.killed)
        self.assertIsNone(monitor.error)
        self.assertEqual(updates, [(0, 2048)])  # only the initial empty bar

    def test_finish_reports_completion(self):
        updates = []
        monitor = _TransferMonitor(lambda: 0, 2048, lambda c, t: updates.append((c, t)),
                                   10.0, self.logger)
        monitor.start(_FakeProcess())
        monitor.stop()
        monitor.finish()
        self.assertEqual(updates[-1], (2048, 2048))

    def test_finish_is_silent_after_a_cancel(self):
        """A cancelled transfer must not report itself complete"""
        def callback(copied, total):
            raise Cancelled()

        monitor = _TransferMonitor(lambda: 0, 2048, callback, 10.0, self.logger)
        monitor.start(_FakeProcess())
        monitor.stop()
        monitor.finish()  # must not raise, must not report 100%
        self.assertIsInstance(monitor.error, Cancelled)


class TestRemoteSizeProbe(unittest.TestCase):
    """The remote size probe used for upload progress"""

    def setUp(self):
        self.conn = SSHConnection("myhost", {})

    def _run_probe(self, stdout, remote_path="/remote/file.bin"):
        with patch('xefm.ssh_connection.subprocess.run') as run:
            run.return_value = Mock(stdout=stdout, stderr="", returncode=0)
            size = self.conn._remote_size(remote_path)
            return size, run.call_args[0][0]

    def test_parses_size(self):
        size, _ = self._run_probe("4096\n")
        self.assertEqual(size, 4096)

    def test_missing_file_reports_zero(self):
        """The remote file does not exist until the upload creates it"""
        size, _ = self._run_probe("0\n")
        self.assertEqual(size, 0)

    def test_empty_output_reports_zero(self):
        size, _ = self._run_probe("")
        self.assertEqual(size, 0)

    def test_runs_over_the_existing_control_master(self):
        """No new SSH session: the probe rides the multiplexed connection"""
        _, argv = self._run_probe("1\n")
        self.assertIn(f"ControlPath={self.conn._control_path}", argv)
        self.assertIn("ControlMaster=no", argv)
        self.assertIn("myhost", argv)

    def test_remote_path_is_shell_quoted(self):
        """A path is interpolated into a remote shell command, so it must be
        quoted against spaces and command substitution"""
        import shlex

        hostile = "/remote/a b/$(touch pwned).bin"
        _, argv = self._run_probe("1\n", hostile)
        command = argv[-1]

        # The shell must see the path as one literal word, not as a word to
        # split and a command to run
        self.assertIn(hostile, shlex.split(command))
        self.assertNotIn("$(touch", shlex.split(command))


class TestSSHTransferWiring(unittest.TestCase):
    """read_file/write_file attach a monitor watching the right file"""

    def setUp(self):
        self.conn = SSHConnection("myhost", {})
        self.conn._connected = True
        self.updates = []
        self.conn.set_progress_callback(
            lambda copied, total: self.updates.append((copied, total)))
        self.content = b"y" * 4096

    def test_download_watches_the_local_temp_file(self):
        """sftp fills a local temp file, so its size on disk is the byte count"""
        captured = {}

        def fake_exec(commands, timeout=None, monitor=None):
            # Emulate the real _execute_sftp_command's contract with the monitor
            captured['monitor'] = monitor
            monitor.start(_FakeProcess())
            try:
                # 'get "<remote>" "<tmp>"' - destination is the last quoted path
                tmp_path = commands[0].rsplit('"', 2)[1]
                with open(tmp_path, 'wb') as f:
                    f.write(self.content[:2048])
                    f.flush()
                    captured['probe_at_half'] = monitor._probe()
                    f.write(self.content[2048:])
            finally:
                monitor.stop()
            return ("", "", 0)

        self.conn.stat = Mock(return_value={'size': len(self.content)})
        self.conn._execute_sftp_command = fake_exec

        data = self.conn.read_file("/remote/payload.bin")

        self.assertEqual(data, self.content)
        self.assertIsNotNone(captured['monitor'])
        # The probe measures real bytes on disk, not a guess
        self.assertEqual(captured['probe_at_half'], 2048)
        self.assertEqual(self.updates, [(0, 4096), (4096, 4096)])

    def test_upload_watches_the_remote_file(self):
        """The source is already complete, so the byte count is the remote size"""
        captured = {}

        def fake_exec(commands, timeout=None, monitor=None):
            captured['monitor'] = monitor
            monitor.start(_FakeProcess())
            monitor.stop()
            return ("", "", 0)

        self.conn._execute_sftp_command = fake_exec
        self.conn._remote_size = Mock(return_value=1234)

        self.conn.write_file("/remote/payload.bin", self.content)

        self.assertEqual(captured['monitor']._probe(), 1234)
        self.conn._remote_size.assert_called_with("/remote/payload.bin")
        self.assertEqual(self.updates, [(0, 4096), (4096, 4096)])

    def test_cancelled_download_raises_cancelled_not_ssh_error(self):
        """The killed sftp process returns non-zero; the cancel must win"""
        def fake_exec(commands, timeout=None, monitor=None):
            monitor.error = Cancelled()
            return ("", "Killed", -9)

        self.conn.stat = Mock(return_value={'size': len(self.content)})
        self.conn._execute_sftp_command = fake_exec

        with self.assertRaises(Cancelled):
            self.conn.read_file("/remote/payload.bin")

    def test_cancelled_upload_raises_cancelled_not_ssh_error(self):
        def fake_exec(commands, timeout=None, monitor=None):
            monitor.error = Cancelled()
            return ("", "Killed", -9)

        self.conn._execute_sftp_command = fake_exec

        with self.assertRaises(Cancelled):
            self.conn.write_file("/remote/payload.bin", self.content)

    def test_genuine_download_failure_is_still_an_ssh_error(self):
        """Cancellation handling must not mask real transfer errors"""
        def fake_exec(commands, timeout=None, monitor=None):
            return ("", "Permission denied", 1)

        self.conn.stat = Mock(return_value={'size': len(self.content)})
        self.conn._execute_sftp_command = fake_exec

        with self.assertRaises(SSHPermissionDeniedError):
            self.conn.read_file("/remote/payload.bin")

    def test_no_monitor_when_nobody_is_watching(self):
        """Without a progress callback there is nothing to sample"""
        captured = {}

        def fake_exec(commands, timeout=None, monitor=None):
            captured['monitor'] = monitor
            return ("", "", 0)

        self.conn.set_progress_callback(None)
        self.conn._execute_sftp_command = fake_exec
        self.conn._remote_size = Mock()

        self.conn.write_file("/remote/payload.bin", self.content)

        self.assertIsNone(captured['monitor'])
        self.conn._remote_size.assert_not_called()


class TestRemoteProgressCheckpoint(unittest.TestCase):
    """file_operations wires cancellation into the byte-progress callback"""

    def test_forwards_progress_until_cancelled(self):
        from xefm.file_operations import FileOperationService

        task = Task("copy")
        prog = Mock()
        report = FileOperationService._remote_progress(task, prog)

        report(512, 2048)
        prog.update_file_byte_progress.assert_called_once_with(512, 2048, None)

        task.request_cancel()
        with self.assertRaises(Cancelled):
            report(1024, 2048)


if __name__ == '__main__':
    unittest.main()

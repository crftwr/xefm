"""
Test that cancelling an S3 upload aborts promptly instead of being retried.

XeFM cancels a remote transfer by raising from the progress callback. For an
S3 upload that callback fires while botocore is reading the request body, and
botocore wraps any exception raised there in its *retryable* HTTPClientError —
so a cancel used to be retried like a network blip by every in-flight
multipart part, max_attempts times with backoff ("Cancelling…" that never
ends). The fix makes _CallbackAbort subclass concurrent.futures.CancelledError,
the one exception botocore's HTTP layer re-raises unwrapped and never retries.

These tests run the real boto3/s3transfer/botocore stack with only the HTTP
transport faked (a fake *client* would bypass exactly the machinery under
test), and pin: a cancel raises out of the upload without any part being
re-attempted, the multipart upload is aborted on S3, and copy_to() hands the
caller back their own exception.

Run with: python -m pytest test/test_s3_upload_cancel.py -v
"""

import io
import time
import email.utils
import threading
import unittest
from concurrent.futures import CancelledError

import boto3
from botocore.config import Config
from botocore.awsrequest import AWSResponse
from botocore.exceptions import HTTPClientError

from xefm.path import Path, _CallbackAbort, _guard_progress
from xefm.s3 import S3PathImpl
from xefm.task import Cancelled

MB = 1024 * 1024


class _FakeRaw:
    """Response body holder with the .stream() interface AWSResponse reads."""

    def __init__(self, body):
        self._body = body

    def stream(self, *args, **kwargs):
        yield self._body


class FakeS3Transport:
    """Stand-in for botocore's URLLib3Session.send, with the same exception
    contract: the request body is drained in chunks (which is what fires the
    s3transfer progress callbacks), CancelledError raised while reading it is
    re-raised as-is, and anything else is wrapped in the retryable
    HTTPClientError — exactly like botocore/httpsession.py. Records every
    part-upload attempt so a retried cancel shows up as attempts > 1."""

    UPLOAD_ID = 'FAKEUPLOADID123'

    def __init__(self):
        self.lock = threading.Lock()
        self.put_attempts = {}   # part number (or 'put_object') -> attempts
        self.aborted = False
        self.completed = False

    def _record_attempt(self, name):
        with self.lock:
            self.put_attempts[name] = self.put_attempts.get(name, 0) + 1

    def _response(self, url, status, headers, body=b''):
        headers = dict(headers)
        headers.setdefault('Date', email.utils.formatdate(usegmt=True))
        headers.setdefault('Content-Length', str(len(body)))
        return AWSResponse(url, status, headers, _FakeRaw(body))

    def send(self, request):
        try:
            url = request.url
            method = request.method
            if method == 'PUT':
                if 'partNumber=' in url:
                    self._record_attempt(url.split('partNumber=')[1].split('&')[0])
                else:
                    self._record_attempt('put_object')

            body = request.body
            if body is not None and hasattr(body, 'read'):
                while True:
                    chunk = body.read(8192)
                    if not chunk:
                        break

            if method == 'POST' and 'uploads' in url:
                xml = (f'<?xml version="1.0"?><InitiateMultipartUploadResult>'
                       f'<Bucket>b</Bucket><Key>k</Key>'
                       f'<UploadId>{self.UPLOAD_ID}</UploadId>'
                       f'</InitiateMultipartUploadResult>').encode()
                return self._response(url, 200, {'Content-Type': 'application/xml'}, xml)
            if method == 'PUT':
                return self._response(url, 200, {'ETag': '"abc123"'})
            if method == 'POST' and 'uploadId=' in url:
                self.completed = True
                xml = (b'<?xml version="1.0"?><CompleteMultipartUploadResult>'
                       b'<Location>x</Location><Bucket>b</Bucket>'
                       b'<Key>k</Key><ETag>"done"</ETag>'
                       b'</CompleteMultipartUploadResult>')
                return self._response(url, 200, {'Content-Type': 'application/xml'}, xml)
            if method == 'DELETE' and 'uploadId=' in url:
                self.aborted = True
                return self._response(url, 204, {})
            return self._response(url, 200, {}, b'')
        except CancelledError:
            raise  # same contract as botocore httpsession.py
        except Exception as e:
            raise HTTPClientError(error=e)


def make_s3_path(transport, uri='s3://test-bucket/video.mp4'):
    """Path over a real boto3 client whose HTTP transport is the fake.

    Retries are pinned so a regression is detected by the attempt counters in
    seconds rather than inheriting whatever max_attempts the machine's
    ~/.aws/config sets (a retried cancel at max_attempts = 100 runs for
    minutes to hours)."""
    client = boto3.client(
        's3',
        region_name='us-east-1',
        aws_access_key_id='FAKE',
        aws_secret_access_key='FAKE',
        config=Config(retries={'max_attempts': 3, 'mode': 'standard'}),
    )
    client._endpoint.http_session.send = transport.send
    path = Path(uri)
    path._impl._s3_client = client
    return path


def cancelling_callback():
    """Progress callback that behaves like a cancel requested mid-transfer:
    the priming (0, total) call passes, every call reporting real bytes raises
    Cancelled — the deterministic equivalent of task.checkpoint() after Esc."""
    def report(bytes_copied, bytes_total):
        if bytes_copied > 0:
            raise Cancelled()
    return report


class TestCallbackAbortContract(unittest.TestCase):

    def test_callback_abort_is_cancelled_error(self):
        # Load-bearing: botocore's HTTP layer re-raises CancelledError
        # unwrapped and its retry logic never retries it; any other base
        # class turns a cancel into a retryable HTTPClientError.
        self.assertTrue(issubclass(_CallbackAbort, CancelledError))


class TestS3UploadCancel(unittest.TestCase):

    def test_cancel_aborts_multipart_upload_without_retries(self):
        transport = FakeS3Transport()
        path = make_s3_path(transport)
        size = 24 * MB  # 3 parts at boto3's default 8MB chunk size
        started = time.monotonic()

        with self.assertRaises(_CallbackAbort) as ctx:
            path._impl.upload_from_stream(
                io.BytesIO(b'\0' * size), size,
                _guard_progress(cancelling_callback()))

        self.assertIsInstance(ctx.exception.original, Cancelled)
        self.assertTrue(transport.put_attempts)
        self.assertEqual(set(transport.put_attempts.values()), {1},
                         f'cancel was retried: {transport.put_attempts}')
        self.assertTrue(transport.aborted,
                        'multipart upload left dangling on S3')
        self.assertFalse(transport.completed)
        # Backstop against the original symptom: a retried cancel backs off
        # for minutes even with retries pinned to 3 attempts.
        self.assertLess(time.monotonic() - started, 30)

    def test_cancel_single_put_without_retries(self):
        transport = FakeS3Transport()
        path = make_s3_path(transport)
        size = 1 * MB  # below the multipart threshold: a single PutObject

        with self.assertRaises(_CallbackAbort):
            path._impl.upload_from_stream(
                io.BytesIO(b'\0' * size), size,
                _guard_progress(cancelling_callback()))

        self.assertEqual(transport.put_attempts, {'put_object': 1})

    def test_upload_completes_without_cancel(self):
        # Sanity for the fake transport itself: with no cancel, the same
        # multipart upload runs to completion, so a green cancel test can't
        # hide behind a broken fake.
        transport = FakeS3Transport()
        path = make_s3_path(transport)
        size = 24 * MB
        seen = []

        sent = path._impl.upload_from_stream(
            io.BytesIO(b'\0' * size), size,
            _guard_progress(lambda copied, total: seen.append(copied)))

        self.assertEqual(sent, size)
        self.assertTrue(transport.completed)
        self.assertFalse(transport.aborted)
        self.assertEqual(sorted(transport.put_attempts), ['1', '2', '3'])
        self.assertEqual(max(seen), size)


class TestCopyToCancel(unittest.TestCase):

    def test_cancel_unwinds_copy_to_as_the_callers_exception(self):
        # End to end through Path.copy_to: the caller's exception must come
        # back as itself (file_operations catches it as Cancelled), not folded
        # into the OSError every transfer failure becomes.
        import tempfile
        transport = FakeS3Transport()
        dest = make_s3_path(transport)
        with tempfile.NamedTemporaryFile(suffix='.mp4') as src_file:
            src_file.write(b'\0' * 9 * MB)  # 2 parts: multipart, but cheap
            src_file.flush()

            with self.assertRaises(Cancelled):
                Path(src_file.name).copy_to(
                    dest, overwrite=True,
                    progress_callback=cancelling_callback())

        self.assertEqual(set(transport.put_attempts.values()), {1})
        self.assertTrue(transport.aborted)


if __name__ == '__main__':
    unittest.main()

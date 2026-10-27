"""Reject wrong or truncated remote objects before accepting an upload."""
import hashlib
import io
import tempfile
import unittest
from pathlib import Path

from upload_cloud import verify, upload_part_with_retry
from unittest.mock import Mock


class RemoteObject:
    def __init__(self, data, digest):
        self.data = data
        self.digest = digest
        self.corrupt_range = False
        self.ignore_range = False
        self.reads = 0

    def head_object(self, **kwargs):
        return {'ContentLength': len(self.data), 'Metadata': {'sha256': self.digest}}

    def get_object(self, Range, **kwargs):
        self.reads += 1
        start, end = map(int, Range.removeprefix('bytes=').split('-'))
        data = self.data[start:end + 1]
        if self.corrupt_range:
            data = data[:-1]
        return {'ContentRange': '' if self.ignore_range else f'bytes {start}-{end}/{len(self.data)}',
                'Body': io.BytesIO(data)}


class UploadIntegrity(unittest.TestCase):
    def test_retries_closed_request_without_changing_part_and_stops_on_forbidden(self):
        class ServiceError(Exception):
            def __init__(self, status):
                self.response = {'ResponseMetadata': {'HTTPStatusCode': status}}
        client = Mock()
        client.upload_part.side_effect = [ServiceError(499), {'ETag': 'checked'}]
        parameters = {'PartNumber': 7, 'Body': b'unchanged', 'ContentMD5': 'digest'}
        self.assertEqual(upload_part_with_retry(client, sleep=lambda _: None, **parameters), {'ETag': 'checked'})
        self.assertEqual(client.upload_part.call_args_list[0], client.upload_part.call_args_list[1])
        client.reset_mock()
        client.upload_part.side_effect = ServiceError(403)
        with self.assertRaises(ServiceError):
            upload_part_with_retry(client, sleep=lambda _: None, **parameters)
        self.assertEqual(client.upload_part.call_count, 1)
        client.reset_mock()
        client.upload_part.side_effect = ServiceError(499)
        with self.assertRaises(ServiceError):
            upload_part_with_retry(client, sleep=lambda _: None, **parameters)
        self.assertEqual(client.upload_part.call_count, 6)

    def test_checks_actual_bytes_and_rejects_wrong_metadata_or_range(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.pack'
            data = bytes(range(256)) * 1000
            path.write_bytes(data)
            digest = hashlib.sha256(data).hexdigest()
            remote = RemoteObject(data, digest)
            verify(remote, path, 'bucket', 'file', len(data), digest)
            self.assertEqual(remote.reads, 3)
            remote.digest = 'different'
            with self.assertRaisesRegex(ValueError, 'refusing overwrite'):
                verify(remote, path, 'bucket', 'file', len(data), digest)
            self.assertEqual(remote.reads, 3)
            remote.digest = digest
            remote.corrupt_range = True
            with self.assertRaisesRegex(ValueError, 'differs'):
                verify(remote, path, 'bucket', 'file', len(data), digest)
            remote.corrupt_range = False
            remote.ignore_range = True
            with self.assertRaisesRegex(ValueError, 'Invalid verification range'):
                verify(remote, path, 'bucket', 'file', len(data), digest)


if __name__ == '__main__':
    unittest.main()

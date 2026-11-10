import copy
import json
from pathlib import Path
import tempfile
import unittest
from merged_asset import read_container, write_container


class MergedContainerTests(unittest.TestCase):
    def test_large_container_preserves_every_binary_byte(self):
        data = bytes(range(251)) * 4
        doc = dict(asset={'version': '2.0'}, buffers=[{'byteLength': len(data)}], extras={'test': True})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for kind, limit in [('glb', 2**32), ('gltf', 100)]:
                out = root / kind
                out.mkdir()
                binary = out / 'model.bin.tmp'
                binary.write_bytes(data)
                asset = write_container(out, copy.deepcopy(doc), binary, glb_limit=limit)
                parsed, payload, offset, digest, total = read_container(out / asset['file'])
                with payload.open('rb') as stream:
                    stream.seek(offset)
                    self.assertEqual(stream.read(len(data)), data)
                parsed['buffers'][0].pop('uri', None)
                self.assertEqual(parsed, doc)
                self.assertEqual(total, asset['bytes'])
                self.assertEqual(len(digest), 64)
            (root / 'gltf/model.bin').write_bytes(data[:-1])
            with self.assertRaisesRegex(ValueError, 'buffer length'):
                read_container(root / 'gltf/model.gltf')

    def test_external_buffer_cannot_escape_release(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'model.gltf'
            path.write_text(json.dumps({'buffers': [{'uri': '../private.bin', 'byteLength': 0}]}))
            with self.assertRaisesRegex(ValueError, 'local model.bin'):
                read_container(path)


if __name__ == '__main__':
    unittest.main()

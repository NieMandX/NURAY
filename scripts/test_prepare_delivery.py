import gzip
import hashlib
import json
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from prepare_delivery import runtime_catalog, validation_summary, compressed_file, prepare


class DeliveryTests(unittest.TestCase):
    def test_external_merged_scene_preserves_header_and_binary(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); source = root / 'scene'; (source / 'merged').mkdir(parents=True)
            (source / 'tileset.json').write_text('{"tiles":[]}')
            (source / 'merged/metadata.json').write_text('{"asset":{"file":"model.gltf"}}')
            header = b'{"buffers":[{"uri":"model.bin","byteLength":8}]}'
            binary = b'geometry'
            (source / 'merged/model.gltf').write_bytes(header)
            (source / 'merged/model.bin').write_bytes(binary)
            with contextlib.redirect_stdout(io.StringIO()):
                result = prepare(source, root / 'delivery')
            for key, expected in [('merged', header), ('mergedBuffer', binary)]:
                spec = result[key]
                self.assertEqual(gzip.decompress((root / spec['url']).read_bytes()), expected)
                self.assertEqual(spec['decodedSha256'], hashlib.sha256(expected).hexdigest())

    def test_preserves_runtime_geometry_and_original_provenance(self):
        original = {'geometryRevision': {'previous': 'large history'}, 'sourceChunks': [1, 2],
                    'tiles': [{'instances': [{'id': 42, 'transform': [1, 2, 3]}]}],
                    'chunks': [{'sha256': 'pin', 'file': 'unchanged.bin.gz'}], 'materials': ['water']}
        compact = runtime_catalog(original)
        self.assertEqual(compact, {k: original[k] for k in ('tiles', 'chunks', 'materials')})
        self.assertIn('geometryRevision', original)
        self.assertEqual(validation_summary({'passed': True, 'transportClearance': {
            'fullWidth': {'passed': True}, 'source': {'interfaces': 5, 'corridors': [{}, {}]}}})
            ['transportClearance']['source'], {'interfaces': 5, 'corridorCount': 2})

    def test_full_round_trip_and_immutable_output(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'source'; path.write_bytes(b'geometry' * 100000)
            target = Path(d) / 'model.glb.gz'
            record = compressed_file(path, target, 'release/model.glb.gz')
            self.assertEqual(gzip.decompress(target.read_bytes()), path.read_bytes())
            self.assertEqual(record['decodedSha256'], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(record['bytes'], target.stat().st_size)
            for proof in record['rangeProofs']:
                data = target.read_bytes()[proof['offset']:proof['offset'] + proof['bytes']]
                self.assertEqual(hashlib.sha256(data).hexdigest(), proof['sha256'])
            with self.assertRaises(ValueError):
                compressed_file(path, target, record['url'])


if __name__ == '__main__':
    unittest.main()

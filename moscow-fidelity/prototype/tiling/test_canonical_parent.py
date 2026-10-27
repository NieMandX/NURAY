import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from canonical_parent import load_parent


class ParentSharingTests(unittest.TestCase):
    def read(self, parent, current, compressed=False):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'city.json'
            raw = json.dumps(parent, ensure_ascii=False).encode()
            if compressed:
                Path(str(path) + '.gz').write_bytes(gzip.compress(raw))
            else:
                path.write_bytes(raw)
            return load_parent(path, current)

    def test_unchanged_arrays_and_nested_values_share_storage(self):
        current = {'surfaces': [{'id': 'a', 'geometry': [[1., 2., 3.]]}],
                   'objectLayer': {'instances': [1, 2]}, 'name': 'Петербург'}
        parent = self.read(current, current, compressed=True)
        self.assertEqual(parent, current)
        self.assertIs(parent['surfaces'], current['surfaces'])
        self.assertIs(parent['objectLayer'], current['objectLayer'])

    def test_reordered_rows_reuse_only_exact_matches(self):
        old = {'surfaces': [{'id': 'a', 'height': 1}, {'id': 'b', 'height': 2},
                            {'id': 'removed', 'height': 3}], 'oldField': True}
        current = {'surfaces': [{'id': 'new', 'height': 4}, {'id': 'b', 'height': 2},
                               {'id': 'a', 'height': 9}], 'newField': None}
        parent = self.read(old, current)
        self.assertEqual(parent, old)
        self.assertIs(parent['surfaces'][1], current['surfaces'][1])
        self.assertIsNot(parent['surfaces'][0], current['surfaces'][2])
        self.assertNotIn('newField', parent)

    def test_scalar_arrays_empty_arrays_and_different_types(self):
        old = {'a': [None, False, 2.5, 'x'], 'b': [], 'c': {'v': [1]}, 'd': 3}
        current = {'a': ['x', 3], 'b': [1], 'c': None, 'd': []}
        self.assertEqual(self.read(old, current), old)

    def test_numeric_types_are_not_silently_replaced(self):
        old = {'rows': [{'id': 'x', 'v': 1}, {'id': 'y', 'v': 1.0}]}
        current = {'rows': [{'id': 'x', 'v': True}, {'id': 'y', 'v': 1}]}
        parent = self.read(old, current)
        self.assertIs(type(parent['rows'][0]['v']), int)
        self.assertIs(type(parent['rows'][1]['v']), float)
        self.assertIsNot(parent['rows'], current['rows'])

    def test_byte_proven_fast_path_and_unexpected_change(self):
        old = {'rows': [{'id': 'x', 'v': 1}], 'revision': {'number': 1}}
        current = {'rows': [{'id': 'x', 'v': 1}], 'revision': {'number': 2}, 'added': True}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'city.json'
            path.write_text(json.dumps(old, ensure_ascii=False, separators=(',', ':')))
            with patch('canonical_parent.value_from_events', side_effect=AssertionError('Unexpected fallback')):
                parent = load_parent(path, current, changed_keys=('revision', 'added'))
            self.assertEqual(parent, old)
            self.assertIs(parent['rows'], current['rows'])
            current['rows'][0]['v'] = 99
            # The fast-path hash must fail. The fallback reads the real parent,
            # so the existing revision comparison can detect this corruption.
            parent = load_parent(path, current, changed_keys=('revision', 'added'))
            self.assertEqual(parent, old)
            self.assertIsNot(parent['rows'][0], current['rows'][0])


if __name__ == '__main__':
    unittest.main()

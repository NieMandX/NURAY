import gzip
import gc
import io
import unittest
from collections import defaultdict
from unittest.mock import patch
from types import SimpleNamespace
import numpy as np
import shapely as sh
import checkpoint_stream as codec
from geometry_pickle import dump


class CheckpointStreamTests(unittest.TestCase):
    def test_cycle_collector_state_restored_without_changing_checkpoint_bytes(self):
        enabled = gc.isenabled()
        try:
            expected = io.BytesIO(); codec.save.__wrapped__(*self.fixture(), expected, batch_size=8)
            for initial in (True, False):
                (gc.enable if initial else gc.disable)()
                actual = io.BytesIO()
                codec.save(*self.fixture(), actual, batch_size=8)
                self.assertEqual(gc.isenabled(), initial)
                self.assertEqual(actual.getvalue(), expected.getvalue())
                actual.seek(0); self.compare(self.fixture(), codec.load(actual))
                self.assertEqual(gc.isenabled(), initial)
                with patch.object(codec, 'dump', side_effect=OSError('simulated disk error')):
                    with self.assertRaises(OSError):codec.save(*self.fixture(), io.BytesIO())
                self.assertEqual(gc.isenabled(), initial)
                with self.assertRaises(EOFError):codec.load(io.BytesIO())
                self.assertEqual(gc.isenabled(), initial)
        finally:
            (gc.enable if enabled else gc.disable)()

    def fixture(self):
        plane = np.array([.01, -.03, 145.])
        polygon = sh.set_precision(sh.box(.003, .007, 2.001, 3.002), .001)
        rows = [dict(id=f'surface:{i}', poly=polygon, plane=plane) for i in range(19)]
        groups = defaultdict(list, {('land', 2): [np.arange(9).reshape(3, 3) + i for i in range(23)]})
        return dict(surfaces=rows, groups=groups, shading_flags={('land', 2): [True, False] * 12},
                    other=dict(bounds=[0, 0, 10000, 10000]), empty=[]), dict(stage='surfaces', roads=polygon)

    def compare(self, expected, actual):
        before, inputs = expected
        after, restored = actual
        self.assertEqual(list(before), list(after))
        for old, new in zip(before['surfaces'], after['surfaces'], strict=True):
            self.assertEqual(old['id'], new['id'])
            self.assertEqual(sh.to_wkb(old['poly']), sh.to_wkb(new['poly']))
            self.assertEqual(sh.get_precision(new['poly']), .001)
            np.testing.assert_array_equal(old['plane'], new['plane'])
        self.assertIs(after['groups'].default_factory, list)
        for old, new in zip(before['groups'][('land', 2)], after['groups'][('land', 2)], strict=True):
            np.testing.assert_array_equal(old, new)
        for key in ('other', 'empty', 'shading_flags'):
            self.assertEqual(before[key], after[key])
        self.assertEqual(inputs['stage'], restored['stage'])
        self.assertEqual(sh.to_wkb(inputs['roads']), sh.to_wkb(restored['roads']))
        self.assertEqual(sh.get_precision(restored['roads']), .001)

    def test_bounded_batches_and_lossless_values(self):
        expected = self.fixture()
        calls = []
        def inspect(value, stream):
            if isinstance(value, list):
                calls.append(len(value))
            dump(value, stream)
        stream = io.BytesIO()
        with patch.object(codec, 'dump', inspect):
            codec.save(*expected, stream, batch_size=8)
        self.assertLessEqual(max(calls), 8)
        stream.seek(0)
        self.compare(expected, codec.load(stream))

    def test_legacy_checkpoint(self):
        expected = self.fixture(); stream = io.BytesIO()
        dump(expected, stream); stream.seek(0)
        self.compare(expected, codec.load(stream))

    def test_gzip_roundtrip(self):
        expected = self.fixture(); stream = io.BytesIO()
        with gzip.GzipFile(fileobj=stream, mode='wb') as compressed:
            codec.save(*expected, compressed, batch_size=8)
        stream.seek(0)
        with gzip.GzipFile(fileobj=stream, mode='rb') as compressed:
            self.compare(expected, codec.load(compressed))

    def test_incomplete_checkpoint_rejected(self):
        stream = io.BytesIO(); codec.save(*self.fixture(), stream, batch_size=8)
        with self.assertRaises((EOFError, __import__('pickle').UnpicklingError)):
            codec.load(io.BytesIO(stream.getvalue()[:-20]))

    def test_legacy_identity_repair_retains_road_witness(self):
        from region_checkpoint import restore_surface_identity
        curb = dict(id='surface:3', kind='curb_top', owner='land:a')
        road = dict(id='surface:3', kind='roadbed_flat', owner='road:a')
        state = SimpleNamespace(surfaces=[curb, road], relationships=[
            dict(type='road-paint-witness', parent='surface:3', sourceObject='road:a')])
        restore_surface_identity(state)
        self.assertEqual(road['id'], 'surface:3')
        self.assertEqual(curb['id'], 'surface:4')
        self.assertEqual(state._surface_id_counter, 5)
        self.assertEqual(state.relationships[0]['parent'], road['id'])
        self.assertEqual(state.relationships[1]['parent'], curb['id'])


if __name__ == '__main__':
    unittest.main()

"""Large-region builds can omit optional GLBs without altering their inputs."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from object_geometry import export_glb


class DeferredExportTests(unittest.TestCase):
    def test_surface_geometry_is_identical_without_monolith(self):
        import build
        import json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            source.mkdir()
            (source / 'plan.json').write_text(json.dumps({'name': 'fixture'}))
            triangles = {('land', 1): [[[2125., 8070., 145.], [2126., 8070., 145.], [2125., 8071., 145.]]]}
            reference = root / 'reference/full'
            deferred = root / 'deferred/full'
            with patch.object(build, 'SOURCE', source), patch.dict(os.environ, NURAY_DEFER_CANONICAL_GLB='0'):
                a = build.export(reference, triangles)
            with patch.object(build, 'SOURCE', source), patch.dict(os.environ, NURAY_DEFER_CANONICAL_GLB='1'):
                b = build.export(deferred, triangles)
            self.assertGreater(a['glbBytes'], 0)
            self.assertEqual(b['glbBytes'], 0)
            for filename in ('scene.json', 'mesh-000.bin.gz'):
                self.assertEqual((reference / filename).read_bytes(), (deferred / filename).read_bytes())

    def test_canonical_export_only_is_deferred(self):
        scene = dict(chunks=[], instances=[], materials=[], textures={}, origin=[0, 0, 0])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            canonical = root / 'canonical/full'
            canonical.mkdir(parents=True)
            marker = canonical / 'mesh.bin.gz'
            marker.write_bytes(b'retained canonical geometry')
            with patch.dict(os.environ, NURAY_DEFER_CANONICAL_GLB='0'):
                size = export_glb(scene, canonical)
                original = (canonical / 'model.glb').read_bytes()
                self.assertEqual(size, len(original))
            with patch.dict(os.environ, NURAY_DEFER_CANONICAL_GLB='1'):
                self.assertEqual(export_glb(scene, canonical), 0)
                self.assertFalse((canonical / 'model.glb').exists())
                self.assertEqual(marker.read_bytes(), b'retained canonical geometry')
                library = root / 'library'
                library.mkdir()
                self.assertEqual(export_glb(scene, library), size)
                self.assertEqual((library / 'model.glb').read_bytes(), original)


if __name__ == '__main__':
    unittest.main()

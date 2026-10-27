from pathlib import Path
import tempfile
import unittest
from support_assets import copy_support_assets


class SupportAssetsTest(unittest.TestCase):
    def test_revision_preserves_libraries_and_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)/'base';output=Path(folder)/'output'
            wanted=['library/approved-index.json','library/birch/model.glb','textures/atlas.png',
                    'fence-library/preview.png','street-objects.json','canonical/terrain.npz',
                    'canonical/street-source-evidence.json.gz']
            stale=['canonical/validation.json','canonical/urban-model.json','canonical/transport-metadata.json']
            for name in wanted+stale:
                p=base/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(name.encode())
            (output/'canonical').mkdir(parents=True)
            (output/'canonical/validation.json').write_text('new verdict')
            copy_support_assets(base,output)
            for name in wanted:self.assertEqual((output/name).read_bytes(),(base/name).read_bytes())
            self.assertEqual((output/'canonical/validation.json').read_text(),'new verdict')
            self.assertFalse((output/'canonical/urban-model.json').exists())
            self.assertFalse((output/'canonical/transport-metadata.json').exists())
            copy_support_assets(base,output)  # An unpublished version can be repaired safely.

    def test_in_place_copy_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):copy_support_assets(folder,folder)


if __name__=='__main__':unittest.main()

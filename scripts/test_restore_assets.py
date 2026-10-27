"""Check packed restoration against real files, including corrupt ranges."""
import hashlib
import tempfile
import unittest
from pathlib import Path
from restore_assets import unpack, valid

class PackedRestore(unittest.TestCase):
    def test_restores_exact_files_and_skips_existing_pack_download(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);chunks=[b'first compressed block',b'second block\x00\xff']
            data=b''.join(chunks);(root/'meshes.pack').write_bytes(data)
            pack={'path':'meshes.pack','bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
            rows=[];offset=0
            for i,chunk in enumerate(chunks):
                rows.append({'path':f'meshes/{i}.bin.gz','bytes':len(chunk),'sha256':hashlib.sha256(chunk).hexdigest(),'pack':{'path':'meshes.pack','offset':offset}})
                offset+=len(chunk)
            unpack(rows,pack,root,'http://invalid.test/')
            self.assertTrue(all(valid(row,root) for row in rows))
            # A restored project works without downloading the pack again.
            (root/'meshes.pack').unlink()
            unpack(rows,pack,root,'http://invalid.test/')
            # A bad mapping must never replace a valid destination.
            (root/'meshes.pack').write_bytes(data)
            (root/'meshes/1.bin.gz').unlink()
            rows[1]['pack']['offset']=0
            with self.assertRaisesRegex(ValueError,'checksum mismatch'):
                unpack(rows,pack,root,'http://invalid.test/')
            self.assertFalse((root/'meshes/1.bin.gz').exists())
            self.assertTrue(valid(rows[0],root))
            rows[1]['pack']['offset']=len(data)
            with self.assertRaisesRegex(ValueError,'Invalid packed range'):
                unpack(rows,pack,root,'http://invalid.test/')

if __name__=='__main__':unittest.main()

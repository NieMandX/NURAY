import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from canonical_store import copy_asset


class StageCopies(unittest.TestCase):
    def check_copy(self,disabled):
        with tempfile.TemporaryDirectory(prefix='nuray-stage-copy-') as folder:
            root=Path(folder);source=root/'parent';source.mkdir()
            a=source/'mesh with spaces.bin';a.write_bytes(bytes(range(256))*4096)
            with patch.dict(os.environ,{'NURAY_DISABLE_CLONES':disabled}):
                shutil.copytree(source,root/'child',copy_function=copy_asset)
            b=root/'child'/a.name
            self.assertEqual(a.read_bytes(),b.read_bytes())
            with b.open('r+b') as f:f.write(b'child')
            self.assertNotEqual(a.read_bytes()[:5],b'child')
            with a.open('r+b') as f:f.seek(20);f.write(b'parent')
            self.assertNotEqual(b.read_bytes()[20:26],b'parent')

    def test_platform_copy_is_independent(self):self.check_copy('0')
    def test_fallback_copy_is_independent(self):self.check_copy('1')


if __name__=='__main__':unittest.main()

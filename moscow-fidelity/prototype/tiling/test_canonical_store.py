import gc,io,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from canonical_store import dump_compact,save_canonical,load_canonical,canonical_digest,JsonRows,copy_asset,_clone_asset
import hashlib
import sys


class CanonicalStorage(unittest.TestCase):
    def test_asset_copies_preserve_bytes_metadata_and_independent_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'источник.bin';destination=Path(folder)/'copy.bin'
            original=bytes(range(256))*1024
            source.write_bytes(original);source.chmod(0o640)
            os.utime(source,ns=(1500000000123456789,1500000000987654321))
            stat=source.stat()
            with patch('subprocess.run',side_effect=AssertionError('Asset copy must not fork')):
                copy_asset(source,destination)
            self.assertEqual(destination.read_bytes(),original)
            self.assertEqual(destination.stat().st_mode,stat.st_mode)
            self.assertEqual(destination.stat().st_mtime_ns,stat.st_mtime_ns)
            self.assertNotEqual(source.stat().st_ino,destination.stat().st_ino)
            with destination.open('r+b') as file:file.write(b'new')
            self.assertEqual(source.read_bytes(),original)
            with source.open('r+b') as file:file.write(b'old')
            self.assertEqual(destination.read_bytes(),b'new'+original[3:])

    @unittest.skipUnless(sys.platform=='darwin','Native APFS clone check')
    def test_native_clone_is_available_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source';destination=Path(folder)/'target'
            source.write_bytes(b'exact source')
            if not _clone_asset(source,destination):self.skipTest('Temporary filesystem does not support cloning')
            self.assertEqual(destination.read_bytes(),b'exact source')
            self.assertFalse(_clone_asset(source,destination))
            self.assertEqual(destination.read_bytes(),b'exact source')

    def test_unsupported_clone_and_disabled_clone_keep_copy2_semantics(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'source';destination=Path(folder)/'target'
            source.write_bytes(b'first')
            with patch('canonical_store._clone_asset',return_value=False):copy_asset(source,destination)
            self.assertEqual(destination.read_bytes(),b'first')
            source.write_bytes(b'second')
            with patch('canonical_store._clone_asset',side_effect=AssertionError('Existing path must use copy2')):
                copy_asset(source,destination)
            self.assertEqual(destination.read_bytes(),b'second')
            destination.unlink()
            with patch.dict(os.environ,NURAY_DISABLE_CLONES='1'),patch('canonical_store._clone_asset',side_effect=AssertionError('Cloning disabled')):
                copy_asset(source,destination)
            self.assertEqual(destination.read_bytes(),b'second')

    def test_reader_restores_collector_after_success_and_failures(self):
        original=gc.isenabled()
        class Watched(io.BytesIO):
            def read(self,*args):
                self_test.assertFalse(gc.isenabled())
                return super().read(*args)
            def readinto(self,*args):
                self_test.assertFalse(gc.isenabled())
                return super().readinto(*args)
            def close(self):
                self_test.assertFalse(gc.isenabled())
                return super().close()
        self_test=self
        try:
            for enabled in (True,False):
                (gc.enable if enabled else gc.disable)()
                with patch('canonical_store.open_canonical',return_value=Watched(b'{"ok":1}')):
                    self.assertEqual(load_canonical('unused'),{'ok':1})
                self.assertEqual(gc.isenabled(),enabled)
                with patch('canonical_store.open_canonical',return_value=Watched(b'{"cut":')):
                    with self.assertRaises(ValueError):load_canonical('unused')
                self.assertEqual(gc.isenabled(),enabled)
                with patch('canonical_store.open_canonical',side_effect=OSError('input unavailable')):
                    with self.assertRaises(OSError):load_canonical('unused')
                self.assertEqual(gc.isenabled(),enabled)
        finally:
            (gc.enable if original else gc.disable)()

    def test_large_registry_read_is_bounded_and_preserves_values(self):
        value={'surfaces':[{'id':f'surface:{i}', 'heightPlane':[i*.1,-0.0,1e-20],
                           'name':'Берёза', 'valid':True} for i in range(30000)]}
        raw=json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()
        class Bounded(io.BytesIO):
            def read(self,size=-1):
                if size<0:raise AssertionError('Unbounded canonical read')
                return super().read(size)
        with patch('canonical_store.open_canonical',return_value=Bounded(raw)):
            actual=load_canonical('unused')
        self.assertEqual(json.dumps(actual,ensure_ascii=False,separators=(',',':')).encode(),raw)
        first,second=actual['surfaces'][:2]
        self.assertIs(next(iter(first)),next(iter(second)))

    def test_streaming_read_keeps_large_integer_semantics_and_rejects_trailing_data(self):
        for raw in (b'{"id":18446744073709551616}',b'{"empty":null}'):
            with patch('canonical_store.open_canonical',return_value=io.BytesIO(raw)):
                self.assertEqual(load_canonical('unused'),json.loads(raw))
        for raw in (b'{"ok":1} {"extra":2}', b'{"cut":', b''):
            with patch('canonical_store.open_canonical',return_value=io.BytesIO(raw)):
                with self.assertRaises(ValueError):load_canonical('unused')

    def test_derived_rows_are_streamed_in_bounded_batches(self):
        for count in (0,1,4096,4097,8200):
            produced=[];writes=[]
            def rows():
                for i in range(count):
                    produced.append(i)
                    yield {'id':i,'name':'Ель','xyz':[i*.1,0.,-1.]}
            class Sink(io.StringIO):
                def write(self,text):
                    if text.startswith('{"id":'):writes.append(len(produced))
                    return super().write(text)
            value={'surfaces':JsonRows(rows()),'after':True}
            self.assertEqual(produced,[])
            out=Sink();dump_compact(value,out)
            expected={'surfaces':list(rows()),'after':True}
            self.assertEqual(out.getvalue(),json.dumps(expected,ensure_ascii=False,separators=(',',':')))
            self.assertEqual(writes,[min(start+4096,count) for start in range(0,count,4096)])

    def test_serialized_provenance_bytes_are_unchanged(self):
        rows=[{'id':i,'coordinates':[[i*.1,-0.0,1e-20]],'name':'Берёза "A"\n'} for i in range(8200)]
        value={'surfaces':rows,'objectLayer':{'placements':rows},'empty':[],
            'flags':(True,False,None),'numericKeys':{2:'x',False:'y',None:'z'}}
        out=io.StringIO();dump_compact(value,out)
        self.assertEqual(out.getvalue(),json.dumps(value,ensure_ascii=False,separators=(',',':')))

    def test_compression_switch_cannot_read_stale_sibling(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'urban-model.json'
            for compressed,revision in [('0',1),('1',2),('0',3)]:
                value={'revision':revision,'name':'Петербург'}
                with patch.dict(os.environ,NURAY_COMPRESS_CANONICAL=compressed):save_canonical(path,value)
                self.assertEqual(load_canonical(path),value)
                expected=json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()
                self.assertEqual(canonical_digest(path),hashlib.sha256(expected).hexdigest())
                self.assertEqual(path.exists(),compressed=='0')
                self.assertEqual(Path(str(path)+'.gz').exists(),compressed=='1')


if __name__=='__main__':unittest.main()

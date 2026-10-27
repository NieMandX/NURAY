import io,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from canonical_store import dump_compact,save_canonical,load_canonical,canonical_digest,JsonRows
import hashlib


class CanonicalStorage(unittest.TestCase):
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

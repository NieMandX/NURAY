"""The large-registry writer must preserve the established serialized format."""
import io,json
from prepare_transport import dump_registry

def test_batched_registry_is_byte_identical():
    row={'id':'2ГИС:дорога','heightPlane':[0.1,-1e-9,145.0],
         'geometry':{'type':'Polygon','coordinates':[[[1,2],[3,4],[1,2]]]},
         'optional':None,'passed':True}
    registry={'sourceSnapshot':{'freshAcquisition':True},'surfaces':[row]*19,
              'empty':[],'small':[1,2],'tail':{'nested':[row]*5}}
    expected=json.dumps(registry,ensure_ascii=False,separators=(',',':'))
    for size in [1,3,19,4096]:
        output=io.StringIO();dump_registry(registry,output,size)
        assert output.getvalue()==expected
        assert json.loads(output.getvalue())==registry

if __name__=='__main__':
    test_batched_registry_is_byte_identical()
    print('Transport registry: byte-identical batches passed')

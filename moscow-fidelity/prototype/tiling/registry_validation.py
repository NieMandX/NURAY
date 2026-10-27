"""Compare the independent transport registry without a second city in RAM."""
import gzip,json
from collections.abc import Mapping,Iterator
from itertools import islice
import ijson


def compare_json(stream, expected):
    events=iter(ijson.basic_parse(stream,use_float=True))
    def compare(first,value,path):
        event,actual=first
        if event=='start_map':
            if not isinstance(value,Mapping):raise AssertionError(('Expected object',path))
            seen=set()
            while True:
                kind,key=next(events)
                if kind=='end_map':break
                if kind!='map_key' or key not in value or key in seen:
                    raise AssertionError(('Unexpected or repeated registry key',path,key))
                seen.add(key);compare(next(events),value[key],path+(key,))
            if seen!=set(value):raise AssertionError(('Missing registry fields',path,set(value)-seen))
        elif event=='start_array':
            if isinstance(value,(str,bytes,Mapping)):
                raise AssertionError(('Expected array',path))
            try:rows=iter(value)
            except TypeError:raise AssertionError(('Expected array',path)) from None
            index=0;sentinel=object()
            while True:
                token=next(events)
                if token[0]=='end_array':break
                row=next(rows,sentinel)
                if row is sentinel:raise AssertionError(('Extra registry array item',path,index))
                compare(token,row,path+(index,));index+=1
            if next(rows,sentinel) is not sentinel:raise AssertionError(('Missing registry array items',path,index))
        else:
            kind='null' if value is None else 'boolean' if isinstance(value,bool) else 'string' if isinstance(value,str) else 'number' if isinstance(value,(int,float)) else None
            if event!=kind or actual!=value:raise AssertionError(('Registry value mismatch',path,event,actual,value))
    compare(next(events),expected,())
    if next(events,None) is not None:raise AssertionError('Trailing registry value')


def expected_registry(city,manifest,report):
    sources=[]
    for chunk in manifest['chunks']:
        row={k:chunk[k] for k in ('id','name','triangles')}
        if chunk.get('instanced'):row['instanced']=True
        elif chunk.get('sourceObjectIds'):row['sourceObjectIds']=chunk['sourceObjectIds']
        sources.append(row)
    expected=dict(version=1,sourceChunks=sources,
        features=({k:f[k] for k in ('id','source','layer','properties','semantics')} for f in city['features']))
    for key in ('sourceSnapshot','roadPaint','objectLayer','streetLayer','railwayLayer','landscape','geometryRevision','groundRoadGeometry','tunnelWalls','sourceStyle','sourceStyleChecks','surfaces','relationships','roadNodes','roadInterfaces','gradeConnections','roadSeamRepairs','roadSeamChecks'):
        if key in city:expected[key]=city[key]
    if 'semantics' in report:expected['semantics']=report['semantics']
    return expected


def serialized_parts(expected,batch_size=4096):
    """Bounded C-encoder batches match the transport writer's JSON bytes."""
    encode=lambda value:json.dumps(value,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    yield b'{'
    for index,(key,value) in enumerate(expected.items()):
        if index:yield b','
        yield encode(key)+b':'
        if isinstance(value,(list,Iterator)):
            yield b'[';rows=iter(value);first=True
            while batch:=list(islice(rows,batch_size)):
                if not first:yield b','
                yield encode(batch)[1:-1];first=False
            yield b']'
        else:yield encode(value)
    yield b'}'


def matches_serialized(stream,expected):
    for part in serialized_parts(expected):
        if stream.read(len(part))!=part:return False
    return stream.read(1)==b''


def verify_registry(root,city,manifest,report):
    path=root/'objects.json.gz'
    with gzip.open(path,'rb') as stream:
        identical=matches_serialized(stream,expected_registry(city,manifest,report))
    # Fast byte equality proves every field. Older writers may use whitespace
    # or another key order: retain an independent semantic comparison for them.
    if not identical:
        with gzip.open(path,'rb') as stream:compare_json(stream,expected_registry(city,manifest,report))
    return dict(passed=True,features=len(city['features']),surfaces=len(city['surfaces']),streamed=True,identicalSerialization=identical)

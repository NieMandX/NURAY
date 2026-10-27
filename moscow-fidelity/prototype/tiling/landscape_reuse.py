"""Reuse already verified cell partitions only outside every changed mask.

This is a calculation cache of the current live snapshot, not another source.
The normal release validator still checks the entire freshly serialized output.
"""
import hashlib,io,json,mmap
from collections import defaultdict
import numpy as np
import shapely as sh
from canonical_store import open_canonical


def array_records(path,key,block_size=4*1024*1024):
    """Stream a canonical top-level array without loading a second whole city."""
    if not path.exists():
        import ijson
        with open_canonical(path,'rb') as stream:
            yield from ijson.items(stream,key+'.item',use_float=True)
        return
    marker=('"'+key+'":[').encode()
    with path.open('rb') as stream:
        with mmap.mmap(stream.fileno(),0,access=mmap.ACCESS_READ) as data:
            offset=data.find(marker)
            if offset<0:raise ValueError(('Missing canonical array',key))
        stream.seek(offset+len(marker));reader=io.TextIOWrapper(stream,encoding='utf-8')
        buffer='';position=0;decoder=json.JSONDecoder();finished=False
        while True:
            while position<len(buffer) and buffer[position] in ' \n\r\t,':position+=1
            if position<len(buffer) and buffer[position]==']':return
            if position<len(buffer):
                try:record,end=decoder.raw_decode(buffer,position)
                except json.JSONDecodeError:
                    if finished:raise
                else:
                    yield record;position=end;continue
            if finished:raise ValueError(('Truncated canonical array',key))
            more=reader.read(block_size);finished=not more
            buffer=buffer[position:]+more;position=0



def changed_mask(before,layout):
    pairs=[('raisedGeometry','raised'),('curbGeometry','band'),('railApronGeometry','railApron')]
    differences=[sh.geometry.shape(before.get(key,{'type':'Polygon','coordinates':[]})).symmetric_difference(layout[name])
                 for key,name in pairs]
    # No cut/edge/top-height decision may differ within a reused source cell.
    return sh.union_all(differences).buffer(layout['precision']*5,join_style='mitre')


def prepare(previous,base,city,layout):
    proof=json.loads((previous/'validation.json').read_text());assert proof['passed']
    report=json.loads((previous/'canonical/validation.json').read_text());rev=report['geometryRevision']
    assert rev['type']=='landscape' and rev['parent']==base.name
    assert rev['previousRevision']==city.get('geometryRevision')
    assert rev['terrainSha256']==hashlib.sha256((base/'canonical/terrain.npz').read_bytes()).hexdigest()
    mask=changed_mask(report['landscape'],layout);sh.prepare(mask)
    cache=defaultdict(list)
    for row in array_records(previous/'canonical/urban-model.json','surfaces'):
        role=row.get('landscapeRole')
        if not role:continue
        parent=row['id'].rsplit(':landscape:',1)[0]
        poly=sh.geometry.shape(row['geometry'])
        if not mask.intersects(poly):cache[parent].append((role,poly,np.asarray(row['heightPlane'])))
    return mask,cache,dict(version=1,fromVersion=previous.name,
        validationSha256=hashlib.sha256((previous/'validation.json').read_bytes()).hexdigest(),
        changedMaskM2=mask.area,reusedCells=0,recomputedCells=0,
        policy='Reuse partitions from the validated same-parent live snapshot only where the complete source cell is disjoint from all changed green, curb and rail-apron masks. Revalidate all emitted geometry.')

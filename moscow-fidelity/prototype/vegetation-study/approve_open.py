"""Save the exact live GLB selection, replacing only its central trunk.

Run after build.py --model open and build_editor.py --model open --fragments-only.
The downloaded foliage and branch buffers are never regenerated or simplified.
"""
from pathlib import Path
import argparse,hashlib,json,struct
import numpy as np
import build

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main(input_path,state_path):
    raw=Path(input_path).read_bytes();state=json.loads(Path(state_path).read_text())
    magic,version,total=struct.unpack_from('<4sII',raw)
    assert (magic,version,total)==(b'glTF',2,len(raw))
    json_length,kind=struct.unpack_from('<I4s',raw,12);assert kind==b'JSON'
    doc=json.loads(raw[20:20+json_length]);binary=bytearray(raw[28+json_length:])
    assert doc['extras']['model']=='open' and doc['extras']['foliageMode']=='boolean'
    assert doc['extras']['foliageSettings']==state['settings'] and state['model']=='open'
    primitives=doc['meshes'][0]['primitives'];attributes=primitives[0]['attributes']
    assert all(p['attributes']==attributes for p in primitives)
    def accessor(index):
        a=doc['accessors'][index];v=doc['bufferViews'][a['bufferView']]
        assert 'byteStride' not in v
        dtype={5126:'<f4',5125:'<u4'}[a['componentType']]
        width={'VEC3':3,'SCALAR':1}[a['type']]
        return np.frombuffer(binary,dtype,count=a['count']*width,offset=v.get('byteOffset',0)+a.get('byteOffset',0)).reshape(a['count'],width)
    positions=accessor(attributes['POSITION']);normals=accessor(attributes['NORMAL'])
    count=len(positions)//3;assert len(positions)%3==0 and count==state['triangles']
    materials=np.full(count,-1,dtype=np.int32)
    for p in primitives:
        ix=accessor(p['indices']).reshape(-1,3)
        assert np.array_equal(ix[:,1:],ix[:,:1]+[1,2]) and np.all(ix[:,0]%3==0)
        assert np.all(materials[ix[:,0]//3]==-1)
        materials[ix[:,0]//3]=p['material']
    assert np.all(materials>=0)
    def geometry():
        return np.concatenate([positions,normals,np.zeros((len(positions),2),dtype=np.float32)],axis=1).reshape(count,3,8).copy()
    before=geometry();catalog_path=build.OUT/'catalog.json';catalog=json.loads(catalog_path.read_text())
    row=next(m for m in catalog['models'] if m['id']=='open');palette=catalog['materials']
    old,old_m,_=build.make('open',row['sourceBounds'],round_trunk=False)
    corrected,_,parts=build.make('open',row['sourceBounds'])
    build.validate(corrected,parts)
    trunk=next(p for p in parts if p.get('role')=='trunk');end=trunk['end'];assert trunk['start']==0
    wood=old[old_m>=4];assert len(wood)==state['woodTriangles']
    assert np.array_equal(before[:len(wood),:,:3],wood[:,:,:3].astype(np.float32)), 'Unexpected source wood: do not patch a different model'
    positions[:end*3]=corrected[:end,:,:3].reshape(-1,3)
    normals[:end*3]=corrected[:end,:,3:6].reshape(-1,3)
    after=geometry()
    assert np.array_equal(after[end:],before[end:]),'Only the central trunk may change, including normals'
    assert len(after)==len(before) and len(after)==684
    assert (materials<4).sum()==state['foliageTriangles']
    for index in [attributes['POSITION'],attributes['NORMAL']]:
        a=accessor(index);doc['accessors'][index].update(min=a.min(0).tolist(),max=a.max(0).tolist())
    correction=dict(method='Inscribed circular sections after envelope fitting; thin long principal axis',
        changedTriangles=end,sections=trunk['roundSections'],rootAnchored=True,unchangedFoliageAndBranches=True)
    doc['extras']['trunkCorrection']=correction
    doc['nodes'][0]['name']='Лиственное · сквозистое · выбранная форма'
    j=json.dumps(doc,ensure_ascii=False,separators=(',',':')).encode();j+=b' '*((-len(j))%4)
    patched=struct.pack('<4sII',b'glTF',2,28+len(j)+len(binary))+struct.pack('<I4s',len(j),b'JSON')+j+struct.pack('<I4s',len(binary),b'BIN\0')+binary
    before_folder=build.OUT/'open-selected-before-trunk';folder=build.OUT/'open-approved-01'
    if (folder/'selection.json').exists():
        assert json.loads((folder/'selection.json').read_text())['inputGlbSha256']==sha(input_path),'Existing selection differs; use a new revision'
    before_meta=build.export(before_folder,before,materials,palette)
    (before_folder/'model.glb').write_bytes(raw)
    (before_folder/'selection.json').write_text(json.dumps(state,ensure_ascii=False,indent=2))
    meta=build.export(folder,after,materials,palette)
    (folder/'model.glb').write_bytes(patched)
    assert meta['triangles']==state['triangles'] and meta['bounds']==before_meta['bounds']
    selected=dict(variant=folder.name,folder=folder.name,label='Сквозистое · выбранная форма',
        description='Выбранная в мастерской крона: общий размер 100%, X и Y 200%, Z 100%, повороты 0%, Boolean и упрощение 683%. Центральный ствол сужен до круглых сечений.',
        triangles=meta['triangles'],foliageTriangles=state['foliageTriangles'],woodTriangles=state['woodTriangles'],
        baseFoliageTriangles=state['baseFoliageTriangles'],bounds=meta['bounds'],settings=state['settings'],mode=state['mode'],
        sourceGeometrySha256=sha(build.OUT/'open/geometry.npz'),geometrySha256=sha(folder/'geometry.npz'),glbSha256=sha(folder/'model.glb'),
        inputGlbSha256=sha(input_path),selectedBy='user',date='2026-10-11',integrated=False,trunkCorrection=correction,
        provenance='Exact live GLB foliage and branches; only the 56 central-trunk triangles and their normals replaced by the corrected generator.',
        engines=dict(manifold='3.5.4',meshoptimizer='1.3.0'))
    (folder/'selection.json').write_text(json.dumps(selected,ensure_ascii=False,indent=2))
    choices_path=build.OUT/'choices.json';choices=json.loads(choices_path.read_text());choices['open']=selected
    choices_path.write_text(json.dumps(choices,ensure_ascii=False,indent=2))
    comparison=dict(value=before_folder.name,folder=before_folder.name,label='Выбранная крона · прежний ствол',
        triangles=before_meta['triangles'],bounds=before_meta['bounds'],description='Точная выбранная в мастерской форма до исправления овальных сечений ствола.')
    row['comparisons']=[c for c in row.get('comparisons',[]) if c['value']!=comparison['value']]+[comparison]
    catalog_path.write_text(json.dumps(catalog,ensure_ascii=False,indent=2))
    print(json.dumps({k:selected[k] for k in ['variant','triangles','foliageTriangles','woodTriangles','glbSha256']},indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--glb',required=True);parser.add_argument('--state',required=True)
    args=parser.parse_args();main(args.glb,args.state)

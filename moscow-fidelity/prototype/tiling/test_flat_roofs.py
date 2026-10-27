import json,gzip,tempfile,subprocess,os
from pathlib import Path
import numpy as np
import shapely as sh
from flat_roofs import recessed_cap,encode_faces,eligible_rows,INSET,DEPTH,LEVEL_TOLERANCE,RAISE,PARAPET_HEIGHT,raise_existing

def house(poly,h=10):
    xyz=[]
    for t in sh.constrained_delaunay_triangles(poly).geoms:
        p=np.array(t.exterior.coords)[:3];xyz.append(np.column_stack([p[:,0],np.full(3,h),p[:,1]]))
    for ring in [poly.exterior,*poly.interiors]:
        p=list(ring.coords)
        for a,b in zip(p,p[1:]):
            xyz.extend([[[a[0],0,a[1]],[b[0],0,b[1]],[a[0],h,a[1]]],[[b[0],0,b[1]],[b[0],h,b[1]],[a[0],h,a[1]]]])
    return encode_faces(xyz,4)

shapes=[sh.box(0,0,10,8),sh.Polygon([(0,0),(12,0),(12,4),(4,4),(4,12),(0,12)]),sh.Polygon([(0,0),(20,0),(20,20),(0,20)],holes=[[(5,5),(5,15),(15,15),(15,5)]])]
for poly in shapes:
    original=house(poly);remove,added,records=recessed_cap(original,8)
    assert records and remove.any()
    xyz=added.view('<f4')[:,:,:3].astype(float);mid=added[:,0,6]&0x7fffffff
    center=xyz[mid==8];assert np.allclose(center[:,:,1],10-DEPTH,atol=1e-6)
    center_domain=sh.union_all(sh.polygons(center[:,:,[0,2]]))
    assert center_domain.symmetric_difference(poly.buffer(-INSET,join_style='mitre')).area<1e-4
    n=np.cross(xyz[:,1]-xyz[:,0],xyz[:,2]-xyz[:,0]);horizontal=abs(n[:,1])>1e-5
    assert np.all(n[horizontal,1]>0)
    assert abs(np.linalg.norm(n[~horizontal],axis=1).sum()/2-(center_domain.length*PARAPET_HEIGHT+poly.length*RAISE))<.0001
    # Closed surface at both lips: every recessed floor boundary segment has
    # matching wall edges; no change to facade height or roof outline.
    total=np.concatenate([original[~remove],added]).view('<f4')[:,:,:3]
    assert np.allclose(total.max((0,1)),original.view('<f4')[:,:,:3].max((0,1))+[0,RAISE,0])
    assert abs(sh.union_all(sh.polygons(xyz[horizontal][:,:,[0,2]])).area-poly.area)<.0001
small=house(sh.box(0,0,.7,10));assert not recessed_cap(small,8)[0].any()
stepped=np.concatenate([house(sh.box(0,0,10,10),8),house(sh.box(10,0,20,10),12)])
assert len(recessed_cap(stepped,8)[2])==2
sloped=house(sh.box(0,0,10,10));sloped.view('<f4')[:,:,1]+=sloped.view('<f4')[:,:,0]*.1
assert not recessed_cap(sloped,8)[0].any()
# One continuous roof must not acquire a diagonal parapet just because its
# separately horizontal source triangles differ by a millimetre in height.
for offset in (0,.00049,.00099):
 noisy=house(sh.box(0,0,10,8));p=noisy.view('<f4')[:,:,:3]
 top=np.flatnonzero(np.all(p[:,:,1]==10,axis=1));assert len(top)==2
 for i,delta in zip(top,(offset,offset+.0012)):p[i,:,1]+=delta
 remove,added,records=recessed_cap(noisy,8)
 assert remove[top].all() and len(records)==1 and abs(records[0]['areaM2']-80)<1e-6
 center=added.view('<f4')[(added[:,0,6]&0x7fffffff)==8,:,:3]
 domain=sh.union_all(sh.polygons(center[:,:,[0,2]]))
 assert domain.symmetric_difference(sh.box(0,0,10,8).buffer(-INSET,join_style='mitre')).area<1e-4
 assert records[0]['sourceHeightSpanM']<LEVEL_TOLERANCE
# Real small elevation changes remain distinct; disconnected terraces do not
# get joined by a tolerance chain that spans more than source precision.
close_steps=np.concatenate([house(sh.box(0,0,10,10),10),house(sh.box(10,0,20,10),10.04)])
assert len(recessed_cap(close_steps,8)[2])==2
chain=np.concatenate([house(sh.box(i*10,0,(i+1)*10,10),10+i*.008) for i in range(3)])
assert not recessed_cap(chain,8)[0].any()
rows=[dict(id='body',category='building',sourceBuildingId='123',sourceLayer='Dwelling_house_123',bounds={'min':[0,0,0],'max':[10,10,10]})]
assert 'body' in eligible_rows(rows,[-1,-1,20,20])[0]
assert not eligible_rows(rows+[dict(id='roof',category='building',sourceBuildingId='123',sourceLayer='Dwelling_house_roof_123')],[-1,-1,20,20])[0]
assert not eligible_rows(rows,[-1,-1,5,20])[0]
with tempfile.TemporaryDirectory() as d:
 p=Path(d);source=dict(features=[],surfaces=[],sourceChunks=[{'id':0,'triangles':2}],geometryRevision={'type':'old'},objectLayer={'buildings':rows,'stats':{'ordinaryBuildingObjects':1},'vegetation':[{'id':'keep'}]})
 patch=dict(features=[],surfaces=[],sourceChunks=[{'id':0,'triangles':20}],geometryRevision={'type':'flat-roofs'},objectLayerUpdate={'buildings':[{'id':'body','retainedTriangles':20}],'stats':{'uniqueObjectTriangles':20},'roofs':{'policy':'test'}})
 (p/'in.gz').write_bytes(gzip.compress(json.dumps(source).encode()));(p/'patch.json').write_text(json.dumps(patch))
 subprocess.run([os.environ['NODE'],str(Path(__file__).with_name('restyle_registry.mjs')),str(p/'in.gz'),str(p/'out.gz'),str(p/'patch.json')],check=True)
 result=json.loads(gzip.decompress((p/'out.gz').read_bytes()));assert result['sourceChunks']==patch['sourceChunks']
 assert result['objectLayer']['buildings'][0]['retainedTriangles']==20 and result['objectLayer']['vegetation']==source['objectLayer']['vegetation']
print('Roof fixtures passed: inset/depth, inner wall area, upward winding, concavity, courtyard, stepped caps, narrow/slope/source-roof/boundary exclusions, sparse provenance rewrite.')

# Migrate an old 40 cm rim without moving its roof floor or existing facade.
import flat_roofs
flat_roofs.RAISE=0
for poly in shapes:
 original=house(poly);remove,added,records=recessed_cap(original,8)
 old=np.concatenate([original[~remove],added]);flat_roofs.RAISE=.6
 new=raise_existing(old,records,8)
 floor=(old[:,0,6]&0x7fffffff)==8
 assert np.array_equal(new[:len(old)][floor],old[floor])
 assert np.array_equal(new[:len(original[~remove])],original[~remove])
 assert abs(new.view('<f4')[:,:,1].max()-10.6)<1e-5
 assert np.array_equal(raise_existing(new,records,8,.6),new)
 flat_roofs.RAISE=0
flat_roofs.RAISE=.6
print('Parapet upgrade: fixed floor, unchanged original facade, 1 m height, idempotent.')

"""Rebuild every descent wall/header from canonical inputs into a new version.

Preserve chunk identities for buildings, vegetation instances and railway UVs.
The only allowed changes are retaining structures and pedestrian floor material.
"""
from pathlib import Path
from collections import defaultdict
import argparse,gzip,hashlib,json,shutil,sys
import numpy as np
import shapely as sh
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from build import triangulate,z_at,plane
from tunnel_walls import build
from semantics import classify
from object_geometry import pack,export_glb

WALLS={'tunnel_wall_top','tunnel_wall_bottom','tunnel_wall_side','inferred-walls'}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--base',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--terrain',type=Path,help='Exact shared terrain cache; defaults to base/canonical/terrain.npz')
    args=ap.parse_args();terrain=args.terrain or args.base/'canonical/terrain.npz'
    if args.base.resolve()==args.output.resolve():raise ValueError('Write a separate version')
    folder=args.output/'canonical/full';folder.mkdir(parents=True,exist_ok=True)
    for f in (args.base/'canonical/full').iterdir():shutil.copy2(f,folder/f.name)
    from support_assets import copy_support_assets
    copy_support_assets(args.base,args.output)
    shutil.copy2(terrain,args.output/'canonical/terrain.npz')
    city=json.loads((args.base/'canonical/urban-model.json').read_text());report=json.loads((args.base/'canonical/validation.json').read_text());assert report['passed']
    manifest=json.loads((folder/'scene.json').read_text());origin=np.asarray(city['originMSK'])
    cache=np.load(terrain);assert np.array_equal(cache['bounds'],city['boundsMSK'])
    dem=list(zip(sh.from_wkb(cache['polygons']),cache['planes']));tree=sh.STRtree([p for p,c in dem])
    rows=[{**s,'poly':sh.geometry.shape(s['geometry']),'plane':np.asarray(s['heightPlane'])} for s in city['surfaces']]
    groups=defaultdict(list)
    print('BUILD ALL DESCENT WALLS',len(rows),len(dem),flush=True)
    _,walls=build(rows,city['features'],dem,tree,groups,sh.box(*city['boundsMSK']),1e-5,city['gradeConnections'],city['sourceStyle'],triangulate,z_at,plane)
    print('WALL REPORT',json.dumps({**walls,'groups':[{k:v for k,v in r.items() if k not in ('bandGeometry','portalHeaders')} | {'headers':{k:v for k,v in r['portalHeaders'].items() if k not in ('bandGeometry','openings')}} for r in walls['groups']]}),flush=True)
    if not walls['passed']:raise ValueError('Wall/header validation failed')
    changed=[];preserved=[];material_only=[]
    def raw(c):return gzip.decompress((folder/Path(c['file']).name).read_bytes())
    def write_faces(c,faces):
        xyz=(np.asarray(faces)-origin)[:,:,[0,2,1]]*[1,1,-1]
        n=np.cross(xyz[:,1]-xyz[:,0],xyz[:,2]-xyz[:,0]);lens=np.linalg.norm(n,axis=1)
        keep=lens>1e-9;xyz=xyz[keep];n=n[keep]/lens[keep,None]
        t=np.concatenate([xyz,np.repeat(n[:,None,:],3,axis=1),xyz[:,:,[0,2]]],axis=2)
        meta=pack(t,np.full(len(t),6,dtype=np.uint32),folder/Path(c['file']).name)
        if not meta:raise ValueError('Unexpected empty retaining-wall chunk')
        c.update(meta)
    for name in WALLS:
        chunks=[c for c in manifest['chunks'] if c['name']==name]
        faces=np.asarray(groups[(name,6)])
        for c,part in zip(chunks,np.array_split(faces,len(chunks))):
            changed.append(dict(id=c['id'],name=name,beforeSha256=hashlib.sha256(raw(c)).hexdigest()))
            write_faces(c,part)
    for c in manifest['chunks']:
        if c['name'] in WALLS:continue
        data=raw(c);before=hashlib.sha256(data).hexdigest()
        if c['name'] in {'roadbed_tunnel_descent','roadbed_tunnel'}:
            words=np.frombuffer(data[:c['vertexBytes']],'<u4').reshape(-1,8).copy();mask=(words[:,6]&0x7fffffff)==11
            if np.any(mask):
                words[mask,6]=np.uint32(0x80000000|7)
                with gzip.GzipFile(filename=str(folder/Path(c['file']).name),mode='wb',mtime=0) as f:f.write(words.tobytes()+data[c['vertexBytes']:])
                material_only.append(dict(id=c['id'],name=c['name'],beforeSha256=before,fromMaterial=11,toMaterial=7));continue
        preserved.append(dict(id=c['id'],sha256=before))
    for name in ['portal_guard_top','portal_guard_bottom','portal_guard_side']:
        faces=groups[(name,6)];idx=len(manifest['chunks']);file=f'mesh-{idx:03d}.bin.gz'
        c=dict(id=idx,name=name,category=name,file=file);write_faces(c,faces)
        manifest['chunks'].append(c);manifest['instances'].append(dict(mesh=idx,matrix=[1,0,0,0,0,1,0,0,0,0,1,0]))
    for s in city['surfaces']:
        if s.get('transport')=='pedestrian' and s['kind'] in {'roadbed_tunnel','roadbed_tunnel_descent'}:
            s.update(material=7,surfaceType='pedestrian-paving')
    for f in city['features']:f['semantics']=classify(f['layer'],f['properties'],f['geometryType'])
    city['tunnelWalls']=walls;report['tunnelWalls']=walls;city['rules']['tunnelWalls']=walls['policy']
    city['geometryRevision']=dict(version=1,parent=args.base.name,wallRebuilds=changed,materialRemaps=material_only,preservedChunks=preserved,
        terrainSha256=hashlib.sha256(terrain.read_bytes()).hexdigest(),newChunks=[c['id'] for c in manifest['chunks'] if c['name'].startswith('portal_guard')])
    report['geometryRevision']=city['geometryRevision']
    city['limitations']=[s for s in city['limitations'] if 'Existing rail-entry inferred transverse walls' not in s]
    city['limitations'].append('Portal fascia drop is a 0.5 m construction default, limited to 20% of actual opening depth; source data supplies portal position, not a measured beam section.')
    manifest['stats'].update(uniqueTriangles=sum(c['triangles'] for c in manifest['chunks']),expandedTriangles=sum(manifest['chunks'][i['mesh']]['triangles'] for i in manifest['instances']))
    report['export'].update(triangles=manifest['stats']['uniqueTriangles'],expandedTriangles=manifest['stats']['expandedTriangles'],chunks=len(manifest['chunks']),downloadBytes=sum((folder/Path(c['file']).name).stat().st_size for c in manifest['chunks']))
    (folder/'scene.json').write_text(json.dumps(manifest,ensure_ascii=False,separators=(',',':')));export_glb(manifest,folder)
    report['export']['glbBytes']=(folder/'model.glb').stat().st_size
    (args.output/'canonical/urban-model.json').write_text(json.dumps(city,ensure_ascii=False,separators=(',',':')))
    (args.output/'canonical/validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print('PORTAL VERSION WRITTEN',args.output,flush=True)

if __name__=='__main__':main()

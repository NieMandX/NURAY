"""Add one connected railway UV layer to a validated, immutable city version."""
from pathlib import Path
import argparse,json,shutil
import numpy as np
import shapely as sh
from railway_texture import make_texture
from object_geometry import pack,export_glb
from railway_support import POLICY
from railway_layer import generate, select_input
from canonical_store import load_canonical, save_canonical


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--base',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    if args.base.resolve()==args.output.resolve():raise ValueError('Write a separate version')
    folder=args.output/'canonical/full';folder.mkdir(parents=True,exist_ok=True)
    for file in (args.base/'canonical/full').iterdir():shutil.copy2(file,folder/file.name)
    from support_assets import copy_support_assets
    copy_support_assets(args.base,args.output)
    city=load_canonical(args.base/'canonical/urban-model.json');report=json.loads((args.base/'canonical/validation.json').read_text());assert report['passed']
    manifest=json.loads((folder/'scene.json').read_text());origin=np.asarray(city['originMSK']);x0,y0,x1,y1=city['boundsMSK'];clip=[x0-origin[0],origin[1]-y1,x1-origin[0],origin[1]-y0]
    sources=[f for f in city['features'] if f['layer'] in ('Railroad_line','Railroad_tunnel_line') and f['geometryType']=='polyline']
    name,texture=make_texture(folder);shutil.copy2(folder/name,args.output/'textures'/name)
    bed=len(manifest['materials']);rail=bed+1
    for label,rough,metal in [('Железная дорога · щебень и шпалы',.93,0),('Железная дорога · сталь рельсов',.32,.88)]:
        manifest['materials'].append(dict(name=label,family='railway',color=[.65,.65,.65],roughness=rough,metallic=metal,ior=1.5,kind=1,texture='textures/'+name,alphaCutoff=0))
    # Keep the generic base appearance separate from the explicit rail layer.
    # Proximity alone cannot classify a slab at a multilevel crossing. Retain
    # this distance as diagnostic evidence, never as an automatic material rule.
    axes=sh.union_all([sh.LineString(f['coordinates']) for f in sources]);transport=[s for s in city['surfaces'] if s['material']==12]
    distances=[sh.geometry.shape(s['geometry']).representative_point().distance(axes) for s in transport]
    confirmed=False
    rail_city=select_input({k:city[k] for k in ('boundsMSK','originMSK')},city['features'],iter(city['surfaces']))
    chunks,generated=generate(rail_city,dict(bed=bed,rail=rail))
    stats=generated['stats'];joins=generated['sourceJoints'];rows=generated['edges']
    source_rows={r['source']:r for r in rows}
    for source,tris,mats in chunks:
        idx=len(manifest['chunks']);file=f'mesh-{idx:03d}.bin.gz';meta=pack(tris,mats,folder/file)
        if meta:
            manifest['chunks'].append(dict(id=idx,name='railway',category='railway',file=file,**meta,objectGeometry=True,sourceObjectIds=[source]))
            manifest['instances'].append(dict(mesh=idx,matrix=[1,0,0,0,0,1,0,0,0,0,1,0]))
        source_rows[source]['chunk']=idx if meta else None
    stats['textureBytes']=texture['bytes']
    layer=dict(version=2,heightBinding=POLICY,stats=stats,texture=dict(file='textures/'+name,**texture),edges=rows,sourceJoints=dict(joins),materials=dict(bed=bed,rail=rail),
       baseRestyle=dict(applied=confirmed,maxDistanceToRailAxisM=max(distances,default=0)),waterCrossings=generated['waterCrossings'],
       policy=dict(heightBinding=POLICY,uv='Unwrapped V is accumulated 3D length / 0.6 m on the connected source graph; U is a transported miter cross-section; interpolate all attributes at tile cuts.',
       geometry='3.4 m flat ribbon, two steel material bands, one periodic sleeper; existing source polylines retained, no centreline smoothing.',
       height='Canonical ground + 2 cm, canonical transport floor + 12 cm: a 10 cm ballast layer aligns with the existing 10 cm raised ground; grade-aware endpoint welding.',
       evidence='Source supplies axes and vertical transport surfaces. Rail gauge, width, sleeper size and materials are explicit prototype defaults.',
       loops='Minimum-length spanning forest; each closing edge distributes the correction needed for equal endpoint phase modulo one texture period. Measured sleeper spacing is retained in cycleClosures.'))
    city['railwayLayer']=layer;report['railwayLayer']=dict(passed=True,**stats)
    city['limitations']+=['Railway is a flat texture ribbon, without 3D rail heads or engineered turnout frogs; branches overlap ribbons.', 'Railway source curves are retained as polylines; cyclic closure slightly adjusts sleeper spacing, as recorded per closing edge.', 'Existing rail-entry inferred transverse walls and transport shoulder geometry have not been rebuilt by this texture layer.']
    if layer['waterCrossings']:city['limitations'].append('Ground-class rail axes over water without a source 3D deck use a bank-interpolated ribbon profile. The inferred height is archived per crossing; structural bridge decks/supports are not invented.')
    manifest['textures'][name]=texture
    manifest['stats'].update(uniqueTriangles=sum(c['triangles'] for c in manifest['chunks']),expandedTriangles=sum(manifest['chunks'][i['mesh']]['triangles'] for i in manifest['instances']))
    report['export'].update(triangles=manifest['stats']['uniqueTriangles'],expandedTriangles=manifest['stats']['expandedTriangles'],chunks=len(manifest['chunks']),
        downloadBytes=sum((folder/Path(c['file']).name).stat().st_size for c in manifest['chunks']),
        textureBytes=sum(p.stat().st_size for p in (args.output/'textures').iterdir() if p.is_file()))
    (folder/'scene.json').write_text(json.dumps(manifest,ensure_ascii=False,separators=(',',':')));export_glb(manifest,folder)
    report['export']['glbBytes']=(folder/'model.glb').stat().st_size
    save_canonical(args.output/'canonical/urban-model.json',city)
    (args.output/'canonical/validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print('RAILWAY LAYER',json.dumps(stats),flush=True)

if __name__=='__main__':main()

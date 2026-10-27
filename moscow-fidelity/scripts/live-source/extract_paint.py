"""Archive fresh source paint in MSK XY + relative Z, before canonical binding."""
import argparse,gzip,json
from pathlib import Path
import numpy as np

def main():
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    plan=json.loads((a.source/'plan.json').read_text())
    scene=json.load(gzip.open(a.source/'output'/plan.get('output_subdir','area_5000')/'scene_with_icons.json.gz','rt'))
    dest=a.output/'corrected';dest.mkdir(parents=True,exist_ok=True);rows=[]
    for mesh in scene['meshes']:
        if mesh['category'] not in {'Road_markings','Road_marking_symbols'}:continue
        vertices=np.asarray(mesh['vertices']);indices=[];polygons=[];tiers=[];all_tiers=[]
        for i,face in enumerate(mesh['faces']):
            for j in range(1,len(face)-1):
                indices.append([face[0],face[j],face[j+1]]);polygons.append(i);tiers.append(max(mesh['face_tiers'][i] or [0]));all_tiers.append(mesh['face_tiers'][i] or [0])
        if not indices:continue
        name,*suffix=mesh['name'].split('__');color=suffix[0] if suffix else 'white'
        if 'waffle' in name:color='yellow'
        file=f'paint-{len(rows):04d}.npz';tri=vertices[np.asarray(indices)]
        tier_matrix=np.full((len(tri),max(map(len,all_tiers))),-32768,dtype=np.int32)
        for i,values in enumerate(all_tiers):tier_matrix[i,:len(values)]=values
        np.savez_compressed(dest/file,triangles=tri,polygon_indices=polygons,material_indices=np.zeros(len(tri),dtype=np.uint32),**{'2gis_tier':np.asarray(tiers,dtype=np.int32),'source_tiers':tier_matrix})
        rows.append(dict(name=name,file=file,hidden=False,categories=[mesh['category']],materials=[color],heightReference='source-relative',heightBinding='source-tier-floor',triangles=len(tri)))
    (dest/'manifest.json').write_text(json.dumps(dict(bounds=scene['plan']['extent_msk_east_north'],source=str(a.source.resolve()),objects=rows),indent=2))
    print('FRESH PAINT',len(rows),sum(r['triangles'] for r in rows),flush=True)
if __name__=='__main__':main()

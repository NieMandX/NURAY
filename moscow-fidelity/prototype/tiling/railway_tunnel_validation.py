"""Independent source-derived clearance audit of railway tunnel approaches.

Inspect the complete exposed descent and both interfaces, rather than trusting
the generator's accepted mouth list. The shallow slab-to-ground seam and the
deep tunnel header are different: a header above the passage is legitimate.
"""
import json
import sys
from pathlib import Path
import numpy as np
import shapely as sh
from shapely.geometry import shape
from shapely.ops import substring
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from build import z_at,triangulate
from railway_transitions import discover,source_candidates,TRACK_OFFSET
from transitions import shared_interfaces,parts
from interface_validation import check_interfaces
from prepare_railway_entries import load_terrain,near_passages,meshes

PRECISION=1e-5
APPROACH_DEPTH=1.05
SIDE_INSET=.05
LOWER=TRACK_OFFSET+.02
UPPER=TRACK_OFFSET+.75


def inventory(city):
    extent=sh.box(*city['boundsMSK'])
    candidates=source_candidates(city['features'],extent)
    _,ground=discover(candidates,city['features'],extent,PRECISION,z_at,
                      part='roadbed_tunnel_descent')
    deep=[r for r in shared_interfaces(candidates,extent,PRECISION,z_at)
          if {e['kind'] for e in r['ends']}=={'roadbed_tunnel','roadbed_tunnel_descent'}]
    for i,r in enumerate(deep):r['id']=f'railway-tunnel-deep-interface:{i}'
    rows=[r for r in candidates if r['part']=='roadbed_tunnel_descent']
    components=[]
    for level in sorted({tuple(r['tiers']) for r in rows}):
        for poly in parts(sh.union_all([r['poly'] for r in rows if tuple(r['tiers'])==level],grid_size=PRECISION)):
            parents=sorted(r['id'] for r in rows if tuple(r['tiers'])==level and r['poly'].intersection(poly).area>PRECISION**2)
            top=[r for r in ground if set(parents).intersection(r['ends'][0]['parents'])]
            bottom=[r for r in deep if any(set(parents).intersection(e['parents']) for e in r['ends'])]
            clipped=poly.distance(extent.boundary)<PRECISION*5
            components.append(dict(id=f'railway-tunnel-corridor:{len(components)}',level=list(level),
                parents=parents,poly=poly,ground=top,deep=bottom,regionClipped=clipped,
                passed=bool((top and bottom) or clipped)))
    return ground,deep,components


def volume_cells(poly,height,origin,lower=LOWER,upper=UPPER):
    ox,oy,oz=origin;cells=[]
    a,b,c=height;h=np.array([a,-b,a*ox+b*oy+c-oz])
    for t in triangulate(poly,np.zeros(3)):
        xy=(t[:,:2]-[ox,oy])*[1,-1];centre=xy.mean(0);planes=[]
        # A positive but sub-ULP source sliver can collapse when translated
        # into render coordinates. It has no area here and cannot define a
        # volume. Drop only exact zero area, never a positive-width passage.
        d,e=xy[1:]-xy[0]
        if d[0]*e[1]-d[1]*e[0]==0:continue
        for aa,bb in zip(xy,np.roll(xy,-1,axis=0)):
            n=np.array([-(bb-aa)[1],(bb-aa)[0]]);n/=np.linalg.norm(n)
            if (centre-aa)@n<0:n=-n
            planes.append([n[0],0,n[1],-n@aa])
        planes.extend([[-h[0],1,-h[1],-h[2]-lower],[h[0],-1,h[1],h[2]+upper]])
        assert np.isfinite(planes).all(), 'Non-finite passage volume'
        cells.append((sh.Polygon(xy),np.asarray(planes)))
    return cells


def volumes(city,dem,demtree):
    ground,deep,components=inventory(city);result=[]
    floors=[s for s in city['surfaces'] if s['kind'] in ('roadbed_tunnel_descent','roadbed_tunnel')]
    polys=[shape(s['geometry']) for s in floors];tree=sh.STRtree(polys)
    all_descents=sh.union_all([r['poly'] for r in components])
    def floor_cells(gate,parents):
        cells=[];covered=[]
        for i in tree.query(gate,predicate='intersects'):
            s=floors[int(i)]
            if s['owner'] not in parents:continue
            piece=gate.intersection(polys[int(i)])
            cells.extend(volume_cells(piece,s['heightPlane'],city['originMSK']));covered.append(piece)
        return cells,sh.union_all(covered)
    for r in ground+deep:
        line=shape(r['mouthGeometry']);line=substring(line,SIDE_INSET,line.length-SIDE_INSET)
        gate=line.buffer(APPROACH_DEPTH,cap_style='flat')
        parents={p for e in r['ends'] for p in e['parents']}
        cells,covered=floor_cells(gate,parents)
        if r in ground:
            outside=gate.difference(all_descents)
            for i in demtree.query(outside,predicate='intersects'):
                piece=outside.intersection(dem[int(i)][0]);cells.extend(volume_cells(piece,dem[int(i)][1],city['originMSK']))
                covered=covered.union(piece)
        # Missing floor witnesses must never turn an untested entrance green.
        assert gate.difference(covered.buffer(PRECISION*5)).area<.001,('Missing railway floor witness',r['id'])
        assert cells
        result.append((r,cells))
    for c in components:
        mouths=[shape(r['mouthGeometry']) for r in c['ground']+c['deep']]
        # Inset only lateral edges. Keep the full longitudinal extent so no
        # blind strip remains between the upper entry and the tunnel portal.
        lateral=c['poly'].boundary.difference(sh.union_all(mouths).buffer(PRECISION*5))
        gate=c['poly'].difference(lateral.buffer(SIDE_INSET))
        cells,covered=floor_cells(gate,set(c['parents']))
        assert gate.difference(covered.buffer(PRECISION*5)).area<.001
        r=dict(id=c['id'],mouthWidthM=0,ends=[dict(kind='railway_descent_corridor')])
        result.append((r,cells))
    coverage=[{k:v for k,v in c.items() if k not in ('poly','ground','deep')}|
              dict(groundEntries=len(c['ground']),deepPortals=len(c['deep'])) for c in components]
    return result,dict(groundEntries=len(ground),deepPortals=len(deep),corridors=len(components),coverage=coverage,
                       passed=all(c['passed'] for c in components))


def audit(city,dem,demtree,mesh_stream):
    gates,source=volumes(city,dem,demtree)
    result=check_interfaces(gates,near_passages(mesh_stream,gates))
    result.update(source=source,passed=result['passed'] and source['passed'],
        halfWidthM=APPROACH_DEPTH,heightRangeAboveFloorM=[round(LOWER,8),round(UPPER,8)],
        scope='source-confirmed railway ground entries, entire exposed descents and deep tunnel portals; serialized faces')
    result.pop('heightRangeAboveRoadM',None)
    return result


if __name__=='__main__':
    root=Path(sys.argv[1]);city=json.loads((root/'canonical/urban-model.json').read_text())
    scene=json.loads((root/'canonical/full/scene.json').read_text());dem,tree=load_terrain(root)
    result=audit(city,dem,tree,meshes(root,scene))
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
    sys.exit(0 if result['passed'] else 1)

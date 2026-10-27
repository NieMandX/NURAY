"""Classify continuous transport slabs from same-tier rail centre lines.

The provider can split a slab longitudinally: its shoulder need not contain a
centre line. Only a shared edge at the same physical height joins those parts;
an XY crossing, a nearby pavement or another deck above it is not evidence.
"""
import numpy as np
import shapely as sh

RAIL_COLOR=[.105,.115,.120]

def _slab(feature, precision):
    xyz=np.asarray(feature['coordinates'],dtype=float);triangles=[];planes=[]
    for i in range(len(xyz)-2):
        t=xyz[i:i+3];p=sh.Polygon(t[:,:2])
        if p.area<=1e-8:continue
        triangles.append(p)
        planes.append(np.linalg.solve(np.column_stack([t[:,:2],np.ones(3)]),t[:,2]))
    poly=sh.union_all(triangles,grid_size=precision)
    return dict(feature=feature,poly=poly,triangles=triangles,planes=planes,
                tree=sh.STRtree(triangles),tiers=tuple(sorted(feature['properties'].get('db_tiers') or [0])))


def _height(slab, xy):
    point=sh.Point(xy);i=int(slab['tree'].nearest(point))
    # Overlay rounding can put a boundary probe micrometres outside its cell.
    contact=sh.shortest_line(point,slab['triangles'][i])
    if not contact.is_empty:xy=np.asarray(contact.coords)[-1,:2]
    c=slab['planes'][i]
    return float(np.dot(c[:2],xy)+c[2])


def _continuous_edge(a,b,precision):
    edge=sh.intersection(a['poly'].boundary,b['poly'].boundary,grid_size=precision)
    if edge.length<=.1:return False
    def lines(g):
        if g.geom_type=='LineString':return [g]
        return [line for sub in getattr(g,'geoms',[]) for line in lines(sub)]
    for line in lines(edge):
        for xy in list(line.coords)+[line.interpolate(.5,normalized=True).coords[0]]:
            if abs(_height(a,xy)-_height(b,xy))>.002:return False
    return True


def confirmed_owners(features, precision=1e-5):
    rails=[f for f in features if f['layer'] in ('Railroad_line','Railroad_tunnel_line')
           and f['geometryType']=='polyline' and len(f['coordinates'])>1]
    slabs=[]
    for f in features:
        p=f['properties'];part=p.get('db_road_part')
        if f['layer']!='Transport_Roadbed' or f['geometryType']!='polygon' or part not in (
            'roadbed_overpass','roadbed_tunnel','roadbed_tunnel_descent'): continue
        slabs.append(_slab(f,precision))
    tree=sh.STRtree([s['poly'] for s in slabs]);parent=list(range(len(slabs)))
    def root(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    for i,a in enumerate(slabs):
        for j in tree.query(a['poly'].buffer(precision),predicate='intersects'):
            j=int(j)
            if j<=i or a['tiers']!=slabs[j]['tiers']:continue
            if _continuous_edge(a,slabs[j],precision):parent[root(j)]=root(i)
    components={}
    for i in range(len(slabs)):components.setdefault(root(i),[]).append(i)
    rail_lines=[sh.LineString(np.asarray(r['coordinates'])[:,:2]) for r in rails]
    rail_tree=sh.STRtree(rail_lines);result=[]
    for ids in components.values():
        poly=sh.union_all([slabs[i]['poly'] for i in ids],grid_size=precision)
        tiers=slabs[ids[0]]['tiers'];matches=[]
        for j in rail_tree.query(poly,predicate='intersects'):
            r=rails[int(j)]
            if tuple(sorted(r['properties'].get('db_tiers') or [0]))!=tiers:continue
            length=poly.intersection(rail_lines[int(j)]).length
            if length>.1:matches.append(dict(source=r['id'],lengthM=length))
        # Reject a mere transverse crossing of a long slab. The rail network
        # must run through its length, not just touch its boundary/projection.
        length=sum(m['lengthM'] for m in matches)
        if length and length*length>=poly.area*.5:
            owners=sorted(slabs[i]['feature']['id'] for i in ids)
            for i in ids:
                s=slabs[i];f=s['feature'];p=f['properties']
                result.append(dict(source=f['id'],part=p['db_road_part'],tiers=p.get('db_tiers') or [0],
                    railAxes=matches,sourceAreaM2=s['poly'].area,continuousSlabOwners=owners,
                    evidence='rail-axis-in-height-continuous-slab'))
    return sorted(result,key=lambda r:r['source'])

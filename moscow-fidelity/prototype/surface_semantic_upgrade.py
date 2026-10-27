"""Apply newly supported land classes to an existing canonical height partition.

Source ranks and contours select ownership. Roads, water, heights, openings and
curb dimensions are unchanged; this is not a coordinate-specific repair.
"""
import numpy as np
import shapely as sh
from partition_refinement import clip_triangle
from spatial_mask import SpatialMask


def priority(row):
    return (-row['rank'],row['poly'].area,row['id'])


def upgrade(b,candidates,added):
    if not added:return dict(features=0,affectedCells=0,coverageExactlyPreserved=True)
    added=sorted(added,key=priority)
    old_by_id={r['id']:r for r in candidates if r['kind']=='land'}
    land=[s for s in b.surfaces if s['kind'] in ('land','curb_top')]
    tree=sh.STRtree([s['poly'] for s in land]);atree=sh.STRtree([r['poly'] for r in added])
    affected=set()
    for row in added:
        for i in tree.query(row['poly'],predicate='intersects'):
            cell=land[int(i)];old=old_by_id.get(cell['owner'])
            if (old is None or priority(row)<priority(old)) and cell['poly'].intersection(row['poly']).area>1e-9:
                affected.add(int(i))
    rows=[land[i] for i in sorted(affected)]
    print('SEMANTIC LAND CELLS',len(rows),'new features',len(added),flush=True)
    if not rows:return dict(features=len(added),affectedCells=0,coverageExactlyPreserved=True)
    replaced=b.union([s['poly'] for s in rows]);mask=SpatialMask(replaced)
    bounds=sh.STRtree([sh.box(*g.bounds) for g in b.parts(replaced)])
    # Select local faces by vectorized bounding-box queries. A disconnected
    # district-wide change must not clip every triangle in its total envelope.
    for key,faces in list(b.groups.items()):
        if key[0] not in ('land','curb_top','curb_bottom') or not faces:continue
        flags=b.shading_flags.get(key,[]);out=[];out_flags=[]
        for first in range(0,len(faces),8192):
            batch=faces[first:first+8192];a=np.asarray(batch)
            lo=a[:,:,:2].min(1);hi=a[:,:,:2].max(1)
            boxes=sh.box(lo[:,0],lo[:,1],hi[:,0],hi[:,1]);hits=set(map(int,bounds.query(boxes)[0]))
            if not hits:
                out.extend(batch)
                if flags:out_flags.extend(flags[first:first+len(batch)])
                continue
            for j,t in enumerate(batch):
                if j not in hits:
                    out.append(t)
                    if flags:out_flags.append(flags[first+j])
                    continue
                cut=mask.near(sh.Polygon(t[:,:2]))
                pieces=clip_triangle(t,cut,b.triangulate,b.plane) if not cut.is_empty else [t]
                out.extend(pieces)
                if flags:out_flags.extend([flags[first+j]]*len(pieces))
        b.groups[key]=out
        if flags:b.shading_flags[key]=out_flags
        print('SEMANTIC FACES',key,len(faces),'->',len(out),flush=True)
    exact=True;changed_area=0.;removed={s['id'] for s in rows}
    for index,s in enumerate(rows):
        old=old_by_id.get(s['owner']);remaining=s['poly'];first=len(b.surfaces)
        pieces=[]
        for j in sorted(map(int,atree.query(remaining,predicate='intersects'))):
            row=added[j]
            if old is not None and priority(row)>=priority(old):continue
            piece=remaining.intersection(row['poly'])
            if piece.area<=1e-9:continue
            pieces.append((piece,row['id'],row['material']));changed_area+=piece.area
            remaining=remaining.difference(piece)
        pieces.append((remaining,s['owner'],s['material']))
        for piece,owner,material in pieces:
            material=9 if s['kind']=='curb_top' else material
            b.add_surface(piece,s['plane'],owner,material,s['kind'],s['tiers'])
        created=b.surfaces[first:]
        exact &= bool(sh.union_all([r['poly'] for r in created],grid_size=b.GRID).equals(s['poly']))
        if s['kind']=='curb_top':
            for r in created:
                b.groups[('curb_bottom',9)].extend(t[::-1] for t in b.triangulate(r['poly'],r['plane']-[0,0,.1]))
                b.relationships.append(dict(type='curb-on-raised-territory',parent=r['id'],sourceObject=r['owner'],
                    heightM=.1,widthM=.15,evidence='reconstruction-rule'))
        if index and index%10000==0:print('SEMANTIC REPARTITION',index,'/',len(rows),flush=True)
    b.surfaces[:]=[s for s in b.surfaces if s['id'] not in removed]
    b.relationships[:]=[r for r in b.relationships if not any(r.get(k) in removed for k in ('a','b','parent'))]
    for row in b.unresolved:
        if row.get('type')=='unknown-land-cover':
            row['areaM2']=sum(s['poly'].area for s in b.surfaces if s['owner']=='inferred:unclassified-land')
    report=dict(features=len(added),affectedCells=len(rows),reclassifiedAreaM2=changed_area,coverageExactlyPreserved=bool(exact))
    print('SEMANTIC LAND UPGRADE',report,flush=True)
    return report

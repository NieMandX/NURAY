"""Join DEM tile boundaries before producing terrain faces.

Boundary samples are unioned in the provider's integer map coordinate system.
Both adjacent tiles get the same piecewise-linear seam. Conflicting heights are
averaged explicitly and reported; this is a reconstruction policy, not surveying.
"""
import json, math
from collections import defaultdict
import numpy as np
import shapely as sh
from shapely.geometry import Polygon

def conforming_dem(cache, keys, project, extent):
    tiles=[];edges=defaultdict(list)
    def project_world(world):
        lon=world[:,0]/2**32*360
        lat=np.degrees(np.arctan(np.sinh(world[:,1]/2**32*2*math.pi)))
        x,y=project.transform(lon,lat)
        return np.column_stack((x,y)),lat
    for key in keys:
        d=json.loads((cache/f'dem_{key}.json').read_text());info=d['tile_info']
        world=np.asarray(d['positions']).reshape(-1,2)*(info['size']/32768)+np.asarray(info['offset'][:2])
        xy,lat=project_world(world);heights=np.asarray(d['heights'])*np.cos(np.radians(lat))
        tile=dict(key=key,world=world,xy=xy,z=heights,ix=np.asarray(d['indices']).reshape(-1,3),edges={})
        for axis in [0,1]:
            other=1-axis
            for edge in [world[:,axis].min(),world[:,axis].max()]:
                ii=np.flatnonzero(world[:,axis]==edge);ii=ii[np.argsort(world[ii,other])]
                k=(axis,edge,world[ii,other].min(),world[ii,other].max())
                edges[k].append((world[ii,other],heights[ii]));tile['edges'][k]=True
        tiles.append(tile)
    seams={};node_z=defaultdict(list);max_disagreement=0.
    for k,profiles in edges.items():
        if len(profiles)<2:continue
        ts=np.unique(np.concatenate([p[0] for p in profiles]))
        zz=np.array([np.interp(ts,p[0],p[1]) for p in profiles])
        max_disagreement=max(max_disagreement,float(np.ptp(zz,axis=0).max()))
        zs=zz.mean(0);seams[k]=ts
        axis,edge,_,_=k
        for t,z in zip(ts,zs):
            w=(edge,t) if axis==0 else (t,edge);node_z[w].append(float(z))
    node_z={k:float(np.mean(v)) for k,v in node_z.items()}
    output=[];corrections=[];inserted=0;changed={}
    for tile in tiles:
        for indices in tile['ix']:
            original=tile['world'][indices];xy=tile['xy'][indices]
            if not Polygon(xy).intersects(extent):continue
            points=[];zs=[]
            for j,a in enumerate(original):
                b=original[(j+1)%3];za=tile['z'][indices[j]]
                z=node_z.get(tuple(a),float(za));points.append(a);zs.append(z);corrections.append(abs(z-za))
                if abs(z-za)>1e-6:changed[(tile['key'],*a)]=dict(tile=tile['key'],worldXY=a.tolist(),originalHeightM=float(za),reconciledHeightM=z)
                for k in tile['edges']:
                    if k not in seams:continue
                    axis,edge,lo,hi=k;other=1-axis
                    if a[axis]!=edge or b[axis]!=edge:continue
                    ts=seams[k];inside=ts[(ts>min(a[other],b[other]))&(ts<max(a[other],b[other]))]
                    if a[other]>b[other]:inside=inside[::-1]
                    for t in inside:
                        w=np.array([edge,t] if axis==0 else [t,edge]);points.append(w);zs.append(node_z[tuple(w)]);inserted+=1
            # Triangulate in projected coordinates, with explicitly identical shared nodes.
            points=np.array(points);pp,_=project_world(points);zz=np.array(zs)
            if len(pp)==3:
                output.append(np.column_stack([pp,zz]));continue
            # A fan around the original triangle centroid preserves every boundary
            # sample, including collinear samples with non-linear height profiles.
            center=xy.mean(0);cz=float(tile['z'][indices].mean())
            for i in range(len(pp)):
                j=(i+1)%len(pp);t=np.array([[*center,cz],[*pp[i],zz[i]],[*pp[j],zz[j]]])
                if Polygon(t[:,:2]).area>1e-10:output.append(t)
    return output,dict(sourceTiles=keys,seamCount=len(seams),insertedBoundaryVertices=inserted,
        maxSourceSeamDisagreementM=max_disagreement,maxAppliedVertexAdjustmentM=max(corrections,default=0),
        heightPolicy='mean of the two source edge profiles at unioned breakpoints; shared corner mean',adjustedVertices=list(changed.values()))

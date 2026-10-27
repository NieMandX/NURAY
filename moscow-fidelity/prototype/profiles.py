"""A shared smooth road height model, with source-linked reference profiles.

The map DEM is an observation of the surroundings, not a road design profile.
Fit a C2 cubic B-spline surface, penalize bending along source ground-road axes,
and use one function on both sides of every road join. Cross-sections are cut
from the source road footprint. This is a visual reconstruction, not surveying.
"""
import math
from collections import defaultdict
import numpy as np
import shapely as sh
from shapely.geometry import Point, LineString, Polygon, box, mapping, shape

AXES = {'Main_road', 'Other_road', 'Internal_road', 'Oneway_intercity_road',
        'Oneway_other_road', 'Oneway_internal_road', 'Segmental_road'}


def ground_axes(records, bounds):
    extent=box(*bounds);out=[]
    for f in records:
        p=f['properties']
        if f['layer'] not in AXES or f['geometryType']!='polyline':continue
        if any(p.get(k,0)!=0 for k in ['db_segment_level','db_segment_begin_level','db_segment_end_level']):continue
        line=LineString(np.array(f['coordinates'])[:,:2]).intersection(extent)
        for piece in ([line] if line.geom_type=='LineString' else getattr(line,'geoms',[])):
            if piece.geom_type=='LineString' and piece.length>=2:out.append((f['id'],piece))
    return out


def reference_junctions(records, bounds):
    """Ground reference-line endpoints on other ground axes identify T joins.
    No connection is inferred just because a bridge crosses a road in XY.
    """
    axes=ground_axes(records,bounds);tree=sh.STRtree([line for owner,line in axes]);nodes={}
    extent=box(*bounds)
    for i,(owner,line) in enumerate(axes):
        for xy in [line.coords[0],line.coords[-1]]:
            point=Point(xy)
            if extent.boundary.distance(point)<.1:continue
            near=[int(j) for j in tree.query(point.buffer(.1),predicate='intersects') if j!=i and axes[j][0]!=owner]
            if not near:continue
            key=tuple(np.round(np.array(xy)/.05).astype(int))
            if key not in nodes:nodes[key]=dict(id=f'road-junction:{len(nodes)}',xy=list(xy),level=0,sourceAxes=[])
            nodes[key]['sourceAxes']=sorted(set(nodes[key]['sourceAxes']+[owner]+[axes[j][0] for j in near]))
    return list(nodes.values())


def repair_junction_gaps(road, candidates, records, bounds, max_reach=.5):
    """Resolve small open wedges at evidenced ground-axis junctions.
    Require two source asphalt owners and a T-join within 3 m. Protect explicit
    greenery, pedestrian areas, open descents and marked traffic islands.
    Store every patch as inferred geometry with its source parents and limits.
    """
    nodes=reference_junctions(records,bounds)
    protected=sh.union_all([r['poly'] for r in candidates if r['material'] in [2,7] or r.get('part')=='roadbed_tunnel_descent'])
    markings=[]
    for f in records:
        if 'save_island' in f['layer'] and len(f['coordinates'])>1:
            markings.append(LineString(np.array(f['coordinates'])[:,:2]).buffer(.05))
    protected=sh.union_all([protected]+markings)
    closed=road.buffer(max_reach,join_style=2).buffer(-max_reach,join_style=2)
    extra=closed.difference(road).intersection(box(*bounds));repairs=[]
    patches=[extra] if extra.geom_type=='Polygon' else list(getattr(extra,'geoms',[]))
    parents=[r for r in candidates if r['kind']=='road' and r['part']=='roadbed_flat']
    parent_tree=sh.STRtree([r['poly'] for r in parents])
    node_points=sh.points(np.asarray([n['xy'] for n in nodes]).reshape(-1,2));node_tree=sh.STRtree(node_points)
    for p in patches:
        if p.geom_type!='Polygon' or not (.01<p.area<1):continue
        if p.intersection(protected).area>1e-4:continue
        nearby=[nodes[i] for i in node_tree.query(p.buffer(3)) if p.distance(node_points[i])<3]
        if not nearby:continue
        owners=[parents[i]['id'] for i in parent_tree.query(p.buffer(.0001)) if p.boundary.intersection(parents[i]['poly'].buffer(.0001)).length>.1]
        if len(owners)<2:continue
        radius=float(sh.distance(p.representative_point(),road))
        repairs.append(dict(type='junction-wedge',geometry=mapping(p),areaM2=p.area,maxSampledHalfWidthM=radius,
            evidence='inferred wedge at source-axis T-junction with two asphalt owners; protected land and island markings excluded',
            widthLimitM=max_reach*2,sourceParents=owners,junctions=[n['id'] for n in nearby]))
    return sh.union_all([road]+[shape(r['geometry']) for r in repairs]),repairs,nodes


class RoadHeightModel:
    knot_spacing = 25.
    mesh_spacing = 3.
    transition_width = 20.

    def __init__(self, dem, records, road, bounds, sparse_fit=None):
        self.dem = dem
        self.tree = sh.STRtree([p for p, c in dem])
        self.planes = np.array([c for p, c in dem])
        self.road = road
        sh.prepare(self.road)
        edges=[]
        for poly in sh.get_parts(road):
            for ring in [poly.exterior,*poly.interiors]:
                xy=np.asarray(ring.coords)[:,:2]
                edges.extend(sh.linestrings(np.stack((xy[:-1],xy[1:]),axis=1)))
        self.road_edge_tree=sh.STRtree(edges)
        self.local_roads=[]
        if max(np.asarray(bounds)[2:]-np.asarray(bounds)[:2])>1500:
            for y in np.arange(bounds[1],bounds[3],250):
                for x in np.arange(bounds[0],bounds[2],250):
                    piece=road.intersection(box(x,y,min(x+250,bounds[2]),min(y+250,bounds[3])))
                    if not piece.is_empty:self.local_roads.append(piece)
        self.local_road_tree=sh.STRtree(self.local_roads) if self.local_roads else None
        self.bounds = np.array(bounds)
        self.origin = self.bounds[:2]
        self.nx, self.ny = (np.ceil((self.bounds[2:] - self.origin) / self.knot_spacing).astype(int) + 4)
        self.sparse_fit = bool(self.nx*self.ny >= 4096 if sparse_fit is None else sparse_fit)
        self.junctions=reference_junctions(records,bounds)
        self.axes = self.reference_axes(records)
        # Spatially uniform observations avoid overweighting densely triangulated
        # DEM patches. Profiles add longitudinal bending constraints, not invented
        # absolute elevations or a universal road slope.
        xx = np.arange(bounds[0], bounds[2] + .01, 8.)
        yy = np.arange(bounds[1], bounds[3] + .01, 8.)
        sample = np.array(np.meshgrid(xx, yy)).reshape(2, -1).T
        observed = self.raw(sample)
        a = self.design(sample)
        finite = np.isfinite(observed)
        a, sample, observed = a[finite], sample[finite], observed[finite]
        if self.sparse_fit:
            from scipy import sparse
            from scipy.sparse.linalg import spsolve
            def second_difference(n):
                return sparse.diags([np.ones(n-2),-2*np.ones(n-2),np.ones(n-2)], [0,1,2],shape=(n-2,n),format='csr')
            regular=sparse.vstack([sparse.kron(sparse.eye(self.ny),second_difference(self.nx)),
                                   sparse.kron(second_difference(self.ny),sparse.eye(self.nx))],format='csr')
            longitudinal=[]
            for axis in self.axes:
                xy=np.asarray(axis['stationsXY'])
                if len(xy)<3:continue
                design=self.design(xy);intervals=np.diff(axis['stationDistanceM'])
                previous,following=intervals[:-1],intervals[1:]
                longitudinal.append(design[1:-1]-design[:-2].multiply((following/(previous+following))[:,None])-design[2:].multiply((previous/(previous+following))[:,None]))
            penalty=12.*(regular.T@regular)
            longitudinal_count=sum(row.shape[0] for row in longitudinal)
            if longitudinal:
                along=sparse.vstack(longitudinal,format='csr');penalty+=16.*(along.T@along)
            penalty=penalty+sparse.eye(self.nx*self.ny)*1e-7
            weights=np.ones(len(observed))
            for iteration in range(4):
                print('ROAD HEIGHT SOLVE',iteration+1,'/ 4','controls',self.nx*self.ny,flush=True)
                normal=(a.T@a.multiply(weights[:,None])+penalty).tocsc()
                self.coefficients=spsolve(normal,np.asarray(a.T@(weights*observed)).ravel())
                residual=a@self.coefficients-observed
                weights=np.minimum(1.,.5/np.maximum(np.abs(residual),1e-9))
        else:
            bending = []
            for j in range(self.ny):
                for i in range(1, self.nx - 1):
                    row = np.zeros(self.nx * self.ny)
                    row[j*self.nx+i-1:j*self.nx+i+2] = [1, -2, 1]
                    bending.append(row)
            for j in range(1, self.ny - 1):
                for i in range(self.nx):
                    row = np.zeros(self.nx * self.ny)
                    row[(j-1)*self.nx+i] = 1
                    row[j*self.nx+i] = -2
                    row[(j+1)*self.nx+i] = 1
                    bending.append(row)
            regular = np.array(bending)
            longitudinal = []
            for axis in self.axes:
                xy = np.array(axis['stationsXY'])
                if len(xy) < 3: continue
                b = self.design(xy)
                intervals=np.diff(axis['stationDistanceM']);previous=intervals[:-1];following=intervals[1:]
                longitudinal.extend(b[1:-1] - (b[:-2]*following[:,None] + b[2:]*previous[:,None])/(previous+following)[:,None])
            penalty = 12. * (regular.T @ regular)
            if longitudinal:
                along = np.array(longitudinal)
                penalty += 16. * (along.T @ along)
            # Huber reweighting retains broad hills while limiting narrow DEM spikes.
            weights = np.ones(len(observed))
            for _ in range(4):
                wa = a * weights[:, None]
                self.coefficients = np.linalg.solve(a.T @ wa + penalty + np.eye(a.shape[1])*1e-7,
                                                    a.T @ (weights * observed))
                residual = a @ self.coefficients - observed
                weights = np.minimum(1., .5 / np.maximum(np.abs(residual), 1e-9))
            longitudinal_count=len(longitudinal)
        fitted = self.smooth(sample)
        road_mask = sh.covers(road, sh.points(sample))
        delta = fitted - observed
        self.report = dict(method='shared C2 cubic B-spline height surface with source-axis longitudinal bending constraints',
            knotSpacingM=self.knot_spacing, outputGridSpacingM=self.mesh_spacing,
            landTransitionWidthM=self.transition_width, uniformDEMObservations=len(observed),
            referenceAxes=len(self.axes), longitudinalBendingConstraints=longitudinal_count, sparseFit=self.sparse_fit,
            referenceJunctions=len(self.junctions),
            rmsRoadAdjustmentM=float(np.sqrt(np.mean(delta[road_mask]**2))),
            maxRoadAdjustmentM=float(np.max(np.abs(delta[road_mask]))),
            evidence='fitted to map DEM; reconstructed smooth heights, not measured road elevations')
        self.finish_profiles()

    def raw(self, xy):
        xy = np.atleast_2d(xy)
        out = np.full(len(xy), np.nan)
        pairs = self.tree.query(sh.points(xy), predicate='covered_by')
        if len(pairs[0]):
            c = self.planes[pairs[1]]
            out[pairs[0]] = np.sum(xy[pairs[0]] * c[:, :2], axis=1) + c[:, 2]
        return out

    def stencil(self, xy):
        u = (np.atleast_2d(xy) - self.origin) / self.knot_spacing + 1
        integer = np.floor(u).astype(int)
        t = u - integer
        # Cardinal cubic B-spline basis; adjacent spans have matching first and
        # second derivatives. Bounds are padded by three control points.
        b = np.stack(((1-t)**3, 3*t**3-6*t*t+4,
                      -3*t**3+3*t*t+3*t+1, t**3), axis=2) / 6
        indices, weights = [], []
        for j in range(4):
            for i in range(4):
                ix = np.clip(integer[:, 0]-1+i, 0, self.nx-1)
                iy = np.clip(integer[:, 1]-1+j, 0, self.ny-1)
                indices.append(iy*self.nx+ix)
                weights.append(b[:, 0, i]*b[:, 1, j])
        return np.array(indices).T, np.array(weights).T

    def design(self, xy):
        ids, weights = self.stencil(xy)
        if self.sparse_fit:
            from scipy.sparse import coo_matrix
            return coo_matrix((weights.ravel(),(np.repeat(np.arange(len(ids)),ids.shape[1]),ids.ravel())),shape=(len(ids),self.nx*self.ny)).tocsr()
        a = np.zeros((len(ids), self.nx*self.ny))
        np.add.at(a, (np.arange(len(ids))[:, None], ids), weights)
        return a

    def smooth(self, xy):
        ids, weights = self.stencil(xy)
        return np.sum(self.coefficients[ids] * weights, axis=1)

    def smooth_gradient(self, xy):
        xy = np.atleast_2d(xy)
        e = .01
        return np.column_stack([(self.smooth(xy + np.eye(2)[i]*e) -
                                  self.smooth(xy - np.eye(2)[i]*e))/(2*e) for i in range(2)])

    def height(self, xy):
        xy = np.atleast_2d(xy)
        raw, smooth = self.raw(xy), self.smooth(xy)
        points=sh.points(xy)
        inside=sh.covers(self.road,points)
        distance=np.full(len(xy),self.transition_width);distance[inside]=0.
        outside=np.flatnonzero(~inside)
        if len(outside):
            pairs,dist=self.road_edge_tree.query_nearest(points[outside],max_distance=self.transition_width,return_distance=True,all_matches=False)
            distance[outside[pairs[0]]]=dist
        t = np.clip(distance / self.transition_width, 0, 1)
        w = 1 - (3*t*t - 2*t*t*t)
        return np.where(np.isfinite(raw), raw*(1-w) + smooth*w, smooth)

    def gradient(self, xy):
        xy = np.atleast_2d(xy)
        e = .01
        return np.column_stack([(self.height(xy + np.eye(2)[i]*e) -
                                  self.height(xy - np.eye(2)[i]*e))/(2*e) for i in range(2)])

    def reference_axes(self, records):
        axes = []
        for owner,piece in ground_axes(records,self.bounds):
                n=max(2, math.ceil(piece.length/10.) + 1)
                distances=np.unique(np.r_[np.linspace(0,piece.length,n),[piece.project(Point(j['xy'])) for j in self.junctions if owner in j['sourceAxes']]])
                stations=np.array([piece.interpolate(s).coords[0] for s in distances])
                axes.append(dict(id=f"profile:{len(axes)}", source=owner, level=0,
                    sourceGeometry=mapping(piece), stationDistanceM=distances.tolist(),
                    stationsXY=stations.tolist(), evidence='source reference line; fit height from map DEM'))
        return axes

    def finish_profiles(self):
        nodes = {}
        for axis in self.axes:
            xy = np.array(axis['stationsXY'])
            zs = self.smooth(xy)
            raw = self.raw(xy)
            axis['heightM'] = zs.tolist()
            axis['rawDEMHeightM'] = [float(z) if np.isfinite(z) else None for z in raw]
            axis['grades'] = (np.diff(zs)/np.diff(axis['stationDistanceM'])).tolist()
            axis['crossSections'] = []
            for i, point in enumerate(xy):
                direction = xy[min(i+1, len(xy)-1)] - xy[max(0, i-1)]
                direction /= max(np.linalg.norm(direction), 1e-9)
                normal = np.array([-direction[1], direction[0]])
                line=LineString([point-normal*35, point+normal*35])
                local=sh.union_all([self.local_roads[k] for k in self.local_road_tree.query(line)]) if self.local_road_tree is not None else self.road
                section = line.intersection(local)
                pieces = [section] if section.geom_type == 'LineString' else list(getattr(section, 'geoms', []))
                for piece in pieces:
                    if piece.geom_type != 'LineString' or piece.is_empty or piece.length < .1 or piece.distance(Point(point)) > .05: continue
                    samples = np.array([piece.interpolate(s).coords[0] for s in np.linspace(0, piece.length, max(2, math.ceil(piece.length/2)+1))])
                    axis['crossSections'].append(dict(station=i, xy=samples.tolist(), heightM=self.smooth(samples).tolist(),
                        evidence='cross-section cut from source footprint; no invented crown or measured crossfall'))
            for end in [0, -1]:
                key = tuple(np.round(xy[end]/.05).astype(int))
                if key not in nodes: nodes[key] = dict(id=f'road-node:{len(nodes)}', xy=xy[end].tolist(), level=0, heightM=float(zs[end]), profiles=[])
                nodes[key]['profiles'].append(axis['id'])
        self.nodes = list(nodes.values())
        for junction in self.junctions:
            junction['heightM']=float(self.smooth([junction['xy']])[0])
            junction['profiles']=[a['id'] for a in self.axes if a['source'] in junction['sourceAxes']]

    def controls(self):
        return dict(basis='cardinal cubic B-spline, tensor product; u=(xy-origin)/spacing+1',
                    originXY=self.origin.tolist(),spacingM=self.knot_spacing,
                    controlHeightsM=self.coefficients.reshape(self.ny,self.nx).tolist())

    def grid(self):
        if max(self.bounds[2:]-self.bounds[:2])>1500:
            return self.adaptive_grid()
        x0,y0,x1,y1 = self.bounds
        xx=np.linspace(x0,x1,math.ceil((x1-x0)/self.mesh_spacing)+1)
        yy=np.linspace(y0,y1,math.ceil((y1-y0)/self.mesh_spacing)+1)
        xy=np.array(np.meshgrid(xx,yy)).reshape(2,-1).T
        zz=np.concatenate([self.height(xy[start:start+100000]) for start in range(0,len(xy),100000)]).reshape(len(yy),len(xx))
        out=[]
        for j in range(len(yy)-1):
            # Batched rows preserve the exact regular tessellation while avoiding
            # millions of Python geometry constructors and small LAPACK calls.
            n=len(xx)-1
            v=np.stack((np.column_stack((xx[:-1],np.full(n,yy[j]),zz[j,:-1])),
                        np.column_stack((xx[1:],np.full(n,yy[j]),zz[j,1:])),
                        np.column_stack((xx[1:],np.full(n,yy[j+1]),zz[j+1,1:])),
                        np.column_stack((xx[:-1],np.full(n,yy[j+1]),zz[j+1,:-1]))),axis=1)
            t=v[:,[[0,1,2],[0,2,3]]].reshape(-1,3,3)
            matrix=np.concatenate((t[:,:,:2],np.ones((len(t),3,1))),axis=2)
            planes=np.linalg.solve(matrix,t[:,:,2,None])[:,:,0]
            out.extend(zip(sh.polygons(t[:,:,:2]),planes))
        return out

    def adaptive_grid(self,tolerance=.0075):
        """Conforming shared terrain for large regions; 3–24 m cells.

        Refine by height error against the same height function, never by tile
        ownership. Split coarse edges at every fine neighbour vertex, so an
        adaptive leaf cannot create a crack or a transverse wall.
        """
        from bisect import bisect_left,bisect_right
        x0,y0,x1,y1=self.bounds
        nx,ny=np.ceil((self.bounds[2:]-self.bounds[:2])/(self.mesh_spacing*8)).astype(int)*8
        dx,dy=(x1-x0)/nx,(y1-y0)/ny
        leaves=[];pending=np.array([(i,j,8) for j in range(0,ny,8) for i in range(0,nx,8)],dtype=np.int32)
        fractions=np.array([[0,0],[1,0],[1,1],[0,1],[.5,.5],[.5,0],[1,.5],[.5,1],[0,.5],[.25,.25],[.75,.25],[.75,.75],[.25,.75]])
        samples=0;max_terminal_error=0.
        while len(pending):
            # Evaluate in bounded blocks; each leaf's diagonal planes are the
            # same two triangles used by the former regular-grid builder.
            next_level=[]
            for start in range(0,len(pending),8000):
                cells=pending[start:start+8000];uv=cells[:,None,:2]+cells[:,None,2:]*fractions[None]
                xy=uv*np.array([dx,dy])+[x0,y0]
                z=self.height(xy.reshape(-1,2)).reshape(len(cells),-1);samples+=z.size
                fx,fy=fractions[:,0],fractions[:,1]
                predicted=np.where(fx>=fy,z[:,0,None]+fx*(z[:,1,None]-z[:,0,None])+fy*(z[:,2,None]-z[:,1,None]),
                                   z[:,0,None]+fy*(z[:,3,None]-z[:,0,None])+fx*(z[:,2,None]-z[:,3,None]))
                errors=np.max(np.abs(z-predicted),axis=1)
                refine=(errors>tolerance)&(cells[:,2]>1)
                leaves.extend(cells[~refine].tolist())
                if np.any(~refine):max_terminal_error=max(max_terminal_error,float(errors[~refine].max()))
                for cell in cells[refine]:
                    i,j,n=map(int,cell);h=n//2;next_level.extend([(i,j,h),(i+h,j,h),(i,j+h,h),(i+h,j+h,h)])
            pending=np.asarray(next_level,dtype=np.int32)
        rows=defaultdict(set);cols=defaultdict(set)
        for i,j,n in leaves:
            for x,y in [(i,j),(i+n,j),(i+n,j+n),(i,j+n)]:rows[y].add(x);cols[x].add(y)
        rows={k:sorted(v) for k,v in rows.items()};cols={k:sorted(v) for k,v in cols.items()}
        def between(seq,a,b):return seq[bisect_left(seq,a):bisect_right(seq,b)]
        points={};triangles=[]
        def vertex(x,y):
            key=(x,y)
            if key not in points:points[key]=len(points)
            return points[key]
        for i,j,n in leaves:
            edge=[(x,j) for x in between(rows[j],i,i+n)[:-1]]
            edge += [(i+n,y) for y in between(cols[i+n],j,j+n)[:-1]]
            edge += [(x,j+n) for x in between(rows[j+n],i,i+n)[::-1][:-1]]
            edge += [(i,y) for y in between(cols[i],j,j+n)[::-1][:-1]]
            ids=[vertex(x,y) for x,y in edge]
            if len(ids)==4:triangles.extend([[ids[0],ids[1],ids[2]],[ids[0],ids[2],ids[3]]])
            else:
                mid=vertex(i+n/2,j+n/2)
                triangles.extend([[mid,ids[k],ids[(k+1)%len(ids)]] for k in range(len(ids))])
        xy=np.asarray(list(points))*[dx,dy]+[x0,y0]
        zz=np.concatenate([self.height(xy[s:s+100000]) for s in range(0,len(xy),100000)])
        vertices=np.c_[xy,zz];out=[]
        for start in range(0,len(triangles),50000):
            t=vertices[np.asarray(triangles[start:start+50000])]
            matrix=np.concatenate((t[:,:,:2],np.ones((len(t),3,1))),axis=2)
            planes=np.linalg.solve(matrix,t[:,:,2,None])[:,:,0]
            out.extend(zip(sh.polygons(t[:,:,:2]),planes))
        self.report['tessellation']=dict(method='shared adaptive conforming quadtree; coarse edges split at all fine neighbours',
            targetSampleErrorM=tolerance,maxLeafSampleErrorM=max_terminal_error,minSpacingM=min(dx,dy),maxSpacingM=max(dx,dy)*8,
            leafCells=len(leaves),triangles=len(out),heightSamples=samples,minimumCellLimitReached=max_terminal_error>tolerance)
        print('ADAPTIVE TERRAIN',self.report['tessellation'],flush=True)
        return out


def repair_slits(road, max_width=.05):
    """Fill only enclosed slits whose every sampled interior point is within 2.5 cm
    of the source boundary. Outer contours and broad islands remain untouched.
    """
    repairs=[]
    polygons=[road] if road.geom_type=='Polygon' else list(road.geoms)
    for p in polygons:
        for ring in p.interiors:
            hole=Polygon(ring)
            if not (1e-4 < hole.area < 1): continue
            # Interior midpoint of every constrained triangle + representative
            # point: catch wide bulbs attached to an otherwise very thin slit.
            triangles=sh.get_parts(sh.constrained_delaunay_triangles(hole))
            samples=np.array([t.centroid.coords[0] for t in triangles]+[hole.representative_point().coords[0]])
            radius=float(np.max(sh.distance(sh.points(samples),hole.boundary)))
            if radius>max_width/2 or not hole.buffer(-max_width/2).is_empty: continue
            repairs.append(dict(type='enclosed-slit',geometry=mapping(hole),areaM2=hole.area,maxSampledHalfWidthM=radius,
                evidence='inferred enclosed contour slit; source geometry retained',widthLimitM=max_width))
    return sh.union_all([road]+[shape(r['geometry']) for r in repairs]), repairs

#!/usr/bin/env python3
"""Build a mixed-provider city in one metric frame before transport tiling.

Yandex owns physical geometry; 2GIS owns DEM and point vegetation. No provider
IDs or hand-picked locations are used to repair geometry or plant conflicts.
"""
import argparse, collections, gc, gzip, hashlib, json, math, shutil, sys, pickle
from pathlib import Path
import numpy as np
import shapely as sh
from shapely.ops import substring
from pyproj import Transformer
from prepare_supplement import Terrain
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'prototype/tiling'))
from object_geometry import pack

IDENTITY=[1,0,0,0,0,1,0,0,0,0,1,0]
R=math.pi*6378137
BASE_SCALE={'bush':.276,'low':.474,'growth':.378,'spruce':.396,'open':.45,'birch':.42,'thuja':.48,'compact':.42,'pine':.36}
WIDTHS={'1':20,'2':18,'3':14,'4':12,'5':9,'6':7,'7':5.5,'8':3.5,'9':3,'10_pedestrian':1.6,'10_park':2.4,'crosswalk':2.4,'stairs':2.0,'construction':4}

def dump(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,separators=(',',':'))+'\n')
def polygons(g):
    if g.geom_type=='Polygon':
        if g.area>1e-7:yield g
    elif hasattr(g,'geoms'):
        for p in g.geoms:yield from polygons(p)
def lines(g):
    if g.geom_type in ('LineString','LinearRing'):
        if g.length>1e-6:yield g
    elif hasattr(g,'geoms'):
        for p in g.geoms:yield from lines(p)
def clean(g):return sh.make_valid(g) if not g.is_valid else g
def union(gs):return clean(sh.union_all(gs)) if gs else sh.Polygon()
def cdt(g):
    parts=list(polygons(g))
    if not parts:return np.empty((0,3,2))
    out=[]
    for p in parts:
        for t in sh.get_parts(sh.constrained_delaunay_triangles(p)):
            out.append(np.asarray(t.exterior.coords)[:3,:2])
    return np.asarray(out).reshape(-1,3,2)
def metadata(f,suffix):return next((v for k,v in f['metadata'].items() if k.endswith('.'+suffix)),None)

def clip_circle_attributes(triangles,circle):
    """Convex polygon clip with every attribute interpolated, including height."""
    xy=triangles[:,:,[0,2]].copy();xy[:,:,1]*=-1
    inside=np.linalg.norm(xy,axis=2).max(1)<2999.99
    nearest=np.maximum(xy.min(1),np.minimum(np.zeros((len(xy),2)),xy.max(1)))
    outside=np.linalg.norm(nearest,axis=1)>3000.00001
    output=[triangles[inside]];boundary=np.asarray(circle.exterior.coords)
    # Shapely buffer rings are clockwise, so the interior is right of each edge.
    for tri in triangles[~inside&~outside]:
        pts=[v.copy() for v in tri]
        for a,b in zip(boundary[:-1],boundary[1:]):
            if not pts:break
            edge=b-a
            def signed(v):return edge[1]*(v[0]-a[0])-edge[0]*(-v[2]-a[1])
            values=[signed(v) for v in pts]
            if min(values)>=-1e-8:continue
            result=[]
            for j,p in enumerate(pts):
                q=pts[(j+1)%len(pts)];u=values[j];v=values[(j+1)%len(pts)]
                if u>=0:result.append(p)
                if (u>=0)!=(v>=0):result.append(p+(q-p)*(u/(u-v)))
            pts=result
        if len(pts)>2:output.append(np.array([[pts[0],pts[i],pts[i+1]] for i in range(1,len(pts)-1)]))
    return np.concatenate(output)

class Builder:
    def __init__(self,source,out,reference):
        self.source,self.out,self.ref=source,out,reference;self.full=out/'canonical/full';self.full.mkdir(parents=True,exist_ok=True)
        self.supp=json.loads((source/'supplement-2gis/audit.json').read_text());self.project=Transformer.from_crs('EPSG:3395',self.supp['crs'],always_xy=True)
        self.terrain=Terrain(np.load(source/'supplement-2gis/terrain.npz')['triangles']);self.alt=float(self.terrain.sample([[0,0]])[0]);self.circle=sh.Point(0,0).buffer(3000,quad_segs=512)
        self.refscene=json.loads((reference/'scene.json').read_text());self.materials=[];self.matmap={};self.textures={};self.chunks=[];self.instances=[];self.batches=collections.defaultdict(list);self.features=[];self.audit=collections.Counter();self.buildings=[];self.models=[];self.embedded=[];self.paint=[];self.rails=[];self.fences=[];self.groups=collections.defaultdict(list);self.rows=[];self.support={};self.covered=[]
        for i in (0,1,2,3,4,5,6,7,9,10,13,25,26,27,28,29,30,31,317,327,329):self.material(i)
        # The reference manifest contains hundreds of thousands of instance
        # dictionaries. It is immutable; don't rescan it for each new polygon.
        gc.freeze()
        self.building_tops=[]
        self.approaches=collections.defaultdict(list)
        self.batch_counts=collections.Counter()
        gc.disable()
    def texture(self,name,folder):
        name=Path(name).name;raw=(folder/name).read_bytes();(self.full/name).write_bytes(raw);self.textures[name]={'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
    def material(self,index):
        if index not in self.matmap:
            m=dict(self.refscene['materials'][index]);self.matmap[index]=len(self.materials);self.materials.append(m)
            if m.get('texture'):self.texture(m['texture'],self.ref)
        return self.matmap[index]
    def xy(self,vertices):
        a=np.asarray([[p['x'],p['y']] for p in vertices])*R
        return np.column_stack(self.project.transform(a[:,0],a[:,1]))
    def geometry(self,f):
        ps=[];ls=[]
        for p in f['geometry'].get('polygons',[]):
            rings=[self.xy(r) for r in p['vertexRings'] if len(r)>=3]
            if rings:ps.append(clean(sh.Polygon(rings[0],rings[1:])))
        for p in f['geometry'].get('polylines',[]):
            if len(p['vertices'])>1:ls.append(sh.LineString(self.xy(p['vertices'])))
        return union(ps).intersection(self.circle),union(ls).intersection(self.circle)
    def read(self):
        cache=self.source/'projected-scene-v1.pickle'
        if cache.exists():
            with cache.open('rb') as stream:self.rows,self.features,self.models,self.embedded=pickle.load(stream)
            print('SOURCE CACHE',len(self.rows),flush=True);return
        groups={}
        for file in sorted((self.source/'decoded').glob('*.json.gz')):
            tile=json.loads(gzip.decompress(file.read_bytes()))
            for f in tile['features']:
                g,l=self.geometry(f)
                if g.is_empty and l.is_empty:continue
                # Source node placeholders are full tile rectangles, not footprints.
                if metadata(f,'GLB_NODE_METADATA'):
                    self.embedded.append((tile['sourceTile'],f));continue
                if f['layer']=='model_a':self.models.append((tile['sourceTile'],f,g));continue
                fid=str(f.get('id')) if f.get('id') is not None else hashlib.sha256((g.wkb_hex+l.wkb_hex).encode()).hexdigest()[:24]
                key=(f['layer'],fid,json.dumps(f['attributes'],sort_keys=True))
                if key not in groups:groups[key]=[f,[],[]]
                if not g.is_empty:groups[key][1].append(g)
                if not l.is_empty:groups[key][2].append(l)
        for (layer,fid,_),(f,ps,ls) in groups.items():
            g,l=union(ps),union(ls);a=f['attributes'];self.rows.append((f,g,l))
            self.features.append(dict(id='yandex:'+layer+':'+fid,source='yandex',layer=layer,properties=a,semantics={'purpose':layer}))
        print('SOURCE',len(self.rows),'features',len(self.models),'model fragments',len(self.embedded),'embedded nodes',flush=True)
        with cache.open('wb') as stream:pickle.dump((self.rows,self.features,self.models,self.embedded),stream,protocol=5)
    def add(self,t,mat,name,tint=None):
        if not len(t):return
        t=np.asarray(t,dtype=float);assert np.isfinite(t).all()
        mats=np.full(len(t),mat,dtype=np.uint32) if np.isscalar(mat) else np.asarray(mat,dtype=np.uint32)
        self.batches[name].append((t,mats,np.ones((len(t),3)) if tint is None else np.maximum(tint,1e-6)))
        self.batch_counts[name]+=len(t)
        if self.batch_counts[name]>90000:self.flush(name)
    def flush(self,name):
        parts=self.batches[name]
        if not parts:return
        t=np.concatenate([p[0] for p in parts]);m=np.concatenate([p[1] for p in parts]);tint=np.concatenate([p[2] for p in parts]);self.batches[name]=[];self.batch_counts[name]=0
        idx=len(self.chunks);file=f'mesh-{idx:03}.bin.gz';info=pack(t,m,self.full/file,tints=None if np.all(tint==1) else tint)
        if info:
            self.chunks.append(dict(id=idx,name=name,category='building' if name in ('buildings','landmarks','industrial-chimneys') else 'fence' if name=='street-fences' else name,file=file,**info))
            self.instances.append(dict(mesh=idx,matrix=IDENTITY))
    def surface(self,g,mat,name,offset=0,height=None):
        # Clip against the actual DEM triangles, not a coarse resampling grid.
        parts=[]
        for polygon in polygons(g):
            if sh.get_num_coordinates(polygon)>1500:
                x0,y0,x1,y1=polygon.bounds
                for x in range(math.floor(x0/250)*250,math.ceil(x1/250)*250,250):
                    for y in range(math.floor(y0/250)*250,math.ceil(y1/250)*250,250):
                        parts.extend(polygons(clean(sh.clip_by_rect(polygon,x,y,x+250,y+250))))
            else:parts.append(polygon)
        for poly in parts:
            for index in self.terrain.tree.query(poly,predicate='intersects'):
                xy=cdt(poly.intersection(self.terrain.polygons[index]))
                if not len(xy):continue
                z=xy@self.terrain.planes[index,:2]+self.terrain.planes[index,2] if height is None else height(xy.reshape(-1,2)).reshape(xy.shape[:2])
                t=np.zeros((len(xy),3,8));t[:,:,0]=xy[:,:,0];t[:,:,1]=z+offset-self.alt;t[:,:,2]=-xy[:,:,1];t[:,:,6:8]=xy*.1
                n=np.cross(t[:,1,:3]-t[:,0,:3],t[:,2,:3]-t[:,0,:3]);flip=n[:,1]<0;t[flip]=t[flip][:,[0,2,1]];n[flip]*=-1;n/=np.maximum(np.linalg.norm(n,axis=1,keepdims=True),1e-20);t[:,:,3:6]=n[:,None,:];self.add(t,mat,name)
    def flat(self,g,z,mat,name):self.surface(g,mat,name,height=lambda xy:np.full(len(xy),z))
    def road_curbs(self):
        from curbs import band,LAND_RAISE,CURB_WIDTH
        openings=[]
        for (kind,level,placement),geometries in self.groups.items():
            if placement=='deck' and kind in ('road','rail'):
                openings.extend(g.buffer(.2,join_style='mitre',mitre_limit=2) for g in geometries)
        for f,g,l in self.rows:
            a=f['attributes']
            if int(a.get('z_level',0)) or a.get('struct','none') not in ('none',''):continue
            if f['layer']=='road' and a.get('class') in ('crosswalk','stairs'):
                openings.append(l.buffer(WIDTHS[a['class']]/2+.2,cap_style='square'))
            if f['layer'].startswith('hd_road_marking') and any('crosswalk' in str(v).lower() or 'zebra' in str(v).lower() or 'polygonal-pedestrian' in str(v).lower() for v in a.values()):
                openings.append(g.buffer(.35))
        opening=union(openings+[self.holes,self.building_footprint,self.finished['water']])
        self.road_curb=band(self.finished['road'],opening,self.circle.buffer(-.02),1e-5)
        # Same Moscow dimensions, measured from this adapter's asphalt datum.
        road_offset=.035;top=road_offset+LAND_RAISE
        self.surface(self.road_curb,self.material(9),'road-curbs',offset=top)
        self.boundary_walls(self.road_curb,lambda xy:self.terrain.sample(xy)+road_offset,
                            lambda xy:self.terrain.sample(xy)+top,self.material(9),'road-curbs')
        self.road_curb_audit={'widthM':CURB_WIDTH,'heightAboveRoadM':LAND_RAISE,'areaM2':self.road_curb.area,
                             'roadOverlapM2':self.road_curb.intersection(self.finished['road']).area,
                             'openingOverlapM2':self.road_curb.intersection(opening).area,
                             'policy':'Moscow curb band on the union of ground roads, before tile cuts; source crossings and other-level approaches stay open.'}
        print('ROAD CURBS',self.road_curb_audit,flush=True)
    def boundary_walls(self,g,bottom,top,mat,name,*,inward=False,clip=None):
        """Face the air, independent of source/boolean polygon winding.

        wall() faces right of a directed edge in the East/North plane. Solid
        exteriors must therefore be CCW and courtyard rings CW. A roof recess
        is a void, so its wall faces the opposite way. Keep ring order and UVs;
        reverse only triangle winding and its matching shading normal.
        """
        for p in polygons(g):
            for hole,ring in enumerate([p.exterior,*p.interiors]):
                reverse=(bool(sh.is_ccw(ring))==bool(hole)) != inward
                # Clip each directed segment separately: GEOS may reverse a
                # line intersection, which must not reverse a wall's front.
                if clip is None:
                    self.wall(ring,bottom,top,mat,name,reverse=reverse)
                else:
                    xy=np.asarray(ring.coords)
                    for a,b in zip(xy[:-1],xy[1:]):
                        for line in lines(sh.LineString([a,b]).intersection(clip)):
                            q=np.asarray(line.coords)
                            if np.dot(q[-1]-q[0],b-a)<0:line=sh.reverse(line)
                            self.wall(line,bottom,top,mat,name,reverse=reverse)
    def wall(self,line,bottom,top,mat,name,uvheight=3,*,reverse=False):
        for part in lines(line):
            xy=np.asarray(sh.segmentize(part,5).coords);z0=np.full(len(xy),bottom) if np.isscalar(bottom) else bottom(xy);z1=np.full(len(xy),top) if np.isscalar(top) else top(xy)
            length=np.r_[0,np.cumsum(np.linalg.norm(np.diff(xy,axis=0),axis=1))]
            a=np.column_stack([xy[:,0],z0-self.alt,-xy[:,1]]);b=np.column_stack([xy[:,0],z1-self.alt,-xy[:,1]])
            t=np.zeros((2*(len(xy)-1),3,8));t[::2,:,:3]=np.stack([a[:-1],a[1:],b[1:]],axis=1);t[1::2,:,:3]=np.stack([a[:-1],b[1:],b[:-1]],axis=1)
            uv0=np.column_stack([length,z0/uvheight]);uv1=np.column_stack([length,z1/uvheight]);t[::2,:,6:8]=np.stack([uv0[:-1],uv0[1:],uv1[1:]],axis=1);t[1::2,:,6:8]=np.stack([uv0[:-1],uv1[1:],uv1[:-1]],axis=1)
            if reverse:t=t[:,[0,2,1]]
            n=np.cross(t[:,1,:3]-t[:,0,:3],t[:,2,:3]-t[:,0,:3]);n/=np.maximum(np.linalg.norm(n,axis=1,keepdims=True),1e-20);t[:,:,3:6]=n[:,None,:];self.add(t,mat,name)
    def node_world(self,t,tile,transform=None):
        size=2*R/2**tile['z'];left=-R+tile['x']*size;top=R-tile['y']*size
        p=t[:,:,:3]
        if transform is not None:
            a=np.array(transform).reshape(4,3).T;p=p@a[:,:3].T+a[:,3]
        mx=left+p[:,:,0]*size;my=top-p[:,:,2]*size
        x,y=self.project.transform(mx.ravel(),my.ravel());xy=np.column_stack([x,y]).reshape(p.shape[0],3,2)
        # Ellipsoidal Mercator scale converts source projected metres to metres.
        lat=math.radians(51.725354);factor=math.cos(lat)/math.sqrt(1-.00669437999014*math.sin(lat)**2)
        return xy,p[:,:,1]*size*factor
    def import_models(self):
        grouped=collections.defaultdict(list)
        for tile,f,g in self.models:grouped[metadata(f,'MODEL_METADATA')['light']['id']].append((tile,f,g))
        footprints=[]
        for mid,parts in grouped.items():
            tile,f,_=parts[0];g=union([p[2] for p in parts]);manifest=json.loads((self.source/'decoded-models'/f'{mid}.json').read_text())
            remap=[]
            for m in manifest['materials']:
                remap.append(len(self.materials));self.materials.append(m)
                if m.get('texture'):self.texture(m['texture'],self.source/'decoded-models')
            anchor=g.representative_point();base=float(self.terrain.sample([[anchor.x,anchor.y]])[0])+.12
            bounds=[]
            for node in manifest['nodes'].values():
                data=np.load(self.source/'decoded-models'/node['file']);t=data['triangles'].copy().astype(float);xy,h=self.node_world(t,tile,metadata(f,'MODEL_METADATA')['light']['transform'])
                t[:,:,0]=xy[:,:,0];t[:,:,2]=-xy[:,:,1];t[:,:,1]=h+base-self.alt
                # Only whole detailed objects intersecting the circle are retained.
                # Their source geometry remains intact at the outer perimeter.
                self.add(t,np.array([remap[x] if x>=0 else self.material(317) for x in data['materials']]),'landmarks',data['tints']);bounds.append([xy.min((0,1)).tolist(),xy.max((0,1)).tolist()])
            self.building_tops.append((g,base+float(h.max())))
            footprints.append(g);self.covered.append({'sourceId':f['id'],'model':mid,'footprintAreaM2':g.area,'baseM':base,'bounds':bounds,'animatedSourceTracks':manifest.get('sourceAnimations',0)})
        self.model_footprint=union(footprints)
        print('DETAILED MODELS',len(grouped),flush=True)
    def import_transport(self):
        top_parts=collections.defaultdict(list);cuts=[]
        for tile,f in self.embedded:
            stem=f"{tile['z']}-{tile['x']}-{tile['y']}";node=str(metadata(f,'GLB_NODE_METADATA')['nodeId']);manifest=json.loads((self.source/'decoded-models'/f'{stem}.json').read_text());entry=manifest['nodes'].get(node)
            if not entry:continue
            data=np.load(self.source/'decoded-models'/entry['file']);t=data['triangles'].astype(float);xy,h=self.node_world(t,tile)
            t[:,:,0]=xy[:,:,0];t[:,:,2]=-xy[:,:,1];t[:,:,1]=h
            t=clip_circle_attributes(t,self.circle)
            if not len(t):continue
            xy=t[:,:,[0,2]].copy();xy[:,:,1]*=-1;h=t[:,:,1].copy();g=union(list(sh.polygons(xy)))
            if f['layer']=='hd_road_tunnel_hole':cuts.append(g);continue
            a=f['attributes'];typ=a.get('type','surface');level=int(a.get('z_level',0))
            t[:,:,1]=self.terrain.sample(xy.reshape(-1,2)).reshape(xy.shape[:2])+h-self.alt+.025
            n=np.cross(t[:,1,:3]-t[:,0,:3],t[:,2,:3]-t[:,0,:3]);n/=np.maximum(np.linalg.norm(n,axis=1,keepdims=True),1e-20);t[:,:,3:6]=n[:,None,:]
            if typ=='surface':
                mask=np.abs(n[:,1])>.15;top_parts[level].append(t[mask]);mat=self.material(0)
            elif 'stair' in typ or 'ramp' in typ:mat=self.material(7)
            else:mat=self.material(10)
            self.add(t,mat,'transport-structures');self.audit['embeddedTransportNodes']+=1
        self.holes=union(cuts).intersection(self.circle)
        for level,parts in top_parts.items():
            t=np.concatenate(parts);xy=t[:,:,[0,2]].copy();xy[:,:,1]*=-1;ps=sh.polygons(xy);valid=sh.area(ps)>1e-7;t=t[valid];xy=xy[valid];ps=ps[valid]
            planes=np.linalg.solve(np.concatenate([xy,np.ones((len(xy),3,1))],axis=2),t[:,:,1,None]+self.alt)[:,:,0]
            self.support[level]=(ps,sh.STRtree(ps),planes,union(list(ps)))
        print('TRANSPORT',self.audit['embeddedTransportNodes'],'nodes, levels',list(self.support),flush=True)
    def deck_height(self,level):
        def height(xy):
            h=self.terrain.sample(xy)
            for geometry,profile in self.approaches[level]:
                selected=sh.covers(geometry,sh.points(xy))
                if selected.any():h[selected]=profile(xy[selected])+.04
            # Source 3D surfaces always win over an inferred non-HD profile.
            if level in self.support:
                ps,tree,planes,_=self.support[level];pi,ti=tree.query(sh.points(xy),predicate='intersects');h[pi]=(xy[pi]*planes[ti,:2]).sum(1)+planes[ti,2]
            return h
        return height
    def classify(self):
        for f,g,l in self.rows:
            a=f['attributes'];layer=f['layer'];level=int(a.get('z_level',0));ft=a.get('ft_type_name','');kind=None
            if layer=='building':
                if metadata(f,'COVERED_BY_MODEL_METADATA') and not g.intersection(self.model_footprint).is_empty:self.audit['sourceBuildingsCoveredByModel']+=1;continue
                self.buildings.append((f,g));continue
            if layer.startswith('hd_road_marking'):self.paint.append((f,g,l));continue
            if layer=='fence_a':self.fences.append((f,g,l));continue
            if layer=='transport_way':self.rails.append((f,l));continue
            if layer in ('vegetation','vegetation_planned','hd_road_vegetation'):kind='grass'
            elif layer=='hydro_a':kind='water'
            elif layer=='hydro_l' and not l.is_empty:
                kind='water';g=l.buffer(2.2 if 'small' in ft else 4,quad_segs=3)
            elif layer=='landuse_a':
                kind='parking' if 'parking' in ft else 'cemetery' if 'cemetery' in ft else 'sand' if 'beach' in ft else None
            elif layer=='hd_road_surface':
                typ=a.get('type');kind='road' if typ in ('road','tram','railway_crossing') else 'ped' if typ in ('pedestrian','stairs') else 'island' if typ in ('divider','island') else 'rail' if typ=='railway' else None
                if a.get('struct') in ('bridge','tunnel') or level:
                    if kind:self.groups[(kind,level,'deck')].append(g)
                    continue
            elif layer=='roadnet_a':
                if 'square' in ft:kind='ped'
                elif 'bridge' in ft:
                    # Source bridge envelopes sit on the detailed source mesh.
                    level=1;kind='ped' if 'pedestrian' in ft else 'road';self.groups[(kind,level,'deck')].append(g);continue
            elif layer in ('road','road_underpass'):
                cls=a.get('class','8');ped=cls.startswith('10') or cls in ('crosswalk','stairs');kind='ped' if ped else 'road'
                if a.get('hd_covered')=='1':continue
                width=WIDTHS.get(cls,WIDTHS.get(cls.split('_')[0],3.5));g=l.buffer(width/2,quad_segs=3,join_style='bevel')
                self.audit['lineRoadsWithEstimatedWidth']+=1
                if a.get('struct')=='tunnel' or layer=='road_underpass':self.groups[(kind,-1,'deck')].append(g);continue
                if a.get('struct')=='bridge' or level:
                    self.groups[(kind,level or 1,'deck')].append(g);continue
            if kind and not g.is_empty:self.groups[(kind,0,'ground')].append(g)
        self.building_footprint=union([g for f,g in self.buildings]+[self.model_footprint])
        self.land={k:union(v).intersection(self.circle) for k,v in self.groups.items()};print('CLASSIFIED',len(self.buildings),'buildings',len(self.paint),'paint',len(self.rails),'rail',flush=True)
    def grounds(self):
        # Explicit, non-overlapping ground partition. Elevated roads do not erase rivers.
        from paving_domains import specific_square_surfaces
        square_green,square_parking=specific_square_surfaces(self.rows)
        ped_key=('ped',0,'ground')
        if ped_key in self.land:
            self.land[ped_key]=self.land[ped_key].difference(square_green.union(square_parking))
        occupied=self.building_footprint.union(self.holes);self.finished={};areas={}
        definitions=[('road',0,.035),('ped',7,.075),('rail',28,.025),('island',9,.15),('parking',31,.035),('water',13,-.12),('cemetery',25,.1),('grass',2,.1),('sand',29,0)]
        # Water takes precedence over non-HD estimates; explicit HD bridges remain above it.
        water=self.land.get(('water',0,'ground'),sh.Polygon()).difference(self.building_footprint)
        for kind,mi,offset in definitions:
            g=self.land.get((kind,0,'ground'),sh.Polygon()).difference(occupied)
            if kind not in ('water','grass','cemetery','sand'):g=g.difference(water)
            if kind in ('grass','cemetery'):g=g.difference(water)
            self.finished[kind]=g;occupied=occupied.union(g);areas[kind]=g.area
            self.surface(g,self.material(mi),'water' if kind=='water' else 'land',offset=offset)
            if kind in ('grass','cemetery','island'):
                self.boundary_walls(g,self.terrain.sample,lambda xy:self.terrain.sample(xy)+offset,self.material(9),'curbs',clip=self.circle.buffer(-.02))
            print('GROUND',kind,round(g.area),flush=True)
        remaining=self.circle.difference(occupied);self.finished['default']=remaining;self.surface(remaining,self.material(1),'land')
        # A model footprint can include an open entrance or an arcade. Keep the
        # ground below buildings too; their footprints are only exclusion masks
        # for planting and competing top-level surfaces, never holes in terrain.
        self.surface(self.building_footprint.difference(self.holes),self.material(1),'land')
        gap=self.circle.difference(union([*self.finished.values(),self.building_footprint,self.holes])).area
        assert gap<.01,('ground coverage gap',gap);self.audit['groundCoverageGapMm2']=round(gap*1e6)
        self.ground_areas=areas
        self.road_domain={0:self.finished['road']}
        for (kind,level,mode),g in self.land.items():
            if mode!='deck':continue
            support=self.support.get(level);covered=support[3] if support else sh.Polygon()
            # Exact 3D support geometry is already emitted; paint will sample it.
            extra=g.difference(covered.buffer(.02)).difference(self.holes)
            for part in polygons(extra):
                rect=np.asarray(part.minimum_rotated_rectangle.exterior.coords)[:4]
                edges=np.roll(rect,-1,axis=0)-rect;direction=edges[np.argmax(np.linalg.norm(edges,axis=1))];direction/=np.linalg.norm(direction)
                coords=np.asarray(part.exterior.coords);projected=coords@direction;start,end=projected.min(),projected.max()
                def profile(xy,d=direction,a=start,b=end,z=level):
                    along=xy@d;clearance=np.clip(np.minimum(along-a,b-along)/20,0,1)
                    return self.terrain.sample(xy)+clearance*z*5
                self.approaches[level].append((part,profile))
                self.surface(part,self.material(7 if kind=='ped' else 0),'transport-approaches',offset=.04,height=profile)
                self.audit['estimatedTransportApproachParts']+=1
            if kind=='road':self.road_domain[level]=self.road_domain.get(level,sh.Polygon()).union(g).union(covered)
        for level,data in self.support.items():self.road_domain[level]=self.road_domain.get(level,sh.Polygon()).union(data[3])
    def markings(self):
        kept=discard=0
        for f,g,l in self.paint:
            a=f['attributes'];level=int(a.get('z_level',0));domain=self.road_domain.get(level,sh.Polygon())
            if not l.is_empty:
                width=float(a.get('width',15) or 15)/100;segments=[];dash=a.get('dash','')
                for line in lines(l):
                    if dash and '_' in dash:
                        on,off=[float(x)/100 for x in dash.split('_')[:2]]
                        if on<=0:continue
                        # Stable metre phase follows provider polyline distance.
                        distance=f['geometry'].get('polylines',[{}])[0].get('distance',0)*R*math.cos(math.radians(51.725354))
                        start=-(distance%(on+off))
                        while start<line.length:
                            if start+on>0:segments.append(substring(line,max(0,start),min(line.length,start+on)).buffer(width/2,cap_style='flat'))
                            start+=on+off
                    else:segments.append(line.buffer(width/2,cap_style='flat',join_style='bevel'))
                g=g.union(union(segments))
            clipped=g.intersection(domain).difference(self.finished['water']);discard+=g.area-clipped.area;kept+=clipped.area
            self.surface(clipped,self.material(4 if a.get('color')=='yellow' else 5 if a.get('color')=='blue' else 3),'paint',offset=.055,height=self.deck_height(level))
        self.paint_audit={'sourceFeatures':len(self.paint),'renderedAreaM2':kept,'clippedOutsideRoadM2':discard,'policy':'Clip to own-level road footprint; height from same-level source 3D surface or shared ground'}
        print('PAINT',self.paint_audit,flush=True)
    def buildings_mesh(self):
        from industrial_chimneys import detect,emit
        chimneys=detect(self.buildings)
        chimney_parts={p['index'] for group in chimneys for p in group['parts']}
        emit(self,chimneys)
        self.audit['industrialChimneys']=len(chimneys)
        missing=0;count=0
        for building_index,(f,g) in enumerate(self.buildings):
            if building_index in chimney_parts:continue
            height=f['attributes'].get('height')
            if not isinstance(height,(int,float)) or height<=0:height=3.;missing+=1
            for p in polygons(g):
                samples=np.asarray(sh.segmentize(p.exterior,5).coords);base=float(np.max(self.terrain.sample(samples)))+.1;top=base+float(height)
                self.building_tops.append((p,top+.6))
                # Outer walls descend to the actual terrain, avoiding floating bases.
                self.boundary_walls(p,lambda xy:self.terrain.sample(xy),top+.6,self.material(329),'buildings')
                interior=p.buffer(-.4,join_style='mitre')
                if interior.is_empty:self.flat(p,top,self.material(327),'buildings');self.audit['smallRoofFallbacks']+=1
                else:
                    self.flat(p.difference(interior),top+.6,self.material(317),'buildings');self.flat(interior,top-.4,self.material(327),'buildings');self.boundary_walls(interior,top-.4,top+.6,self.material(317),'buildings',inward=True)
                count+=1
            if count and count%2000==0:print('BUILDINGS',count,flush=True)
        self.audit['genericBuildingParts']=count;self.audit['missingHeightFallbackBuildings']=missing
        # Source fences are polygon ribbons: preserve them as short extrusions.
        for f,g,l in self.fences:
            if g.is_empty:continue
            self.surface(g,self.material(10),'street-fences',offset=1.2)
            self.boundary_walls(g,self.terrain.sample,lambda xy:self.terrain.sample(xy)+1.2,self.material(10),'street-fences')
        for f,l in self.rails:
            if l.is_empty:continue
            a=f['attributes'];level=int(a.get('z_level',0));height=self.deck_height(level)
            for line in lines(l):
                for distance in (-.72,.72):
                    rail=line.offset_curve(distance,join_style='bevel').buffer(.045,cap_style='flat');self.surface(rail,self.material(10),'rails',offset=.09,height=height)
        print('BUILDINGS COMPLETE',dict(self.audit),flush=True)
    def vegetation(self):
        plants=json.loads(gzip.decompress((self.source/'supplement-2gis/vegetation.json.gz').read_bytes()))
        # Prepared predicates preserve geometry and avoid re-indexing a regional
        # MultiPolygon for every plant root.
        sh.prepare(self.finished['grass']);sh.prepare(self.finished['cemetery'])
        crown_bounds={}
        for model in {p['approvedModel'] for p in plants}:
            chunk=next(c for c in self.refscene['chunks'] if c['name']=='nuray-approved-'+model)
            raw=gzip.decompress((self.ref/Path(chunk['file']).name).read_bytes());words=np.frombuffer(raw[:chunk['vertexBytes']],'<u4').reshape(-1,8);v=words.view('<f4');ids=words[:,6]&0x7fffffff
            leaf=np.array([any(word in self.refscene['materials'][int(i)]['name'] for word in ('Листва','Хвоя')) for i in ids])
            crown_bounds[model]=(float(np.linalg.norm(v[leaf][:,[0,2]],axis=1).max()),float(v[leaf,1].min()))
        building_tree=sh.STRtree([p for p,top in self.building_tops]);building_tops=np.array([top for p,top in self.building_tops])
        # Root clearances are physical (stem/crown at ground), not a canopy radius:
        # a tall crown may overhang a pavement without being a collision.
        blockers={'building':self.building_footprint,'water':self.finished['water'],'road':union([*self.road_domain.values(),getattr(self,'road_curb',sh.Polygon())]), 'walkway':self.finished['ped']}
        masks={'root':{k:sh.to_wkb(v).hex() for k,v in blockers.items()},'buildings':[(sh.to_wkb(p).hex(),float(h)) for p,h in self.building_tops],'crowns':crown_bounds}
        with gzip.open(self.out/'placement-masks.json.gz','wt') as stream:json.dump(masks,stream,separators=(',',':'))
        for geometry in blockers.values():sh.prepare(geometry)
        accepted=[];rejected=[]
        for p in plants:
            xy=p['eastNorth'];model=p['approvedModel'];s=BASE_SCALE[model]*p['scale'];radius,low=crown_bounds[model];radius*=s;low*=s
            clearance=max(.22,radius if low<2.5 else .22)
            footprint=sh.Point(xy).buffer(clearance,quad_segs=4);reasons=[k for k,geometry in blockers.items() if geometry.intersects(footprint)]
            root=float(self.terrain.sample([xy])[0]);nearby=building_tree.query(sh.Point(xy).buffer(radius,quad_segs=8),predicate='intersects')
            if len(nearby) and np.any(building_tops[nearby]>root+low):reasons.append('buildingCanopy')
            if reasons:rejected.append({'id':p['id'],'lonLat':p['lonLat'],'model':model,'conflicts':reasons,'clearanceM':clearance});continue
            point=sh.Point(xy);raise_by=.1 if self.finished['grass'].covers(point) or self.finished['cemetery'].covers(point) else 0
            y=float(self.terrain.sample([xy])[0])+raise_by-self.alt;angle=p['yawRadians'];c,sn=math.cos(angle)*s,math.sin(angle)*s
            matrix=[c,0,sn,xy[0],0,s,0,y,-sn,0,c,-xy[1]];accepted.append((p,matrix))
        for model in sorted({p['approvedModel'] for p,m in accepted}):
            c=next(c for c in self.refscene['chunks'] if c['name']=='nuray-approved-'+model);raw=gzip.decompress((self.ref/Path(c['file']).name).read_bytes());words=np.frombuffer(raw[:c['vertexBytes']],'<u4').copy().reshape(-1,8)
            old=words[:,6]&0x7fffffff
            for mid in np.unique(old):words[old==mid,6]=self.material(int(mid))|0x80000000
            idx=len(self.chunks);file=f'mesh-{idx:03}.bin.gz';(self.full/file).write_bytes(gzip.compress(words.tobytes()+raw[c['vertexBytes']:],compresslevel=6,mtime=0));chunk={**c,'id':idx,'file':file};self.chunks.append(chunk)
            for p,matrix in accepted:
                if p['approvedModel']!=model:continue
                x,n=p['eastNorth'];self.instances.append(dict(id=p['id'],objectId=p['id'],mesh=idx,matrix=matrix,tileId=f'{min(23,max(0,int((x+3000)//250)))}-{min(23,max(0,int((n+3000)//250)))}'))
        assert len({p['id'] for p,m in accepted})==len(accepted)
        self.plant_audit={'source':len(plants),'accepted':len(accepted),'rejected':len(rejected),'byConflict':dict(collections.Counter(r for p in rejected for r in p['conflicts'])),'byModel':dict(collections.Counter(p['approvedModel'] for p,m in accepted)), 'policy':'Keep source XY; deterministic yaw/scale; ground root. Reject root and low crowns against roads, walkways and water; conservative canopy envelope against building heights. No arbitrary relocation. Before tiling.','rejectedPoints':rejected,'acceptedPoints':[{'id':p['id'],'eastNorth':p['eastNorth'],'model':p['approvedModel'],'matrix':m} for p,m in accepted]}
        with gzip.open(self.out/'plant-placement-audit.json.gz','wt') as f:json.dump(self.plant_audit,f,separators=(',',':'))
        print('VEGETATION', {k:v for k,v in self.plant_audit.items() if not k.endswith('Points')},flush=True)
    def finish(self):
        for name in list(self.batches):self.flush(name)
        stats={'uniqueTriangles':sum(c['triangles'] for c in self.chunks),'expandedTriangles':sum(self.chunks[i['mesh']]['triangles'] for i in self.instances)}
        scene={'version':1,'name':'Курск · радиус 3 км от цирка','origin':[0,0,self.alt],'axes':'x east, y up, z south','extentMetres':6000,'materials':self.materials,'textures':self.textures,'chunks':self.chunks,'instances':self.instances,'stats':stats}
        dump(self.full/'scene.json',scene)
        receipt=hashlib.sha256((self.source/'manifest.json').read_bytes()+(self.source/'supplement-2gis/audit.json').read_bytes()).hexdigest()
        city={'name':'Курск','crsProj':self.supp['crs'],'boundsMSK':[-3000,-3000,3000,3000],'originMSK':[0,0,self.alt],'transportTileSizeM':250,'features':self.features,'surfaces':[],
          'sourceSnapshot':{'provider':'Yandex geometry + 2GIS terrain and vegetation','freshAcquisition':True,'receiptSha256':receipt,'centerLonLat':[36.189045,51.725354],'radiusM':3000,'displayZoom':21},
          'limitations':['Non-HD road widths are class-based estimates; source 3D interchange geometry is retained.', '2GIS map terrain is not a surveyed elevation datum.', 'Non-HD transport approach heights are inferred; animation tracks in landmark models are frozen.', 'Source fences do not identify materials; rendered in neutral grey.', 'Tree coordinates are mapped source instances; conflicting root positions are excluded with a report.'],
          'objectLayer':{'stats':{'vegetationInstances':self.plant_audit['accepted'],'treeTemplates':len(self.plant_audit['byModel']),'buildingObjects':self.audit['genericBuildingParts'],'detailedModelGroups':len(self.covered)},'policy':{'vegetation':self.plant_audit['policy']}},
          'sourceStyle':{'provider':'Yandex display21 semantic layers; approved NURAY materials'},'geometryRevision':{'version':'yandex-boundaries-2'}}
        dump(self.out/'canonical/urban-model.json',city)
        report={'passed':True,'adapter':'yandex-2gis','sourceFeatures':len(self.features),'terrain':{'triangles':len(self.terrain.triangles),'originAltitude':self.alt,'fullCircleCoverage':self.circle.difference(union(list(self.terrain.polygons))).area<.01},'groundAreasM2':self.ground_areas,'paint':self.paint_audit,'geometryCounts':dict(self.audit),'landmarks':self.covered,'plants':{k:v for k,v in self.plant_audit.items() if not k.endswith('Points')},'stats':stats}
        report['roadCurbs']=getattr(self,'road_curb_audit',None)
        assert report['terrain']['fullCircleCoverage'];dump(self.out/'canonical/validation.json',report)
        np.savez_compressed(self.out/'canonical/terrain.npz',triangles=self.terrain.triangles)
        dump(self.out/'build-audit.json',report);print('CANONICAL COMPLETE',stats,flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--reference',type=Path,required=True);a=p.parse_args()
    b=Builder(a.source,a.output,a.reference);b.read();b.import_models();b.import_transport();b.classify();b.grounds();b.road_curbs();b.markings();b.buildings_mesh();b.vegetation();b.finish()
if __name__=='__main__':main()

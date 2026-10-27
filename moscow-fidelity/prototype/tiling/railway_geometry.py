"""Railway ribbons: metre-based path coordinates before any spatial tile cut.

Source map lines are retained, not inferred from the colour of a transport slab.
Only coincident endpoints at compatible physical heights are connected. Crossings
in the middle of segments never create graph nodes. Cycles close on an integer
texture period, distributing a measured phase correction along the closing edge.
"""
from collections import defaultdict, deque
import numpy as np

WIDTH = 3.4
PERIOD = .6
GAUGE = 1.52
RAIL_HEAD = .07
# Two narrow material bands on the very same UV chart as the ballast/sleepers.
BANDS = np.array([-WIDTH/2, -GAUGE/2-RAIL_HEAD, -GAUGE/2,
                   GAUGE/2, GAUGE/2+RAIL_HEAD, WIDTH/2])


def densify(points, step=.75):
    points = np.asarray(points, float)
    out = []
    for a, b in zip(points[:-1], points[1:]):
        n = max(1, int(np.ceil(np.linalg.norm((b-a)[:2])/step)))
        out.extend(a+(b-a)*t/n for t in range(n))
    return np.asarray(out+[points[-1]])


def network(records, xy_tolerance=.03, z_tolerance=.15):
    """Return oriented edges with common node positions and unwrapped station.

    Records contain id and sampled 3D points in a common metric frame. The sort
    is stable under source input order, and endpoint matching honours grade.
    """
    edges = [dict(r, points=np.asarray(r['points'], float).copy()) for r in sorted(records,key=lambda r:r['id'])]
    nodes=[]; bins=defaultdict(list); adjacency=defaultdict(list)
    for ei,e in enumerate(edges):
        ends=[]
        for end in (0,-1):
            p=e['points'][end];cell=tuple(np.floor(p[:2]/xy_tolerance).astype(int));candidates=[]
            for dx in (-1,0,1):
                for dy in (-1,0,1):
                    for ni in bins[(cell[0]+dx,cell[1]+dy)]:
                        q=nodes[ni]['point']
                        if np.linalg.norm(p[:2]-q[:2])<=xy_tolerance and abs(p[2]-q[2])<=z_tolerance:candidates.append(ni)
            if len(candidates)>1:raise ValueError('Ambiguous railway endpoint: '+e['id'])
            if candidates:ni=candidates[0];nodes[ni]['members'].append((ei,end,p.copy()))
            else:
                ni=len(nodes);nodes.append(dict(point=p.copy(),members=[(ei,end,p.copy())]));bins[cell].append(ni)
            ends.append(ni);adjacency[ni].append(ei)
        e['nodes']=ends
    max_snap=0.
    for n in nodes:
        n['point']=np.mean([m[2] for m in n['members']],axis=0)
        for ei,end,p in n['members']:
            max_snap=max(max_snap,float(np.linalg.norm(p-n['point'])))
            edges[ei]['points'][end]=n['point']
    # A minimum-length spanning forest leaves the longest cyclic edges for UV
    # closure. Thus a phase correction never gets concentrated on a tiny source
    # fragment merely because it was encountered last during traversal.
    parent=list(range(len(nodes)))
    def root_of(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    lengths=[float(np.linalg.norm(np.diff(e['points'],axis=0),axis=1).sum()) for e in edges]
    forest=set();closing=[]
    for ei in sorted(range(len(edges)),key=lambda i:(lengths[i],edges[i]['id'])):
        a,b=map(root_of,edges[ei]['nodes'])
        if a==b:closing.append(ei)
        else:parent[a]=b;forest.add(ei)
    visited=set();seen_edges=set();out=[];components=0;node_component={}
    while len(visited)<len(nodes):
        remaining=[i for i in range(len(nodes)) if i not in visited]
        leaves=[i for i in remaining if len(adjacency[i])==1]
        root=min(leaves or remaining,key=lambda i:tuple(nodes[i]['point']))
        components+=1;visited.add(root);nodes[root]['station']=0.;node_component[root]=components-1;queue=deque([root])
        while queue:
            start=queue.popleft()
            for ei in sorted(adjacency[start]):
                if ei in seen_edges or ei not in forest:continue
                seen_edges.add(ei);e=edges[ei];end=e['nodes'][1] if e['nodes'][0]==start else e['nodes'][0]
                points=e['points'] if e['nodes'][0]==start else e['points'][::-1].copy()
                station=nodes[start]['station']+np.r_[0,np.cumsum(np.linalg.norm(np.diff(points,axis=0),axis=1))]
                nodes[end]['station']=float(station[-1]);node_component[end]=components-1;visited.add(end);queue.append(end)
                out.append(dict(e,points=points,station=station,nodes=[start,end],component=components-1))
    closures=[]
    for ei in sorted(closing,key=lambda i:edges[i]['id']):
        e=edges[ei];a,b=e['nodes'];p=e['points'];length=lengths[ei]
        if length<1e-8:raise ValueError('Zero-length railway cycle: '+e['id'])
        start=nodes[a]['station'];end=nodes[b]['station']
        periods=round((start+length-end)/PERIOD)
        span=end+periods*PERIOD-start
        if span<=1e-8:span+=PERIOD
        distance=np.r_[0,np.cumsum(np.linalg.norm(np.diff(p,axis=0),axis=1))]
        station=start+distance*(span/length)
        out.append(dict(e,station=station,component=node_component[a]))
        closures.append(dict(source=e['id'],lengthM=length,phaseCorrectionM=span-length,
                             sleeperSpacingM=PERIOD*length/span))
    # A shared miter at a degree-two node makes two source records one ribbon.
    oriented={e['id']:e for e in out}
    for e in out:
        for which in (0,1):
            node=e['nodes'][which];others=[edges[i] for i in adjacency[node] if edges[i]['id']!=e['id']]
            if e['nodes'][0]==e['nodes'][1]:
                e['before' if which==0 else 'after']=e['points'][-2 if which==0 else 1]
                continue
            if len(others)==1:
                other=oriented[others[0]['id']];p=other['points']
                neighbour=p[1] if other['nodes'][0]==node else p[-2]
                e['before' if which==0 else 'after']=neighbour
    return out,dict(components=components,nodes=len(nodes),sourceEdges=len(edges),branchNodes=sum(len(v)>2 for v in adjacency.values()),maxEndpointSnapM=max_snap,
                    cycleClosures=closures,maxCycleSpacingChangeFraction=max((abs(c['sleeperSpacingM']/PERIOD-1) for c in closures),default=0))


def ribbon(edge, height, material_bed, material_rail, origin, bounds=None):
    """Unwrapped V = 3D station / period; U follows the curve's cross section.

    `height(xy, source, centreZ)` supplies the cross-section floor. Ring endpoints
    are shared at source joints. No modulo is applied before interpolation.
    """
    p=edge['points'];station=edge['station'];xy=p[:,:2]
    prev=np.vstack([edge.get('before',p[0]-(p[1]-p[0])),p[:-1]])[:,:2]
    nxt=np.vstack([p[1:],edge.get('after',p[-1]+(p[-1]-p[-2]))])[:,:2]
    a=xy-prev;b=nxt-xy;a/=np.maximum(np.linalg.norm(a,axis=1)[:,None],1e-12);b/=np.maximum(np.linalg.norm(b,axis=1)[:,None],1e-12)
    left_a=np.column_stack([-a[:,1],a[:,0]]);left_b=np.column_stack([-b[:,1],b[:,0]])
    m=left_a+left_b;length=np.linalg.norm(m,axis=1)
    m/=np.maximum(length[:,None],1e-12)
    denom=(m*left_b).sum(1)
    bad=denom<.4;outside=np.zeros(len(p),bool)
    if bounds is not None:
        # Source records continue well beyond the requested region. A remote
        # cusp must not abort or create a giant miter inside the exported area.
        # Permit a bounded placeholder only when BOTH incident segments and
        # their complete maximum-width envelope are outside the region.
        lo=np.minimum(np.minimum(prev,xy),nxt);hi=np.maximum(np.maximum(prev,xy),nxt)
        margin=WIDTH/2/.4
        outside=(hi[:,0]+margin<bounds[0])|(lo[:,0]-margin>bounds[2])|(hi[:,1]+margin<bounds[1])|(lo[:,1]-margin>bounds[3])
    if np.any(bad&~outside):raise ValueError('Railway bend needs a bevel or an explicit junction: '+edge['id'])
    edge['outsideRegionMiters']=int(np.count_nonzero(bad&outside))
    m[bad&(length<1e-12)]=left_b[bad&(length<1e-12)]
    denom=np.maximum(denom,.4)
    m/=denom[:,None]
    rings=np.zeros((len(p),len(BANDS),8),float)
    for i in range(len(p)):
        coords=xy[i]+BANDS[:,None]*m[i]
        heights=height(coords,edge,p[i,2])
        rings[i,:,0]=coords[:,0]-origin[0];rings[i,:,1]=heights-origin[2];rings[i,:,2]=origin[1]-coords[:,1]
        rings[i,:,6]=(BANDS+WIDTH/2)/WIDTH;rings[i,:,7]=station[i]/PERIOD
    # Smooth normals use the transported tangent. Shared endpoints get the same
    # horizontal frame; a slight floor pitch is retained inside each source edge.
    along=np.gradient(rings[:,:,:3],axis=0);across=rings[:,-1,:3]-rings[:,0,:3]
    normals=np.cross(along,across[:,None]);normals/=np.maximum(np.linalg.norm(normals,axis=2,keepdims=True),1e-12)
    normals=np.where(normals[:,:,1,None]<0,-normals,normals);rings[:,:,3:6]=normals
    ts=[];ms=[]
    for i in range(len(rings)-1):
        for j in range(len(BANDS)-1):
            quad=[rings[i,j],rings[i,j+1],rings[i+1,j+1],rings[i+1,j]]
            for ids in ((0,1,2),(0,2,3)):
                t=np.asarray([quad[k] for k in ids])
                if np.cross(t[1,:3]-t[0,:3],t[2,:3]-t[0,:3])[1]<0:t=t[[0,2,1]]
                ts.append(t);ms.append(material_rail if j in (1,3) else material_bed)
    return np.asarray(ts),np.asarray(ms,dtype=np.uint32),rings

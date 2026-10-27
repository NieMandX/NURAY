"""Geometric regressions for the foundation rule, independent of Moscow IDs."""
from types import SimpleNamespace
import numpy as np
import shapely as sh
from adaptive_foundations import base_edges, panels_for_edge, panel_triangles, eligible, BURIAL


def surface(strips):
    tris=[]
    for x0,x1,y0,y1 in strips:
        a,b,c,d=np.array([[x0,y0,-2],[x1,y1,-2],[x1,y1,2],[x0,y0,2.]])
        tris.extend([[a,b,c],[a,c,d]])
    tris=np.array(tris);polys=sh.polygons(tris[:,:,[0,2]])
    return SimpleNamespace(tris=tris,tree=sh.STRtree(polys),refs=[(0,i) for i in range(len(tris))])


def facade(a,b,height=3):
    a,b=np.array(a,float),np.array(b,float);c=a+[0,height,0];d=b+[0,height,0]
    return np.array([[a,b,d],[a,d,c]])


def test_slope_and_flat():
    a,b=np.array([0,0,0.]),np.array([10,0,0.])
    pp,missing=panels_for_edge(a,b,surface([(0,10,0,-5)]))
    assert missing<1e-8 and pp and max(p['maxGapM'] for p in pp)==5
    for p in pp:
        bottom=np.array(p['bottom']);assert np.allclose(bottom[:,1],-.5*bottom[:,0]-BURIAL)
    assert not panels_for_edge(a,b,surface([(0,10,0,0)]))[0]
    assert not panels_for_edge(a,b,surface([(0,10,1,1)]))[0]


def test_valley_and_crossing():
    a,b=np.array([0,0,0.]),np.array([10,0,0.])
    pp,_=panels_for_edge(a,b,surface([(0,5,0,-3),(5,10,-3,0)]))
    assert any(abs(q[0]-5)<1e-8 and abs(q[1]+3+BURIAL)<1e-8 for p in pp for q in p['bottom'])
    pp,_=panels_for_edge(a,b,surface([(0,10,2,-2)]))
    assert min(q[0] for p in pp for q in p['top'])==5


def test_void_and_upper_envelope():
    a,b=np.array([0,0,0.]),np.array([10,0,0.])
    pp,missing=panels_for_edge(a,b,surface([(0,4,-2,-2),(6,10,-2,-2)]))
    assert abs(missing-2)<1e-8
    assert all(max(q[0] for q in p['top'])<=4 or min(q[0] for q in p['top'])>=6 for p in pp)
    pp,_=panels_for_edge(a,b,surface([(0,10,-2,-4),(0,10,-4,-2)]))
    for p in pp:
        bottom=np.array(p['bottom']);x=bottom[:,0]
        assert np.allclose(bottom[:,1]+BURIAL,np.maximum(-2-.2*x,-4+.2*x))


def test_arch_and_courtyard():
    # Two ground-level piers and an elevated lintel: no foundation under the opening.
    t=np.concatenate([facade([0,0,0],[2,0,0]),facade([4,0,0],[6,0,0]),facade([2,3,0],[4,3,0])])
    edges=base_edges(t,0)
    assert len(edges)==2 and all(not(a[0]<3<b[0]) for a,b in edges)
    # A concave outline and inner courtyard keep their exact edges. No convex hull.
    outer=[[0,0,0],[8,0,0],[8,0,4],[4,0,4],[4,0,8],[0,0,8]]
    inner=[[1,0,1],[1,0,3],[3,0,3],[3,0,1]]
    t=np.concatenate([facade(a,b) for ring in [outer,inner] for a,b in zip(ring,ring[1:]+ring[:1])])
    assert len(base_edges(t,0))==10
    assert not base_edges(t,20)
    row=dict(category='building',sourceLayer='Canopy_1',placement=dict(targetBaseM=1,sourceBaseM=1))
    assert not eligible(row)
    assert not eligible({**row,'sourceLayer':'Dwelling_house_roof_2'})
    assert eligible({**row,'sourceLayer':'Dwelling_house_2'})


def test_exact_top_and_normals():
    a,b=np.array([0,.0004,0.]),np.array([10,.0005,0.])
    pp,_=panels_for_edge(a,b,surface([(0,10,-1,-4)]))
    assert np.array_equal(np.array(pp[0]['top'])[0],a)
    assert np.array_equal(np.array(pp[-1]['top'])[1],b)
    for p in pp:
        t=panel_triangles(p);n=t[:,:,3:6]
        assert np.allclose(np.linalg.norm(n,axis=2),1)
        assert np.allclose(np.sum(n[:,0]*(t[:,1,:3]-t[:,0,:3]),axis=1),0)
        assert np.allclose(np.sum(n[:,0]*(t[:,2,:3]-t[:,0,:3]),axis=1),0)


def test_bounded_contact_and_zero_precision():
    # Source foot is 1 cm beyond the finished surface; a broad real void remains open.
    g=surface([(0,10,-1,-1)])
    a,b=np.array([0,0,2.01]),np.array([10,0,2.01])
    pp,missing=panels_for_edge(a,b,g)
    assert pp and missing<1e-8 and all(abs(p['groundOffsetM'][1])==.025 for p in pp)
    assert not panels_for_edge(a+[0,0,.1],b+[0,0,.1],g)[0]
    a,b=np.array([1.1e-16,0,0]),np.array([10,0,0])
    pp,_=panels_for_edge(a,b,g)
    assert pp[0]['top'][0][0]==0.


def test_outward_winding():
    for a,b in [([0,0,0],[10,0,0]),([10,0,0],[0,0,0]),([0,0,1],[0,0,-1])]:
        t=facade(a,b);normal=np.cross(t[0,1]-t[0,0],t[0,2]-t[0,0])
        aa,bb=base_edges(t,0)[0]
        assert np.dot(np.cross([0,-1,0],bb-aa),normal)>0


def test_kilometre_offset_float32_column_collapse():
    a=np.array([2400.00013,10.,2400.00013]);b=np.array([2400.00029,10.,2400.00029])
    assert np.linalg.norm((b-a)[[0,2]])>.0001
    panel=dict(top=[a.tolist(),b.tolist()],bottom=[(a-[0,1,0]).tolist(),(b-[0,1,0]).tolist()])
    assert len(panel_triangles(panel))==0
    b=a+[.02,0,.02]
    panel=dict(top=[a.tolist(),b.tolist()],bottom=[(a-[0,1,0]).tolist(),(b-[0,1,0]).tolist()])
    assert len(panel_triangles(panel))==2


def test_coverage_on_nearly_collinear_panel_chain():
    from prepare_foundations import covers_base_probe
    # A real coordinate/rounding pattern: buffering this nearly collinear
    # chain as one network can silently discard its first branch in GEOS.
    chain=np.array([[191.3875579834,-778.5220031877],
                    [191.8120117188,-778.2314453125],
                    [192.4438476562,-778.0849609375],
                    [192.4694170748,-778.1016649218],
                    [192.4986146387,-778.1207391],
                    [192.529146521,-778.1406849616],
                    [192.9909667969,-778.4423828125]])
    tree=sh.STRtree([sh.LineString([a,b]) for a,b in zip(chain,chain[1:])])
    p=np.array([192.1279296875,0.,-778.158203125])
    assert covers_base_probe(tree,p)
    direction=chain[2]-chain[1];normal=np.array([-direction[1],direction[0]])/np.linalg.norm(direction)
    q=p.copy();q[[0,2]]+=normal*.0001
    assert covers_base_probe(tree,q)
    q=p.copy();q[[0,2]]+=normal*.0002
    assert not covers_base_probe(tree,q)
    assert not covers_base_probe(sh.STRtree([]),p)


def test_rounded_boundary_contact_and_real_void():
    import copy,json
    from pathlib import Path
    from prepare_foundations import foundation_contact
    from street_placement import SurfaceSampler
    cases=json.loads((Path(__file__).parents[1]/'fixtures/foundation-rounded-contact.json').read_text())['cases']
    for case in cases:
        g=object.__new__(SurfaceSampler);g.tris=np.array([case['triangle']]);g.refs=[case['reference']]
        g.polys=sh.polygons(g.tris[:,:,[0,2]]);g.tree=sh.STRtree(g.polys)
        p=case['panel'];s=case['station'];bottom=np.asarray(p['bottom']);q=bottom[0]+s*(bottom[1]-bottom[0])
        assert g.ground(*(q[[0,2]]+p['groundOffsetM'])) is None
        hit=foundation_contact(g,p,s)
        assert hit and hit['boundaryRoundingM']<1e-10
        assert abs(q[1]+BURIAL-hit['height'])<1e-9
        wrong=copy.deepcopy(p);wrong['ground']=[-1,-1]
        assert foundation_contact(g,wrong,s) is None
        # Move away from the real edge: even a 0.1 micrometre gap is not
        # attributable to the constructor's rounding and must still fail.
        xz=q[[0,2]]+p['groundOffsetM'];edge=sh.shortest_line(sh.Point(xz),g.polys[0])
        closest=np.array(edge.coords[-1]);direction=xz-closest;direction/=np.linalg.norm(direction)
        displaced=copy.deepcopy(p)
        for row in displaced['bottom']:
            row[0]+=direction[0]*1e-7;row[2]+=direction[1]*1e-7
        assert foundation_contact(g,displaced,s) is None


def test_rounded_step_contact_keeps_upper_envelope():
    import copy,json
    from pathlib import Path
    from prepare_foundations import foundation_contact
    from street_placement import SurfaceSampler
    cases=json.loads((Path(__file__).parents[1]/'fixtures/foundation-rounded-step-contact.json').read_text())['cases']
    for case in cases:
        g=object.__new__(SurfaceSampler);g.tris=np.array(case['triangles']);g.refs=case['references']
        g.polys=sh.polygons(g.tris[:,:,[0,2]]);g.tree=sh.STRtree(g.polys)
        p=case['panel'];s=case['station'];bottom=np.asarray(p['bottom']);q=bottom[0]+s*(bottom[1]-bottom[0])
        xz=q[[0,2]]+p['groundOffsetM'];strict=g.ground(*xz)
        assert strict and abs(q[1]+BURIAL-strict['height'])>.099
        hit=foundation_contact(g,p,s)
        assert hit and hit['boundaryRoundingM']<1e-10
        assert abs(q[1]+BURIAL-hit['height'])<1e-9
        closest=np.array(sh.shortest_line(sh.Point(xz),g.polys[0]).coords[-1])
        direction=xz-closest;direction/=np.linalg.norm(direction)
        displaced=copy.deepcopy(p)
        for row in displaced['bottom']:
            row[0]+=direction[0]*1e-7;row[2]+=direction[1]*1e-7
        assert abs(q[1]+BURIAL-foundation_contact(g,displaced,s)['height'])>.099
        # Another real higher floor must not be suppressed by declared ownership.
        g.tris[1,:,1]+=1
        assert foundation_contact(g,p,s)['height']>q[1]+BURIAL+.8


def test_base_probe_on_raised_surface_boundary():
    import json
    from pathlib import Path
    from prepare_foundations import base_probe_ground
    from street_placement import SurfaceSampler
    c=json.loads((Path(__file__).parents[1]/'fixtures/foundation-rounded-base-probe.json').read_text())
    g=object.__new__(SurfaceSampler);g.tris=np.array(c['triangles']);g.refs=c['references']
    g.polys=sh.polygons(g.tris[:,:,[0,2]]);g.tree=sh.STRtree(g.polys)
    a,b=np.array(c['a']),np.array(c['b']);s=c['station'];q=a+s*(b-a)
    assert q[1]-g.ground(q[0],q[2])['height']>.04
    hit=base_probe_ground(g,a,b,s)
    assert hit['height']>q[1] and hit['boundaryRoundingM']<1e-12
    edge=(b-a)[[0,2]];direction=np.array([-edge[1],edge[0]])/np.linalg.norm(edge)
    if direction@(g.tris[1][:,[0,2]].mean(axis=0)-q[[0,2]])>0:direction=-direction
    shift=np.array([direction[0],0,direction[1]])*1e-7
    # A genuine offset on the lower surface still requires a foundation.
    assert q[1]-base_probe_ground(g,a+shift,b+shift,s)['height']>.04
    g.tris=g.tris[:1];g.refs=g.refs[:1];g.polys=g.polys[:1];g.tree=sh.STRtree(g.polys)
    assert q[1]-base_probe_ground(g,a,b,s)['height']>.04


if __name__=='__main__':
    for test in [test_slope_and_flat,test_valley_and_crossing,test_void_and_upper_envelope,test_arch_and_courtyard,test_exact_top_and_normals,test_bounded_contact_and_zero_precision,test_outward_winding,test_kilometre_offset_float32_column_collapse,test_coverage_on_nearly_collinear_panel_chain,test_rounded_boundary_contact_and_real_void,test_rounded_step_contact_keeps_upper_envelope,test_base_probe_on_raised_surface_boundary]:
        test();print('PASS',test.__name__)

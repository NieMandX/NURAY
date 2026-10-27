import numpy as np
import shapely as sh
from road_quality import quality

def test_collapsed_reference_lines_do_not_change_road_audit():
    a,b=sh.box(0,0,5,5),sh.box(5,0,10,5)
    rows=[dict(kind='roadbed_flat',poly=p,plane=np.array([.01,.02,100.])) for p in (a,b)]
    mixed=[{**r,'poly':sh.GeometryCollection([r['poly'],sh.LineString([(12,0),(12,5)]),sh.Point(20,20)])} for r in rows]
    assert quality(rows)==quality(mixed)

if __name__=='__main__':
    test_collapsed_reference_lines_do_not_change_road_audit()
    print('Road quality ignores collapsed non-areal overlay remnants')

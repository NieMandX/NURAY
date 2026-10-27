import numpy as np
import shapely as sh
from build import plane,triangulate,z_at

def test_narrow_map_coordinate_triangle():
    xy=np.array([[4500.,9500.],[4500.00002,9500.00001],[4500.00001,9500.000015]])
    expected=np.array([.2,-.3,150.])
    t=np.column_stack((xy,z_at(expected,xy)))
    recovered=plane(t)
    assert np.max(np.abs(z_at(recovered,xy)-t[:,2]))<1e-10
    for p in [sh.Polygon(xy),sh.Polygon(xy[::-1])]:
        result=triangulate(p,expected)
        assert result and all(sh.Polygon(q[:,:2]).area>0 for q in result)
        assert abs(sum(sh.Polygon(q[:,:2]).area for q in result)-p.area)<1e-18

def test_zero_area_plane_is_rejected():
    try:plane(np.array([[4500,9500,1],[4501,9501,2],[4502,9502,3]]))
    except ValueError:pass
    else:raise AssertionError('A collinear triangle cannot define a plane')

if __name__=='__main__':
    test_narrow_map_coordinate_triangle();test_zero_area_plane_is_rejected()
    print('Stable map-coordinate planes passed')

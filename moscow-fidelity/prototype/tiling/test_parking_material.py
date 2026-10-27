"""Parking appearance must not change ownership or spill over detailed paving."""
import sys
from pathlib import Path
import numpy as np
import shapely as sh
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from parking_cover import owns_surface, material, MATERIAL_INDEX
from semantics import classify
from material_remap import remap
from prepare_cemetery_cover import choose_faces


def test_parking_keeps_land_priority():
    parking = classify('Parking_area', {'db_road_part':'roadbed_flat'}, 'polygon')
    road = classify('Main_Roadbed', {}, 'polygon')
    assert parking['material'] == MATERIAL_INDEX and road['material'] == 0
    assert parking['kind'] == 'land' and parking['rank'] == 20
    assert parking['surface'] == 'asphalt'
    for layer in ('Pedestrian_quarter', 'Internal_lawn', 'Immersive_park_polygon_pedestrian_stone'):
        detail = classify(layer, {}, 'polygon')
        assert detail['rank'] > parking['rank'] and detail['material'] != 0
    assert classify('Garage_quarter', {}, 'polygon')['material'] == 1
    assert owns_surface(dict(kind='land', owner='parking'), {'parking'})
    assert not owns_surface(dict(kind='land', owner='path'), {'parking'})
    assert not owns_surface(dict(kind='curb_side', owner='parking'), {'parking'})


def test_separate_parking_appearance():
    road = dict(name='Асфальт', color=[.045,.051,.056], roughness=.93,
                metallic=0, texture=None, family='Асфальт')
    parking = material(road)
    assert np.allclose(parking['color'], np.array(road['color'])*1.3)
    assert road['color'] == [.045,.051,.056]
    assert parking['family'] == 'parking-asphalt'
    for key in ('roughness','metallic','texture'): assert parking[key] == road[key]


def test_remap_only_final_parking_triangle():
    vertices = np.zeros((4, 8), dtype='<f4')
    vertices[:, :3] = [[0,0,0], [1,0,0], [0,0,-1], [1,0,-1]]
    words = vertices.view('<u4'); words[:,6] = 1
    indices = np.array([[0,1,2], [1,3,2]], dtype='<u4')
    data = words.tobytes()+indices.tobytes()
    rows = [dict(owner='parking', material=1, heightPlane=[0,0,0],
                 geometry=sh.geometry.mapping(sh.Polygon([[0,0],[1,0],[0,1]])))]
    flags, area, escape = choose_faces(data, dict(vertexBytes=words.nbytes), np.zeros(3), rows)
    assert flags.tolist() == [True, False] and area == .5 and escape == 0
    updated, vb, added = remap(data, words.nbytes, indices.nbytes, flags, 0)
    out = np.frombuffer(updated[:vb], '<u4').reshape(-1,8)
    ix = np.frombuffer(updated[vb:], '<u4').reshape(-1,3)
    assert added == 2
    assert np.all(out[ix[0],6] == 0) and np.all(out[ix[1],6] == 1)
    assert np.array_equal(out[ix][:,:,[0,1,2,3,4,5,7]], words[indices][:,:,[0,1,2,3,4,5,7]])


if __name__ == '__main__':
    test_parking_keeps_land_priority()
    test_separate_parking_appearance()
    test_remap_only_final_parking_triangle()
    print('PASS: parking albedo x1.3, unchanged roads, land priorities, detailed paving and shared-boundary geometry.')

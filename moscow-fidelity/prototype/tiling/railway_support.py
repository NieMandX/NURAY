"""Bind railway ribbons to source drawing tiers, never to a highest XY hit.

Drawing tiers are identifiers, not heights in metres. The actual height comes
from the canonical floor cells of that tier, including ramps between levels.
"""
from collections import defaultdict
import numpy as np
import shapely as sh
from shapely.ops import substring
from railway_geometry import WIDTH

KINDS = {'ground': {'land', 'roadbed_flat'},
         'elevated': {'roadbed_overpass'},
         'below': {'roadbed_tunnel_descent', 'roadbed_tunnel'}}
POLICY = 'Source-tier railway floor binding; cross-sections stay on their own physical sheet; no nearest floor on another tier.'


def source_tiers(feature):
    return tuple(sorted(feature['properties'].get('db_tiers') or [0]))


def floor_group(feature):
    tiers = source_tiers(feature)
    if feature['layer'] == 'Railroad_tunnel_line' or min(tiers) < 0:
        return 'below'
    return 'elevated' if max(tiers) > 0 else 'ground'


class Floors:
    def __init__(self, city):
        self.bounds = sh.box(*city['boundsMSK'])
        self.sources = {f['id']: f for f in city['features']}
        rows = defaultdict(list)
        for s in city['surfaces']:
            group = next((g for g, kinds in KINDS.items() if s['kind'] in kinds), None)
            if group is None:
                continue
            # Material can be restyled after rail generation. Height selection
            # uses source semantics, never the old white material number.
            if group != 'ground' and (s.get('transport') == 'pedestrian' or
                    s.get('purpose') not in (None, 'unclassified', 'transport-unspecified', 'railway')):
                continue
            key = (group, tuple(sorted(s.get('tiers') or [0])) if group != 'ground' else (0,))
            rows[key].append(s)
        self.groups = {}
        for key, items in rows.items():
            items.sort(key=lambda s: s['id'])
            polys = np.array([sh.geometry.shape(s['geometry']) for s in items], object)
            self.groups[key] = (sh.STRtree(polys), polys, items)
        self.fallbacks = []
        self.owners = defaultdict(set)
        self.samples = 0
        # Water is evidence of a crossing, never a substitute floor. A source
        # ground-class rail may cross it without providing a separate 3D deck.
        self.water = sh.union_all([sh.geometry.shape(s['geometry']) for s in city['surfaces'] if s['kind']=='water'])
        self.water_profiles = {}
        self.water_samples = 0

    def water_height(self, point, record):
        if not self.water.covers(point):return None
        tree,polys,rows=self.groups[('ground',(0,))]
        if record not in self.water_profiles:
            axis=sh.LineString(np.asarray(self.sources[record]['coordinates'])[:,:2])
            profiles=[]
            for piece in sh.get_parts(axis.intersection(self.water)):
                if piece.geom_type!='LineString' or piece.length<1e-7:continue
                ends=sorted([axis.project(sh.Point(piece.coords[0])),axis.project(sh.Point(piece.coords[-1]))])
                lo,hi=ends
                # Both banks must be represented by this source path. Never
                # extrapolate an unbounded missing bridge or borrow a deck of
                # another tier. Adjacent water cells are united above first.
                if lo<.03 or hi>axis.length-.03:continue
                banks=[]
                for station in (lo-.02,hi+.02):
                    bank=axis.interpolate(station);hits=tree.query(bank,predicate='covered_by')
                    if not len(hits):break
                    roads=[int(i) for i in hits if rows[int(i)]['kind']=='roadbed_flat']
                    selected=min(roads or list(map(int,hits)),key=lambda i:rows[i]['id'])
                    row=rows[selected]
                    plane=np.asarray(row['heightPlane'])+np.array([0,0,.02 if row['kind']=='land' else .12])
                    banks.append(dict(surface=row['id'],owner=row['owner'],plane=plane.tolist(),position=list(bank.coords[0])))
                if len(banks)!=2:continue
                domain=substring(axis,lo,hi).buffer(WIDTH/2/.4+.05,cap_style='flat').intersection(self.water)
                profiles.append(dict(source=record,stationStartM=lo,stationEndM=hi,lengthM=hi-lo,
                    banks=banks,axis=axis,domain=domain,
                    evidence='Source ground-class rail crosses source water between two confirmed ground banks; height is inferred, no structural deck supplied.'))
            self.water_profiles[record]=profiles
        matches=[p for p in self.water_profiles[record] if p['domain'].covers(point)]
        if len(matches)!=1:return None
        profile=matches[0];station=profile['axis'].project(point)
        t=float(np.clip((station-profile['stationStartM'])/profile['lengthM'],0,1))
        a,b=profile['banks'];plane=(1-t)*np.asarray(a['plane'])+t*np.asarray(b['plane'])
        self.owners[record].update((a['owner'],b['owner']));self.water_samples+=1
        return float(plane@np.array([point.x,point.y,1]))

    def sample(self, points, group, record):
        key = (group, source_tiers(self.sources[record]) if group != 'ground' else (0,))
        if key not in self.groups:
            raise ValueError(f'No source-tier railway floor: {record}, {key}')
        tree, polys, rows = self.groups[key]
        out = []
        for xy in points:
            point = sh.Point(*xy)
            hits = tree.query(point, predicate='covered_by')
            if not len(hits):
                if group=='ground' and self.bounds.covers(point):
                    height=self.water_height(point,record)
                    if height is not None:
                        out.append(height);self.samples+=1
                        continue
                nearest = int(tree.nearest(point))
                distance = float(point.distance(polys[nearest]))
                if self.bounds.covers(point) and distance > 4:
                    raise ValueError(f'No confirmed {key} floor for {record}: {xy}, {distance:.3f} m')
                hits = tree.query(point, predicate='dwithin', distance=distance + 1e-7)
                if self.bounds.covers(point) and distance > .05:
                    self.fallbacks.append(dict(source=record, tiers=list(key[1]), distanceM=distance))
            # Prefer an explicit ground road floor to the surrounding terrain.
            if group == 'ground':
                roads = [int(i) for i in hits if rows[int(i)]['kind'] == 'roadbed_flat']
                if roads:
                    hits = roads
            heights = [float(np.dot(rows[int(i)]['heightPlane'], [*xy, 1])) +
                       (.02 if rows[int(i)]['kind'] == 'land' else .12) for i in hits]
            if group != 'ground' and self.bounds.covers(point) and np.ptp(heights) > .03:
                raise ValueError(f'Ambiguous railway sheet {record} at {xy}: {list(zip([rows[int(i)]["owner"] for i in hits], heights))}')
            idx = min(range(len(hits)), key=lambda j: rows[int(hits[j])]['id'])
            self.owners[record].add(rows[int(hits[idx])]['owner'])
            out.append(heights[idx]); self.samples += 1
        return np.asarray(out)

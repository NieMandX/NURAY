"""Trusted local checkpoints retaining GEOS precision as well as coordinates.

Shapely's default pickle is WKB, which does not retain the precision model.
Two identical coordinate lists can then produce different overlay/buffer
results after a resume. This reducer preserves each geometry's own grid.
"""
import pickle
import shapely as sh


def restore_geometry(wkb,precision):
    geometry=sh.from_wkb(wkb)
    return sh.set_precision(geometry,precision,mode='pointwise') if precision else geometry


class GeometryPickler(pickle.Pickler):
    def reducer_override(self,value):
        if isinstance(value,sh.Geometry):
            return restore_geometry,(sh.to_wkb(value,include_srid=True),float(sh.get_precision(value)))
        return NotImplemented


def dump(value,stream):
    GeometryPickler(stream,protocol=pickle.HIGHEST_PROTOCOL).dump(value)


def restore_source_precision(state,candidates,grid):
    """Migrate only a signature-matched source_data/make_dem cache.

    Both recipes start with clean() on every triangle and union only those
    fixed-grid polygons. Never apply a guessed grid to arbitrary later stages.
    """
    def recover(geometry):
        result=restore_geometry(sh.to_wkb(geometry,include_srid=True),grid)
        if not sh.equals_exact(result,geometry,0):
            raise ValueError('Source cache coordinates are not on the signed recipe grid')
        return result
    for row in candidates:
        row['poly']=recover(row['poly'])
        row['patches']=[(recover(poly),plane) for poly,plane in row['patches']]
    state['dem']=[(recover(poly),plane) for poly,plane in state['dem']]
    state['demtree']=sh.STRtree([poly for poly,plane in state['dem']])
    state['_sourcePrecisionVersion']=1

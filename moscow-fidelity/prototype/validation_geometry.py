"""Content-checked local cache of expensive canonical footprint unions."""
import hashlib,pickle
import shapely as sh
from tiling.geometry_pickle import dump as dump_geometry

def footprint_fingerprint(groups,precision):
    h=hashlib.sha256(repr(float(precision)).encode())
    for name,polygons in groups.items():
        h.update(name.encode()+b'\0');h.update(len(polygons).to_bytes(8,'little'))
        for start in range(0,len(polygons),4096):
            h.update(sh.get_precision(polygons[start:start+4096]).astype('<f8').tobytes())
            for data in sh.to_wkb(polygons[start:start+4096]):
                h.update(len(data).to_bytes(8,'little'));h.update(data)
    return h.hexdigest()

def footprint_unions(groups,union,precision,path):
    """Only unions are cached; all overlap, heights and solid checks still run.

    Exact ordered WKB and surface roles identify the inputs. Changing even one
    coordinate or its role invalidates this derived cache. A plane-only change
    does not affect footprints and is checked separately by the caller.
    """
    fingerprint=footprint_fingerprint(groups,precision)
    if path.exists():
        with path.open('rb') as f:saved=pickle.load(f)
        if saved.get('fingerprint')==fingerprint and saved.get('precisionVersion')==1:
            print('VALIDATION FOOTPRINT CACHE HIT',flush=True)
            return saved['footprints']
    footprints={}
    for name,polygons in groups.items():
        print('VALIDATION FOOTPRINT',name,len(polygons),flush=True)
        footprints[name]=union(polygons)
    temporary=path.with_suffix(path.suffix+'.tmp')
    # Default Shapely pickle retains coordinates but discards the GEOS grid.
    # A resumed intersection can then differ from this fresh union. Legacy
    # caches have no trustworthy grid metadata and must be recomputed once.
    with temporary.open('wb') as f:
        dump_geometry(dict(fingerprint=fingerprint,footprints=footprints,precisionVersion=1),f)
    temporary.replace(path)
    print('VALIDATION FOOTPRINTS SAVED',flush=True)
    return footprints

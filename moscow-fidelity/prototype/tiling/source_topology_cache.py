"""Cache pure source topology, never emitted-mesh clearance verdicts."""
import hashlib,io,json,os,pickle
from pathlib import Path
import numpy as np
import shapely as sh


class _TopologyPickler(pickle.Pickler):
    def persistent_id(self,value):
        if isinstance(value,sh.Geometry):
            # Shapely's default pickle preserves coordinates but drops GEOS's
            # precision model. Subsequent overlays then differ on cache hits.
            return ('geometry-v1',sh.to_wkb(value,include_srid=True),float(sh.get_precision(value)))
        return None


class _TopologyUnpickler(pickle.Unpickler):
    def persistent_load(self,value):
        if not isinstance(value,tuple) or len(value)!=3 or value[0]!='geometry-v1':
            raise pickle.UnpicklingError('Unknown source topology geometry encoding')
        _,wkb,precision=value
        geometry=sh.from_wkb(wkb)
        # Coordinates are already snapped. Pointwise restores precision
        # without reordering rings or removing vertices from the cached shape.
        if not precision:return geometry
        return sh.set_srid(sh.set_precision(geometry,precision,mode='pointwise'),sh.get_srid(geometry))


def _serialize(value):
    stream=io.BytesIO()
    _TopologyPickler(stream,protocol=pickle.HIGHEST_PROTOCOL).dump(value)
    return stream.getvalue()


def _deserialize(payload):
    return _TopologyUnpickler(io.BytesIO(payload)).load()


def cached_inventory(city,build,directory):
    h=hashlib.sha256()
    def put(value):h.update(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode());h.update(b'\n')
    put(dict(bounds=city['boundsMSK'],ground=city['groundRoadGeometry'],numpy=np.__version__,shapely=sh.__version__))
    for row in city['features']:put(row)
    # Conservatively include the entire local geometry/validation Python code.
    # Changes to any dependency invalidate derived source topology.
    prototype=Path(__file__).resolve().parents[1]
    for p in sorted([*prototype.glob('*.py'),*(prototype/'tiling').glob('*.py')]):
        h.update(str(p.relative_to(prototype)).encode());h.update(p.read_bytes())
    directory.mkdir(parents=True,exist_ok=True);key=h.hexdigest()
    data_path=directory/(key+'.pkl');proof=directory/(key+'.json')
    if data_path.exists() and proof.exists():
        try:
            expected=json.loads(proof.read_text()).get('sha256')
            payload=data_path.read_bytes()
            if hashlib.sha256(payload).hexdigest()==expected:
                result=_deserialize(payload)
                print('SOURCE TOPOLOGY CACHE VERIFIED',key[:12],flush=True)
                return result
        except (OSError,ValueError,EOFError,pickle.UnpicklingError):pass
    result=build(city);payload=_serialize(result)
    temporary=data_path.with_suffix(f'.{os.getpid()}.tmp');temporary.write_bytes(payload);temporary.replace(data_path)
    metadata=proof.with_suffix(f'.{os.getpid()}.tmp')
    metadata.write_text(json.dumps(dict(formatVersion=2,inputSha256=key,sha256=hashlib.sha256(payload).hexdigest(),
        scope='source features, bounds and ground topology only; actual mesh checks are always rerun')))
    metadata.replace(proof)
    return result

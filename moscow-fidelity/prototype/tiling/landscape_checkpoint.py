"""Exact local restart cache for the expensive global landscape layout.

Only locally generated, hashed checkpoints are consumed. Geometry precision
and prepared predicates survive, unlike ordinary Shapely WKB/pickle roundtrips.
"""
from pathlib import Path
import gzip,hashlib,json,pickle
import shapely as sh


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b''):h.update(block)
    return h.hexdigest()


def signature(base,code_root):
    names=['validation.json','canonical/validation.json','canonical/full/scene.json',
           'canonical/terrain.npz','canonical/urban-model.json']
    inputs={}
    for name in names:
        path=base/name
        if not path.exists() and name.endswith('urban-model.json'):path=Path(str(path)+'.gz')
        inputs[name]=digest(path)
    code=hashlib.sha256()
    for path in sorted(code_root.rglob('*.py')):
        code.update(str(path.relative_to(code_root)).encode()+b'\0')
        code.update(bytes.fromhex(digest(path)))
    return dict(version=1,inputs=inputs,codeSha256=code.hexdigest())


def restore_geometry(wkb,precision,prepared,srid):
    geometry=sh.from_wkb(wkb)
    if precision:geometry=sh.set_precision(geometry,precision,mode='pointwise')
    if srid:geometry=sh.set_srid(geometry,srid)
    if geometry.wkb!=wkb or sh.get_precision(geometry)!=precision:
        raise ValueError('Landscape cache changed geometry or its precision')
    if prepared:sh.prepare(geometry)
    return geometry


class LayoutPickler(pickle.Pickler):
    def reducer_override(self,obj):
        if isinstance(obj,sh.Geometry):
            args=(obj.wkb,float(sh.get_precision(obj)),bool(sh.is_prepared(obj)),int(sh.get_srid(obj)))
            restore_geometry(*args)  # Prove exact restoration before writing.
            return restore_geometry,args
        return NotImplemented


def save(path,key,value):
    path=Path(path);temporary=Path(str(path)+'.tmp')
    try:
        with temporary.open('wb') as raw,gzip.GzipFile(filename='',mode='wb',fileobj=raw,compresslevel=1,mtime=0) as stream:
            LayoutPickler(stream,protocol=5).dump(value)
        temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)
    meta=dict(key=key,sha256=digest(path),bytes=path.stat().st_size)
    sidecar=Path(str(path)+'.json');temp_meta=Path(str(sidecar)+'.tmp')
    temp_meta.write_text(json.dumps(meta,separators=(',',':')));temp_meta.replace(sidecar)
    return meta


def load(path,key):
    path=Path(path);sidecar=Path(str(path)+'.json')
    if not path.exists() or not sidecar.exists():return None
    try:meta=json.loads(sidecar.read_text())
    except (json.JSONDecodeError,UnicodeDecodeError):return None
    if not isinstance(meta,dict) or meta.get('key')!=key or meta.get('sha256')!=digest(path):return None
    with gzip.open(path,'rb') as stream:return pickle.load(stream)

"""Lossless optional compression for large offline city registries.

Runtime tile files are unaffected. Readers accept either representation;
provenance hashes always cover the uncompressed JSON bytes.
"""
import gzip
import gc
import hashlib
import json
import os
import shutil
import sys
from functools import lru_cache
from itertools import islice
from pathlib import Path


@lru_cache(maxsize=1)
def _clonefile_api():
    if sys.platform != 'darwin':
        return None
    import ctypes
    try:
        clone = ctypes.CDLL('/usr/lib/libSystem.B.dylib', use_errno=True).clonefile
        clone.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32)
        clone.restype = ctypes.c_int
        return clone
    except (AttributeError, OSError):
        return None


def _clone_asset(source, destination):
    clone = _clonefile_api()
    return clone is not None and clone(os.fsencode(source), os.fsencode(destination), 0) == 0


def copy_asset(source, destination, *, follow_symlinks=True):
    """Independent stage copy, sharing unchanged APFS blocks when available.

    This is copy-on-write, never a hard link: later in-place writes cannot alter
    a validated parent. Other filesystems keep ordinary shutil.copy2 semantics.
    """
    source, destination=Path(source),Path(destination)
    if (sys.platform=='darwin' and os.environ.get('NURAY_DISABLE_CLONES')!='1'
            and source.is_file() and not source.is_symlink() and not destination.exists()):
        # Forking a process for each file duplicates the large city's page
        # tables. Call the same native COW operation without a child process.
        if _clone_asset(source.resolve(), destination.resolve()):
            shutil.copystat(source,destination,follow_symlinks=follow_symlinks)
            return str(destination)
    return shutil.copy2(source,destination,follow_symlinks=follow_symlinks)


class JsonRows:
    """A one-pass JSON array whose derived records need not coexist in RAM."""
    def __init__(self, rows):
        self.rows = rows


class _SharedKeys(dict):
    __slots__ = ()
    def __setitem__(self, key, value):
        super().__setitem__(sys.intern(key), value)


def open_canonical(path, mode='rt'):
    path = Path(path)
    if path.exists():
        return path.open(mode, **({'encoding': 'utf-8'} if 't' in mode else {}))
    return gzip.open(str(path) + '.gz', mode, **({'encoding': 'utf-8'} if 't' in mode else {}))


def load_canonical(path):
    # Parsed JSON is an acyclic tree retained by the result. Repeated cyclic
    # collections during construction rescan millions of reachable records.
    # Keep normal reference-count cleanup and restore the caller's GC state
    # after the stream is closed, including malformed-file and I/O failures.
    enabled = gc.isenabled()
    gc.disable()
    try:
        return _read_canonical(path)
    finally:
        if enabled:
            gc.enable()


def _read_canonical(path):
    # json.load first reads the complete document into a second, city-sized
    # string. The streaming parser builds the same registry without that copy.
    # Share repeated property names too, as the standard JSON decoder does.
    import ijson
    with open_canonical(path, 'rb') as stream:
        values = ijson.items(stream, '', use_float=True, map_type=_SharedKeys)
        try:
            result = next(values)
            # Consume the end of the document: do not accept trailing JSON.
            if next(values, None) is not None:
                raise ValueError('More than one canonical JSON value')
            return result
        except (ijson.JSONError, StopIteration):
            # Retain standard JSON semantics for unusual integers outside the
            # fast parser's native range, and its normal malformed-file error.
            values = None
            result = None
            stream.seek(0)
            return json.load(stream)


def canonical_digest(path):
    digest = hashlib.sha256()
    with open_canonical(path, 'rb') as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def dump_compact(value, stream, batch_size=4096):
    """Use the C encoder on bounded rows, without a city-sized JSON string.

    Preserve json.dump's compact byte representation so existing provenance
    digests remain stable. Large nested object/placement lists are batched too.
    """
    encode=lambda row:json.dumps(row,ensure_ascii=False,separators=(',', ':'))
    def write(row):
        if isinstance(row,dict):
            stream.write('{')
            for index,(key,item) in enumerate(row.items()):
                if index:stream.write(',')
                # Let JSON's key conversion retain its normal int/bool/null
                # handling as well as string escaping.
                stream.write(encode({key:None})[1:-5]);write(item)
            stream.write('}')
        elif isinstance(row,JsonRows):
            stream.write('[')
            iterator=iter(row.rows);first=True
            while batch:=list(islice(iterator,batch_size)):
                if not first:stream.write(',')
                stream.write(encode(batch)[1:-1]);first=False
            stream.write(']')
        elif isinstance(row,(list,tuple)) and len(row)>batch_size:
            stream.write('[')
            for start in range(0,len(row),batch_size):
                if start:stream.write(',')
                stream.write(encode(row[start:start+batch_size])[1:-1])
            stream.write(']')
        else:stream.write(encode(row))
    write(value)


def save_canonical(path, value):
    path = Path(path)
    compressed = os.environ.get('NURAY_COMPRESS_CANONICAL') == '1'
    destination = Path(str(path) + '.gz') if compressed else path
    temporary = Path(str(destination) + '.tmp')
    opener = gzip.open if compressed else open
    options = dict(encoding='utf-8')
    if compressed:
        options['compresslevel'] = 1
    with opener(temporary, 'wt', **options) as stream:
        dump_compact(value, stream)
    temporary.replace(destination)
    # A copied parent may have used the other representation. It must never
    # shadow this newly serialized revision on the next read.
    alternate = path if compressed else Path(str(path) + '.gz')
    if alternate.exists():
        alternate.unlink()


def archive_intermediate_glb(root):
    """Keep a verified lossless copy of an intermediate's optional monolith.

    Streaming and all later generators read the retained scene/chunk files.
    The final release keeps its directly downloadable GLB.
    """
    if os.environ.get('NURAY_ARCHIVE_INTERMEDIATE_GLB') != '1':
        return
    path=Path(root)/'canonical/full/model.glb'
    if not path.exists():return
    archive=Path(str(path)+'.gz');temporary=Path(str(archive)+'.tmp')
    digest=hashlib.sha256();size=path.stat().st_size
    with path.open('rb') as source,gzip.open(temporary,'wb',compresslevel=1) as target:
        while block:=source.read(8*1024*1024):digest.update(block);target.write(block)
    check=hashlib.sha256();restored=0
    with gzip.open(temporary,'rb') as source:
        while block:=source.read(8*1024*1024):check.update(block);restored+=len(block)
    if digest.digest()!=check.digest() or restored!=size:raise ValueError('Intermediate GLB archive verification failed')
    temporary.replace(archive)
    path.with_suffix('.glb.archive.json').write_text(json.dumps(dict(version=1,originalBytes=size,
        compressedBytes=archive.stat().st_size,sha256=digest.hexdigest(),encoding='gzip',
        restore='gzip -dk model.glb.gz'),indent=2))
    path.unlink()
    print('VERIFIED INTERMEDIATE GLB ARCHIVE',archive,size,'->',archive.stat().st_size,flush=True)

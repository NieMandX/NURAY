"""Read the exact terrain cache without a city-sized Unicode WKB buffer."""
import binascii
import zipfile
import numpy as np
import shapely as sh


def read_terrain_arrays(path, batch_size=32768):
    if batch_size<1:raise ValueError('Positive terrain batch size required')
    with np.load(path) as cache:planes=cache['planes']
    with zipfile.ZipFile(path) as archive,archive.open('polygons.npy') as stream:
        version=np.lib.format.read_magic(stream)
        readers={(1,0):np.lib.format.read_array_header_1_0,
                 (2,0):np.lib.format.read_array_header_2_0}
        if version not in readers:raise ValueError('Unsupported terrain array header')
        shape,fortran,dtype=readers[version](stream)
        if len(shape)!=1 or dtype.kind not in ('U','S'):
            raise ValueError('Terrain polygons must be a one-dimensional WKB array')
        count=shape[0]
        if planes.shape!=(count,3):raise ValueError('Terrain polygon/plane count mismatch')
        polygons=np.empty(count,dtype=object)
        # The retained format stores hex WKB in fixed-width Unicode strings.
        # Convert hex in C before GEOS parsing, and discard each Unicode batch.
        # No coordinates, ordering or height coefficients are recomputed.
        for start in range(0,count,batch_size):
            size=min(batch_size,count-start)
            raw=stream.read(size*dtype.itemsize)
            if len(raw)!=size*dtype.itemsize:raise ValueError('Truncated terrain polygon array')
            values=np.frombuffer(raw,dtype=dtype)
            if dtype.kind=='U':values=[binascii.unhexlify(s) for s in values]
            polygons[start:start+size]=sh.from_wkb(values)
        if stream.read(1):raise ValueError('Trailing bytes in terrain polygon array')
    return polygons,planes


def read_terrain(path, batch_size=32768):
    polygons,planes=read_terrain_arrays(path,batch_size)
    return list(zip(polygons,planes))

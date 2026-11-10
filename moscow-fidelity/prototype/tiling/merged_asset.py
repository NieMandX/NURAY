"""A merged glTF asset can outgrow GLB's 32-bit container without losing geometry."""
import hashlib
import json
from pathlib import Path
import shutil
import struct


def write_container(out, doc, binary, glb_limit=2**32):
    out, binary = Path(out), Path(binary)
    binary_size = binary.stat().st_size
    header = json.dumps(doc, separators=(',', ':')).encode()
    header += b' ' * (-len(header) % 4)
    padding = -binary_size % 4
    size = 28 + len(header) + binary_size + padding
    if size >= glb_limit:
        # Standard glTF with one external buffer; no split geometry or LOD.
        doc['buffers'][0]['uri'] = 'model.bin'
        header = json.dumps(doc, separators=(',', ':')).encode()
        temporary = out / 'model.gltf.tmp'
        temporary.write_bytes(header)
        binary.replace(out / 'model.bin')
        temporary.replace(out / 'model.gltf')
        return dict(file='model.gltf', format='gltf', bytes=len(header) + binary_size,
                    headerBytes=len(header), binaryBytes=binary_size)
    target = out / 'model.glb.tmp'
    with target.open('wb') as sink, binary.open('rb') as source:
        sink.write(struct.pack('<4sII', b'glTF', 2, size))
        sink.write(struct.pack('<I4s', len(header), b'JSON'))
        sink.write(header)
        sink.write(struct.pack('<I4s', binary_size + padding, b'BIN\0'))
        shutil.copyfileobj(source, sink, 8 * 1024 * 1024)
        sink.write(b'\0' * padding)
    target.replace(out / 'model.glb')
    binary.unlink()
    return dict(file='model.glb', format='glb', bytes=size,
                headerBytes=len(header), binaryBytes=binary_size + padding)


def read_container(path):
    path = Path(path)
    if path.suffix == '.gltf':
        raw = path.read_bytes()
        doc = json.loads(raw)
        buffers = doc.get('buffers', [])
        if len(buffers) != 1 or buffers[0].get('uri') != 'model.bin':
            raise ValueError('Expected one local model.bin buffer')
        binary = path.parent / 'model.bin'
        if binary.stat().st_size != buffers[0]['byteLength']:
            raise ValueError('Invalid glTF buffer length')
        return doc, binary, 0, hashlib.sha256(raw).hexdigest(), len(raw) + binary.stat().st_size
    with path.open('rb') as stream:
        magic, version, length, json_size, json_type = struct.unpack('<5I', stream.read(20))
        if (magic, version, json_type) != (0x46546c67, 2, 0x4e4f534a) or length != path.stat().st_size:
            raise ValueError('Invalid GLB')
        raw = stream.read(json_size)
        doc = json.loads(raw)
        binary_size, binary_type = struct.unpack('<2I', stream.read(8))
        if binary_type != 0x004e4942 or stream.tell() + binary_size != length:
            raise ValueError('Invalid BIN')
        return doc, path, stream.tell(), hashlib.sha256(raw).hexdigest(), length

"""Read-only accounting of referenced runtime files versus build artifacts.

Sizes are logical bytes, not allocated APFS blocks (which can be shared by
copy-on-write stage copies). Shared meshes are counted once, not per instance.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil


def measure(root):
    root = Path(root).resolve()
    catalog = root / 'tileset.json'
    scene = json.loads(catalog.read_text())
    meshes = {row['file'] for row in scene['chunks']}
    textures = {f'textures/{name}' for name in scene.get('textures', {})}

    def size(names):
        total = 0
        for name in names:
            path = (root / name).resolve()
            if not path.is_relative_to(root):
                raise ValueError(f'Asset outside release: {name}')
            total += path.stat().st_size
        return total

    validation = root / 'validation.json'
    runtime = dict(geometryBytes=size(meshes), catalogBytes=catalog.stat().st_size,
                   textureBytes=size(textures),
                   validationBytes=validation.stat().st_size if validation.exists() else 0)
    runtime['totalBytes'] = sum(runtime.values())
    extras = {}
    for name in ('canonical/full/model.glb', 'canonical/full/model.glb.gz',
                 'canonical/urban-model.json', 'canonical/urban-model.json.gz',
                 'objects.json.gz', 'street-objects.json'):
        path = root / name
        if path.exists():
            extras[name] = path.stat().st_size
    return dict(measuredAt=datetime.now(timezone.utc).isoformat(), release=str(root),
                validated=json.loads(validation.read_text()).get('passed') if validation.exists() else False,
                tiles=len(scene['tiles']), geometryFiles=len(meshes), textureFiles=len(textures),
                runtime=runtime, optionalOrOfflineFiles=extras,
                uniqueTriangles=scene['stats']['uniqueTriangles'],
                expandedTriangles=scene['stats']['fullTriangles'],
                freeDiskBytes=shutil.disk_usage(root).free,
                accounting='Logical file bytes; shared geometry counted once; excludes viewer code and offline sources/caches. APFS clones may share allocated blocks.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('release', type=Path)
    args = parser.parse_args()
    print(json.dumps(measure(args.release), ensure_ascii=False, indent=2))

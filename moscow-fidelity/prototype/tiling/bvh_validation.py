"""Reuse only the BVH proof for identical serialized mesh bytes and layout.

The caller must verify the SHA-256 of the freshly read block on every run.
Material, lineage, tile-boundary and transport-clearance checks are separate
and are never skipped by this cache. Only locally generated proofs are read.
"""
import hashlib
import json
import os
from pathlib import Path
import numpy as np

RECIPE = hashlib.sha256(Path(__file__).read_bytes()+np.__version__.encode()).hexdigest()
LAYOUT = ('format','vertexBytes','indexBytes','nodeBytes','lineageBytes','nodeCount','triangles')


def validate(points, nf, nu):
    covered = np.zeros(len(points), np.uint32)

    def visit(node):
        assert node < len(nu)
        lo, hi = nf[node, :3], nf[node, 4:7]
        assert np.isfinite(lo).all() and np.isfinite(hi).all() and np.all(lo <= hi)
        first, count = map(int, nu[node, [3, 7]])
        if count:
            assert 0 < count <= 8 and first + count <= len(points)
            q = points[first:first+count]
            assert np.all(q >= lo - 2e-5) and np.all(q <= hi + 2e-5)
            covered[first:first+count] += 1
            return node+1
        assert node+1 < first <= len(nu)
        right = visit(node+1)
        end = visit(right)
        assert end == first
        for child in [node+1, right]:
            assert np.all(nf[child, :3] >= lo - 2e-5) and np.all(nf[child, 4:7] <= hi + 2e-5)
        return end

    assert visit(0) == len(nu) and np.all(covered == 1)


def validate_cached(folder, chunk, verified_sha256, points, nf, nu):
    """Return True on a verified local cache hit; otherwise run the full audit."""
    context = dict(recipe=RECIPE,sha256=verified_sha256,
                   layout={key:chunk[key] for key in LAYOUT})
    key = hashlib.sha256(json.dumps(context,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    path = Path(folder)/RECIPE/(key+'.json')
    proof = dict(context=context,nodes=len(nu),triangles=len(points))
    try:
        if json.loads(path.read_text()) == proof:return True
    except (OSError,ValueError):
        pass
    validate(points,nf,nu)
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(f'.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(proof,separators=(',',':')))
    temporary.replace(path)
    return False

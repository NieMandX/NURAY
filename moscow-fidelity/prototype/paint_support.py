"""Validate emitted paint independently of imperfect source line placement."""
import numpy as np
import shapely as sh
from paint_domain import accepts

def audit(checks,surfaces,tolerance):
    needed={row[2] for row in checks}
    support={s['id']:s for s in surfaces if s['id'] in needed}
    invalid=sorted(sid for sid in needed if sid not in support or not accepts(support[sid]))
    missing=0.;core=0.
    for begin in range(0,len(checks),8192):
        rows=[r for r in checks[begin:begin+8192] if r[2] in support]
        if not rows:continue
        triangles=sh.polygons(np.asarray([r[0][:,:2] for r in rows]))
        targets=np.asarray([support[r[2]]['poly'] for r in rows],dtype=object)
        difference=sh.difference(triangles,targets)
        areas=sh.area(difference);missing+=float(areas.sum())
        significant=difference[areas>1e-12]
        if len(significant):core+=float(sh.area(sh.buffer(significant,-tolerance)).sum())
    return dict(triangles=len(checks),invalidSupportIds=invalid,outsideSupportM2=missing,
                outsideSupportCoreM2=core,positionToleranceM=tolerance,
                passed=not invalid and core<1e-8)

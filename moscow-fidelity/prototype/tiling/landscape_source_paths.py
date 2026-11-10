"""Source-path witnesses at the actual packed ground-coordinate precision."""
import numpy as np
import shapely as sh
from landscape import parts


class SourceGreenPrecision:
    """Exclude only complete source islands with zero packed footprint.

    A micron-wide source triangle may intersect a path for centimetres while
    all of its packed XY vertices become collinear. Such a disconnected island
    has no rendered lawn. A surviving area, an attached thin tail, or any actual
    raised green at either footprint remains subject to the normal path audit.
    No distance or length tolerance is increased.
    """
    def __init__(self,source_green,actual_green,origin):
        self.source_green=source_green;self.actual_green=actual_green
        self.origin=np.asarray(origin,dtype=float)[:2]
        self.components=None;self.tree=None;self.collapsed={};self.used=set()
        self.excluded_length=0.

    def filter(self,uncovered):
        if uncovered.is_empty:return uncovered
        if self.tree is None:
            self.components=parts(self.source_green)
            self.tree=sh.STRtree(self.components)
            sh.prepare(self.actual_green)
        for index in self.tree.query(uncovered,predicate='intersects'):
            index=int(index);source=self.components[index]
            if index not in self.collapsed:
                packed=sh.make_valid(sh.transform(source,lambda xy:
                    (xy-self.origin).astype(np.float32).astype(np.float64)+self.origin))
                self.collapsed[index]=(packed.area==0 and
                    not self.actual_green.intersects(source) and
                    not self.actual_green.intersects(packed))
            if not self.collapsed[index]:continue
            remainder=uncovered.difference(source)
            removed=uncovered.length-remainder.length
            if removed>0:
                self.used.add(index);self.excluded_length+=removed
            uncovered=remainder
        return uncovered

    def report(self):
        return dict(components=len(self.used),sourceAreaM2=sum(self.components[i].area for i in self.used),
            excludedSourcePathLengthM=self.excluded_length,
            policy='Only complete disconnected source lawn components with exactly zero float32 packed XY area and no actual raised green at original or packed footprint. Existing path tolerances unchanged.')

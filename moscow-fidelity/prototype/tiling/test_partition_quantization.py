import unittest
import numpy as np
from partition_quantization import verify_quantized_partition,area


class QuantizedPartitions(unittest.TestCase):
    def setUp(self):
        # A long, narrow roof far from the local origin: the same floating-point
        # issue occurs for large cities regardless of which building it is.
        self.original=np.array([[4813.93310546875,26.692977905273438,914.8759155273438],
            [4948.03173828125,26.692977905273438,1153.8031005859375],
            [4797.9658203125,26.692977905273438,886.5220947265625]])
        a,b,c=self.original
        ab=a+(b-a)*((1000-a[2])/(b[2]-a[2]));cb=c+(b-c)*((1000-c[2])/(b[2]-c[2]))
        left=np.asarray([[a,ab,cb],[a,cb,c]],dtype=np.float32).astype(float)
        right=np.asarray([[ab,b,cb]],dtype=np.float32).astype(float)
        self.parts=[(left,dict(min=[4750,-100,750],max=[5000,100,1000])),
                    (right,dict(min=[4750,-100,1000],max=[5000,100,1250]))]

    def test_rounding_proof_preserves_area(self):
        self.assertGreater(abs(sum(area(p).sum() for p,_ in self.parts)-area(self.original[None])[0]),.02)
        proof=verify_quantized_partition(self.original,self.parts)
        self.assertLess(proof['maxCoordinateRoundingM'],.00025)
        self.assertLess(proof['unquantizedAreaErrorM2'],1e-8)

    def test_missing_face_rejected(self):
        parts=[(self.parts[0][0][:1],self.parts[0][1]),self.parts[1]]
        with self.assertRaises(AssertionError):verify_quantized_partition(self.original,parts)

    def test_duplicate_face_rejected(self):
        with self.assertRaises(AssertionError):verify_quantized_partition(self.original,self.parts+[self.parts[1]])

    def test_displaced_vertex_rejected(self):
        self.parts[1][0][0,0,1]+=.001
        with self.assertRaises(AssertionError):verify_quantized_partition(self.original,self.parts)

    def test_interior_grid_corners_on_sloped_face(self):
        import shapely as sh
        from shapely.geometry.polygon import orient
        ring=np.array([[4201.125,4207.625],[4971.375,4212.875],[4214.625,4993.125]])
        def lift(xz):
            return np.column_stack((xz[:,0],.07*xz[:,0]+.03*xz[:,1]+5,xz[:,1]))
        original=lift(ring).astype(np.float32).astype(float)
        # Derive the actual plane from the serialized source, not the decimal
        # construction above (which itself has already been rounded).
        n=np.cross(original[1]-original[0],original[2]-original[0])
        polygon=sh.Polygon(original[:,[0,2]]);parts=[]
        for x in (4000,4250,4500,4750):
            for z in (4000,4250,4500,4750):
                cut=polygon.intersection(sh.box(x,z,x+250,z+250))
                if cut.is_empty:continue
                xz=np.asarray(orient(cut,sign=1).exterior.coords)[:-1]
                y=original[0,1]-(n[0]*(xz[:,0]-original[0,0])+n[2]*(xz[:,1]-original[0,2]))/n[1]
                p=np.column_stack((xz[:,0],y,xz[:,1]));tri=np.asarray([[p[0],p[i],p[i+1]] for i in range(1,len(p)-1)])
                parts.append((tri.astype(np.float32).astype(float),dict(min=[x,-100,z],max=[x+250,1000,z+250])))
        proof=verify_quantized_partition(original,parts)
        self.assertLess(proof['maxCoordinateRoundingM'],.00025)


if __name__=='__main__':unittest.main()

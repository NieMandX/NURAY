import unittest
import numpy as np
import shapely as sh
from industrial_chimneys import detect,mesh
from apply_chimneys import replacement_mask


def parts(kind='urban-structure'):
    return [(dict(id=i,attributes=dict(ft_type_name=kind,height=h)),sh.Point(100,200).buffer(r,quad_segs=16).difference(sh.Point(100,200).buffer(2,quad_segs=16))) for i,(r,h) in enumerate([(6,50),(5,100),(4,150)])]


class Chimneys(unittest.TestCase):
    def test_conservative_detection(self):
        self.assertEqual(len(detect(parts())),1)
        self.assertFalse(detect(parts('urban-residential')))
        self.assertFalse(detect(parts()[:1]))
        self.assertFalse(detect([(f,sh.affinity.scale(g,2,1)) for f,g in parts()]))
        self.assertFalse(detect([(f,sh.affinity.translate(g,i*20,0)) for i,(f,g) in enumerate(parts())]))

    def test_continuity_stripes_and_outward_normals(self):
        group=detect(parts())[0]
        t,m=mesh(group,10,lambda xy:np.full(len(xy),10.),10)
        normals=np.cross(t[:,1,:3]-t[:,0,:3],t[:,2,:3]-t[:,0,:3])
        self.assertTrue(np.all((normals*t[:,:,3:6].mean(1)).sum(1)>0))
        side=t[:48*2*8];radius=np.linalg.norm(side[:,:,[0,2]]-[100,-200],axis=2)
        y=side[:,:,1];u=np.maximum(y,0)/150
        np.testing.assert_allclose(radius,group['baseRadius']+(group['topRadius']-group['baseRadius'])*u,atol=1e-10)
        self.assertEqual(m[:48*2*8].reshape(8,-1)[:,0].tolist(),[0,1,0,1,0,1,0,1])
        for a,b in zip(range(7),range(1,8)):
            av=side[a*96:(a+1)*96,:,:3].reshape(-1,3);bv=side[b*96:(b+1)*96,:,:3].reshape(-1,3)
            height=150*(a+1)/8
            np.testing.assert_allclose(np.unique(av[np.isclose(av[:,1],height)],axis=0),np.unique(bv[np.isclose(bv[:,1],height)],axis=0))

    def test_adjoining_low_building_not_removed(self):
        group=detect(parts())[0];group['baseLocal']=0
        t=np.zeros((3,3,8));t[:,:,[0,2]]=[[[105,-200],[105,-201],[105,-200]],[[105,-200],[105,-201],[105,-200]],[[120,-200],[120,-201],[120,-200]]]
        t[:,:,1]=[[0,0,50],[0,0,5],[0,0,150]]
        self.assertEqual(replacement_mask(t,group,0).tolist(),[True,False,False])


if __name__=='__main__':unittest.main()

"""Catalogue of actual generated fence geometry; samples are not map objects."""
import argparse,json,tempfile
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from fence_geometry import build,TYPES,EXTRA_MATERIALS
from street_library import MATERIALS,Mesh
from street_placement import SurfaceSampler
from object_geometry import pack,export_glb


def raster(screen,depth,colors,width,height):
    # Pixel depth avoids painter-order triangles across long opaque panels.
    rgb=np.full((height,width,3),[250,249,245],dtype=np.uint8)
    zbuffer=np.full((height,width),-np.inf)
    for tri,z,color in zip(screen,depth,colors):
        lo=np.maximum(0,np.floor(tri.min(0)).astype(int));hi=np.minimum([width-1,height-1],np.ceil(tri.max(0)).astype(int))
        if np.any(lo>hi):continue
        a,b,c=tri;d=(b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(d)<1e-10:continue
        yy,xx=np.mgrid[lo[1]:hi[1]+1,lo[0]:hi[0]+1];xx=xx+.5;yy=yy+.5
        u=((b[1]-c[1])*(xx-c[0])+(c[0]-b[0])*(yy-c[1]))/d
        v=((c[1]-a[1])*(xx-c[0])+(a[0]-c[0])*(yy-c[1]))/d;w=1-u-v
        dep=u*z[0]+v*z[1]+w*z[2];dest=zbuffer[lo[1]:hi[1]+1,lo[0]:hi[0]+1]
        mask=(u>=0)&(v>=0)&(w>=0)&(dep>dest)
        dest[mask]=dep[mask];rgb[lo[1]:hi[1]+1,lo[0]:hi[0]+1][mask]=(color*255).astype(np.uint8)
    return Image.fromarray(rgb)


def main(root):
    rules=json.loads((root/'canonical/fence-source-rules.json').read_text())['rules']
    output=root/'fence-library';output.mkdir(exist_ok=True)
    materials=MATERIALS+EXTRA_MATERIALS;catalog=[]
    font='/System/Library/Fonts/Supplemental/Arial.ttf'
    title=ImageFont.truetype(font,28);regular=ImageFont.truetype(font,20);small=ImageFont.truetype(font,16)
    image=Image.new('RGB',(1440,780),'#ecebe5');draw=ImageDraw.Draw(image)
    draw.text((24,17),'NURAY · ограждения по типам 2ГИС',font=title,fill='#25332c')
    draw.text((24,56),'Образцы по 5 м. Высота — параметр нашей модели. Образцы не добавлены на карту.',font=regular,fill='#556058')
    eye=np.array([1.9,1.8,5.]);eye/=np.linalg.norm(eye);right=np.cross([0,1,0],eye);right/=np.linalg.norm(right);up=np.cross(eye,right)
    light=np.array([-.4,.8,.6]);light/=np.linalg.norm(light)
    with tempfile.TemporaryDirectory() as td:
        tmp=Path(td);(tmp/'canonical/full').mkdir(parents=True);m=Mesh();m.quad([[-1,0,-1],[-1,0,1],[6,0,1],[6,0,-1]],0)
        t,mat=m.arrays();meta=pack(t,mat,tmp/'canonical/full/ground.gz')
        ground=SurfaceSampler(tmp,dict(chunks=[dict(id=0,name='land',file='ground.gz',**meta)]),{'land'})
        for slot,code in enumerate([0,1,2,3,4,5,6,None]):
            props=dict(db_sublayer='Fence',db_fence_type=code)
            record=dict(layer='Fence',sourceRecordId='library-sample',source=dict(coordinateStepM=1),properties=props,coordinatesMSK=[[0,0,0],[5,0,0]])
            mesh,objects,_,_,_=build([record],dict(originMSK=[0,0,0],boundsMSK=[-1,-1,6,1]),ground,rules)
            t,mat=mesh.arrays();spec=objects[0]['classification'];folder=output/spec['resource'];folder.mkdir(exist_ok=True)
            meta=pack(t,mat,folder/'mesh.bin.gz')
            scene=dict(origin=[0,0,0],materials=materials,chunks=[dict(id=0,name=spec['label'],file='mesh.bin.gz',**meta)],instances=[dict(mesh=0,matrix=[1,0,0,0,0,1,0,0,0,0,1,0])])
            export_glb(scene,folder)
            catalog.append(dict(**spec,triangles=len(t),file=f"{spec['resource']}/model.glb"))
            p=t[:,:,:3];q=p-[2.5,.95,0];projected=np.stack([q@right,-q@up],axis=-1)
            x=(slot%4)*360;y=100+(slot//4)*335
            draw.rounded_rectangle((x+8,y,x+352,y+325),radius=12,fill='#faf9f5')
            screen=projected*57+[170,125]
            colors=np.array([materials[i]['color'] for i in mat])*(.5+.8*np.maximum(0,t[:,0,3:6]@light))[:,None]
            colors=np.clip(colors,0,1);colors=np.where(colors<=.0031308,colors*12.92,1.055*colors**(1/2.4)-.055)
            image.paste(raster(screen,q@eye,colors,340,225),(x+10,y+10))
            draw.text((x+20,y+242),spec['label'],font=regular,fill='#25332c')
            draw.text((x+20,y+275),f"Код {code if code is not None else 'неизвестен'} · {spec['heightM']:.1f} м · {len(t)} тр.",font=small,fill='#657168')
    image.save(output/'preview.png');(output/'catalog.json').write_text(json.dumps(dict(models=catalog,dimensions='display defaults'),ensure_ascii=False,indent=2))
    print(output/'preview.png')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('release',type=Path);main(p.parse_args().release)

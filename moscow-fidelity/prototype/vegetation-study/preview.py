"""Contact sheets of actual prototype meshes, no generated bitmap tree art."""
import json,sys
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from build import OUT,PALETTE

def main():
    data=json.loads((OUT/'catalog.json').read_text());font='/System/Library/Fonts/Supplemental/Arial.ttf'
    choices=json.loads((OUT/'choices.json').read_text()) if (OUT/'choices.json').exists() else {}
    title=ImageFont.truetype(font,29);label=ImageFont.truetype(font,22);small=ImageFont.truetype(font,17)
    W,H=530,610;rows=(len(data['models'])+2)//3;img=Image.new('RGB',(W*3,H*rows+100),'#f1efe7');d=ImageDraw.Draw(img)
    d.text((28,18),'NURAY / Растительность · согласование моделей',font=title,fill='#303d2e')
    integrated=sum(bool(c.get('integrated')) for c in choices.values())
    d.text((28,59),f"{len(data['models'])} отдельных 3D-моделей · {integrated} подключено к макету.",font=label,fill='#647059')
    for slot,row in enumerate(data['models']):
        x=slot%3*W;y=slot//3*H+100
        choice=choices.get(row['id']);key=choice['variant'] if choice else row['id']
        light=np.array([-.6,.85,.7]);light/=np.linalg.norm(light)
        if choice and choice.get('library'):
            sys.path.insert(0,str(OUT.parents[2]/'prototype/tiling'))
            from approved_vegetation import read_glb
            doc,p,n,colors,mats=read_glb(OUT/choice['library']['file'])
            base=np.asarray([m['pbrMetallicRoughness']['baseColorFactor'][:3] for m in doc['materials']])[mats]
            c=(colors*base[:,None,:]*(.65+.7*np.maximum(0,n@light))[:,:,None]).mean(1)
        else:
            mesh=np.load(OUT/key/'geometry.npz');p=mesh['attributes'][:,:,:3];n=mesh['attributes'][:,0,3:6]
            c=np.array([PALETTE[k][1] for k in mesh['materials']])*(.65+.7*np.maximum(0,n@light))[:,None]
        color=np.where(c<=.0031308,c*12.92,1.055*c**(1/2.4)-.055)
        eye=np.array([.18,.17,1.]);eye/=np.linalg.norm(eye)
        right=np.cross([0,1,0],eye);right/=np.linalg.norm(right);up=np.cross(eye,right)
        center=(p.min((0,1))+p.max((0,1)))/2;q=p-center
        proj=np.stack([q@right,-q@up],axis=-1)
        zoom=min((W-85)/np.ptp(proj[:,:,0]),(H-150)/np.ptp(proj[:,:,1]));screen=proj*zoom+[x+W/2,y+H/2-25]
        d.rounded_rectangle((x+10,y+6,x+W-10,y+H-8),radius=12,fill='#faf9f4')
        base_y=float(screen[:,:,1].max());d.ellipse((x+W*.23,base_y-7,x+W*.77,base_y+6),fill='#d8d9cb')
        for i in np.argsort((q@eye).mean(1)):
            d.polygon([tuple(v) for v in screen[i]],fill=tuple((np.clip(color[i],0,1)*255).astype(int)))
        d.text((x+25,y+H-83),row['label'],font=label,fill='#303d2e')
        details=f"{len(p)} треугольников · "+('выбрано' if choice else f"{row['foliageGroups']} групп листвы")
        d.text((x+25,y+H-50),details,font=small,fill='#647059')
    img.save(OUT/'preview.png')
    print(OUT/'preview.png')

if __name__=='__main__':main()

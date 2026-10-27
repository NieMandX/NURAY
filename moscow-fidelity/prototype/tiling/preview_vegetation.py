"""Render a catalogue from actual exported geometry (orthographic, flat PBR colours)."""
import argparse,json
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFont
from vegetation_library import PALETTE

def render(library):
    library=Path(library)
    lib=json.loads((library/'catalog.json').read_text())
    fontpath='/System/Library/Fonts/Supplemental/Arial.ttf'
    regular=ImageFont.truetype(fontpath,18);small=ImageFont.truetype(fontpath,15);title=ImageFont.truetype(fontpath,27)
    columns=3 if lib['version']==2 else 5;rows=(len(lib['models'])+columns-1)//columns
    w,h=400,360;img=Image.new('RGB',(w*columns,h*rows+105),'#edece6');draw=ImageDraw.Draw(img)
    draw.text((25,16),f"NURAY · {len(lib['models'])} моделей растительности",font=title,fill='#26372c')
    draw.text((25,54),'Габариты моделей сцены до масштаба экземпляров. Каждая ячейка показана в своём масштабе.',font=regular,fill='#536052')
    eye=np.array([4.,2.5,8.]);eye/=np.linalg.norm(eye)
    right=np.cross([0,1,0],eye);right/=np.linalg.norm(right);up=np.cross(eye,right)
    light=np.array([-.45,.85,.4]);light/=np.linalg.norm(light)
    for slot,m in enumerate(lib['models']):
        if lib['version']==2:
            from approved_vegetation import read_glb
            doc,p,n,c,mats=read_glb(library/m['file'])
            axes=np.asarray(m.get('sceneAxisScale',[1.,1.,1.]))
            p=p*m['uniformTemplateScale']*axes
            n=n/axes;n=n/np.linalg.norm(n,axis=2,keepdims=True)
            base=np.array([x['pbrMetallicRoughness']['baseColorFactor'][:3] for x in doc['materials']])[mats]
            color=(c*base[:,None,:]*(.55+.85*np.maximum(0,n@light))[:,:,None]).mean(1)
        else:
            data=np.load(library/m['id']/'geometry.npz');attrs=data['attributes'];p=attrs[:,:,:3];n=attrs[:,0,3:6]
            color=np.array([PALETTE[i][1] for i in data['materials']])*(.55+.85*np.maximum(0,n@light))[:,None]
        color=np.clip(color,0,1)
        color=np.where(color<=.0031308,color*12.92,1.055*color**(1/2.4)-.055)
        q=p-(p.min((0,1))+p.max((0,1)))/2
        projected=np.stack([q@right,-q@up],axis=-1)
        zoom=min((w-70)/np.ptp(projected[:,:,0]),(h-105)/np.ptp(projected[:,:,1]))
        x=(slot%columns)*w;y=105+(slot//columns)*h
        draw.rounded_rectangle((x+9,y+6,x+w-9,y+h-6),radius=12,fill='#f9f8f3')
        screen=projected*zoom+[x+w/2,y+157]
        for i in np.argsort((q@eye).mean(1)):
            draw.polygon([tuple(v) for v in screen[i]],fill=tuple((color[i]*255).astype(int)))
        draw.text((x+20,y+292),f"{m['label']} · {m['triangles']} тр.",font=regular,fill='#26372c')
        lo=np.array(m['bounds']['min']);hi=np.array(m['bounds']['max']);d=hi-lo
        draw.text((x+20,y+320),f'{d[0]:.1f} × {d[2]:.1f} м · высота {d[1]:.1f} м',font=small,fill='#647163')
    img.save(library/'preview.png')
    print(library/'preview.png')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('library',type=Path);a=ap.parse_args()
    render(a.library)

if __name__=='__main__':main()

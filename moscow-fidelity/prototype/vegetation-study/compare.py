"""Compare actual study meshes with identical projection/light, plus silhouette masks."""
import json, hashlib
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from build import OUT, PALETTE


def load(key):
    data=np.load(OUT/key/'geometry.npz')
    return data['attributes'],data['materials']


def project(attrs,yaw,pitch,center):
    eye=np.array([np.sin(yaw)*np.cos(pitch),np.sin(pitch),np.cos(yaw)*np.cos(pitch)])
    right=np.cross([0,1,0],eye);right/=np.linalg.norm(right)
    up=np.cross(eye,right);q=attrs[:,:,:3]-center
    return np.stack([q@right,-q@up],axis=-1),q@eye


def mask(p,scale):
    image=Image.new('1',(640,640));draw=ImageDraw.Draw(image)
    for tri in p*scale+[320,320]:draw.polygon([tuple(v) for v in tri],fill=1)
    return np.asarray(image)


def main():
    report=json.loads((OUT/'optimization.json').read_text())
    assert report['sourceGeometrySha256']==hashlib.sha256((OUT/'compact/geometry.npz').read_bytes()).hexdigest()
    meshes={'compact':load('compact')}
    meshes.update({r['id']:load(r['id']) for r in report['variants']})
    original=meshes['compact'][0];center=(original[:,:,:3].min((0,1))+original[:,:,:3].max((0,1)))/2
    scores={key:[] for key in meshes if key!='compact'}
    step_scores={key:[] for key in report.get('reductionSteps',{}).get('variants',[])}
    for pitch in (.15,.60):
        for yaw in np.arange(12)*2*np.pi/12:
            p,_=project(original,yaw,pitch,center)
            scale=570/np.ptp(p.reshape(-1,2),axis=0).max()
            baseline=mask(p,scale)
            step_baseline=mask(project(meshes['compact-reduced-35'][0],yaw,pitch,center)[0],scale)
            for key in scores:
                candidate=mask(project(meshes[key][0],yaw,pitch,center)[0],scale)
                scores[key].append(float((candidate&baseline).sum()/(candidate|baseline).sum()))
                if key in step_scores:
                    step_scores[key].append(float((candidate&step_baseline).sum()/(candidate|step_baseline).sum()))
    for row in report['variants']:
        row['silhouetteIoUMean']=float(np.mean(scores[row['id']]))
        row['silhouetteIoUMin']=float(min(scores[row['id']]))
        if row['id'] in step_scores:
            row['stepBaseSilhouetteIoUMean']=float(np.mean(step_scores[row['id']]))
            row['stepBaseSilhouetteIoUMin']=float(min(step_scores[row['id']]))
    report['silhouetteTest']=dict(views=24,azimuthStepDegrees=30,elevationsRadians=[.15,.60],resolution=[640,640],
        metric='Binary silhouette intersection-over-union, same orthographic camera and scale; not a pixel color or render speed test.')
    report['selectedVariant']='compact-reduced-35'
    (OUT/'optimization.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    font='/System/Library/Fonts/Supplemental/Arial.ttf'
    title=ImageFont.truetype(font,28);label=ImageFont.truetype(font,21);small=ImageFont.truetype(font,17)
    choices=[('compact','Исходная модель · 1 824'),('compact-union','Объединение · 3 216'),('compact-reduced-35','Объединение + упрощение · 1 328')]
    jobs=[(choices,'optimization-preview.png','NURAY · внешняя оболочка кроны')]
    if step_scores:
        steps=[('compact-reduced-35','Принятая версия · 1 328')]
        steps.extend((r['id'],f"Ступень {r['stage']} · {r['triangles']} треугольников") for r in report['variants'] if r.get('stage'))
        jobs.append((steps,'reduction-steps-preview.png','NURAY · ещё −20%, ещё −20%, ещё −20%'))
    light=np.array([-.6,.85,.7]);light/=np.linalg.norm(light)
    for choices,filename,heading in jobs:
        W,H=(400 if len(choices)>3 else 530),540
        sheet=Image.new('RGB',(W*len(choices),H*2+105),'#f1efe7');d=ImageDraw.Draw(sheet)
        d.text((25,15),heading,font=title,fill='#303d2e')
        d.text((25,57),'Одна камера и масштаб. Ствол и ветви без изменений.',font=label,fill='#647059')
        for row,yaw in enumerate((.62,2.19)):
            base,_=project(original,yaw,.16,center);scale=min((W-65)/np.ptp(base[:,:,0]),(H-95)/np.ptp(base[:,:,1]))
            for col,(key,caption) in enumerate(choices):
                attrs,mats=meshes[key];p,depth=project(attrs,yaw,.16,center)
                x,y=col*W,105+row*H
                d.rounded_rectangle((x+8,y+6,x+W-8,y+H-8),radius=12,fill='#faf9f4')
                screen=p*scale+[x+W/2,y+(H-50)/2]
                color=np.array([PALETTE[k][1] for k in mats])*(.65+.7*np.maximum(0,attrs[:,0,3:6]@light))[:,None]
                color=np.where(color<=.0031308,color*12.92,1.055*color**(1/2.4)-.055)
                for i in np.argsort(depth.mean(1)):
                    d.polygon([tuple(v) for v in screen[i]],fill=tuple((np.clip(color[i],0,1)*255).astype(int)))
                d.text((x+20,y+H-62),caption,font=label,fill='#303d2e')
                d.text((x+20,y+H-34),'Ракурс ¾' if row==0 else 'Обратная сторона',font=small,fill='#647059')
        sheet.save(OUT/filename)
    for row in report['variants']:
        print(row['id'],row['triangles'],'IoU min/mean',row['silhouetteIoUMin'],row['silhouetteIoUMean'])


if __name__=='__main__':main()

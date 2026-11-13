"""Package a validated mixed-provider canonical scene for both viewer backends."""
import argparse,json,os,shutil,subprocess,sys
from pathlib import Path

def main(root):
    tiling=Path(__file__).resolve().parents[2]/'prototype/tiling';full=root/'canonical/full'
    if (root/'survey-terrain.json').exists():
        from survey_fairing import refresh_ground_normals
        refresh_ground_normals(root)
    canonical=json.loads((full/'scene.json').read_text())
    # Inspection presets follow the audit locations, not hand-patched geometry.
    if (root/'survey-outliers.json').exists():
        audit=json.loads((root/'survey-outliers.json').read_text())
        for i,point in enumerate(audit['quarantined']):
            east,north,_=point['point'];key=f'survey-outlier-{i+1}-review'
            canonical.setdefault('witnessViews',{})[key]=dict(yaw=.31,pitch=.35,distance=155,
              target=[east,point['interpolatedTerrainHeightM']-canonical['origin'][2],-north])
            canonical.setdefault('witnessViewLabels',{})[key]=f'Склон · исправленный пик {i+1}'
        (full/'scene.json').write_text(json.dumps(canonical,ensure_ascii=False,separators=(',',':'))+'\n')
    textures=root/'textures';textures.mkdir(exist_ok=True)
    for name in canonical['textures']:shutil.copyfile(full/Path(name).name,textures/Path(name).name)
    subprocess.run([os.environ['NODE'],str(tiling/'pack_tiles.mjs'),str(root)],check=True)
    catalog=json.loads((root/'tileset.json').read_text())
    catalog.update(radiusM=3000,geography={'latitude':51.725354,'longitude':36.189045,'timeZone':'Europe/Moscow','utcOffset':3,'label':'Курск'},
      witnessViews={'overview':{'yaw':.15,'pitch':1.15,'distance':9200,'target':[0,20,0]},'center':{'yaw':-.35,'pitch':.72,'distance':450,'target':[25,10,-30]},'circus-review':{'yaw':-.35,'pitch':.72,'distance':450,'target':[25,10,-30]}},
      witnessViewLabels={'circus-review':'Курский цирк · ближе'})
    catalog['witnessViews'].update(canonical.get('witnessViews',{}))
    catalog['witnessViewLabels'].update(canonical.get('witnessViewLabels',{}))
    (root/'tileset.json').write_text(json.dumps(catalog,ensure_ascii=False,separators=(',',':'))+'\n')
    subprocess.run([sys.executable,str(Path(__file__).with_name('verify_scene.py')),str(root)],check=True)
    subprocess.run([sys.executable,str(tiling/'export_merged_glb.py'),'--source',str(root),'--output',str(root/'merged')],check=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);main(p.parse_args().root)

"""Upgrade this capture's land semantics without refitting terrain or roads."""
import argparse,pickle,sys,json,gc,time,hashlib,signal,faulthandler
from pathlib import Path
import numpy as np
import shapely as sh
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'prototype'))
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'prototype/tiling'))
import build as b
from region_checkpoint import restore,save
from surface_semantic_upgrade import upgrade
from validation_geometry import footprint_fingerprint
from finish_region import finish
from partition_refinement import refine


def footprint_inputs():
    return dict(flat=[s['poly'] for s in b.surfaces if s['kind']=='roadbed_flat'],
                land=[s['poly'] for s in b.surfaces if s['kind'] in ('land','curb_top')],
                water=[s['poly'] for s in b.surfaces if s['kind']=='water'])


def main():
    p=argparse.ArgumentParser();p.add_argument('--checkpoint',type=Path,required=True)
    p.add_argument('--source-decode',type=Path,required=True);p.add_argument('--output-checkpoint',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True);a=p.parse_args()
    faulthandler.register(signal.SIGUSR1,all_threads=True)
    inputs=restore(b,a.checkpoint);print('RESTORED FOR SEMANTIC UPGRADE',len(b.surfaces),flush=True)
    parent=b.DATA
    if a.output_dir.exists():raise FileExistsError(a.output_dir)
    a.output_dir.mkdir(parents=True);b.DATA=a.output_dir.resolve()
    with a.source_decode.open('rb') as f:_,state,candidates,_=pickle.load(f)
    for tile,digest in {r['source']['tile']:r['source']['fileSha256'] for r in state['records']}.items():
        if hashlib.sha256((b.SOURCE/'source/cache'/f'{tile}.json').read_bytes()).hexdigest()!=digest:
            raise ValueError('Source decode differs from this live capture')
    del state;gc.collect()
    added=[];changed=[]
    for r in b.records:
        old=r['semantics'];new=b.classify(r['layer'],r['properties'],r['geometryType'])
        r['semantics']=new
        if new['status']!='built' or old['status']=='built':continue
        if new['kind']!='land':raise ValueError(('New non-land class requires a structural rebuild',r['layer']))
        xyz=np.asarray(r['coordinates']);patches=[];polys=[]
        for i in range(len(xyz)-2):
            t=xyz[i:i+3]
            if abs(np.linalg.det(np.column_stack((t[:,:2],np.ones(3)))))<1e-8:continue
            g=b.clean(sh.Polygon(t[:,:2])).intersection(b.EXTENT)
            if g.area>1e-9:polys.append(g);patches.append((g,b.plane(t)))
        if not polys:continue
        metadata=dict(purpose=new['purpose'],construction=new['construction'],surfaceType=new['surface'],styleId=new['styleId'])
        b.source_owners[r['id']]=metadata
        added.append(dict(id=r['id'],layer=r['layer'],kind='land',material=new['material'],rank=new['rank'],**metadata,
            tiers=r['properties'].get('db_tiers') or [0],part=r['properties'].get('db_road_part','roadbed_flat'),poly=b.union(polys),patches=patches))
        changed.append(r['id'])
    audit=b.audit_semantics(b.records)
    if not audit['passed']:raise ValueError(('Unsupported classes remain',audit['counts']))
    cache=None;cache_path=parent/'validation-footprints.pkl'
    if cache_path.exists():
        with cache_path.open('rb') as f:cache=pickle.load(f)
        if cache.get('fingerprint')!=footprint_fingerprint(footprint_inputs(),b.GRID):cache=None
    report=upgrade(b,candidates,added);report['sourceFeatures']=changed
    (b.DATA/'semantic-upgrade.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    if cache is not None and report['coverageExactlyPreserved']:
        # Every replaced cell was proven geometrically equal to its pieces;
        # the road/water rows were not touched. Only the expensive unions are
        # reused. All overlap, height, opening and emitted-solid tests rerun.
        old_fingerprint=cache['fingerprint'];cache['fingerprint']=footprint_fingerprint(footprint_inputs(),b.GRID)
        cache['derivation']=dict(type='exact-cell-coverage-preserving-land-semantics',parentFingerprint=old_fingerprint,
                                affectedCells=report['affectedCells'])
        with (b.DATA/'validation-footprints.pkl').open('wb') as f:pickle.dump(cache,f)
        print('TRANSFERRED EXACT FOOTPRINT PROOF',flush=True)
    opening,road,checks,total,bound=inputs
    candidates.extend(added)
    raw=b.union([r['poly'] for r in candidates if r['kind']=='road' and r['part']=='roadbed_flat']).difference(opening)
    b.protected_road_islands,_=b.road_seam_protection(candidates,b.records,raw,b.GRID)
    road=refine(b,opening,road,candidates)
    inputs=(opening,road,checks,total,bound)
    # Any changed road/land rows invalidate the transferred footprint cache by
    # its complete content fingerprint. All validation is performed below.
    del candidates,added;gc.collect()
    save(b,a.output_checkpoint,inputs)
    finish(b,*inputs,time.time(),fresh_source=True)


if __name__=='__main__':main()

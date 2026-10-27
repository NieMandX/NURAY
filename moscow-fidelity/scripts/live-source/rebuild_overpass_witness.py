"""Rebuild independent structural sheets; cache exact source-derived results."""
import sys,pickle,json,hashlib,time,argparse,shutil,ast
from pathlib import Path
from collections import defaultdict
from multiprocessing import get_context
import numpy as np
import shapely as sh
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'prototype'))
from overpasses import build
from overpass_sheets import structural_sheets
from build import triangulate,z_at,plane
from portal_cache_compatibility import previous_function,unchanged


_JOB_CONTEXT=None

def job(index):
    w,demtree,sheets,connections,receipt,cache,prior,old_function,floors,floortree=_JOB_CONTEXT
    level,transport,rows=sheets[index];parents={r['owner'] for r in rows}
    width=max(r.get('profile',{}).get('overhang',1.) for r in rows)
    reach=sh.union_all([r['poly'] for r in rows],grid_size=.00001).buffer(width*3+.01)
    dem=[w['dem'][int(i)] for i in sorted(demtree.query(reach,predicate='intersects'))]
    nearby_floors=[floors[int(i)] for i in sorted(floortree.query(reach,predicate='intersects'))]
    entries=[r for r in connections if r['kind']=='roadbed_overpass' and r.get('transport','vehicle')==transport and parents.intersection(r['sourceParents'])]
    h=hashlib.sha256(receipt.encode());h.update(w['extent'].wkb);h.update(json.dumps(entries,sort_keys=True).encode())
    for row in rows:
        h.update(row['poly'].wkb);h.update(np.asarray(row['plane']).tobytes())
        h.update(json.dumps({k:row.get(k) for k in ('owner','kind','tiers','transport','material','profile')},sort_keys=True).encode())
    for g,c in dem:h.update(g.wkb);h.update(np.asarray(c).tobytes())
    for row in nearby_floors:
        h.update(row['poly'].wkb);h.update(np.asarray(row['plane']).tobytes());h.update(row['owner'].encode())
    path=cache/(h.hexdigest()+'.pkl')
    if not path.exists():
        groups=defaultdict(list)
        args=(rows,dem,sh.STRtree([g for g,c in dem]),groups,w['extent'],.00001,triangulate,z_at,plane,entries)
        old_path=prior/path.name if prior else None
        try:
            if old_path and old_path.exists():
                with old_path.open('rb') as f:previous=pickle.load(f)
                if all(p['passed'] for p in previous['profiles']) and (old_function=='partition-only' or unchanged(args,old_function)):
                    temporary=path.with_suffix('.tmp');shutil.copyfile(old_path,temporary);temporary.replace(path)
                    path.with_suffix('.equivalence.json').write_text(json.dumps(dict(
                        priorRecipe=prior.name,sourceReceiptSha256=receipt,inputHash=h.hexdigest(),
                        priorResultSha256=hashlib.sha256(old_path.read_bytes()).hexdigest(),
                        proof=('prepartitioned construction code identical; exact source cells, resolved entries, DEM and collision floors match'
                            if old_function=='partition-only' else
                            'all geometry code except joined_portal_datums identical; exact WKB/station/value equality of old and new function outputs')),indent=2))
                    print('SHEET EQUIVALENT',index+1,'/',len(sheets),flush=True)
                    return path
                del previous
            profiles,count=build(*args,prepartitioned=True,collision_floors=nearby_floors)
        except Exception:
            with path.with_suffix('.input.pkl').open('wb') as f:pickle.dump(dict(surfaces=rows,dem=dem,connections=entries,extent=w['extent']),f)
            print('SHEET EXCEPTION',index+1,'/',len(sheets),path,flush=True)
            raise
        temporary=path.with_suffix('.tmp')
        with temporary.open('wb') as f:pickle.dump(dict(profiles=profiles,groups=groups,count=count),f)
        temporary.replace(path)
        if not all(p['passed'] for p in profiles):
            with path.with_suffix('.input.pkl').open('wb') as f:pickle.dump(dict(surfaces=rows,dem=dem,connections=entries,extent=w['extent']),f)
        print('SHEET RESULT',index+1,'/',len(sheets),'passed',all(p['passed'] for p in profiles),flush=True)
    else:print('SHEET CACHE',index+1,'/',len(sheets),flush=True)
    return path


def main():
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path)
    parser.add_argument('--witness',type=Path);parser.add_argument('--output',type=Path)
    parser.add_argument('--portal-cache',help='Prior recipe to compare by exact portal-function output, never an unchecked cache fallback')
    parser.add_argument('--partition-cache',help='Prior recipe with identical prepartitioned construction and exact job input hashes')
    options=parser.parse_args();root=options.root;start=time.time();recipe=hashlib.sha256()
    prototype=Path(__file__).resolve().parents[2]/'prototype'
    for name in ('overpasses.py','overpass_sheets.py','transitions.py','structure_clearance.py'):
        recipe.update((Path(__file__).resolve().parents[2]/'prototype'/name).read_bytes())
    recipe_hash=recipe.hexdigest();receipt=hashlib.sha256((root/'sources.json').read_bytes()).hexdigest()
    cache=root/'overpass-sheet-cache'/recipe_hash;cache.mkdir(parents=True,exist_ok=True)
    (cache/'code').mkdir(exist_ok=True)
    for name in ('overpasses.py','overpass_sheets.py','transitions.py','structure_clearance.py'):
        (cache/'code'/name).write_bytes((prototype/name).read_bytes())
    assert not (options.portal_cache and options.partition_cache)
    prior_name=options.portal_cache or options.partition_cache
    prior=root/'overpass-sheet-cache'/prior_name if prior_name else None
    old_function=None
    if options.partition_cache:
        names=('overpasses.py','overpass_sheets.py','transitions.py','structure_clearance.py')
        old={name:(prior/'code'/name).read_bytes() for name in names}
        assert hashlib.sha256(b''.join(old.values())).hexdigest()==prior_name
        for name in names:
            if name!='overpass_sheets.py':assert old[name]==(prototype/name).read_bytes(),name
        def without_partition(source):
            tree=ast.parse(source)
            tree.body=[n for n in tree.body if not (isinstance(n,ast.FunctionDef) and n.name=='structural_sheets')]
            return ast.dump(tree,include_attributes=False)
        assert without_partition(old['overpass_sheets.py'])==without_partition((prototype/'overpass_sheets.py').read_bytes())
        old_function='partition-only'
    elif prior:old_function=previous_function(prior,prototype,options.portal_cache)
    witness=options.witness or root/'overpass-witness.pkl'
    w=pickle.load(witness.open('rb'));w.pop('profiles',None)
    witness_hash=hashlib.file_digest(witness.open('rb'),'sha256').hexdigest()
    floors=w.get('collisionFloors',w['surfaces']);floortree=sh.STRtree([r['poly'] for r in floors])
    print('FULL SOURCE WITNESS',len(w['surfaces']),len(w['dem']),flush=True)
    demtree=sh.STRtree([g for g,c in w['dem']])
    sheets,connections=structural_sheets(w['surfaces'],w['connections'],w['dem'],demtree,.00001,z_at)

    global _JOB_CONTEXT
    _JOB_CONTEXT=(w,demtree,sheets,connections,receipt,cache,prior,old_function,floors,floortree)
    # Each geometry job is independent. Processes avoid the Python GIL in
    # triangle construction; the immutable witness is inherited copy-on-write.
    with get_context('fork').Pool(processes=4) as pool:paths=pool.map(job,range(len(sheets)),chunksize=1)
    groups=defaultdict(list);profiles=[];count=0
    for path in paths:
        with path.open('rb') as f:result=pickle.load(f)
        profiles.extend(result['profiles']);count+=result['count']
        for key,faces in result['groups'].items():groups[key].extend(faces)
    report=[{k:v for k,v in p.items() if 'Geometry' not in k and k!='extensionHeightCells'} for p in profiles]
    (root/'overpass-rebuild-report.json').write_text(json.dumps(report,indent=2))
    (root/'overpass-sheet-results.json').write_text(json.dumps([str(p) for p in paths],indent=2))
    print('FULL PROFILES',len(profiles),'FAILED',sum(not p['passed'] for p in profiles),'seconds',time.time()-start,flush=True)
    if not all(p['passed'] for p in profiles):raise ValueError('Full structural source witness failed; per-sheet geometry/input caches retained')
    target=options.output or root/'overpass-rebuilt.pkl';temporary=target.with_suffix('.tmp')
    with temporary.open('wb') as f:pickle.dump(dict(profiles=profiles,groups=groups,count=count,recipeSha256=recipe_hash,sourceReceiptSha256=receipt,witnessSha256=witness_hash),f)
    current=hashlib.sha256()
    for name in ('overpasses.py','overpass_sheets.py','transitions.py','structure_clearance.py'):
        current.update((Path(__file__).resolve().parents[2]/'prototype'/name).read_bytes())
    if current.hexdigest()!=recipe_hash:raise RuntimeError('Structural rule changed during the rebuild; result was not published')
    temporary.replace(target)
    print('FULL STRUCTURES VERIFIED',time.time()-start,flush=True)


if __name__=='__main__':main()

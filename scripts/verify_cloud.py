#!/usr/bin/env python3
"""Verify published object sizes, content encoding, and public CORS."""
import argparse,concurrent.futures,hashlib,json,time
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.parse import quote,urljoin
ROOT=Path(__file__).resolve().parents[1]
def check_once(row,base):
    try:
        with urlopen(Request(urljoin(base,quote(row['path'],safe='/')),method='HEAD',headers={'Origin':'https://niemandx.github.io'}),timeout=30) as r:
            size=int(r.headers.get('Content-Length',-1))
            if size!=row['bytes']:return {'path':row['path'],'error':f'size {size} != {row["bytes"]}'}
            if r.headers.get('Access-Control-Allow-Origin') not in ['*','https://niemandx.github.io']:return {'path':row['path'],'error':'CORS missing'}
            if row['path'].endswith(('.bin.gz','.pack')) and r.headers.get('Content-Encoding'):return {'path':row['path'],'error':'Unexpected Content-Encoding; viewer decompresses explicitly'}
        return None
    except Exception as e:return {'path':row['path'],'error':str(e)}
def check(row,base):
    for attempt in range(3):
        error=check_once(row,base)
        if not error:return None
        if attempt<2:time.sleep(attempt+1)
    return error
def check_ranges(manifest):
    errors=[]
    for pack in manifest.get('packs',[]):
        rows=[r for r in manifest['files'] if r.get('pack',{}).get('path')==pack['path']]
        for row in (rows[0],rows[len(rows)//2],rows[-1]):
            offset=row['pack']['offset'];end=offset+row['bytes']-1
            try:
                req=Request(urljoin(manifest['baseURL'],quote(pack['path'],safe='/')),headers={'Origin':'https://niemandx.github.io','Range':f'bytes={offset}-{end}'})
                with urlopen(req,timeout=60) as r:
                    if r.status!=206 or r.headers.get('Content-Range')!=f'bytes {offset}-{end}/{pack["bytes"]}':raise ValueError('Invalid byte-range response')
                    data=r.read(row['bytes']+1)
                    if len(data)!=row['bytes'] or hashlib.sha256(data).hexdigest()!=row['sha256']:raise ValueError('Range checksum mismatch')
            except Exception as e:errors.append({'path':row['path'],'error':str(e)})
    return errors
def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,default=ROOT/'docs/assets-manifest.json');p.add_argument('--output',type=Path,default=ROOT/'.local/cloud-check.json');p.add_argument('--workers',type=int,default=8);a=p.parse_args()
    m=json.loads(a.manifest.read_text());bad=[]
    objects=[r for r in m['files'] if 'pack' not in r]+m.get('packs',[])
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
        fs=[pool.submit(check,r,m['baseURL']) for r in objects]
        for i,f in enumerate(concurrent.futures.as_completed(fs),1):
            v=f.result()
            if v:bad.append(v)
            if i%50==0:print(i,'checked,',len(bad),'pending/errors',flush=True)
    bad.extend(check_ranges(m))
    result={'checkedAt':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'logicalFiles':len(m['files']),'storageObjects':len(objects),'rangeSamples':3*len(m.get('packs',[])),'passed':not bad,'errors':bad}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n');print('RESULT',len(objects),len(bad),flush=True)
    raise SystemExit(bool(bad))
if __name__=='__main__':main()

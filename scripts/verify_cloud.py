#!/usr/bin/env python3
"""Verify published object sizes, content encoding, and public CORS."""
import argparse,concurrent.futures,json,time
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.parse import quote,urljoin
ROOT=Path(__file__).resolve().parents[1]
def check(row,base):
    try:
        with urlopen(Request(urljoin(base,quote(row['path'],safe='/')),method='HEAD',headers={'Origin':'https://niemandx.github.io'}),timeout=30) as r:
            size=int(r.headers.get('Content-Length',-1))
            if size!=row['bytes']:return {'path':row['path'],'error':f'size {size} != {row["bytes"]}'}
            if r.headers.get('Access-Control-Allow-Origin') not in ['*','https://niemandx.github.io']:return {'path':row['path'],'error':'CORS missing'}
            if row['path'].endswith('.bin.gz') and r.headers.get('Content-Encoding'):return {'path':row['path'],'error':'Unexpected Content-Encoding; viewer decompresses explicitly'}
        return None
    except Exception as e:return {'path':row['path'],'error':str(e)}
def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,default=ROOT/'docs/assets-manifest.json');p.add_argument('--output',type=Path,default=ROOT/'.local/cloud-check.json');p.add_argument('--workers',type=int,default=8);a=p.parse_args()
    m=json.loads(a.manifest.read_text());bad=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers) as pool:
        fs=[pool.submit(check,r,m['baseURL']) for r in m['files']]
        for i,f in enumerate(concurrent.futures.as_completed(fs),1):
            v=f.result()
            if v:bad.append(v)
            if i%1000==0:print(i,'checked,',len(bad),'pending/errors',flush=True)
    result={'checkedAt':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'files':len(m['files']),'passed':not bad,'errors':bad}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2)+'\n');print('RESULT',len(m['files']),len(bad),flush=True)
    raise SystemExit(bool(bad))
if __name__=='__main__':main()

"""Verify versioned public viewer files against the local export without credentials."""
import argparse,concurrent.futures,hashlib,json,re,time,urllib.request
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--url',required=True);p.add_argument('--report',type=Path,required=True)
a=p.parse_args();m=json.loads((a.root/'scene.json').read_text());names=['scene.json']+[c['file'] for c in m['chunks']]+list(m['textures'])
assert len(names)==len(set(names))
def check(name):
    path=a.root/name;raw=path.read_bytes()
    request=urllib.request.Request(a.url.rstrip('/')+'/'+name,method='HEAD',headers={'Origin':'https://niemandx.github.io'})
    try:
        with urllib.request.urlopen(request,timeout=45) as r:
            h=r.headers
            assert r.status==200,(name,r.status)
            assert int(h['Content-Length'])==len(raw),(name,'size',h['Content-Length'],len(raw))
            etag=h.get('ETag','').strip('"')
            if re.fullmatch('[0-9a-f]{32}',etag):
                assert etag==hashlib.md5(raw).hexdigest(),(name,'ETag mismatch')
            else:
                with urllib.request.urlopen(a.url.rstrip('/')+'/'+name,timeout=60) as body:
                    assert hashlib.sha256(body.read()).digest()==hashlib.sha256(raw).digest(),(name,'Content mismatch')
            assert h.get('Access-Control-Allow-Origin') in ['*','https://niemandx.github.io'],(name,'CORS')
            if name.endswith('.gz'):assert not h.get('Content-Encoding'),(name,'Unexpected automatic gzip decoding')
        return {'file':name,'ok':True,'bytes':len(raw)}
    except Exception as e:return {'file':name,'ok':False,'error':str(e)}
rows=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
    for row in pool.map(check,names):
        rows.append(row)
        if len(rows)%100==0:print('VERIFIED',len(rows),'/',len(names),flush=True)
report={'baseURL':a.url,'files':len(rows),'bytes':sum(r.get('bytes',0) for r in rows),'failures':[r for r in rows if not r['ok']]}
a.report.write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
if report['failures']:raise SystemExit(1)

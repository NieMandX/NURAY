#!/usr/bin/env python3
"""Restore immutable scene assets, streaming downloads and checking SHA-256."""
import argparse, concurrent.futures, hashlib, json, os, time
from pathlib import Path
from urllib.parse import urljoin, quote
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(4*1024*1024),b''): h.update(block)
    return h.hexdigest()
def selected(row,mode):
    rel=row['path'].split('/',1)[1]
    return mode=='all' or (mode=='tiles' and not rel.startswith('merged/')) or (mode=='merged' and not rel.startswith(('meshes/','textures/')))
def restore(row,root,base,check_only=False):
    path=(root/row['path']).resolve()
    if not path.is_relative_to(root.resolve()): raise ValueError('Unsafe manifest path')
    if path.is_file() and path.stat().st_size==row['bytes'] and digest(path)==row['sha256']: return 'verified'
    if check_only: raise ValueError(f"Missing/corrupt: {row['path']}")
    path.parent.mkdir(parents=True,exist_ok=True);partial=path.with_name(path.name+'.partial')
    url=urljoin(base,quote(row['path'],safe='/'))
    for attempt in range(4):
        try:
            offset=partial.stat().st_size if partial.exists() else 0
            if offset>=row['bytes']: partial.unlink();offset=0
            headers={'Range':f'bytes={offset}-'} if offset else {}
            with urlopen(Request(url,headers=headers),timeout=120) as response:
                append=bool(offset and response.status==206)
                if append and not response.headers.get('Content-Range','').startswith(f'bytes {offset}-'): raise ValueError('Invalid range response')
                with partial.open('ab' if append else 'wb') as f:
                    for block in iter(lambda:response.read(4*1024*1024),b''): f.write(block)
            if partial.stat().st_size!=row['bytes'] or digest(partial)!=row['sha256']:
                partial.unlink();raise ValueError(f"Checksum mismatch: {row['path']}")
            os.replace(partial,path);return 'downloaded'
        except Exception:
            if attempt==3: raise
            time.sleep(2**attempt)
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,default=ROOT/'docs/assets-manifest.json')
    p.add_argument('--destination',type=Path,default=ROOT/'moscow-fidelity/web-preview/prototype/tiles')
    p.add_argument('--mode',choices=['all','merged','tiles'],default='merged')
    p.add_argument('--workers',type=int,default=4);p.add_argument('--check-only',action='store_true')
    args=p.parse_args();m=json.loads(args.manifest.read_text());rows=[r for r in m['files'] if selected(r,args.mode)]
    print(f"{len(rows)} files, {sum(r['bytes'] for r in rows)/1e9:.2f} GB",flush=True)
    errors=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1,min(12,args.workers))) as pool:
        futures={pool.submit(restore,r,args.destination,m['baseURL'],args.check_only):r for r in rows}
        for i,f in enumerate(concurrent.futures.as_completed(futures),1):
            try: state=f.result()
            except Exception as e: errors.append(str(e));state='FAILED'
            if i%100==0 or i==len(rows) or state=='FAILED': print(f'{i}/{len(rows)} {state}',flush=True)
    if errors: raise SystemExit('\n'.join(errors))
    print('All selected files verified.')
if __name__=='__main__':main()

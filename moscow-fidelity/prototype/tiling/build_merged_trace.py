"""Build an optional ray acceleration cache from model.glb, never from tiles.

The GLB stays unchanged. Each compressed cache holds only its reordered index
buffer and BLAS, with hashes binding it to the exact GLB vertex/index bytes.
The browser uploads all GLB geometry and preserves every instance transform.
"""
import argparse,gzip,hashlib,json,struct,subprocess,tempfile
from pathlib import Path

def header(path):
    with path.open('rb') as f:
        magic,version,length,jlen,jtype=struct.unpack('<5I',f.read(20))
        if (magic,version,jtype)!=(0x46546c67,2,0x4e4f534a) or length!=path.stat().st_size:
            raise ValueError('Invalid GLB')
        raw=f.read(jlen);doc=json.loads(raw);blen,btype=struct.unpack('<2I',f.read(8))
        if btype!=0x004e4942 or f.tell()+blen!=length:raise ValueError('Invalid BIN')
        return doc,f.tell(),hashlib.sha256(raw).hexdigest()

def digest_range(f,offset,size):
    f.seek(offset);h=hashlib.sha256()
    while size:
        data=f.read(min(size,8*1024*1024))
        if not data:raise ValueError('Truncated GLB')
        h.update(data);size-=len(data)
    return h.hexdigest()

def build(glb):
    doc,offset,header_hash=header(glb);meta=doc['extras']['nuray'];out=glb.parent/'trace';out.mkdir(exist_ok=True)
    manifest=dict(format='nuray-merged-trace-v1',glbBytes=glb.stat().st_size,headerSha256=header_hash,draws=[],stats=meta['stats'])
    with tempfile.TemporaryDirectory(prefix='nuray-merged-bvh-') as tmp,glb.open('rb') as f:
        tmp=Path(tmp);exe=tmp/'builder';raw=tmp/'mesh.bin'
        subprocess.run(['clang++','-O3','-std=c++17',str(Path(__file__).with_name('merged_bvh.cpp')),'-o',str(exe)],check=True)
        for d in meta['draws']:
            v=doc['bufferViews'][d['vertexView']];ix=doc['bufferViews'][d['indexView']]
            vh=digest_range(f,offset+v['byteOffset'],v['byteLength']);ih=digest_range(f,offset+ix['byteOffset'],ix['byteLength'])
            key=hashlib.sha256((vh+ih+'sah-v1').encode()).hexdigest()[:20];info_path=out/(key+'.json');compressed=out/(key+'.bin.gz')
            if info_path.exists() and compressed.exists():info=json.loads(info_path.read_text())
            else:
                result=subprocess.run([str(exe),str(glb),str(offset+v['byteOffset']),str(v['byteLength']),str(offset+ix['byteOffset']),str(ix['byteLength']),str(raw)],check=True,capture_output=True,text=True)
                info=json.loads(result.stdout);info.update(nodeBytes=info['nodeCount']*32,vertexSha256=vh,indexSha256=ih)
                h=hashlib.sha256()
                with raw.open('rb') as source,compressed.open('wb') as sink,gzip.GzipFile(fileobj=sink,mode='wb',compresslevel=3,mtime=0) as z:
                    while data:=source.read(8*1024*1024):h.update(data);z.write(data)
                info.update(sha256=h.hexdigest(),compressedBytes=compressed.stat().st_size);info_path.write_text(json.dumps(info));raw.unlink()
            assert info['triangles']==d['triangles'] and info['vertexSha256']==vh and info['indexSha256']==ih
            manifest['draws'].append(dict(id=d['id'],vertexBytes=d['vertexBytes'],indexBytes=d['indexBytes'],file=compressed.name,**info))
            print(f"BVH {len(manifest['draws'])}/{len(meta['draws'])}: {d['name']} / {info['nodeCount']:,} nodes",flush=True)
    manifest['geometryBytes']=sum(d['vertexBytes']+d['indexBytes'] for d in manifest['draws'])
    manifest['nodeBytes']=sum(d['nodeBytes'] for d in manifest['draws'])
    manifest['compressedBytes']=sum(d['compressedBytes'] for d in manifest['draws'])
    target=out/'manifest.json';temporary=target.with_suffix('.tmp');temporary.write_text(json.dumps(manifest,separators=(',',':')));temporary.replace(target)
    print(json.dumps({k:v for k,v in manifest.items() if k not in ('draws','stats')},indent=2),flush=True)
    return manifest

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('glb',type=Path);a=ap.parse_args();build(a.glb.resolve())

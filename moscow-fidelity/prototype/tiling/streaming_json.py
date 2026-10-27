"""Copy untouched canonical fields byte-for-byte; iterate large arrays."""
import io,json,os,subprocess
from pathlib import Path
import ijson

class Window(io.RawIOBase):
    def __init__(self,path,start,end):
        self.file=Path(path).open('rb');self.file.seek(start);self.remaining=end-start
    def readable(self):return True
    def readinto(self,buffer):
        n=self.file.readinto(memoryview(buffer)[:min(len(buffer),self.remaining)])
        self.remaining-=n;return n
    def close(self):
        self.file.close();super().close()

class Document:
    def __init__(self,path):
        self.path=Path(path);self.index=self.path.with_suffix('.fields.json')
        info=json.loads(self.index.read_text()) if self.index.exists() else {}
        stat=self.path.stat()
        if info.get('bytes')!=stat.st_size or abs(info.get('mtimeMs',0)-stat.st_mtime*1000)>.01:
            subprocess.run([os.environ.get('NODE','node'),str(Path(__file__).with_name('index_json.mjs')),
                            str(self.path),str(self.index)],check=True)
            info=json.loads(self.index.read_text())
        self.fields={f['key']:f for f in info['fields']}
    def stream(self,key):
        f=self.fields[key];return io.BufferedReader(Window(self.path,f['start'],f['end']))
    def read(self,key):
        with self.stream(key) as f:return json.load(f)
    def items(self,key):
        with self.stream(key) as f:yield from ijson.items(f,'item',use_float=True)
    def rewrite(self,target,replacements,iterators=None):
        iterators=iterators or {};encode=lambda v:json.dumps(v,ensure_ascii=False,separators=(',',':')).encode()
        temporary=Path(target).with_suffix('.tmp')
        with temporary.open('wb') as out:
            out.write(b'{')
            keys=list(self.fields)+[k for k in replacements if k not in self.fields]
            for i,key in enumerate(keys):
                if i:out.write(b',')
                out.write(encode(key)+b':')
                if key in iterators:
                    out.write(b'[')
                    for j,value in enumerate(iterators[key]()):
                        if j:out.write(b',')
                        out.write(encode(value))
                    out.write(b']')
                elif key in replacements:out.write(encode(replacements[key]))
                else:
                    with self.stream(key) as src:
                        while block:=src.read(8*1024*1024):out.write(block)
            out.write(b'}')
        temporary.replace(target)

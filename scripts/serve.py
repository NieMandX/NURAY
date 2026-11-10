#!/usr/bin/env python3
"""Serve the current viewer without a build step."""
import argparse,http.server,functools,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8776);p.add_argument('--local-assets',action='store_true',help='Preview built local releases without changing the published cloud configuration');args=p.parse_args()
root=Path(__file__).resolve().parents[1]/'moscow-fidelity/web-preview'
class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if args.local_assets and self.path.split('?')[0]=='/prototype/tiles/config.json':
            config=json.loads((root/'prototype/tiles/config.json').read_text())
            config.pop('assetBase',None)
            config.pop('assetDelivery',None)
            config.pop('meshPacks',None)
            body=json.dumps(config).encode()
            self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        else:super().do_GET()
handler=functools.partial(Handler,directory=str(root))
print(f'Open http://127.0.0.1:{args.port}/',flush=True)
http.server.ThreadingHTTPServer(('127.0.0.1',args.port),handler).serve_forever()

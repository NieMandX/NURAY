#!/usr/bin/env python3
"""Serve the current viewer without a build step."""
import argparse,http.server,functools
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8776);args=p.parse_args()
root=Path(__file__).resolve().parents[1]/'moscow-fidelity/web-preview'
handler=functools.partial(http.server.SimpleHTTPRequestHandler,directory=str(root))
print(f'Open http://127.0.0.1:{args.port}/',flush=True)
http.server.ThreadingHTTPServer(('127.0.0.1',args.port),handler).serve_forever()

"""Exact, deterministic seamless railway repeat. Dimensions are model defaults.

A code-generated tile avoids perspective, baked shadows and mismatched image
edges. The same chart feeds dielectric ballast/sleepers and metallic rail bands.
"""
from pathlib import Path
import hashlib
import numpy as np
from PIL import Image
from railway_geometry import WIDTH,PERIOD,GAUGE,RAIL_HEAD


def make_texture(folder):
    size=512
    u=np.linspace(-WIDTH/2,WIDTH/2,size)[None,:]
    v=np.linspace(0,PERIOD,size)[:,None]
    # Periodic, deterministic aggregate noise. The edge texels are identical.
    rng=np.random.default_rng(314159);noise=np.zeros((size,size))
    for _ in range(45):
        kx=int(rng.integers(1,80));ky=int(rng.integers(1,32));phase=float(rng.random()*2*np.pi)
        noise+=np.cos(2*np.pi*(kx*(u/WIDTH+.5)+ky*v/PERIOD)+phase)/np.sqrt(45)
    rgb=np.clip(np.array([112,113,109])+noise[:,:,None]*13,0,255)
    sleeper=(np.abs(v-PERIOD/2)<.125)&(np.abs(u)<1.35)
    # A weathered concrete sleeper, darker than road paint even under the sun.
    concrete=np.clip(np.array([173,166,148])+noise[:,:,None]*5,0,255)
    rgb=np.where(sleeper[:,:,None],concrete,rgb)
    rail=(np.abs(u)>GAUGE/2)&(np.abs(u)<GAUGE/2+RAIL_HEAD)
    rail=np.broadcast_to(rail,(size,size))
    rgb=np.where(rail[:,:,None],np.array([216,222,225]),rgb)
    # Plates under the rail at each sleeper. The steel itself stays continuous.
    plates=(np.abs(np.abs(u)-(GAUGE/2+RAIL_HEAD/2))<.10)&(np.abs(v-PERIOD/2)<.095)&~rail
    rgb=np.where(plates[:,:,None],np.array([86,82,73]),rgb)
    rgb=np.rint(rgb).astype(np.uint8);rgb[-1]=rgb[0];rgb[:,-1]=rgb[:,0]
    name='railway-repeat-v1.png';path=Path(folder)/name;Image.fromarray(rgb).save(path,optimize=True)
    raw=path.read_bytes()
    return name,dict(sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw),widthM=WIDTH,repeatM=PERIOD,
                    gaugeM=GAUGE,railHeadM=RAIL_HEAD,sleeperLengthM=2.7,sleeperWidthM=.25,
                    dimensionsEvidence='NURAY prototype defaults, not measured 2GIS engineering data')

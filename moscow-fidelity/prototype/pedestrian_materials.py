"""Physical pedestrian appearances selected by explicit 2GIS surface class.

Source styles identify the material; albedos and metre-scale patterns are
authored PBR defaults, not measured source values. Ownership/height is unchanged.
"""
FIRST_MATERIAL = 26
TYPES = ('asphalt', 'stone', 'gravel', 'sand', 'wood')
STYLES = ('788159', '829125', '309670', '502339', '863950')
RULES = {'Immersive_park_polygon_pedestrian_'+kind:
         dict(kind=kind, material=FIRST_MATERIAL+i, styleId=STYLES[i])
         for i,kind in enumerate(TYPES)}
POLICY = ('Explicit 2GIS pedestrian class -> physical material; final canonical '
          'ownership only. Preserve geometry, priorities, heights, UVs and paths. '
          'Pedestrian asphalt linear albedo = road asphalt x 1.5. '
          'Unspecified pedestrian areas and underpasses keep their existing material.')


def is_paving(row):
    return row['kind']=='land' and (row['material']==7 or
           (row.get('purpose')=='pedestrian' and row.get('surfaceType') in TYPES))


def paving_material_ids(scene):
    return {7}|{i for i,m in enumerate(scene['materials']) if m.get('family') in {'pedestrian-'+kind for kind in TYPES}}


def materials(road_color=(.045, .051, .056)):
    settings = [
        ('Асфальт · пешеходный', [float(v)*1.5 for v in road_color], .93),
        ('Брусчатка · пешеходная', [.34, .325, .295], .88),
        ('Гравий · пешеходный', [.30, .285, .25], .97),
        ('Песок · пешеходный', [.47, .365, .225], .98),
        ('Деревянный настил', [.26, .145, .073], .84),
    ]
    return [dict(name=n, family='pedestrian-'+kind, color=c, roughness=r,
                 metallic=0, ior=1.5, kind=1, alphaCutoff=0,
                 texture=None if kind=='asphalt' else 'textures/pedestrian-'+kind+'-v1.png')
            for kind,(n,c,r) in zip(TYPES,settings)]


def make_textures(folder):
    """Seamless one-metre patterns with no baked lighting or perspective.

    Existing ground UVs are in local metres and survive transport tile clipping.
    The texture is shared by all instances of its surface class on both APIs.
    """
    import hashlib
    from pathlib import Path
    import numpy as np
    from PIL import Image
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    size=512
    y,x=np.meshgrid(np.arange(size)/(size-1), np.arange(size)/(size-1), indexing='ij')
    rng=np.random.default_rng(22891)
    def noise(count,maximum):
        out=np.zeros((size,size))
        for _ in range(count):
            kx,ky=rng.integers(1,maximum,2)
            out+=np.cos(2*np.pi*(kx*x+ky*y)+rng.uniform(0,2*np.pi))
        return out/np.sqrt(count)
    grain=noise(24,180)
    textures={}
    for kind in TYPES[1:]:
        if kind=='stone':
            # Running bond: 20 x 10 cm blocks, 4 mm mortar joints.
            row=np.floor(y*10);u=np.mod(x*5+.5*np.mod(row,2),1);v=np.mod(y*10,1)
            joints=(np.minimum(u,1-u)<.01)|(np.minimum(v,1-v)<.02)
            block=.025*np.sin(np.floor(x*5+.5*np.mod(row,2))*4.7+row*2.3)
            scalar=np.where(joints,.57,.94+block+.012*grain)
        elif kind=='gravel':
            # Periodic Voronoi aggregates (~2.5 cm), independent per-stone tone.
            cells=40;gx=x*cells;gy=y*cells;ix=np.floor(gx).astype(int);iy=np.floor(gy).astype(int)
            random=rng.random((cells,cells,3));near=np.full_like(x,1e9);tone=np.zeros_like(x)
            for dy in (-1,0,1):
                for dx in (-1,0,1):
                    q=random[(iy+dy)%cells,(ix+dx)%cells]
                    dist=(gx-(ix+dx+q[:,:,0]))**2+(gy-(iy+dy+q[:,:,1]))**2
                    hit=dist<near;near=np.minimum(near,dist);tone=np.where(hit,q[:,:,2],tone)
            scalar=.76+.22*tone+.012*grain
        elif kind=='sand':
            scalar=.95+.012*grain+.008*noise(12,16)
        else:
            # Six 16.7 cm boards per metre, staggered end joints and long grain.
            board=np.floor(x*6);u=np.mod(x*6,1);v=np.mod(y+.5*np.mod(board,2),1)
            joints=(np.minimum(u,1-u)<.012)|(np.minimum(v,1-v)<.002)
            fibres=np.sin(2*np.pi*(x*100+.16*np.sin(2*np.pi*y)))
            scalar=np.where(joints,.46,.88+.035*np.cos(board*2.4)+.035*fibres+.008*grain)
        rgb=np.repeat(np.rint(np.clip(scalar,0,1)*255).astype(np.uint8)[:,:,None],3,axis=2)
        rgb[-1]=rgb[0];rgb[:,-1]=rgb[:,0]
        name='pedestrian-'+kind+'-v1.png';path=folder/name
        Image.fromarray(rgb).save(path,optimize=True)
        raw=path.read_bytes()
        textures[name]=dict(sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw),repeatM=1,
                            provenance='NURAY authored physical pattern; explicit 2GIS '+kind+' class')
    return textures

"""Measure changed bridge footprints where their underside meets raised land."""
import argparse,json,pickle
from pathlib import Path
import numpy as np
import shapely as sh
from streaming_json import Document
from prepare_railway_entries import load_terrain
from transitions import below,parts

def audit(base,profiles):
    old=Document(base/'canonical/urban-model.json').read('overpassProfiles')
    old_deck=sh.union_all([sh.geometry.shape(p['deckGeometry']) for p in old],grid_size=1e-5)
    new_deck=sh.union_all([sh.geometry.shape(p['deckGeometry']) for p in profiles],grid_size=1e-5)
    added=new_deck.difference(old_deck);removed=old_deck.difference(new_deck)
    print('DECK FOOTPRINT CHANGE',added.area,removed.area,flush=True)
    dem,tree=load_terrain(base);results={}
    for kind,delta,source in [('added',added,profiles),('removed',removed,old)]:
        low=[]
        for p in source:
            if not sh.geometry.shape(p['deckGeometry']).intersects(delta):continue
            for row in p['extensionHeightCells']:
                poly=sh.geometry.shape(row['geometry']);piece=poly.intersection(delta)
                if piece.area<1e-10:continue
                c=np.asarray(row['heightPlane'])
                for i in tree.query(piece,predicate='intersects'):
                    ground,d=dem[int(i)]
                    clip=below(piece.intersection(ground),c-d,.1+p['deckDepthM'])
                    if clip.area>1e-10:low.extend(parts(clip))
        low=sh.union_all(low,grid_size=1e-5)
        results[kind]=dict(footprintAreaM2=delta.area,groundContactAreaM2=low.area,
            groundContactCoreM2=low.buffer(-.0001).area,groundContactGeometry=sh.geometry.mapping(low))
        print('GROUND DELTA',kind,results[kind]['groundContactAreaM2'],flush=True)
    return results

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('base',type=Path);ap.add_argument('product',type=Path);ap.add_argument('output',type=Path);a=ap.parse_args()
    product=pickle.load(a.product.open('rb'))
    a.output.write_text(json.dumps(audit(a.base,product['profiles']),indent=2))

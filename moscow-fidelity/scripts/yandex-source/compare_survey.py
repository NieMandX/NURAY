"""Preview a candidate survey registration against a local city; no scene edits.

The projection must be supplied explicitly. A low nearest-edge residual is
evidence of visual alignment, not proof of the survey CRS/vertical datum.
"""
import argparse,gzip,json,os,pickle
from pathlib import Path
os.environ.setdefault('MPLCONFIGDIR','/tmp/nuray-matplotlib')
import numpy as np
import shapely as sh
from pyproj import Transformer
from build_scene import Terrain

def compare(survey_path,city_root,source,out,projection):
    survey=json.loads(gzip.decompress(survey_path.read_bytes()))
    city=json.loads((city_root/'canonical/urban-model.json').read_text())
    transform=Transformer.from_crs(projection,city['crsProj'],always_xy=True)
    def project(p):
        a=np.array(p,float);a[:,:2]=np.array(transform.transform(a[:,0],a[:,1])).T;return a
    marks=project([r['point'] for r in survey['groundMarks']])
    buildings=[project(r['points'])[:,:2] for r in survey['buildings']]
    rows,*_=pickle.load(open(source/'projected-scene-v1.pickle','rb'))
    source_edges=sh.union_all([g for f,g,l in rows if f['layer']=='building' and not g.is_empty]).boundary
    index=sh.STRtree(list(sh.get_parts(source_edges)))
    samples=sh.get_coordinates(sh.segmentize(sh.MultiLineString(buildings),3))
    points=sh.points(samples);ids=index.nearest(points);distances=sh.distance(points,index.geometries[ids])
    terrain=Terrain(np.load(city_root/'canonical/terrain.npz')['triangles'])
    height_diff=marks[:,2]-terrain.sample(marks[:,:2])
    result=dict(source=survey['report'].get('source'),candidateProjection=projection,
                coordinateStatus='Candidate only; not confirmed by the survey author',verticalDatum='Unconfirmed; no vertical shift applied',
                horizontalFit='None; direct candidate projection, no fitted shift/rotation/scale',
                edgeResidualPercentilesM=np.percentile(distances,[25,50,75,90,95]).tolist(),
                heightDifferencePercentilesM=np.percentile(height_diff,[0,10,25,50,75,90,100]).tolist(),
                groundMarks=len(marks),groundElevationRangeM=[marks[:,2].min(),marks[:,2].max()],appliedToScene=False)
    out.mkdir(parents=True,exist_ok=True)
    (out/'comparison.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    np.savez_compressed(out/'candidate-ground-points.npz',eastNorthHeight=marks)
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    bounds=[marks[:,0].min()-30,marks[:,0].max()+30,marks[:,1].min()-30,marks[:,1].max()+30]
    window=sh.box(bounds[0],bounds[2],bounds[1],bounds[3]);fig,axes=plt.subplots(1,2,figsize=(16,9))
    axes[0].add_collection(LineCollection([np.asarray(l.coords) for l in sh.get_parts(source_edges.intersection(window))],colors='#498bc2',linewidths=1.7,label='Яндекс · здания'))
    axes[0].add_collection(LineCollection(buildings,colors='#d46732',linewidths=.8,label='DWG · контуры зданий'))
    axes[0].scatter(marks[:,0],marks[:,1],s=1,c='#758e70',alpha=.3,label='Отметки земли');axes[0].legend();axes[0].set_title('Предварительное совмещение планов')
    plot=axes[1].scatter(marks[:,0],marks[:,1],s=4,c=height_diff,cmap='coolwarm',vmin=-8,vmax=8)
    fig.colorbar(plot,ax=axes[1],fraction=.04,pad=.03,label='DWG − рельеф 2ГИС, м');axes[1].set_title('Разница высот в точках съёмки')
    for ax in axes:ax.set(xlim=bounds[:2],ylim=bounds[2:],aspect='equal',xlabel='Восток от цирка, м',ylabel='Север от цирка, м');ax.grid(alpha=.15)
    fig.suptitle('Курский Детинец · система координат и высот пока не подтверждена',fontsize=15);fig.tight_layout();fig.savefig(out/'alignment-preview.png',dpi=140)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--survey',type=Path,required=True);p.add_argument('--city',type=Path,required=True);p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--candidate-proj',required=True);a=p.parse_args()
    compare(a.survey,a.city,a.source,a.output,a.candidate_proj)

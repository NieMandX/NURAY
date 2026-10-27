"""Reproducible repair stage after the standard 2GIS Blender assembly.

Run using Python with numpy, shapely and pyproj. Blender needs Shapely in
ROOT/python_libs311 (or pass --dependencies). Output is always a separate file.
"""
import argparse,subprocess,sys
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--blender',type=Path,default=Path('/Applications/Blender 2.app/Contents/MacOS/Blender'))
    parser.add_argument('--input',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--dependencies',type=Path)
    args=parser.parse_args();root=args.root.resolve();scripts=root/'scripts';area=root/'output/area_10000'
    source=args.input or area/'MoscowCity_10000m_MSK77.blend'
    output=args.output or area/'MoscowCity_10000m_MSK77_corrected.blend'
    if source.resolve()==output.resolve():parser.error('Input and output must differ')
    masks=area/'fidelity_masks'
    subprocess.run([sys.executable,str(scripts/'prepare_fidelity_sources.py'),str(root),str(masks)],check=True)
    subprocess.run([str(args.blender),'--background',str(source),'--python-exit-code','1','--python',str(scripts/'repair_blender.py'),'--','--masks',str(masks),'--output',str(output),'--dependencies',str(args.dependencies or root/'python_libs311')],check=True)
    if not output.is_file() or not output.with_suffix('.report.json').is_file():raise RuntimeError('Repair did not produce both scene and validation report')
    print('Corrected scene:',output)

if __name__=='__main__':main()

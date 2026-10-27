"""Carry source libraries and evidence through canonical geometry revisions."""
from pathlib import Path
import shutil
from canonical_store import copy_asset


def copy_support_assets(base,output):
    base,output=Path(base),Path(output)
    if base.resolve()==output.resolve():raise ValueError('Support assets require a separate output version')
    for name in ('textures','library','fence-library'):
        if (base/name).exists():shutil.copytree(base/name,output/name,dirs_exist_ok=True,copy_function=copy_asset)
    if (base/'street-objects.json').exists():
        output.mkdir(parents=True,exist_ok=True)
        copy_asset(base/'street-objects.json',output/'street-objects.json')
    canonical=output/'canonical';canonical.mkdir(parents=True,exist_ok=True)
    # Keep the shared terrain and source evidence, not obsolete generated
    # city/transport metadata or a previous stage's validation verdict.
    for source in (base/'canonical').iterdir():
        if source.is_file() and (source.suffix=='.npz' or source.name.endswith('.json.gz')):
            copy_asset(source,canonical/source.name)

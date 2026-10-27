"""Reuse a geometry result only after proving the changed function is inert.

This narrowly handles a change to joined_portal_datums. All other source code,
input geometry, source receipt and resolved portal datums must be identical.
It never adopts a failed result and never treats a changed datum as equivalent.
"""
import ast,hashlib
from pathlib import Path
import numpy as np
import overpass_sheets
import overpasses


def previous_function(cache,prototype,expected_hash):
    names=('overpasses.py','overpass_sheets.py','transitions.py')
    old={name:(cache/'code'/name).read_bytes() for name in names}
    h=hashlib.sha256()
    for name in names:h.update(old[name])
    if h.hexdigest()!=expected_hash:raise ValueError('Prior recipe archive does not match its cache namespace')
    for name in ('overpasses.py','transitions.py'):
        if old[name]!=(prototype/name).read_bytes():raise ValueError('Geometry code outside the portal join changed')
    before=ast.parse(old['overpass_sheets.py']);after=ast.parse((prototype/'overpass_sheets.py').read_text())
    target='joined_portal_datums'
    fn=next(n for n in before.body if isinstance(n,ast.FunctionDef) and n.name==target)
    def other(tree):
        tree.body=[n for n in tree.body if not (isinstance(n,ast.FunctionDef) and n.name==target)]
        return ast.dump(tree,include_attributes=False)
    if other(before)!=other(after):raise ValueError('Sheet construction outside the portal join changed')
    namespace=dict(vars(overpass_sheets))
    exec(compile(ast.Module(body=[fn],type_ignores=[]),str(cache/'code/overpass_sheets.py'),'exec'),namespace)
    return namespace[target]


class SameDatums(Exception):pass
class ChangedDatums(Exception):pass


def unchanged(build_args,old_function):
    current=overpasses.joined_portal_datums
    def probe(*args):
        new=current(*args)
        try:old=old_function(*args)
        except (ValueError,IndexError):raise ChangedDatums()
        same=len(new)==len(old) and all(a[0].wkb==b[0].wkb and
            np.array_equal(a[1],b[1]) and np.array_equal(a[2],b[2]) for a,b in zip(new,old))
        if same:raise SameDatums()
        raise ChangedDatums()
    overpasses.joined_portal_datums=probe
    try:
        overpasses.build(*build_args,prepartitioned=True)
    except SameDatums:return True
    except ChangedDatums:return False
    finally:overpasses.joined_portal_datums=current
    return False

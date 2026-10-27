"""Freeze imported glTF mesh nodes at their evaluated pose before world-space baking."""
from mathutils import Matrix

def bake_static_nodes(objects,transform):
    world={obj:obj.matrix_world.copy() for obj in objects}
    for obj in objects:
        if obj.type!='MESH':continue
        if obj.data.users>1:obj.data=obj.data.copy()
        obj.data.transform(transform@world[obj])
        obj.animation_data_clear()
        obj.parent=None
        obj.matrix_world=Matrix.Identity(4)

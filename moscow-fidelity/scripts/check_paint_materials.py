"""Check the white/yellow reflectance budget and texture multiplier in real Blender."""
import bpy,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from repair_blender import paint_material,cap_other_materials,WHITE,YELLOW
white=paint_material('paint_test_white',WHITE,'white');yellow=paint_material('paint_test_yellow',YELLOW,'yellow')
other=bpy.data.materials.new('white_facade_test');other.use_nodes=True;other.diffuse_color=(1,1,1,1)
bsdf=next(n for n in other.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
tex=other.node_tree.nodes.new('ShaderNodeTexImage');tex.image=bpy.data.images.new('white_reference_image',width=1,height=1)
tex.image.pixels=[1,1,1,1];other.node_tree.links.new(tex.outputs['Color'],bsdf.inputs['Base Color'])
cap_other_materials()
assert other['fidelity_color_image']==tex.image.name
assert abs(other['fidelity_texture_factor']-.65)<1e-6
assert bsdf.inputs['Base Color'].links[0].from_node.type=='VECT_MATH'
for mat,expected in [(white,WHITE),(yellow,YELLOW)]:
    node=next(n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
    assert max(abs(a-b) for a,b in zip(node.inputs['Base Color'].default_value,expected))<1e-6
    assert node.inputs['Emission Strength'].default_value==0
    luminance=sum(a*b for a,b in zip(expected,[.2126,.7152,.0722]))
    assert luminance>.65
print('PASS: white and yellow retain hue, exceed other albedo values, and do not emit light; texture cap preserves its source',flush=True)

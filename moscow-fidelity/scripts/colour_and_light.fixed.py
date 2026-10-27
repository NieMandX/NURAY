"""Restore the source colour textures and use scene lighting in Blender."""
import bpy,math
def source_marking_colour(name):
    # Original style colours for coloured road marking layers (sRGB -> linear).
    values={'LinearMarking_ShortIntermittentBlue':'5294E4','LinearMarking_Stop':'E3D862','PolygonMarkings_waffle':'FEFA53'}
    if name not in values:return None
    srgb=[int(values[name][i:i+2],16)/255 for i in (0,2,4)]
    return [v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in srgb]+[1]

def configure_colour_and_light():
    sc=bpy.context.scene
    bounds=sc.get('extent_msk_east_north')
    if bounds and bounds[2]-bounds[0]>2000:
        # The full square must fit both axes of the top-down overview.
        sc.render.resolution_x=1600;sc.render.resolution_y=1600
    for obj in bpy.data.objects:
        if sc.get('fidelity_repair_version'):continue  # Keep per-face yellow/white assignments.
        colour=source_marking_colour(obj.get('source_layer',obj.name))
        if colour is None or obj.type!='MESH':continue
        name=obj.name+'_source_color';mat=bpy.data.materials.get(name) or bpy.data.materials.new(name);mat.diffuse_color=colour
        obj.data.materials.clear();obj.data.materials.append(mat)
    for mat in bpy.data.materials:
        base=tuple(mat.diffuse_color);mat.use_nodes=True;nodes=mat.node_tree.nodes;links=mat.node_tree.links
        output=next((n for n in nodes if n.type=='OUTPUT_MATERIAL'),None)
        if output is None:output=nodes.new('ShaderNodeOutputMaterial')
        bsdf=next((n for n in nodes if n.type=='BSDF_PRINCIPLED'),None)
        if bsdf is None:bsdf=nodes.new('ShaderNodeBsdfPrincipled')
        images=[n for n in nodes if n.type=='TEX_IMAGE' and n.image]
        bsdf.inputs['Roughness'].default_value=.55 if mat.get('fidelity_paint') else .65
        if images and not bsdf.inputs['Base Color'].is_linked:
            tex=images[0];links.new(tex.outputs['Color'],bsdf.inputs['Base Color']);links.new(tex.outputs['Alpha'],bsdf.inputs['Alpha'])
        elif not images:bsdf.inputs['Base Color'].default_value=base
        for l in list(output.inputs['Surface'].links):links.remove(l)
        links.new(bsdf.outputs['BSDF'],output.inputs['Surface'])
    world=sc.world or bpy.data.worlds.new('Daylight');sc.world=world;world.use_nodes=True
    bg=world.node_tree.nodes.get('Background');bg.inputs['Color'].default_value=(.32,.39,.48,1);bg.inputs['Strength'].default_value=.45
    sun=bpy.data.objects.get('Daylight_Sun')
    if sun is None:
        light=bpy.data.lights.new('Daylight_Sun','SUN');sun=bpy.data.objects.new('Daylight_Sun',light);sc.collection.objects.link(sun)
    sun.data.energy=1.8;sun.data.angle=math.radians(10);sun.rotation_euler=(math.radians(25),math.radians(-25),math.radians(-35))
    try:sc.render.engine='BLENDER_EEVEE_NEXT'
    except TypeError:sc.render.engine='BLENDER_EEVEE'
    # Interactive view uses Eevee's material preview; it shows all original texture images.
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type=='VIEW_3D':
                sp=area.spaces.active;sp.shading.type='MATERIAL';sp.shading.use_scene_lights=True;sp.shading.use_scene_world=True;sp.overlay.show_overlays=False;sp.clip_start=2;sp.clip_end=30000
    sc.view_settings.view_transform='AgX';sc.view_settings.look='AgX - Medium High Contrast';sc.view_settings.exposure=-.3
    return {'texture_images':sum(1 for i in bpy.data.images if i.source=='FILE' or i.packed_file),'textured_materials':sum(any(n.type=='TEX_IMAGE' and n.image for n in m.node_tree.nodes) for m in bpy.data.materials if m.use_nodes)}

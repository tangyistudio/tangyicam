"""Agent-accessible geometry and simulation setup using native Blender data."""
import math
import bpy
from .studio import material


def mesh_model(name,vertices,faces,location=(0,0,0)):
    if not vertices or len(vertices)>200000 or len(faces)>200000:raise ValueError('Invalid mesh size')
    if any(len(v)!=3 or not all(math.isfinite(float(x)) for x in v) for v in vertices):raise ValueError('Invalid vertex')
    if any(len(f)<3 or any(not isinstance(i,int) or i<0 or i>=len(vertices) for i in f) for f in faces):raise ValueError('Invalid face')
    data=bpy.data.meshes.new(name);data.from_pydata(vertices,[],faces);data.update()
    obj=bpy.data.objects.new(name,data);bpy.context.scene.collection.objects.link(obj);obj.location=location
    for face in data.polygons:face.use_smooth=True
    return obj


def lathe(name,profile,segments=48,location=(0,0,0)):
    """Surface of revolution for bottles, bowls and architectural profiles."""
    if len(profile)<2 or len(profile)>200 or segments<8 or segments>256:raise ValueError('Invalid lathe profile')
    vertices=[];faces=[]
    for radius,z in profile:
        if radius<0:raise ValueError('Radius must be nonnegative')
        for j in range(segments):
            a=j*2*math.pi/segments;vertices.append([radius*math.cos(a),radius*math.sin(a),z])
    for i in range(len(profile)-1):
        for j in range(segments):
            n=(j+1)%segments;faces.append([i*segments+j,i*segments+n,(i+1)*segments+n,(i+1)*segments+j])
    return mesh_model(name,vertices,faces,location)


def assign_material(obj,spec):
    if obj.type!='MESH':raise ValueError('Select mesh')
    mat=material(spec.get('name','TC_Material'),tuple(spec.get('color',[.08,.08,.08,1])),spec.get('roughness',.3),spec.get('metallic',0))
    node=mat.node_tree.nodes.get('Principled BSDF')
    node.inputs['Transmission Weight'].default_value=float(spec.get('transmission',0))
    node.inputs['IOR'].default_value=float(spec.get('ior',1.45))
    if 'emission' in spec:
        node.inputs['Emission Color'].default_value=tuple(spec.get('emission_color',[1,.5,.05,1]))
        node.inputs['Emission Strength'].default_value=float(spec['emission'])
    obj.data.materials.clear();obj.data.materials.append(mat)
    return mat


def rigid_body(obj,passive=False,mass=1):
    bpy.ops.object.select_all(action='DESELECT');obj.select_set(True);bpy.context.view_layer.objects.active=obj
    if not obj.rigid_body:bpy.ops.rigidbody.object_add()
    body=obj.rigid_body;body.type='PASSIVE' if passive else 'ACTIVE';body.mass=mass
    body.collision_shape='MESH' if passive else 'CONVEX_HULL';body.friction=.6;body.restitution=.05
    scene=bpy.context.scene;scene.rigidbody_world.substeps_per_frame=8;scene.rigidbody_world.solver_iterations=20
    return {'object':obj.name,'type':body.type}


def fluid_setup(obj,kind='DOMAIN',resolution=32,cache_directory='//tc_fluid/'):
    if kind not in {'DOMAIN','FLOW','EFFECTOR'}:raise ValueError('Unsupported fluid type')
    if obj.type!='MESH':raise ValueError('Fluid requires mesh')
    mod=obj.modifiers.new('TC_Liquid','FLUID');mod.fluid_type=kind
    bpy.context.view_layer.update()
    if kind=='DOMAIN':
        ds=mod.domain_settings;ds.domain_type='LIQUID';ds.resolution_max=max(16,min(256,resolution))
        ds.cache_type='MODULAR';ds.cache_directory=bpy.path.abspath(cache_directory)
        ds.cache_frame_start=bpy.context.scene.frame_start;ds.cache_frame_end=bpy.context.scene.frame_end
        ds.use_mesh=True
    elif kind=='FLOW':
        fs=mod.flow_settings;fs.flow_type='LIQUID';fs.flow_behavior='GEOMETRY'
    else:mod.effector_settings.effector_type='COLLISION'
    return {'object':obj.name,'type':kind,'baked':False}

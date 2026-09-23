"""Editable Blender production tools. No cloud dependency or generated Python execution."""
import json
import math
import re
from pathlib import Path

import bpy
from mathutils import Vector, Quaternion


def curves(owner):
    ad = owner.animation_data
    if not ad or not ad.action:
        return []
    action = ad.action
    if hasattr(action, 'fcurves'):
        return list(action.fcurves)
    result = []
    for layer in action.layers:
        for strip in layer.strips:
            if hasattr(strip, 'channelbag') and ad.action_slot:
                bag = strip.channelbag(ad.action_slot)
                if bag:
                    result.extend(bag.fcurves)
    return result


def remove_curve(owner, fc):
    ad=owner.animation_data
    if hasattr(ad.action, 'fcurves'):
        ad.action.fcurves.remove(fc)
    else:
        for layer in ad.action.layers:
            for strip in layer.strips:
                if hasattr(strip,'channelbag') and ad.action_slot:
                    bag=strip.channelbag(ad.action_slot)
                    if bag and fc in list(bag.fcurves):bag.fcurves.remove(fc);return


def interpolation(owner, mode='BEZIER'):
    for fc in curves(owner):
        for key in fc.keyframe_points:
            key.interpolation = mode
            if mode == 'BEZIER':
                key.handle_left_type = key.handle_right_type = 'AUTO_CLAMPED'


def load_json(path):
    return json.loads(Path(bpy.path.abspath(str(path))).read_text(encoding='utf-8-sig'))


def material(name, color=(.035, .035, .04, 1), roughness=.3, metallic=0):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Base Color'].default_value = color
    bsdf.inputs['Roughness'].default_value = roughness
    bsdf.inputs['Metallic'].default_value = metallic
    return mat


def move_to(obj, collection):
    for old in list(obj.users_collection):
        old.objects.unlink(obj)
    collection.objects.link(obj)


def new_collection(name, scene=None):
    col = bpy.data.collections.new(name)
    (scene or bpy.context.scene).collection.children.link(col)
    return col


def cube(name, loc, size, mat=None, collection=None):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if mat:
        obj.data.materials.append(mat)
    if collection:
        move_to(obj, collection)
    return obj


def fixture(name, loc, watts=130, length=1.2, collection=None):
    """Visible tube and actual area emitter share one animated power property."""
    mat = material(name + '_emission', (1, .93, .8, 1))
    bsdf = mat.node_tree.nodes.get('Principled BSDF')
    bsdf.inputs['Emission Color'].default_value = (1, .93, .8, 1)
    obj = cube(name, loc, (length, .09, .035), mat, collection)
    obj['tc_power'] = 1.0
    obj['tc_watts'] = float(watts)
    data = bpy.data.lights.new(name + '_source', 'AREA')
    data.shape = 'RECTANGLE'
    data.size = length
    data.size_y = .18
    data.color = (1, .93, .8)
    light = bpy.data.objects.new(name + '_source', data)
    (collection or bpy.context.scene.collection).objects.link(light)
    light.parent = obj
    light.location = (0, 0, -.03)
    for socket, prop, expression in ((data, 'energy', f'p*{float(watts)}'),
                                     (bsdf.inputs['Emission Strength'], 'default_value', 'p*6')):
        drv = socket.driver_add(prop).driver
        var = drv.variables.new()
        var.name = 'p'
        var.type = 'SINGLE_PROP'
        var.targets[0].id = obj
        var.targets[0].data_path = '["tc_power"]'
        drv.expression = expression
    return obj


def flicker(obj, start=1, end=96, seed=7):
    """Deterministic, irregular short events on ONE fixture; exposure unchanged."""
    import random
    if 'tc_power' not in obj:
        raise ValueError('Select a TangyiCam light fixture (tc_power).')
    if end <= start:
        raise ValueError('End frame must be after start.')
    # Replace only the controller curve, leaving unrelated animation intact.
    for fc in list(curves(obj)):
        if fc.data_path == '["tc_power"]':
            remove_curve(obj, fc)
    rng = random.Random(seed)
    events = {start: 1., end: 1.}
    t = start + max(2, (end - start) // 5)
    while t < end - 3:
        events[t - 1] = 1.
        events[t] = rng.choice([0.0, .06, .18])
        events[t + 1] = .35
        events[t + 2] = 1.
        t += rng.randint(12, 27)
    for frame, power in sorted(events.items()):
        obj['tc_power'] = power
        obj.keyframe_insert('["tc_power"]', frame=frame)
    for fc in curves(obj):
        if fc.data_path == '["tc_power"]':
            for k in fc.keyframe_points:
                k.interpolation = 'CONSTANT'
    bpy.context.scene.frame_set(bpy.context.scene.frame_current)
    return events


def build_scene(spec, scene=None):
    """Validated declarative recipe; new collection, never clears an existing set."""
    scene = scene or bpy.context.scene
    items = spec.get('objects', [])
    if not items or len(items) > 2000:
        raise ValueError('Recipe requires 1–2000 objects.')
    allowed = {'BOX', 'SPHERE', 'CYLINDER', 'EMPTY', 'LIGHT'}
    names = set()
    for item in items:
        if item.get('type', 'BOX') not in allowed:
            raise ValueError('Unsupported object type')
        name = item.get('name', '')
        if not name or name in names:
            raise ValueError('Every object needs a unique name.')
        names.add(name)
        for field in ('location', 'size'):
            if field in item and (len(item[field]) != 3 or not all(math.isfinite(float(x)) for x in item[field])):
                raise ValueError('Invalid ' + field)
        if any(float(x) <= 0 for x in item.get('size', [1, 1, 1])):
            raise ValueError('Dimensions must be positive')
    col = new_collection(spec.get('name', 'TC_Set'), scene)
    mats = {}
    for key, cfg in spec.get('materials', {}).items():
        mats[key] = material(key, tuple(cfg.get('color', [.1, .1, .1, 1])), cfg.get('roughness', .3), cfg.get('metallic', 0))
    for item in items:
        typ = item.get('type', 'BOX'); name = item['name']
        loc = item.get('location', [0, 0, 0]); size = item.get('size', [1, 1, 1])
        mat = mats.get(item.get('material'))
        if typ == 'BOX':
            obj = cube(name, loc, size, mat, col)
        elif typ == 'LIGHT':
            obj = fixture(name, loc, item.get('watts', 130), size[0], col)
        elif typ == 'EMPTY':
            obj = bpy.data.objects.new(name, None); col.objects.link(obj); obj.location = loc
        else:
            if typ == 'SPHERE':
                bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=16, location=loc)
            else:
                bpy.ops.mesh.primitive_cylinder_add(vertices=32, location=loc)
            obj = bpy.context.object; obj.name = name; obj.dimensions = size
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
            move_to(obj, col)
            if mat: obj.data.materials.append(mat)
        obj.rotation_euler = [math.radians(v) for v in item.get('rotation_degrees', [0, 0, 0])]
        obj['tc_role'] = item.get('role', 'SET')
    col['tc_recipe'] = json.dumps(spec, ensure_ascii=False)
    return col


def room_recipe(prompt='restroom', width=5., length=12., height=3.):
    """Local parametric template, not a general natural-language AI model."""
    kind = 'RESTROOM' if any(x in prompt.lower() for x in ('restroom', 'bathroom', '廁所')) else 'ROOM'
    objects = [dict(name='FLOOR_TC', location=[0, 0, -.1], size=[width, length, .2], material='BlackStone'),
               dict(name='CEILING_TC', location=[0, 0, height+.1], size=[width, length, .2], material='Dark'),
               dict(name='WALL_TC_left', location=[-width/2-.1, 0, height/2], size=[.2, length, height], material='Dark'),
               dict(name='WALL_TC_right', location=[width/2+.1, 0, height/2], size=[.2, length, height], material='Dark'),
               dict(name='WALL_TC_back', location=[0, length/2+.1, height/2], size=[width, .2, height], material='Dark')]
    for i in range(3):
        objects.append(dict(type='LIGHT', name=f'TC_Fixture_{i+1}', location=[0, -length/3+i*length/3, height-.15], size=[1.3, .1, .03], watts=170))
    if kind == 'RESTROOM':
        objects += [dict(name='TC_Counter', location=[-width/2+.5, 0, .9], size=[1, length*.64, .15], material='BlackStone'),
                    dict(name='TC_Mirror', location=[-width/2+.06, 0, 1.85], size=[.03, length*.64, 1.35], material='Mirror')]
        for i in range(4):
            objects.append(dict(type='CYLINDER', name=f'TC_Faucet_{i+1}', location=[-width/2+.35, -2.6+i*1.6, 1.1], size=[.07, .07, .35], material='Brass'))
            objects.append(dict(name=f'TC_StallDoor_{i+1}', location=[-width/2+(i+.5)*width/4, length/2-1.2, 1.2], size=[width/4-.05, .08, 2.2], material='Dark'))
        for i in range(6):
            objects.append(dict(type='SPHERE', name=f'TC_Urinal_Blockout_{i+1}', location=[width/2-.3, -3+i*1.2, .65], size=[.42, .55, .7], material='BlackStone'))
    return {'name': 'TC_'+kind, 'prompt': prompt, 'materials': {
        'BlackStone': {'color': [.018, .022, .027, 1], 'roughness': .2},
        'Dark': {'color': [.035, .038, .04, 1], 'roughness': .5},
        'Mirror': {'color': [.85, .85, .85, 1], 'roughness': .015, 'metallic': 1},
        'Brass': {'color': [.42, .25, .08, 1], 'roughness': .28, 'metallic': .85}}, 'objects': objects}


def import_asset(path, cursor=True):
    path = Path(bpy.path.abspath(str(path))).resolve()
    if not path.is_file(): raise ValueError('File not found: ' + str(path))
    before = set(bpy.data.objects)
    ext = path.suffix.lower()
    if ext in {'.glb', '.gltf'}: bpy.ops.import_scene.gltf(filepath=str(path))
    elif ext == '.fbx': bpy.ops.import_scene.fbx(filepath=str(path))
    elif ext == '.obj': bpy.ops.wm.obj_import(filepath=str(path))
    elif ext == '.blend':
        with bpy.data.libraries.load(str(path), link=False) as (src, dst): dst.objects = src.objects
        for obj in dst.objects:
            if obj: bpy.context.scene.collection.objects.link(obj)
    else: raise ValueError('Use GLB, GLTF, FBX, OBJ or BLEND.')
    added = [o for o in bpy.data.objects if o not in before]
    if cursor:
        offset = bpy.context.scene.cursor.location.copy()
        for obj in added:
            if obj.parent not in added: obj.location += offset
    return added


def image_asset(path, mode='PLANE', target=None):
    img = bpy.data.images.load(bpy.path.abspath(str(path)), check_existing=True)
    mat = material('TC_Image_' + Path(path).stem, (1, 1, 1, 1))
    node = mat.node_tree.nodes.new('ShaderNodeTexImage'); node.image = img
    mat.node_tree.links.new(node.outputs['Color'], mat.node_tree.nodes.get('Principled BSDF').inputs['Base Color'])
    if mode == 'MATERIAL':
        if not target or target.type != 'MESH': raise ValueError('Select a mesh.')
        target.data.materials.append(mat)
        return target
    bpy.ops.mesh.primitive_plane_add(size=2, location=bpy.context.scene.cursor.location)
    obj = bpy.context.object; obj.name = 'TC_Image_' + Path(path).stem
    obj.scale.x = img.size[0] / max(1, img.size[1]); obj.data.materials.append(mat)
    if img.source == 'MOVIE':
        node.image_user.use_auto_refresh = True
        node.image_user.frame_duration = img.frame_duration
    obj['tc_reference'] = str(path)
    return obj


def create_rig(spec, meshes=()):
    """Explicit fitted bone recipe + Blender weights; no guessed human proportions."""
    bones = spec.get('bones', [])
    seen = set()
    for b in bones:
        if b['name'] in seen or (b.get('parent') and b['parent'] not in seen):
            raise ValueError('Bones must be unique and ordered parent first.')
        if (Vector(b['tail'])-Vector(b['head'])).length < .001:
            raise ValueError('Zero-length bone')
        seen.add(b['name'])
    if not bones: raise ValueError('No bones in recipe')
    bpy.ops.object.select_all(action='DESELECT')
    arm = bpy.data.armatures.new(spec.get('name', 'TC_Rig'))
    rig = bpy.data.objects.new(arm.name, arm); bpy.context.scene.collection.objects.link(rig)
    rig.select_set(True); bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode='EDIT')
    try:
        for b in bones:
            bone = arm.edit_bones.new(b['name']); bone.head = b['head']; bone.tail = b['tail']
            if b.get('parent'): bone.parent = arm.edit_bones[b['parent']]
    finally: bpy.ops.object.mode_set(mode='OBJECT')
    rig.show_in_front = True
    if meshes:
        for obj in meshes: obj.select_set(True)
        bpy.ops.object.parent_set(type='ARMATURE_AUTO')
    return rig


def add_ik(rig, bone_name, target, pole=None, chain=2):
    if not rig or rig.type != 'ARMATURE' or bone_name not in rig.pose.bones:
        raise ValueError('Choose an armature and valid end bone')
    c = rig.pose.bones[bone_name].constraints.new('IK')
    c.name = 'TC_Contact_IK'; c.target = target; c.chain_count = chain; c.use_stretch = False
    if pole: c.pole_target = pole
    return c


def apply_motion(rig, spec):
    if not rig or rig.type != 'ARMATURE': raise ValueError('Select an armature')
    for name in spec.get('bones', {}):
        if name not in rig.pose.bones: raise ValueError('Missing bone: ' + name)
    # New action: preserve the old take instead of destructively filtering it.
    rig.animation_data_create(); old = rig.animation_data.action
    if old: old.use_fake_user = True
    rig.animation_data.action = bpy.data.actions.new(spec.get('name', 'TC_Motion'))
    for name, keys in spec.get('bones', {}).items():
        bone = rig.pose.bones[name]; bone.rotation_mode = 'QUATERNION'; previous = None
        for key in sorted(keys, key=lambda k: k['frame']):
            if 'rotation' in key:
                q = Quaternion(key['rotation']); q.normalize()
                if previous and previous.dot(q) < 0: q.negate()
                bone.rotation_quaternion = q; previous = q.copy()
                bone.keyframe_insert('rotation_quaternion', frame=key['frame'])
            if 'location' in key:
                bone.location = key['location']; bone.keyframe_insert('location', frame=key['frame'])
    interpolation(rig)
    return rig.animation_data.action


def camera_path(keys, name='TC_StudioCamera', scene=None):
    """Dense quaternion SLERP along smooth Hermite positions; no Euler wrap."""
    scene = scene or bpy.context.scene
    keys = sorted(keys, key=lambda k: k['frame'])
    if len(keys) < 2 or any(b['frame'] <= a['frame'] for a,b in zip(keys, keys[1:])):
        raise ValueError('At least two distinct increasing camera frames required')
    data = bpy.data.cameras.new(name); cam = bpy.data.objects.new(name, data); scene.collection.objects.link(cam)
    cam.rotation_mode = 'QUATERNION'
    positions = [Vector(k['location']) for k in keys]
    rotations = [(Vector(k['target'])-positions[i]).to_track_quat('-Z', 'Y') for i,k in enumerate(keys)]
    tangents = []
    for i in range(len(keys)):
        a = max(0,i-1); b = min(len(keys)-1,i+1)
        tangents.append((positions[b]-positions[a])/(keys[b]['frame']-keys[a]['frame']))
    previous = None
    for i in range(len(keys)-1):
        a,b=keys[i:i+2]; duration=b['frame']-a['frame']
        for f in range(a['frame'], b['frame']+1):
            t=(f-a['frame'])/duration; u=t*t*(3-2*t)
            cam.location=(2*t**3-3*t*t+1)*positions[i]+(t**3-2*t*t+t)*duration*tangents[i]+(-2*t**3+3*t*t)*positions[i+1]+(t**3-t*t)*duration*tangents[i+1]
            q=rotations[i].slerp(rotations[i+1],u)
            if previous and previous.dot(q)<0:q.negate()
            cam.rotation_quaternion=q;previous=q.copy()
            cam.data.lens=a.get('lens',35)*(1-u)+b.get('lens',35)*u
            for prop in ('location','rotation_quaternion'):cam.keyframe_insert(prop,frame=f)
            cam.data.keyframe_insert('lens',frame=f)
    interpolation(cam,'LINEAR');interpolation(cam.data,'LINEAR')
    scene.camera=cam
    return cam


def audit_motion(scene, objects, start, end, max_step=.5):
    original=scene.frame_current; previous={}; problems=[]; steps={}
    try:
        for f in range(start,end+1):
            scene.frame_set(f)
            for obj in objects:
                p=obj.matrix_world.translation.copy()
                if not all(math.isfinite(x) for x in p): problems.append({'frame':f,'object':obj.name,'issue':'nonfinite'})
                if obj.name in previous:
                    step=(p-previous[obj.name]).length
                    steps[obj.name]=max(steps.get(obj.name,0),step)
                    if step>max_step:problems.append({'frame':f,'object':obj.name,'issue':'position_jump','meters':step})
                previous[obj.name]=p
        return {'position_jumps':problems,'max_step_m':steps,
                'scope':'World-position continuity only. Not proof of anatomical/contact quality.'}
    finally:scene.frame_set(original)


def reference_packet(scene, out_dir, prompt, references):
    out=Path(bpy.path.abspath(str(out_dir)));out.mkdir(parents=True,exist_ok=True)
    missing=[]; seen=set()
    for ref in references:
        if not ref.get('name') or ref['name'] in seen:raise ValueError('References need unique names')
        seen.add(ref['name'])
        if ref.get('path') and not Path(bpy.path.abspath(ref['path'])).is_file(): missing.append(ref['path'])
        if not ref.get('path') and not ref.get('element_id'):missing.append(ref['name'])
    if missing:raise ValueError('Missing reference files: '+', '.join(missing))
    roles={'STORYBOARD':'Action order and blocking only.','SCENE':'Architecture, materials and lighting.',
           'CHARACTER':'Only the named character appearance.','PROP':'Only the named prop.',
           'FIRST_FRAME':'Exact opening composition.','LAST_FRAME':'Exact ending composition.'}
    text=prompt+'\n\nReference bindings:\n'+'\n'.join(
        f"{r['name']}: {roles.get(r.get('role'),r.get('role',''))} Owner: {r.get('owner','scene')}." for r in references)
    manifest={'schema_version':1,'blend':bpy.data.filepath,'fps':scene.render.fps/scene.render.fps_base,
              'frames':[scene.frame_start,scene.frame_end],'camera':scene.camera.name if scene.camera else None,
              'references':references,'prompt':text,'submitted':False}
    (out/'request.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    (out/'prompt.txt').write_text(text,encoding='utf8')
    return manifest

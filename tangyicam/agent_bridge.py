"""Local agent command mailbox. Blender APIs run on its main thread.

No ports, account tokens, eval, generated scripts or shell execution. Requests are
explicit JSON operations in a per-session mailbox, with a response for every ID.
"""
import json
import os
import re
import time
import uuid
from pathlib import Path

import bpy
from . import studio

_active = False
_session = None
_root = None


def base_dir():
    return Path.home() / '.tangyicam' / 'bridge'


def inspect_scene(scene):
    return {'name': scene.name, 'frame': scene.frame_current,
            'range': [scene.frame_start, scene.frame_end], 'camera': scene.camera.name if scene.camera else None,
            'objects': [{'name': o.name, 'type': o.type, 'location': list(o.location),
                         'dimensions': list(o.dimensions), 'parent': o.parent.name if o.parent else None,
                         'bones': list(o.pose.bones.keys()) if o.type == 'ARMATURE' else [],
                         'fixture': 'tc_power' in o} for o in scene.objects]}


def resolve(name):
    obj = bpy.context.scene.objects.get(name)
    if not obj: raise ValueError('Object not found: ' + str(name))
    return obj


def transform(args):
    obj = resolve(args['object'])
    if 'location' in args: obj.location = args['location']
    if 'rotation_degrees' in args:
        import math
        obj.rotation_euler = [math.radians(v) for v in args['rotation_degrees']]
    if 'scale' in args: obj.scale = args['scale']
    if 'frame' in args:
        for source, prop in [('location','location'),('rotation_degrees','rotation_euler'),('scale','scale')]:
            if source in args: obj.keyframe_insert(prop, frame=args['frame'])
        studio.interpolation(obj)
    return {'object': obj.name}


def output_path(path):
    target = Path(bpy.path.abspath(path)).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def render_frame(args):
    scene = bpy.context.scene
    old = (scene.frame_current, scene.camera, scene.render.filepath,
           scene.render.image_settings.file_format, scene.render.resolution_x,
           scene.render.resolution_y, scene.render.resolution_percentage)
    try:
        if args.get('camera'): scene.camera = resolve(args['camera'])
        if not scene.camera or scene.camera.type != 'CAMERA': raise ValueError('No camera selected')
        path = output_path(args['path'])
        scene.frame_set(args.get('frame', scene.frame_current))
        scene.render.filepath = str(path)
        scene.render.image_settings.file_format = 'PNG'
        if 'width' in args:
            ratio = old[5] / max(1,old[4])
            scene.render.resolution_x = max(64,min(3840,int(args['width'])))
            scene.render.resolution_y = max(64,int(scene.render.resolution_x*ratio))
        scene.render.resolution_percentage = 100
        bpy.ops.render.render(write_still=True)
        return {'path':str(path), 'frame':scene.frame_current}
    finally:
        scene.frame_set(old[0]);scene.camera=old[1];scene.render.filepath=old[2]
        scene.render.image_settings.file_format=old[3]
        scene.render.resolution_x,scene.render.resolution_y,scene.render.resolution_percentage=old[4:]


def execute(command, args):
    scene = bpy.context.scene
    if command == 'inspect': return inspect_scene(scene)
    if command in {'mesh_model','lathe'}:
        from . import modeling_tools
        obj=getattr(modeling_tools,command)(**args);return {'object':obj.name,'vertices':len(obj.data.vertices)}
    if command == 'assign_material':
        from .modeling_tools import assign_material
        return {'material':assign_material(resolve(args['object']),args['spec']).name}
    if command == 'rigid_body':
        from .modeling_tools import rigid_body
        return rigid_body(resolve(args['object']),args.get('passive',False),args.get('mass',1))
    if command == 'fluid_setup':
        from .modeling_tools import fluid_setup
        return fluid_setup(resolve(args['object']),args.get('kind','DOMAIN'),args.get('resolution',32),args.get('cache_directory','//tc_fluid/'))

    if command == 'retime_action':
        from .animation_tools import retime_action
        return retime_action(resolve(args['rig']),args['keys'],args.get('hold_bones',()),args.get('hold_interval'),args.get('hold_source'),args.get('hold_blend',4))
    if command == 'audit_contacts':
        from .animation_tools import audit_contacts
        return audit_contacts(resolve(args['actor_a']),resolve(args['actor_b']),args['start'],args['end'])
    if command == 'sync_body_contact':
        from .animation_tools import sync_body_contact
        return sync_body_contact(resolve(args['mover']),args['mover_bone'],resolve(args['receiver']),args['receiver_bone'],args['offsets'],args['start'],args['end'])
    if command == 'adjust_pose':
        from .animation_tools import adjust_pose
        return adjust_pose(resolve(args['rig']),args['offsets'],args['start'],args['full'],args['end'])
    if command == 'root_trajectory':
        from .animation_tools import root_trajectory
        return root_trajectory(resolve(args['rig']),args['bone'],args['keys'])
    if command == 'follow_camera':
        from .animation_tools import follow_camera
        return follow_camera(resolve(args['object']),args.get('bone',''),args['start'],args['end'],args.get('offset',(4,-6,2)),args.get('target_offset',(0,0,0)),args.get('lens',40),args.get('name','TC_FollowCamera'))
    if command == 'import_motion':
        from .animation_tools import import_motion
        return import_motion(args['path'],resolve(args['rig']),args.get('start'),args.get('end'))
    if command == 'contact_target':
        from .animation_tools import contact_target
        return contact_target(resolve(args['rig']),args['bone'],args['start'],args['end'],args.get('pole_offset',(0,-1,0)))
    if command == 'audit_bones':
        from .animation_tools import audit_bones
        return audit_bones(resolve(args['rig']),args['start'],args['end'])

    if command == 'visibility':
        obj=resolve(args['object']);obj.hide_render=bool(args.get('hidden',True));obj.hide_set(obj.hide_render)
        return {'object':obj.name,'hidden':obj.hide_render}
    if command == 'render_settings':
        engine=args.get('engine','BLENDER_EEVEE_NEXT')
        if engine not in {'BLENDER_EEVEE_NEXT','BLENDER_EEVEE','CYCLES','BLENDER_WORKBENCH'}:raise ValueError('Unsupported renderer')
        if engine in {'BLENDER_EEVEE_NEXT','BLENDER_EEVEE'}:
            engine='BLENDER_EEVEE' if bpy.app.version>=(5,0,0) else 'BLENDER_EEVEE_NEXT'
        scene.render.engine=engine
        scene.render.resolution_x=int(args.get('width',640));scene.render.resolution_y=int(args.get('height',360))
        scene.render.resolution_percentage=100
        scene.view_settings.exposure=float(args.get('exposure',0))
        if engine=='CYCLES':scene.cycles.samples=int(args.get('samples',16))
        if engine in {'BLENDER_EEVEE_NEXT','BLENDER_EEVEE'}:
            if hasattr(scene.eevee,'taa_render_samples'):scene.eevee.taa_render_samples=int(args.get('samples',16))
            if hasattr(scene.eevee,'use_raytracing'):scene.eevee.use_raytracing=True
        if scene.world:
            scene.world.use_nodes=True
            scene.world.node_tree.nodes.get('Background').inputs['Strength'].default_value=float(args.get('world_strength',.03))
        return {'engine':engine,'size':[scene.render.resolution_x,scene.render.resolution_y]}
    if command == 'render_sequence':
        out=output_path(args['directory']+'/first.png').parent
        start,end=int(args['start']),int(args['end'])
        if end<start or end-start>10000:raise ValueError('Invalid render range')
        from . import export
        import shutil,subprocess
        paths=[]
        for f in range(start,end+1):
            path=out/f'{f-start:05d}.png'
            render_frame({'path':str(path),'frame':f,'camera':args.get('camera',scene.camera.name if scene.camera else '')})
            paths.append(path)
        shutil.copy2(paths[0],out/'first.png');shutil.copy2(paths[-1],out/'last.png')
        ff=shutil.which('ffmpeg') or export.FFMPEG_FALLBACK
        video=out/'preview.mp4'
        flags={'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}
        result=subprocess.run([ff,'-y','-framerate',str(scene.render.fps/scene.render.fps_base),'-i',str(out/'%05d.png'),'-c:v','libx264','-pix_fmt','yuv420p','-crf','18',str(video)],capture_output=True,**flags)
        if result.returncode:raise RuntimeError(result.stderr.decode(errors='replace')[-1000:])
        return {'path':str(video),'frames':len(paths),'first':str(out/'first.png'),'last':str(out/'last.png')}
    if command == 'properties':
        obj=resolve(args['object'])
        for name,value in args.get('values',{}).items():
            if not name.startswith('tc_'):raise ValueError('Custom properties must start tc_')
            obj[name]=value
            if 'frame' in args:obj.keyframe_insert('['+json.dumps(name)+']',frame=args['frame'])
        return {'object':obj.name}

    if command == 'build_scene':
        col = studio.build_scene(args['recipe'],scene);return {'collection':col.name,'objects':len(col.objects)}
    if command == 'build_room':
        col=studio.build_scene(studio.room_recipe(**args),scene);return {'collection':col.name}
    if command == 'transform': return transform(args)
    if command == 'camera_path':
        cam=studio.camera_path(args['keys'],args.get('name','TC_AgentCamera'),scene);return {'camera':cam.name}
    if command == 'set_frame':
        scene.frame_set(int(args['frame']));return {'frame':scene.frame_current}
    if command == 'set_range':
        start,end=int(args['start']),int(args['end'])
        if end<start:raise ValueError('Invalid range')
        scene.frame_start=start;scene.frame_end=end
        scene.render.fps=int(args.get('fps',24));scene.render.fps_base=1
        return {'frames':[start,end]}
    if command == 'flicker':
        events=studio.flicker(resolve(args['object']),args.get('start',scene.frame_start),args.get('end',scene.frame_end),args.get('seed',7))
        return {'events':events}
    if command == 'import_asset':return {'objects':[o.name for o in studio.import_asset(args['path'],args.get('cursor',True))]}
    if command == 'image_asset':
        o=studio.image_asset(args['path'],args.get('mode','PLANE'),resolve(args['target']) if args.get('target') else None)
        return {'object':o.name}
    if command == 'create_rig':return {'rig':studio.create_rig(args['spec'],[resolve(n) for n in args.get('meshes',[])]).name}
    if command == 'motion':return {'action':studio.apply_motion(resolve(args['rig']),args['spec']).name}
    if command == 'ik':
        c=studio.add_ik(resolve(args['rig']),args['bone'],resolve(args['target']),resolve(args['pole']) if args.get('pole') else None,args.get('chain',2))
        return {'constraint':c.name}
    if command == 'audit':return studio.audit_motion(scene,[resolve(n) for n in args['objects']],args['start'],args['end'],args.get('max_step',.5))
    if command == 'render':return render_frame(args)
    if command == 'save_copy':
        path=output_path(args['path'])
        if path.exists() and not args.get('overwrite',False):raise ValueError('Output exists; use a new versioned filename')
        bpy.ops.wm.save_as_mainfile(filepath=str(path),copy=True);return {'path':str(path)}
    if command == 'reference_packet':return studio.reference_packet(scene,args['directory'],args['prompt'],args['references'])
    raise ValueError('Unsupported command: '+str(command))


def atomic_json(path, value):
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf8')
    os.replace(tmp,path)


def process_pending():
    if not _active:return None
    # One command per tick avoids a backlog monopolizing Blender's main thread.
    jobs=sorted((_root/'requests').glob('*.json'))
    if jobs:
        request=jobs[0];ident=request.stem;result={'id':ident,'ok':False}
        response=_root/'responses'/request.name
        try:
            if response.exists():request.unlink();return .1
            if request.stat().st_size>2_000_000:raise ValueError('Request too large')
            data=json.loads(request.read_text(encoding='utf8'))
            if data.get('session')!=_session:raise ValueError('Stale or incorrect session')
            result['result']=execute(data['command'],data.get('args',{}));result['ok']=True
        except Exception as exc:
            result['error']=str(exc)
        atomic_json(response,result)
        request.unlink(missing_ok=True)
    return .1


def start():
    global _active,_session,_root
    if _active:return str(_root)
    _session=uuid.uuid4().hex;_root=base_dir()/_session
    (_root/'requests').mkdir(parents=True,exist_ok=True);(_root/'responses').mkdir(exist_ok=True)
    _active=True
    atomic_json(base_dir()/'active.json',{'session':_session,'directory':str(_root),'pid':os.getpid(),
                                        'blend':bpy.data.filepath,'started':time.time(),'version':1})
    bpy.app.timers.register(process_pending,first_interval=.1,persistent=True)
    return str(_root)


def stop():
    global _active
    _active=False
    if bpy.app.timers.is_registered(process_pending):bpy.app.timers.unregister(process_pending)
    path=base_dir()/'active.json'
    if path.exists():
        try:
            if json.loads(path.read_text(encoding='utf8')).get('session')==_session:path.unlink()
        except (OSError,ValueError):pass


def running():return _active

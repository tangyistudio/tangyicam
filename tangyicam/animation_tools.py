"""Real armature actions, motion imports and contact controls. No fake humanoid solver."""
import math
import bpy
from mathutils import Vector, Quaternion
from .studio import import_asset, curves, interpolation


def import_motion(path, target, start=None, end=None):
    """Copy compatible local bone animation from FBX, sampled and quaternion-safe.

    Mixamo namespaces are ignored. Rest-space rotations are converted into the
    target bone axes; bone lengths and target non-root translations are preserved. Source remains in its own
    hidden collection for nondestructive inspection.
    """
    if not target or target.type!='ARMATURE':raise ValueError('Choose target armature')
    added=import_asset(path,cursor=False)
    source=next((o for o in added if o.type=='ARMATURE'),None)
    if not source or not source.animation_data or not source.animation_data.action:
        raise ValueError('Imported file does not contain animated armature')
    def canonical(name):return name.split(':')[-1]
    source_map={canonical(b.name):b.name for b in source.data.bones}
    mapping={b.name:source_map[canonical(b.name)] for b in target.data.bones if canonical(b.name) in source_map}
    if len(mapping)<2:raise ValueError('No compatible bone mapping')
    corrections={}
    for dst,src in mapping.items():
        source_rest=source.data.bones[src].matrix_local.to_quaternion()
        target_rest=target.data.bones[dst].matrix_local.to_quaternion()
        corrections[dst]=target_rest.inverted() @ source_rest
    action=source.animation_data.action
    first,last=map(int,action.frame_range)
    first=max(first,start) if start is not None else first
    last=min(last,end) if end is not None else last
    if last<first:raise ValueError('Empty action interval')
    scale=1.
    roots=[n for n in mapping if not target.data.bones[n].parent]
    if roots:
        r=roots[0]
        scale=target.data.bones[r].length/max(.001,source.data.bones[mapping[r]].length)
    scene=bpy.context.scene;oldframe=scene.frame_current
    target.animation_data_create()
    old=target.animation_data.action
    if old:old.use_fake_user=True
    new=bpy.data.actions.new('TC_'+action.name);target.animation_data.action=new
    previous={}
    try:
        for f in range(first,last+1):
            scene.frame_set(f)
            for dst,src in mapping.items():
                pb=target.pose.bones[dst];sp=source.pose.bones[src]
                conversion=corrections[dst]
                q=conversion @ sp.matrix_basis.to_quaternion() @ conversion.inverted();q.normalize()
                if dst in previous and previous[dst].dot(q)<0:q.negate()
                previous[dst]=q.copy();pb.rotation_mode='QUATERNION';pb.rotation_quaternion=q
                pb.location=(corrections[dst] @ sp.matrix_basis.translation)*scale if dst in roots else Vector((0,0,0))
                pb.scale=(1,1,1)
                pb.keyframe_insert('location',frame=f);pb.keyframe_insert('rotation_quaternion',frame=f)
        interpolation(target,'LINEAR')
    finally:scene.frame_set(oldframe)
    for obj in added:obj.hide_render=True;obj.hide_set(True)
    return {'action':new.name,'frames':[first,last],'mapped_bones':len(mapping),'source':source.name}


def contact_target(rig,bone_name,start,end,pole_offset=(0,-1,0)):
    """Plant an end effector with a non-stretch IK and explicit influence keys."""
    from .studio import add_ik
    scene=bpy.context.scene;old=scene.frame_current
    if bone_name not in rig.pose.bones:raise ValueError('Missing bone')
    scene.frame_set(start);pb=rig.pose.bones[bone_name]
    point=rig.matrix_world@pb.tail
    target=bpy.data.objects.new('TC_Contact_'+bone_name,None);scene.collection.objects.link(target)
    target.location=point;target.empty_display_size=.08
    pole=bpy.data.objects.new('TC_Pole_'+bone_name,None);scene.collection.objects.link(pole)
    mid=rig.matrix_world@pb.head
    pole.location=mid+Vector(pole_offset);pole.empty_display_size=.06
    constraint=add_ik(rig,bone_name,target,pole,2)
    for f,value in [(start-1,0),(start,1),(end,1),(end+1,0)]:
        constraint.influence=value;constraint.keyframe_insert('influence',frame=f)
    scene.frame_set(old)
    return {'target':target.name,'pole':pole.name,'constraint':constraint.name,'interval':[start,end]}


def audit_bones(rig,start,end):
    scene=bpy.context.scene;old=scene.frame_current
    lengths={};steps={};previous={}
    try:
        for f in range(start,end+1):
            scene.frame_set(f)
            for bone in rig.pose.bones:
                length=(bone.tail-bone.head).length
                entry=lengths.setdefault(bone.name,[length,length]);entry[0]=min(entry[0],length);entry[1]=max(entry[1],length)
                tail=rig.matrix_world@bone.tail
                if bone.name in previous:steps[bone.name]=max(steps.get(bone.name,0),(tail-previous[bone.name]).length)
                previous[bone.name]=tail.copy()
    finally:scene.frame_set(old)
    return {'bone_length_range':lengths,'max_endpoint_step_m':steps,
            'scope':'Detects stretching and endpoint jumps. Does not establish human performance quality.'}


def retime_action(rig, keys, hold_bones=(), hold_interval=None, hold_source=None, hold_blend=4):
    """Bake an editable action with a monotonic source clock; optional airborne pose hold.
    Root translation always follows source time, so a pose hold does not freeze travel.
    """
    if not rig or rig.type!='ARMATURE' or not rig.animation_data or not rig.animation_data.action:
        raise ValueError('Animated armature required')
    keys=sorted(keys,key=lambda k:k['frame'])
    if len(keys)<2 or any(b['frame']<=a['frame'] or b['source_frame']<a['source_frame'] for a,b in zip(keys,keys[1:])):
        raise ValueError('Time map must be monotonic')
    scene=bpy.context.scene;oldframe=scene.frame_current;source=rig.animation_data.action
    source.use_fake_user=True;poses={};hold={}
    try:
        if hold_bones:
            if hold_source is None or not hold_interval:raise ValueError('Specify hold source and interval')
            scene.frame_set(int(hold_source),subframe=hold_source-int(hold_source))
            for n in hold_bones:
                if n not in rig.pose.bones:raise ValueError('Unknown hold bone '+n)
                hold[n]=rig.pose.bones[n].rotation_quaternion.copy() if rig.pose.bones[n].rotation_mode=='QUATERNION' else rig.pose.bones[n].matrix_basis.to_quaternion()
        for a,b in zip(keys,keys[1:]):
            for f in range(a['frame'],b['frame']+1):
                u=(f-a['frame'])/(b['frame']-a['frame'])
                sf=a['source_frame']*(1-u)+b['source_frame']*u
                scene.frame_set(int(sf),subframe=sf-int(sf))
                poses[f]={}
                for pb in rig.pose.bones:
                    q=pb.matrix_basis.to_quaternion()
                    if pb.name in hold:
                        lo,hi=hold_interval
                        ramp=max(0,int(hold_blend))
                        weight=1. if lo<=f<=hi else (max(0.,1.-(lo-f)/ramp) if f<lo and ramp else max(0.,1.-(f-hi)/ramp) if f>hi and ramp else 0.)
                        weight=weight*weight*(3-2*weight)
                        q=q.slerp(hold[pb.name],weight)
                    poses[f][pb.name]=(pb.location.copy(),q.copy())
        rig.animation_data.action=bpy.data.actions.new('TC_Retime_'+source.name)
        previous={}
        for f,pose in poses.items():
            for name,(loc,q) in pose.items():
                pb=rig.pose.bones[name];pb.rotation_mode='QUATERNION'
                if name in previous and previous[name].dot(q)<0:q.negate()
                previous[name]=q.copy();pb.location=loc;pb.rotation_quaternion=q
                pb.keyframe_insert('location',frame=f);pb.keyframe_insert('rotation_quaternion',frame=f)
        interpolation(rig,'LINEAR')
    finally:scene.frame_set(oldframe)
    return {'action':rig.animation_data.action.name,'frames':[keys[0]['frame'],keys[-1]['frame']]}


def follow_camera(rig,bone_name,start,end,offset=(4,-6,2),target_offset=(0,0,0),lens=40,name='TC_FollowCamera'):
    from .studio import camera_path
    scene=bpy.context.scene;old=scene.frame_current;keys=[]
    if rig.type=='ARMATURE' and bone_name not in rig.pose.bones:raise ValueError('Missing follow bone')
    try:
        for f in range(start,end+1):
            scene.frame_set(f)
            point=rig.matrix_world @ rig.pose.bones[bone_name].head if rig.type=='ARMATURE' else rig.matrix_world.translation
            target=point+Vector(target_offset)
            keys.append({'frame':f,'location':list(target+Vector(offset)),'target':list(target),'lens':lens})
        cam=camera_path(keys,name,scene)
    finally:scene.frame_set(old)
    return {'camera':cam.name,'frames':[start,end]}


def root_trajectory(rig,bone_name,keys):
    """Place only a root bone along an explicit world-space path; preserve limb action."""
    if rig.type!='ARMATURE' or bone_name not in rig.pose.bones:
        raise ValueError('Choose an armature root bone')
    pb=rig.pose.bones[bone_name]
    if pb.parent:raise ValueError('Trajectory is restricted to a root bone')
    keys=sorted(keys,key=lambda k:k['frame'])
    if len(keys)<2 or any(b['frame']<=a['frame'] for a,b in zip(keys,keys[1:])):
        raise ValueError('Unique increasing trajectory frames required')
    if not rig.animation_data or not rig.animation_data.action:
        raise ValueError('Existing pose action required')
    scene=bpy.context.scene;oldframe=scene.frame_current
    original=rig.animation_data.action;original.use_fake_user=True
    rig.animation_data.action=original.copy();rig.animation_data.action.name='TC_Path_'+original.name
    inv_world=rig.matrix_world.inverted();inv_rest=pb.bone.matrix_local.inverted()
    try:
        for a,b in zip(keys,keys[1:]):
            for f in range(a['frame'],b['frame']+1):
                u=(f-a['frame'])/(b['frame']-a['frame'])
                world=Vector(a['location']).lerp(Vector(b['location']),u)
                scene.frame_set(f);pb.location=inv_rest @ (inv_world @ world)
                pb.keyframe_insert('location',frame=f)
        interpolation(rig,'LINEAR')
    finally:scene.frame_set(oldframe)
    return {'action':rig.animation_data.action.name,'frames':[keys[0]['frame'],keys[-1]['frame']]}


def adjust_pose(rig, offsets, start, full, end):
    """Add local bone rotation offsets with a smooth lead-in, preserving the source action."""
    from mathutils import Euler
    if rig.type!='ARMATURE' or not rig.animation_data or not rig.animation_data.action:
        raise ValueError('Animated armature required')
    if not start<=full<=end:raise ValueError('Expected start <= full <= end')
    for name,angles in offsets.items():
        if name not in rig.pose.bones or len(angles)!=3:raise ValueError('Invalid pose offset')
    oldframe=bpy.context.scene.frame_current;original=rig.animation_data.action
    original.use_fake_user=True;samples={}
    try:
        for f in range(start,end+1):
            bpy.context.scene.frame_set(f)
            u=min(1.,(f-start)/max(1,full-start)) if full>start else 1.
            u=u*u*(3-2*u)
            samples[f]={}
            for name,angles in offsets.items():
                q=rig.pose.bones[name].matrix_basis.to_quaternion()
                delta=Euler(tuple(math.radians(v)*u for v in angles),'XYZ').to_quaternion()
                samples[f][name]=q@delta
        rig.animation_data.action=original.copy();rig.animation_data.action.name='TC_Pose_'+original.name
        for f,poses in samples.items():
            for name,q in poses.items():
                pb=rig.pose.bones[name];pb.rotation_mode='QUATERNION';pb.rotation_quaternion=q
                pb.keyframe_insert('rotation_quaternion',frame=f)
        interpolation(rig,'LINEAR')
    finally:bpy.context.scene.frame_set(oldframe)
    return {'action':rig.animation_data.action.name,'bones':list(offsets),'frames':[start,end]}


def sync_body_contact(mover, mover_bone, receiver, receiver_bone, offsets, start, end):
    """Align a selected body point to another actor plus a world-space separation.
    Explicit choreography control, not a rigid-body or mesh collision simulation.
    """
    if mover.type!='ARMATURE' or receiver.type!='ARMATURE':raise ValueError('Two armatures required')
    if mover_bone not in mover.pose.bones or receiver_bone not in receiver.pose.bones:raise ValueError('Missing contact bone')
    roots=[b for b in mover.pose.bones if not b.parent]
    if len(roots)!=1:raise ValueError('Exactly one mover root required')
    keys=sorted(offsets,key=lambda k:k['frame'])
    if len(keys)<2 or keys[0]['frame']>start or keys[-1]['frame']<end:raise ValueError('Offsets must cover interval')
    if any(b['frame']<=a['frame'] for a,b in zip(keys,keys[1:])):raise ValueError('Unique offset frames required')
    old=bpy.context.scene.frame_current;trajectory=[]
    try:
        for f in range(start,end+1):
            bpy.context.scene.frame_set(f)
            a,b=next((a,b) for a,b in zip(keys,keys[1:]) if a['frame']<=f<=b['frame'])
            u=(f-a['frame'])/(b['frame']-a['frame']);u=u*u*(3-2*u)
            off=Vector(a['offset']).lerp(Vector(b['offset']),u)
            current=mover.matrix_world@mover.pose.bones[mover_bone].head
            desired=receiver.matrix_world@receiver.pose.bones[receiver_bone].head+off
            root=mover.matrix_world@roots[0].head
            trajectory.append({'frame':f,'location':list(root+desired-current)})
        result=root_trajectory(mover,roots[0].name,trajectory)
    finally:bpy.context.scene.frame_set(old)
    result['scope']='Kinematic contact alignment; mesh collision and performance require visual review'
    return result


def audit_contacts(actor_a, actor_b, start, end):
    """World-space evaluated mesh intersection report. Does not solve collisions."""
    from mathutils.bvhtree import BVHTree
    def meshes(actor):
        return [o for o in bpy.context.scene.objects if o.type=='MESH' and not o.hide_render and
                (o.parent==actor or any(m.type=='ARMATURE' and m.object==actor for m in o.modifiers))]
    group_a=meshes(actor_a);group_b=meshes(actor_b)
    if not group_a or not group_b:raise ValueError('Both actors need visible skinned meshes')
    old=bpy.context.scene.frame_current;rows=[]
    def tree(objects):
        vertices=[];faces=[];deps=bpy.context.evaluated_depsgraph_get()
        for obj in objects:
            evaluated=obj.evaluated_get(deps);mesh=evaluated.to_mesh()
            try:
                base=len(vertices);vertices.extend(evaluated.matrix_world@v.co for v in mesh.vertices)
                faces.extend(tuple(base+i for i in poly.vertices) for poly in mesh.polygons)
            finally:evaluated.to_mesh_clear()
        bounds = ([min(v[i] for v in vertices) for i in range(3)], [max(v[i] for v in vertices) for i in range(3)])
        return BVHTree.FromPolygons(vertices,faces,all_triangles=False,epsilon=.0001), bounds
    try:
        for f in range(start,end+1):
            bpy.context.scene.frame_set(f);bpy.context.view_layer.update()
            ta,ba=tree(group_a);tb,bb=tree(group_b)
            bounds_overlap=all(ba[0][i]<=bb[1][i]+.0001 and bb[0][i]<=ba[1][i]+.0001 for i in range(3))
            overlaps=ta.overlap(tb) if bounds_overlap else []
            status=('surface_intersection' if overlaps else
                    'bounds_overlap_requires_review' if bounds_overlap else 'bounds_separated')
            rows.append({'frame':f,'overlapping_triangle_pairs':len(overlaps),
                         'bounds_overlap':bounds_overlap,'status':status})
    finally:bpy.context.scene.frame_set(old)
    return {'first_intersection':next((r['frame'] for r in rows if r['overlapping_triangle_pairs']),None),'frames':rows,
            'first_bounds_overlap':next((r['frame'] for r in rows if r['bounds_overlap']),None),
            'requires_review':any(r['status']!='bounds_separated' for r in rows),
            'scope':'Surface intersections plus conservative world AABB triage. No surface hit does not prove separation; coplanar or contained meshes require review. Not contact force or penetration depth.'}

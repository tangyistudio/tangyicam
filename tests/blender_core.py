"""Blender integration assertions for physical light, rig/action and safe recipes."""
import json,sys,math,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import bpy,tangyicam
from tangyicam import studio,animation_tools,modeling_tools,agent_bridge
from mathutils import Vector
tangyicam.register();s=bpy.context.scene;passed=[]

def check(condition,name):
    assert condition,name
    passed.append(name)

col=studio.build_scene(studio.room_recipe('restroom'))
count=len(bpy.data.collections)
try:studio.build_scene({'objects':[{'name':'bad','type':'SHELL'}]})
except ValueError:pass
else:raise AssertionError('Invalid recipe accepted')
check(len(bpy.data.collections)==count,'Invalid recipe rejected before scene mutation')
lamp=bpy.data.objects['TC_Fixture_2'];other=bpy.data.objects['TC_Fixture_3_source']
events=studio.flicker(lamp,1,96,7)
studio.flicker(lamp,1,96,7)
fc=next(f for f in studio.curves(lamp) if f.data_path=='["tc_power"]')
check(len(fc.keyframe_points)==len(events),'Reapplying flicker replaces curve without duplicate keys')
source=bpy.data.objects['TC_Fixture_2_source'];other_values=[];values=[];emission=[]
exposure=s.view_settings.exposure
for frame in (19,20,22):
    s.frame_set(frame);bpy.context.view_layer.update()
    values.append(source.data.energy);other_values.append(other.data.energy)
    emission.append(lamp.data.materials[0].node_tree.nodes.get('Principled BSDF').inputs['Emission Strength'].default_value)
check(values[1]<values[0]*.1 and abs(values[0]-values[2])<.01,'Fixture power dims and restores')
check(emission[1]<emission[0]*.1,'Visible lamp emission follows same power')
check(max(other_values)-min(other_values)<.001,'Other fixture power remains unchanged')
check(s.view_settings.exposure==exposure,'No exposure animation or brightness overlay')

rig=studio.create_rig({'name':'TC_UnitRig','bones':[
    {'name':'upper','head':[0,0,2],'tail':[.1,0,1]},
    {'name':'lower','head':[.1,0,1],'tail':[0,0,0],'parent':'upper'}]})
action=studio.apply_motion(rig,{'name':'TC_TestAction','bones':{'upper':[
    {'frame':1,'rotation':[1,0,0,0]},{'frame':24,'rotation':[-.92388,-.38268,0,0]}]}})
check(len(studio.curves(rig))==4,'Pose quaternion action created')
check(all(fc.keyframe_points[1].co.y>=0 for fc in studio.curves(rig)),'Quaternion hemisphere preserved')
result=animation_tools.retime_action(rig,[{'frame':1,'source_frame':1},{'frame':48,'source_frame':24}])
check(action.use_fake_user and rig.animation_data.action!=action,'Retime preserves original action')
check(list(rig.animation_data.action.frame_range)==[1,48],'Retime writes exact requested range')
targets=animation_tools.contact_target(rig,'lower',1,48)
constraint=rig.pose.bones['lower'].constraints[-1]
check(not constraint.use_stretch and constraint.chain_count==2,'Contact IK prohibits limb stretching')
s.frame_set(24);bpy.context.view_layer.update()
error=((rig.matrix_world@rig.pose.bones['lower'].tail)-bpy.data.objects[targets['target']].location).length
check(error<.02,'Planted endpoint reaches contact target')

obj=modeling_tools.lathe('TC_TestBottle',[(0,0),(.15,0),(.16,.4),(.06,.55),(.05,.65),(0,.65)],32)
check(len(obj.data.vertices)==192 and len(obj.data.polygons)==160,'Editable revolved mesh created')
mat=modeling_tools.assign_material(obj,{'name':'TC_Glass','transmission':1,'ior':1.45,'roughness':.03})
check(mat.node_tree.nodes.get('Principled BSDF').inputs['Transmission Weight'].default_value==1,'Glass material applied')
modeling_tools.rigid_body(obj)
check(obj.rigid_body.type=='ACTIVE','Rigid body configured')
domain=studio.cube('TC_FluidDomain',(3,0,1),(2,2,2))
modeling_tools.fluid_setup(domain,'DOMAIN',32)
check(domain.modifiers['TC_Liquid'].domain_settings.domain_type=='LIQUID','Native liquid simulation domain configured (not baked)')

cam=studio.camera_path([{'frame':1,'location':[1,-4,2],'target':[0,0,1]},
                       {'frame':24,'location':[2,-3,2],'target':[0,0,1]},
                       {'frame':48,'location':[3,-2,2],'target':[0,0,1]}])
audit=studio.audit_motion(s,[cam],1,48,.2)
check(not audit['position_jumps'],'Dense continuous camera path')
from tangyicam import agent_bridge
engine_result=agent_bridge.execute('render_settings',{'engine':'BLENDER_EEVEE_NEXT','width':320,'height':180})
check(engine_result['engine']==('BLENDER_EEVEE' if bpy.app.version>=(5,0,0) else 'BLENDER_EEVEE_NEXT'),'Eevee identifier resolves on current Blender version')
path_rig=studio.create_rig({'name':'TC_PathRig','bones':[{'name':'root','head':[0,0,1],'tail':[0,0,2]}]})
studio.apply_motion(path_rig,{'name':'TC_PathPose','bones':{'root':[{'frame':1,'rotation':[1,0,0,0]},{'frame':10,'rotation':[1,0,0,0]}]}})
animation_tools.root_trajectory(path_rig,'root',[{'frame':1,'location':[1,2,3]},{'frame':10,'location':[2,3,4]}])
s.frame_set(10);bpy.context.view_layer.update()
from mathutils import Vector
check(((path_rig.matrix_world@path_rig.pose.bones['root'].head)-Vector((2,3,4))).length<1e-5,'Root trajectory reaches requested world coordinates')
prior_action=path_rig.animation_data.action
animation_tools.adjust_pose(path_rig,{'root':[0,0,30]},1,5,10)
s.frame_set(1);q0=path_rig.pose.bones['root'].rotation_quaternion.copy()
s.frame_set(10);q1=path_rig.pose.bones['root'].rotation_quaternion.copy()
check(path_rig.animation_data.action!=prior_action and q0.rotation_difference(q1).angle>.5,'Pose offset preserves original and blends into requested rotation')
out=Path(__file__).resolve().parents[1]/'dist'
report={'blender':bpy.app.version_string,'passed':passed,'contact_error_m':error,'light_power':values,'lamp_emission':emission,'other_power':other_values}
(out/f'studio_core_{bpy.app.version[0]}{bpy.app.version[1]}.json').write_text(json.dumps(report,indent=2),encoding='utf8')
tangyicam.unregister();tangyicam.register();tangyicam.unregister()
print('STUDIO_CORE_PASSED',json.dumps(report))

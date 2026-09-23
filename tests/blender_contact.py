"""Check evaluated skinned-mesh collision timing and kinematic contact offsets."""
import sys,json
from pathlib import Path
import bpy
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tangyicam import studio,animation_tools as anim
bpy.ops.wm.read_factory_settings(use_empty=True)
def actor(name):
    rig=studio.create_rig({'name':name,'bones':[{'name':'root','head':[0,0,0],'tail':[0,0,1]}]})
    mesh=studio.cube(name+'_skin',(0,0,.5),(.5,.5,.5))
    vg=mesh.vertex_groups.new(name='root');vg.add(list(range(len(mesh.data.vertices))),1,'REPLACE')
    modifier=mesh.modifiers.new('skin','ARMATURE');modifier.object=rig
    studio.apply_motion(rig,{'name':name+'_pose','bones':{'root':[{'frame':1,'rotation':[1,0,0,0]},{'frame':3,'rotation':[1,0,0,0]}]}})
    return rig
a=actor('A');b=actor('B')
anim.root_trajectory(b,'root',[{'frame':1,'location':[3,0,0]},{'frame':3,'location':[.2,0,0]}])
audit=anim.audit_contacts(a,b,1,3)
assert audit['first_bounds_overlap']==3 and audit['requires_review'],audit
assert audit['frames'][-1]['status']!='bounds_separated',audit
# Non-coplanar faces must also be found by the evaluated mesh narrow phase.
anim.root_trajectory(b,'root',[{'frame':1,'location':[3,.13,.07]},{'frame':3,'location':[.2,.13,.07]}])
narrow=anim.audit_contacts(a,b,1,3)
assert narrow['first_intersection']==3,narrow
source=a.animation_data.action
anim.sync_body_contact(a,'root',b,'root',[{'frame':1,'offset':[-.8,0,0]},{'frame':3,'offset':[-.8,0,0]}],1,3)
assert source!=a.animation_data.action and source.use_fake_user
errors=[]
for f in range(1,4):
    bpy.context.scene.frame_set(f);bpy.context.view_layer.update()
    pa=a.matrix_world@a.pose.bones['root'].head;pb=b.matrix_world@b.pose.bones['root'].head
    errors.append(abs((pa-pb).length-.8))
assert max(errors)<1e-5,errors
separated=anim.audit_contacts(a,b,1,3)
assert not separated['requires_review'] and separated['first_bounds_overlap'] is None,separated
report={'blender':bpy.app.version_string,'first_skinned_intersection':narrow['first_intersection'],'coplanar_overlap_flagged':audit['requires_review'],'max_offset_error_m':max(errors),'separated_after_alignment':True}
(ROOT/f'dist/contact_tools_{bpy.app.version[0]}{bpy.app.version[1]}.json').write_text(json.dumps(report,indent=2),encoding='utf8')
print('CONTACT_TOOLS_PASSED',json.dumps(report))

import bpy,sys,math,json
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import tangyicam
from tangyicam import camera as c
from tangyicam.studio import curves as action_curves
tangyicam.register()
S=bpy.context.scene;S.render.fps=24;S.render.fps_base=1
c.load_shots({'fps':24,'shots':[{'id':'TEST','dur':2,'start':217,'lens':35}]})
driver=c.driven_camera(S);driver.location=(0,0,1);bpy.context.view_layer.update()
c.select_shot(S,driver,'TEST')
# Animate scene subject to ensure camera sampling is not accidentally scene-driven.
bpy.ops.mesh.primitive_cube_add();subject=bpy.context.object
subject.location=(0,0,0);subject.keyframe_insert('location',frame=217)
subject.location=(5,0,0);subject.keyframe_insert('location',frame=265)
c.record_start(S);cam=c.driven_camera(S);t0=c.rt['rec_t0']
for t in [0,.021,.041,.09,.23,.6,.8,1.23,1.7,2.1]:
    cam.location=(t,0,1);cam.data.lens=35+10*t
    bpy.context.view_layer.update()
    c._record_tick(S,cam,t0+t,.016,1)
assert not c.rt['recording']
assert c.rt['takes'][-1][2]==48,c.rt['takes']
assert not driver.animation_data or not driver.animation_data.action,'Driver polluted'
act=cam.animation_data.action
fcs={(f.data_path,f.array_index):f for f in action_curves(cam)}
assert list(act.frame_range)==[217,264],list(act.frame_range)
for f in range(217,265):
    sf=fcs[('["tc_sf"]',0)].evaluate(f)
    x=fcs[('location',0)].evaluate(f)
    assert abs(sf-f)<.001,(f,sf)
    assert abs(x-(f-217)/24)<.002,(f,x)
assert S.camera==driver
assert (driver.location-Vector((2.1,0,1))).length<.002,tuple(driver.location)
# Slow motion preserves monotonic scene time at quarter speed.
c.record_start(S);cam=c.driven_camera(S);t0=c.rt['rec_t0']
for t in [0,.25,.5,.75,1,1.25,1.5,1.75,2.1]:
    cam.location=(t,1,1);bpy.context.view_layer.update()
    c._record_tick(S,cam,t0+t,.016,.25)
sfcurve=next(f for f in action_curves(cam) if f.data_path=='["tc_sf"]')
for f in range(217,265):
    assert abs(sfcurve.evaluate(f)-(217+(f-217)*.25))<.001,(f,sfcurve.evaluate(f))
# Tick edge: first record tick must write to the new take, never TC_CAM.
c.rt['rec_phone']=False
c.apply_payload({'seq':10000,'q':None,'rec':True,'mx':0,'my':0,'mz':0})
c.tick(S)
assert not driver.animation_data or not driver.animation_data.action,'REC edge wrote to TC_CAM'
c.record_stop(S)
# Same duration for keyframe scrub and recording.
assert c._shot_range(S,c.find_shot('TEST'))==(217,264),c._shot_range(S,c.find_shot('TEST'))
# A disconnected phone must stop translation and zoom, and a new client starts at seq=0.
import time
from types import SimpleNamespace
c.state.update(mx=1,my=1,mz=1,zoom=1,q=None,rec=None,last_seen=time.time()-10)
c.rt['smooth_p']=driver.matrix_world.translation.copy();c.rt['raw_p']=c.rt['smooth_p'].copy()
before=driver.matrix_world.translation.copy();lens=driver.data.lens
c.rt['last_tick']=time.perf_counter()-.04
c.tick(S)
assert (driver.matrix_world.translation-before).length<.0001
assert abs(driver.data.lens-lens)<.001
c.state['seq']=50
tangyicam._on_message(SimpleNamespace(),{'seq':0,'shot':'NEW_CONNECTION'})
assert c.state['shot']=='NEW_CONNECTION'
# After auto-stop the same REC=true command must start a new take.
c.rt['rec_phone']=True
c._resolve_record(S,driver,True)
assert c.rt['recording'],'Second phone take ignored after auto-stop'
c.rt['rec_requires_phone']=True
c.state.update(last_seen=time.time()-2,rec=None)
c.tick(S)
assert not c.rt['recording'],'Lost phone kept recording'
# Fractional FPS uses the same frame range in the scrubber and recorder.
S.render.fps=24;S.render.fps_base=1.001
c.load_shots({'fps':24,'shots':[{'id':'LONG','dur':120,'start':1}]})
c.select_shot(S,driver,'LONG')
c.record_start(S)
assert c.rt['rec_end_frame']==c._shot_range(S,c.find_shot('LONG'))[1]
c.record_stop(S)
c.apply_payload({'mx':-3.5,'my':3.5})
assert c.state['mx']==-3.5 and c.state['my']==3.5,'Directional boost is asymmetric'
result={'passed':True,'checks':['48 frames for 2 seconds at 24fps','exact frame/scene-time alignment','skipped tick interpolation','independent clean TC_CAM','first REC tick ownership','quarter-speed scene clock','driver pose preserved after stop','shot scrub ends on last recorded frame','disconnected phone stops movement and zoom','new connection accepts sequence zero','second take after automatic stop','lost phone stops recording','fractional fps scrub and recording match','symmetric joystick boost']}
(ROOT/'dist'/'recording_verification_v021.json').write_text(json.dumps(result,indent=2),encoding='utf8')
print('RECORDING_VERIFIED',json.dumps(result))


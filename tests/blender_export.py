"""Real frames, native encode, save/reload and fail-closed export acceptance."""
from pathlib import Path
import bpy
import json
import math
import sys
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import tangyicam
from tangyicam import camera, export

tangyicam.register()
scene=bpy.context.scene
scene.render.fps=24
scene.render.fps_base=1.001
scene.render.resolution_x=320;scene.render.resolution_y=180
# Factory scene includes a cube. Use a short orbit to produce genuinely different frames.
cam=camera.driven_camera(scene)
cam.rotation_mode='QUATERNION'
for f,x in [(1,4.0),(12,3.0)]:
 cam.location=(x,-6,3)
 cam.rotation_quaternion=(Vector((0,0,0))-cam.location).to_track_quat('-Z','Y')
 cam.keyframe_insert('location',frame=f)
 cam.keyframe_insert('rotation_quaternion',frame=f)
 cam['tc_sf']=float(f);cam.keyframe_insert('["tc_sf"]',frame=f)
 cam.data.lens=35+f;cam.data.keyframe_insert('lens',frame=f)
scene.frame_set(6,subframe=.5)
original=(scene.frame_current,scene.frame_subframe,scene.camera,cam.matrix_world.copy(),cam.data.lens)
out=ROOT/'dist'/'export_acceptance'
out.mkdir(parents=True,exist_ok=True)
message,path=export.export_take(scene,cam,width=320,output_root=out,encoder='blender')
assert path,message
assert scene.frame_current==original[0] and abs(scene.frame_subframe-original[1])<1e-6
assert scene.camera==original[2]
assert all(abs(a-b)<1e-6 for ra,rb in zip(cam.matrix_world,original[3]) for a,b in zip(ra,rb))
assert abs(cam.data.lens-original[4])<1e-6
folder=Path(path).parent
meta=json.loads((folder/'export.json').read_text())
assert meta['frames']==12 and meta['fps']=='24000/1001',meta
assert (folder/'first.png').is_file() and (folder/'last.png').is_file()
assert (folder/'first.png').read_bytes()!=(folder/'last.png').read_bytes(),'Camera movement absent'
# A failing encoder must report failure and cannot overwrite the prior output.
before=Path(path).read_bytes()
original_encoder=export._native_encode
export._native_encode=lambda *a: (_ for _ in ()).throw(RuntimeError('intentional encoder failure'))
failed_message,failed_path=export.export_take(scene,cam,width=64,output_root=out,encoder='blender')
export._native_encode=original_encoder
assert failed_path is None and 'intentional encoder failure' in failed_message
assert Path(path).read_bytes()==before
blend=out/'saved_take.blend'
bpy.ops.wm.save_as_mainfile(filepath=str(blend))
bpy.ops.wm.open_mainfile(filepath=str(blend))
restored=bpy.data.objects.get('TC_CAM')
assert restored and restored.animation_data and restored.animation_data.action
assert list(restored.animation_data.action.frame_range)==[1.0,12.0]
report={'blender':bpy.app.version_string,'passed':True,'mp4':path,'frames':12,'fps':'24000/1001','checks':['actual Workbench frames','built-in H264 encoding','exact encoded frame count','fractional fps','first and last PNG','camera and frame restored','failure returns no success path','previous output preserved','save and reopen animation']}
(ROOT/'dist'/'export_acceptance.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('EXPORT_ACCEPTANCE',json.dumps(report))

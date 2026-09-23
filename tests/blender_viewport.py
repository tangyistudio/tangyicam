"""Interactive GPU path in an isolated test process, including slow scene time."""
from pathlib import Path
import bpy, json, traceback, importlib, io
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[1]
out=ROOT/'dist'/'viewport_acceptance';out.mkdir(parents=True,exist_ok=True)
def run():
 report={'blender':bpy.app.version_string,'passed':False}
 try:
  tc=importlib.import_module('bl_ext.user_default.tangyicam')
  assert tc.preview.HAVE_PIL
  scene=bpy.context.scene;scene.render.resolution_x=320;scene.render.resolution_y=180;scene.render.fps=24
  cam=tc.camera.driven_camera(scene);cam.rotation_mode='QUATERNION'
  for f,x,sf in [(1,4,1),(6,2,2.25)]:
   cam.location=(x,-6,3);cam.rotation_quaternion=(Vector((0,0,0))-cam.location).to_track_quat('-Z','Y')
   cam.keyframe_insert('location',frame=f);cam.keyframe_insert('rotation_quaternion',frame=f)
   cam['tc_sf']=sf;cam.keyframe_insert('["tc_sf"]',frame=f)
  scene.frame_set(6);bpy.context.view_layer.update()
  expected=tc.preview.capture_jpeg(scene,cam,320,180,92,shading='SOLID');assert expected,tc.preview.stats
  (out/'preview.jpg').write_bytes(expected)
  message,path=tc.export.export_take(scene,cam,width=320,output_root=out,encoder='auto');assert path,message
  from PIL import Image, ImageChops, ImageStat
  with Image.open(io.BytesIO(expected)) as a, Image.open(Path(path).parent/'00005.jpg') as b:
   difference=ImageStat.Stat(ImageChops.difference(a,b)).mean
   assert max(difference)<1,('Slow motion camera pose lost during GPU export',difference)
  report.update({'passed':True,'checks':['real GPU camera JPEG','installed Pillow','external FFmpeg encode','slow-time camera endpoint preserved'],'mp4':path})
 except Exception:
  report['error']=traceback.format_exc();print(report['error'])
 (out/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
 print('VIEWPORT_ACCEPTANCE',json.dumps(report))
 bpy.ops.wm.quit_blender()
 return None
bpy.app.timers.register(run,first_interval=2)

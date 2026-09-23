"""Validate, install, restart, disable and re-enable the real ZIP in isolated profiles."""
from pathlib import Path
import argparse, datetime, hashlib, json, os, subprocess
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--blender',action='append',required=True);args=parser.parse_args()
archive=ROOT/'dist'/'releases'/'0.4.0'/'tangyicam-0.4.0-windows-x64.zip'
out=ROOT/'dist'/'install-qa'/datetime.datetime.now().strftime('%Y%m%d-%H%M%S');out.mkdir(parents=True)
results=[]
check="""import bpy, importlib, addon_utils
name='bl_ext.user_default.tangyicam'
assert name in bpy.context.preferences.addons, 'Enabled extension did not survive restart'
m=importlib.import_module(name)
assert m.preview.HAVE_PIL, 'Bundled Pillow failed to load'
assert hasattr(bpy.types.Scene, 'tc_studio')
assert m._srv is None, 'Installation must not start a listener'
addon_utils.disable(name, default_set=True)
assert not hasattr(bpy.types.Scene, 'tc_studio')
addon_utils.enable(name, default_set=True)
assert hasattr(bpy.types.Scene, 'tc_studio')
print('INSTALL_RESTART_DISABLE_ENABLE_PASS', bpy.app.version_string)
"""
for i,exe in enumerate(args.blender):
 target=out/str(i);target.mkdir();env=dict(os.environ)
 for key in ('APPDATA','LOCALAPPDATA','BLENDER_USER_CONFIG','BLENDER_USER_SCRIPTS','BLENDER_USER_DATAFILES','BLENDER_USER_EXTENSIONS'):
  path=target/key;path.mkdir();env[key]=str(path)
 commands=[('validate',['--background','--factory-startup','--command','extension','validate',str(archive)]),('install',['--background','--factory-startup','--command','extension','install-file','-r','user_default','-e',str(archive)]),('restart',['--background','--python-exit-code','17','--python-expr',check])]
 for name,arguments in commands:
  process=subprocess.run([exe]+arguments,capture_output=True,env=env,timeout=90)
  log=(process.stdout+process.stderr).decode('utf-8',errors='replace');(target/(name+'.log')).write_text(log,encoding='utf-8')
  result={'blender':exe,'stage':name,'exit':process.returncode};results.append(result);print(json.dumps(result),flush=True)
  if process.returncode:print(log);break
(out/'results.json').write_text(json.dumps({'package_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'checks':results},indent=2),encoding='utf-8')
print('INSTALL_QA_DIRECTORY',str(out))
raise SystemExit(0 if len(results)==len(args.blender)*3 and all(r['exit']==0 for r in results) else 1)

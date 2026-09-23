"""Agent → open Blender. python agent_client.py inspect | <command> --args file.json
No network or cloud billing. Requires TangyiCam's Local Agent switch or agent_host.
"""
import argparse,json,os,time,uuid
from pathlib import Path

def call(command,args=None,timeout=120,active_path=None):
    path=Path(active_path) if active_path else Path.home()/'.tangyicam/bridge/active.json'
    if not path.exists():raise RuntimeError('Start TangyiCam Local Agent in Blender first.')
    active=json.loads(path.read_text(encoding='utf8'));root=Path(active['directory'])
    ident=uuid.uuid4().hex;request=root/'requests'/f'{ident}.json'
    tmp=request.with_suffix('.tmp')
    tmp.write_text(json.dumps({'session':active['session'],'command':command,'args':args or {}},ensure_ascii=False),encoding='utf8')
    os.replace(tmp,request)
    response=root/'responses'/request.name
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if response.exists():
            result=json.loads(response.read_text(encoding='utf8'))
            if not result['ok']:raise RuntimeError(result.get('error','Command failed'))
            return result['result']
        time.sleep(.1)
    raise TimeoutError('Blender did not respond. Request may still be running; do not resubmit paid or destructive work.')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command');p.add_argument('--args');p.add_argument('--timeout',type=float,default=120)
    a=p.parse_args()
    print(json.dumps(call(a.command,json.loads(Path(a.args).read_text(encoding='utf-8-sig')) if a.args else {},a.timeout),ensure_ascii=False,indent=2))

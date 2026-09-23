"""Loopback-only test fixture; no production credentials or profile changes."""
from pathlib import Path
import argparse, json, sys, threading, time
from test_security import NetworkTests
parser=argparse.ArgumentParser();parser.add_argument('--session',required=True);parser.add_argument('--image');args=parser.parse_args()
NetworkTests.setUpClass()
srv=NetworkTests.srv
state={'rec':False,'commands':[],'shot':None}
srv.shots_provider=lambda:{'fps':24,'shots':[{'id':'DEMO','title':'<img src=x onerror=alert(1)>','dur':2}]}
def receive(client,obj):
    if 'shot' in obj:state['shot']=obj['shot']
    if 'rec' in obj:
        state['rec']=obj['rec'];state['commands'].append(obj['rec'])
    if 'rec' in obj:
        temporary=Path(args.session+'.messages.tmp')
        temporary.write_text(json.dumps(state),encoding='utf-8')
        temporary.replace(args.session+'.messages.json')
srv.on_message=receive
Path(args.session).write_text(json.dumps({'base':NetworkTests.origin,'http':'http://127.0.0.1:'+str(srv.http_port),'code':srv.pairing.code}),encoding='utf-8')
image=Path(args.image).read_bytes() if args.image else None
running=True
def telemetry():
    while running:
        srv.broadcast_text({'t':'tele','rec':state['rec'],'lens':35,'frame':1,'fps':24,'shot':state['shot'],'shot_start':1,'shot_end':48,'shot_dur':2,'keys':[1,24,48]})
        if image:srv.broadcast_video(image)
        time.sleep(.1)
threading.Thread(target=telemetry,daemon=True).start()
try:sys.stdin.readline()
finally:
    running=False;NetworkTests.tearDownClass()

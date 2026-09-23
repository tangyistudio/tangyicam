"""Run with Blender --background --python tools/agent_host.py.
Dedicated non-interactive session; never touches an artist's unsaved open scene.
"""
import sys,time,signal
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import bpy,tangyicam
from tangyicam import agent_bridge
tangyicam.register()
agent_bridge.start()
print('TANGYICAM_AGENT_READY',flush=True)
try:
    while True:
        agent_bridge.process_pending()
        time.sleep(.1)
except (KeyboardInterrupt,SystemExit):
    pass
finally:
    agent_bridge.stop()

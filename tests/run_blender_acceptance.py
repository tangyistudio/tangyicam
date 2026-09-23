"""Run the exact release package using isolated Blender user directories."""
from pathlib import Path
import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]

def run(executables, tests=None):
    release=ROOT/'dist'/'releases'/'0.4.0'
    qa=ROOT/'dist'/'release-qa'/datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    qa.mkdir(parents=True)
    (ROOT/'dist'/'current-release-qa.txt').write_text(str(qa),encoding='utf-8')
    results=[]
    for version,exe in executables:
        target=qa/version;target.mkdir()
        with zipfile.ZipFile(release/'tangyicam-0.4.0-source.zip') as z:z.extractall(target)
        with zipfile.ZipFile(release/'tangyicam-0.4.0-windows-x64.zip') as z:z.extractall(target/'tangyicam')
        (target/'dist').mkdir()
        env=dict(os.environ)
        for key,folder in [('APPDATA','profile/roaming'),('LOCALAPPDATA','profile/local'),('BLENDER_USER_CONFIG','profile/config'),('BLENDER_USER_SCRIPTS','profile/scripts'),('BLENDER_USER_DATAFILES','profile/datafiles'),('BLENDER_USER_EXTENSIONS','profile/extensions')]:
            path=target/folder;path.mkdir(parents=True,exist_ok=True);env[key]=str(path)
        for script in (tests or ['blender_core.py','blender_recording.py','blender_contact.py','blender_export.py']):
            command=[exe,'--background','--factory-startup','--python-exit-code','17','--python',str(target/'tests'/script)]
            try:
                process=subprocess.run(command,capture_output=True,timeout=180,env=env)
                output=(process.stdout+process.stderr).decode('utf-8',errors='replace')
                (target/(script+'.log')).write_text(output,encoding='utf-8')
                entry={'blender':version,'test':script,'exit':process.returncode,'last_lines':output.splitlines()[-6:]}
            except subprocess.TimeoutExpired:
                entry={'blender':version,'test':script,'exit':'timeout'}
            results.append(entry);print(json.dumps(entry,ensure_ascii=True),flush=True)
    (qa/'results.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    (qa/'package-sha256.txt').write_text(hashlib.sha256((release/'tangyicam-0.4.0-windows-x64.zip').read_bytes()).hexdigest(),encoding='ascii')
    print('QA_DIRECTORY',str(qa),flush=True)
    return 0 if all(x['exit']==0 for x in results) else 1

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--blender',action='append',required=True);parser.add_argument('--test',action='append');args=parser.parse_args()
    sys.exit(run([(str(i),p) for i,p in enumerate(args.blender)],args.test))

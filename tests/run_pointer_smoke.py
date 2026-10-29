"""Run real pointer checks on an isolated Xephyr display (requires X11 and libXtst)."""
import os
import subprocess
import sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
server=subprocess.Popen(['Xephyr','-displayfd','1','-screen','1280x900','-ac','-noreset'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
try:
    number=server.stdout.readline().strip()
    if not number:
        raise SystemExit('Could not start nested X11 display')
    env={**os.environ,'DISPLAY': ':'+number,'GDK_BACKEND':'x11','PYTHONPATH':str(root)}
    result=subprocess.run([sys.executable, str(root / 'tests/smoke_pointer_resize.py')],env=env,timeout=55)
    raise SystemExit(result.returncode)
finally:
    server.terminate()
    server.wait(timeout=5)

"""Run the GTK 3 layout smoke check on an isolated Broadway display."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def main():
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="ws-native-smoke-") as directory, tempfile.TemporaryFile() as log:
        env = {**os.environ, "XDG_RUNTIME_DIR": directory, "GDK_BACKEND": "broadway", "BROADWAY_DISPLAY": ":0"}
        server = subprocess.Popen(["broadwayd", "--unixsocket", str(Path(directory) / "http.sock"), ":0"],
                                  env=env, stdout=log, stderr=log)
        try:
            for _ in range(100):
                if (Path(directory) / "broadway1.socket").exists():
                    break
                if server.poll() is not None:
                    log.seek(0)
                    raise RuntimeError(log.read().decode())
                time.sleep(.05)
            return subprocess.run([sys.executable, str(root / "tests/smoke_widgets.py")],
                                  env=env, cwd=root, timeout=40).returncode
        finally:
            server.terminate()
            server.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())

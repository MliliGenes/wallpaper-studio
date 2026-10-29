import fcntl
import json
import os
from pathlib import Path
import pty
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from unittest.mock import patch

from wallpaper_studio import media, storage
from wallpaper_studio.tui import CommandJob, awake_status

ROOT = Path(__file__).resolve().parents[1]


class TerminalBackendTests(unittest.TestCase):
    def test_widgets_panel_includes_now_playing_and_arrange_controls(self):
        from wallpaper_studio import layout, settings
        from wallpaper_studio.tui import Panel
        panel = Panel.__new__(Panel)
        panel.page = 2
        panel.config = settings.DEFAULT_CONFIG.copy()
        panel.placements = layout.load_layout(layout.DEFAULT_FILE)
        rows = panel.items()
        media = next(row for row in rows if row.command == ("layout", "toggle", "now-playing"))
        self.assertEqual(media.label, "Now playing")
        self.assertEqual(media.value, "On")
        self.assertTrue(any(row.setting == "layout_edit" for row in rows))
        for key in ("layout_grid", "layout_grid_size", "layout_grid_gap"):
            self.assertTrue(any(row.setting == key for row in rows))

    def test_expired_awake_requests_display_off(self):
        self.assertEqual(awake_status({}, now=100), "Off")
        self.assertEqual(awake_status({"until": 99}, now=100), "Off")
        self.assertIn("logout", awake_status({"until": -1}, now=100))
        self.assertIn("2 more min", awake_status({"until": 161}, now=100))

    def test_library_discovers_media_and_ignores_hidden_files_and_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ("B.JPG", "a.webm", "notes.txt", ".hidden.png"):
                Path(directory, name).touch()
            Path(directory, "folder.png").mkdir()
            self.assertEqual([Path(path).name for path in media.wallpapers(directory)], ["a.webm", "B.JPG"])
            self.assertTrue(media.is_video("a.webm"))

    def test_no_terminal_produces_actionable_error(self):
        result = subprocess.run([sys.executable, "-m", "wallpaper_studio", "tui"], cwd=ROOT,
                                stdin=subprocess.DEVNULL, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("interactive terminal", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_command_job_uses_shared_validation_and_keeps_bad_value_out_of_config(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"XDG_CONFIG_HOME": directory, "DISPLAY": ""}):
            for value, expected in (("72", 0), ("-5", 1)):
                job = CommandJob(("config", "set", "clock_top", value))
                try:
                    job.process.wait(timeout=10)
                    code, output = job.result()
                    self.assertEqual(code, expected, output)
                finally:
                    job.close()
            config = json.loads(Path(directory, "wallpaper-studio", "config.json").read_text())
            self.assertEqual(config["clock_top"], 72)

    def test_tui_import_does_not_load_gtk(self):
        result = subprocess.run([sys.executable, "-c", "import wallpaper_studio.tui; import sys; assert 'gi' not in sys.modules"],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class InteractiveTerminalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.master, self.slave = pty.openpty()
        self.addCleanup(os.close, self.master)
        self.addCleanup(os.close, self.slave)
        self.resize(24, 100)
        env = {**os.environ, "TERM": "xterm-256color", "XDG_CONFIG_HOME": self.temp.name,
               "XDG_CACHE_HOME": self.temp.name, "XDG_RUNTIME_DIR": self.temp.name, "DISPLAY": "", "ESCDELAY": "25"}
        self.process = subprocess.Popen([sys.executable, "-m", "wallpaper_studio", "tui"], cwd=ROOT,
                                        env=env, stdin=self.slave, stdout=self.slave, stderr=self.slave)
        self.addCleanup(self.stop)
        self.output = b""
        self.wait_for(b"WALLPAPER STUDIO")

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=5)

    def resize(self, height, width):
        fcntl.ioctl(self.slave, termios.TIOCSWINSZ, struct.pack("HHHH", height, width, 0, 0))

    def send(self, keys):
        self.output = b""
        os.write(self.master, keys)

    def wait_for(self, fragment):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            ready, _, _ = select.select([self.master], [], [], .1)
            if ready:
                self.output += os.read(self.master, 65536)
                if fragment in self.output:
                    return
            if self.process.poll() is not None:
                break
        self.fail(f"Missing terminal output {fragment!r}: {self.output[-2500:]!r}")

    def assert_terminal_restored(self):
        self.assertEqual(self.process.wait(timeout=5), 0, self.output)
        flags = termios.tcgetattr(self.slave)[3]
        self.assertTrue(flags & termios.ECHO)
        self.assertTrue(flags & termios.ICANON)

    def test_edit_clock_validate_input_and_cancel_restore(self):
        self.send(b"3")
        self.wait_for(b"Time format")
        self.send(b"j\n")
        self.wait_for(b"Ctrl-U clear")
        self.send(b"\x15%H:%M:%S\n")
        config_path = Path(self.temp.name, "wallpaper-studio", "config.json")
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            config = storage.read_json(str(config_path), {})
            if config.get("clock_format") == "%H:%M:%S":
                break
            time.sleep(.05)
        self.assertEqual(config.get("clock_format"), "%H:%M:%S")
        self.wait_for(b'"%H:%M:%S"')
        self.send(b"jj\n")
        self.wait_for(b"Ctrl-U clear")
        self.send(b"\x15-1\n")
        self.wait_for(b"Error:")
        self.assertEqual(storage.read_json(str(config_path), {})["clock_top"], 32)
        self.send(b"5jjjj\n")
        self.wait_for(b"type restore to confirm")
        self.send(b"\x1b")
        time.sleep(.1)
        self.send(b"q")
        self.assert_terminal_restored()
        self.assertTrue(storage.read_json(str(config_path), {})["clock"])

    def test_small_terminal_resizes_and_quits_cleanly(self):
        self.resize(10, 30)
        os.kill(self.process.pid, signal.SIGWINCH)
        self.wait_for(b"Resize to at least")
        self.send(b"q")
        self.assert_terminal_restored()

    def test_panel_selection_survives_focus_and_section_changes(self):
        self.send(b"3j")
        self.wait_for(b"Time format")
        self.send(b"ljG")
        self.wait_for(b"No X11 display.")
        self.send(b"h\n")
        self.wait_for(b"Time format: strftime time format")
        self.send(b"\x1b")
        time.sleep(.1)
        self.send(b"2")
        self.wait_for(b"Colour mode")
        self.send(b"3\n")
        self.wait_for(b"Time format: strftime time format")
        self.send(b"\x1b")
        time.sleep(.1)
        self.resize(16, 60)
        os.kill(self.process.pid, signal.SIGWINCH)
        self.wait_for(b"Preview / details")
        self.send(b"q")
        self.assert_terminal_restored()


if __name__ == "__main__":
    unittest.main()

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from wallpaper_studio import settings, storage

ROOT = Path(__file__).resolve().parents[1]


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.file = str(Path(self.temp.name) / "config.json")
        for target, value in (("wallpaper_studio.settings.CONFIG", self.file),
                              ("wallpaper_studio.storage.CONFIG_DIR", self.temp.name),
                              ("wallpaper_studio.storage.LOCK", str(Path(self.temp.name) / ".lock"))):
            p = patch(target, value)
            p.start()
            self.addCleanup(p.stop)

    def test_validation_and_normalization(self):
        result = settings.save_config(glass="on", rotate_hours="0.5", light_from="22", folder=self.temp.name)
        self.assertIs(result["glass"], True)
        self.assertEqual(result["rotate_hours"], .5)
        self.assertEqual(settings.load_config()["light_from"], 22)
        self.assertEqual(result["folder"], self.temp.name)

    def test_invalid_changes_never_replace_saved_preferences(self):
        settings.save_config(mode="dark")
        before = Path(self.file).read_text()
        for key, value in (("mode", "night"), ("glass", "maybe"), ("rotate_hours", "nan"),
                           ("rotate_hours", float("inf")), ("light_from", 24), ("light_from", True),
                           ("awake_interval", 0), ("clock_top", -1), ("clock_format", ""),
                           ("awake_method", "invalid"), ("widget_blur_radius", 65), ("widget_blur", "maybe"),
                           ("typo", 1), ("folder", "/missing/ws-test-folder")):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                settings.save_config(**{key: value})
        self.assertEqual(Path(self.file).read_text(), before)

    def test_malformed_and_old_config_recovers(self):
        for text in ("{", "[]", "null", '{"mode":"oops", "glass": true, "unknown":3}'):
            Path(self.file).write_text(text)
            self.assertEqual(settings.load_config()["mode"], "auto")
        self.assertTrue(settings.load_config()["glass"])
        self.assertNotIn("unknown", settings.load_config())

    def test_reset_one_preserves_other_settings(self):
        settings.save_config(mode="dark", glass=True)
        settings.reset_config("mode")
        self.assertEqual(settings.load_config()["mode"], "auto")
        self.assertTrue(settings.load_config()["glass"])

    def test_old_keep_awake_key_mode_migrates_to_mouse(self):
        Path(self.file).write_text('{"awake_method": "key"}')
        self.assertEqual(settings.load_config()["awake_method"], "mouse")
        self.assertEqual(settings.validate("awake_method", "inhibit"), "inhibit")

    def test_day_and_overnight_schedules(self):
        for hour, start, end, expected in ((7, 7, 19, True), (19, 7, 19, False),
                                           (23, 22, 6, True), (5, 22, 6, True),
                                           (6, 22, 6, False), (12, 22, 6, False), (7, 7, 7, False)):
            self.assertEqual(settings.is_light_hour(hour, start, end), expected)


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = {**os.environ, "XDG_CONFIG_HOME": self.temp.name, "XDG_RUNTIME_DIR": self.temp.name}
        self.env.pop("DISPLAY", None)

    def run_cli(self, *args, expected=0):
        result = subprocess.run([sys.executable, "-m", "wallpaper_studio", *args], cwd=ROOT,
                                env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, expected, result.stderr)
        return result.stdout

    def test_config_roundtrip_and_clock(self):
        self.run_cli("config", "set", "glass", "true")
        self.assertEqual(self.run_cli("config", "get", "glass").strip(), "true")
        self.run_cli("config", "set", "clock_format", "%H:%M:%S")
        self.assertEqual(self.run_cli("config", "get", "clock_format").strip(), "%H:%M:%S")
        self.run_cli("clock", "off")
        self.run_cli("clock", "toggle")
        self.assertEqual(self.run_cli("config", "get", "clock").strip(), "true")
        self.run_cli("config", "reset", "glass")
        self.assertEqual(self.run_cli("config", "get", "glass").strip(), "false")
        status = json.loads(self.run_cli("status"))
        self.assertEqual(status["state"], {})
        self.assertEqual(status["config"]["clock_format"], "%H:%M:%S")

    def test_invalid_and_missing_arguments(self):
        self.run_cli("config", "set", "rotate_hours", "nan", expected=1)
        self.run_cli("set", expected=2)
        self.run_cli("config", "set", "mode", expected=2)
        self.run_cli("unknown", expected=2)

    def test_configuration_does_not_import_gtk(self):
        result = subprocess.run([sys.executable, "-c",
                                 "from wallpaper_studio.cli import main; import sys; "
                                 "main(['config', 'list']); assert 'gi' not in sys.modules"],
                                cwd=ROOT, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_concurrent_edits_preserve_both_preferences(self):
        processes = [subprocess.Popen([sys.executable, "-c",
                     f"from wallpaper_studio.settings import save_config; "
                     f"[save_config({change}) for _ in range(30)]"], cwd=ROOT, env=self.env)
                     for change in ("glass=True", "clock_top=85")]
        for process in processes:
            self.assertEqual(process.wait(timeout=15), 0)
        status = json.loads(self.run_cli("status"))
        self.assertTrue(status["config"]["glass"])
        self.assertEqual(status["config"]["clock_top"], 85)


if __name__ == "__main__":
    unittest.main()

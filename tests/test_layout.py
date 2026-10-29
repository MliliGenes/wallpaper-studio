import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wallpaper_studio import layout, settings, storage
from wallpaper_studio.components import resolve


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for name, value in {"CONFIG_DIR": self.temp.name, "LAYOUT": str(Path(self.temp.name) / "layout.json"),
                            "CUSTOM_WIDGETS": str(Path(self.temp.name) / "widgets"),
                            "LOCK": str(Path(self.temp.name) / ".lock")}.items():
            p = patch.object(storage, name, value)
            p.start()
            self.addCleanup(p.stop)
        layout.ensure_layout()
        p = patch.object(settings, "CONFIG", str(Path(self.temp.name) / "config.json"))
        p.start()
        self.addCleanup(p.stop)

    def test_default_layout_and_offsets(self):
        entries = layout.load_layout()
        self.assertEqual([item.component for item in entries], ["Clock", "Calendar", "System", "Notes", "Logtime"])
        self.assertEqual(layout.coordinates(entries[0], 1000, 800, 200, 100, 48), (400, 48))
        self.assertEqual(layout.coordinates(entries[1], 1000, 800, 200, 100), (768, 32))
        self.assertEqual(layout.coordinates(entries[3], 1000, 800, 200, 100), (768, 668))
        self.assertEqual(layout.coordinates(entries[4], 1000, 800, 200, 100), (32, 668))

    def test_bad_layouts_reject_duplicate_ids_scales_and_unsafe_names(self):
        for entries in ([{"id": "x", "component": "Clock", "scale": 0}],
                        [{"id": "x", "component": "Clock", "scale": float("nan")}],
                        [{"id": "../x", "component": "Clock"}],
                        [{"id": "x", "component": "Clock", "anchor": "wrong"}],
                        [{"id": "x", "component": "Clock", "props": {"config": {}}}],
                        [{"id": "x", "component": "Clock"}] * 2):
            with self.assertRaises(ValueError):
                layout.parse_layout({"version": 1, "widgets": entries})

    def test_save_one_position_preserves_other_cards_and_user_props(self):
        before = json.loads(Path(storage.LAYOUT).read_text())
        layout.save_placement("clock", anchor="top-left", x=120, y=240, scale=1.4)
        after = json.loads(Path(storage.LAYOUT).read_text())
        self.assertEqual(after["widgets"][1:], before["widgets"][1:])
        self.assertEqual(layout.load_layout()[0].scale, 1.4)
        layout.ensure_layout()
        self.assertEqual(layout.load_layout()[0].x, 120)

    def test_each_widget_toggle_preserves_all_other_widgets(self):
        original = layout.load_layout()
        layout.set_enabled("calendar", False)
        changed = layout.load_layout()
        self.assertFalse(changed[1].enabled)
        self.assertEqual(changed[0], original[0])
        self.assertEqual(changed[2:], original[2:])
        layout.set_enabled("clock", False)
        self.assertTrue(settings.load_config()["clock"])
        self.assertFalse(layout.widget_enabled(layout.load_layout()[0], settings.load_config()))
        self.assertTrue(layout.load_layout()[2].enabled)

    def test_custom_component_hot_reload_and_bad_edit_keeps_previous_function(self):
        path = Path(storage.CUSTOM_WIDGETS) / "greeting.py"
        template = 'from wallpaper_studio.components import Text, component\n@component\ndef Widget(config, name="world"):\n    return Text("%s " + name)\n'
        path.write_text(template % "Hello")
        loader = layout.ComponentLoader()
        first = loader.load("greeting")
        self.assertEqual(resolve(first(config={}, name="sel-mlil")).props["text"], "Hello sel-mlil")
        self.assertIs(loader.load("greeting"), first)
        path.write_text(template % "Welcome")
        second = loader.load("greeting")
        self.assertIsNot(first, second)
        path.write_text("invalid python !")
        with self.assertLogs("wallpaper_studio.layout", level="ERROR"):
            self.assertIs(loader.load("greeting"), second)


if __name__ == "__main__":
    unittest.main()

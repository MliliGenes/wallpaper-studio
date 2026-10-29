import subprocess
import sys
import unittest
from unittest.mock import patch

from wallpaper_studio.components import Column, Progress, Row, Text, component, resolve
from wallpaper_studio.settings import DEFAULT_CONFIG
from wallpaper_studio.widgets.clock import Clock


class ComponentTests(unittest.TestCase):
    def test_function_components_receive_props_at_render_time(self):
        calls = []

        @component
        def Greeting(name):
            calls.append(name)
            return Row(Text(f"Hello {name}", key="greeting"), class_name="card")

        tree = Greeting(name="sel-mlil", key="person")
        self.assertEqual(calls, [])
        result = resolve(tree)
        self.assertEqual(calls, ["sel-mlil"])
        self.assertEqual(result.kind, "row")
        self.assertEqual(result.key, "person")
        self.assertEqual(result.children[0].props["text"], "Hello sel-mlil")

    def test_nested_lists_and_conditional_children(self):
        result = resolve(Column(Text("first"), None, [False, Row(Text("second"))]))
        self.assertEqual(len(result.children), 2)
        self.assertEqual(result.children[1].children[0].props["text"], "second")

    def test_duplicate_keys_and_recursive_components_fail_clearly(self):
        with self.assertRaisesRegex(ValueError, "unique keys"):
            resolve(Column(Text("one", key="same"), Text("two", key="same")))

        @component
        def Recursive():
            return Recursive()

        with self.assertRaisesRegex(ValueError, "too deep"):
            resolve(Recursive())

    def test_clock_retains_css_and_respects_visibility_preferences(self):
        with patch("wallpaper_studio.widgets.clock.time.strftime", side_effect=lambda fmt, _now: f"formatted:{fmt}"):
            clock = resolve(Clock(config={**DEFAULT_CONFIG, "clock": False, "clock_date_format": ""}))
        self.assertEqual(clock.props["class_name"], "desktop-clock")
        self.assertFalse(clock.props["visible"])
        self.assertEqual(clock.children[0].props["class_name"], "clock-time")
        self.assertEqual(clock.children[0].props["text"], "formatted:%H:%M")
        self.assertFalse(clock.children[1].props["visible"])

    def test_invalid_widget_props_are_rejected_before_gtk(self):
        for factory in (lambda: Column(spacing=-1), lambda: Text("x", align="wrong"),
                        lambda: Text("x", visible="yes"), lambda: Progress(float("nan")),
                        lambda: Progress(2), lambda: Column("unwrapped text")):
            with self.assertRaises((ValueError, TypeError)):
                factory()

    def test_no_gtk_needed_to_import_and_resolve_clock(self):
        result = subprocess.run([sys.executable, "-c",
                                 "from wallpaper_studio.components import resolve; "
                                 "from wallpaper_studio.widgets import Clock; "
                                 "from wallpaper_studio.settings import DEFAULT_CONFIG; "
                                 "resolve(Clock(config=DEFAULT_CONFIG)); "
                                 "import sys; assert 'gi' not in sys.modules"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()

import subprocess
import sys
import unittest
import xml.etree.ElementTree as ET

from wallpaper_studio.components import Icon, IconButton, resolve
from wallpaper_studio.icons import available_icons, svg_data


class IconTests(unittest.TestCase):
    def test_catalog_contains_attributed_valid_svgs(self):
        self.assertTrue({'play', 'pause', 'backward-step', 'forward-step', 'music'} <= set(available_icons()))
        for name in available_icons():
            data = svg_data(name)
            root = ET.fromstring(data)
            self.assertEqual(root.tag, '{http://www.w3.org/2000/svg}svg')
            self.assertIn('viewBox', root.attrib)
            self.assertIn(b'Font Awesome Free 6.7.2', data)

    def test_unsafe_and_unknown_names_fail_before_rendering(self):
        for name in ('../play', '/tmp/play.svg', 'play.svg', 'PLAY', '', None, 'missing-icon'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                Icon(name)

    def test_icon_buttons_preserve_semantics(self):
        calls = []
        button = resolve(IconButton('play', label='Play', on_click=lambda: calls.append(True), key='transport'))
        self.assertEqual(button.kind, 'button')
        self.assertEqual(button.key, 'transport')
        self.assertEqual(button.props['icon'], 'play')
        self.assertEqual(button.props['tooltip'], 'Play')
        button.props['on_click']()
        self.assertEqual(calls, [True])
        with self.assertRaises(ValueError):
            IconButton('play', label='', on_click=lambda: None)
        self.assertEqual(resolve(Icon('music', label='Music')).props['label'], 'Music')

    def test_icons_remain_headless(self):
        result = subprocess.run([sys.executable, '-c',
            'from wallpaper_studio.components import Icon, IconButton, resolve; '
            'resolve(Icon("play")); resolve(IconButton("pause", label="Pause", on_click=lambda: None)); '
            'import sys; assert "gi" not in sys.modules'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

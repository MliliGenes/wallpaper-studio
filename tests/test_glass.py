from pathlib import Path
import tempfile
import unittest

import cairo

from wallpaper_studio.glass import WallpaperGlass


class WallpaperGlassTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "wallpaper.png"
        surface = cairo.ImageSurface(cairo.FORMAT_RGB24, 160, 90)
        context = cairo.Context(surface)
        context.set_source_rgb(.3, .1, .5)
        context.paint()
        context.set_source_rgb(.1, .7, .9)
        context.rectangle(80, 0, 80, 90)
        context.fill()
        surface.write_to_png(str(self.path))

    def test_backdrop_is_cached_and_small_independent_of_desktop_pixel_count(self):
        glass = WallpaperGlass()
        self.assertTrue(glass.load(str(self.path), 1920, 1080, 24))
        original = glass.surface
        self.assertEqual((original.get_width(), original.get_height()), (80, 45))
        self.assertTrue(glass.load(str(self.path), 1920, 1080, 24))
        self.assertIs(glass.surface, original)
        self.assertTrue(glass.load(str(self.path), 2560, 1440, 24))
        self.assertIsNot(glass.surface, original)

    def test_zero_radius_and_missing_wallpaper_fall_back_without_a_surface(self):
        glass = WallpaperGlass()
        glass.load(str(self.path), 1920, 1080)
        self.assertFalse(glass.load(str(self.path), 1920, 1080, 0))
        self.assertIsNone(glass.surface)
        with self.assertLogs("wallpaper_studio.glass", level="WARNING"):
            self.assertFalse(glass.load(str(self.path) + ".missing", 1920, 1080))
        self.assertIsNone(glass.surface)


if __name__ == "__main__":
    unittest.main()

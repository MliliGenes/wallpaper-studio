from pathlib import Path
import tempfile
import sys
import unittest

try:
    import cairo
    from wallpaper_studio.glass import WallpaperGlass, gaussian_blur, gaussian_kernel
except ModuleNotFoundError as error:
    # Skip only when the system bindings are absent; any other import error should still fail.
    if error.name not in ("cairo", "gi"):
        raise
    raise unittest.SkipTest(f"{error.name} is not installed")


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
        self.assertEqual((original.get_width(), original.get_height()), (240, 135))
        self.assertTrue(glass.load(str(self.path), 1920, 1080, 24))
        self.assertIs(glass.surface, original)
        self.assertTrue(glass.load(str(self.path), 2560, 1440, 24))
        self.assertIsNot(glass.surface, original)

    def test_gaussian_weights_are_symmetric_normalized_and_center_weighted(self):
        kernel = gaussian_kernel(2)
        self.assertAlmostEqual(sum(kernel), 1)
        self.assertEqual(kernel, kernel[::-1])
        self.assertGreater(kernel[6], kernel[5])
        self.assertGreater(kernel[5], kernel[4])
        self.assertEqual(gaussian_kernel(0), (1.0,))

    def test_impulse_has_gaussian_falloff_in_both_axes(self):
        surface = cairo.ImageSurface(cairo.FORMAT_RGB24, 21, 21)
        context = cairo.Context(surface)
        context.set_source_rgb(1, 1, 1)
        context.rectangle(10, 10, 1, 1)
        context.fill()
        blurred = gaussian_blur(surface, 2, 2)
        blurred.flush()
        pixels, stride = blurred.get_data(), blurred.get_stride()
        channel = 0 if sys.byteorder == "little" else 1
        def value(x, y):
            return pixels[y * stride + x * 4 + channel]
        kernel = gaussian_kernel(2)
        self.assertEqual(value(10, 10), round(255 * kernel[6] ** 2))
        self.assertGreater(value(10, 10), value(12, 10))
        self.assertGreater(value(12, 10), value(14, 10))
        self.assertEqual(value(12, 10), value(10, 12))
        self.assertEqual(value(8, 10), value(12, 10))
        self.assertEqual(value(0, 0), 0)

    def test_uniform_color_stays_uniform_including_edges(self):
        surface = cairo.ImageSurface(cairo.FORMAT_RGB24, 9, 7)
        context = cairo.Context(surface)
        context.set_source_rgb(.2, .5, .8)
        context.paint()
        result = gaussian_blur(surface, 3, 3)
        surface.flush()
        result.flush()
        self.assertEqual(bytes(result.get_data()), bytes(surface.get_data()))

    def test_strength_changes_cache_and_large_desktops_have_bounded_working_size(self):
        glass = WallpaperGlass()
        self.assertTrue(glass.load(str(self.path), 1920, 1080, 12))
        original = glass.surface
        self.assertTrue(glass.load(str(self.path), 1920, 1080, 24))
        self.assertIsNot(glass.surface, original)
        self.assertTrue(glass.load(str(self.path), 7680, 4320, 1))
        self.assertLessEqual(max(glass.surface.get_width(), glass.surface.get_height()), 640)

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

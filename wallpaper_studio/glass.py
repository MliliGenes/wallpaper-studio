"""Small cached wallpaper backdrop for frosted GTK cards; no compositor extension needed.

The wallpaper is filtered with a separable Gaussian kernel at a bounded working
resolution, then cached and sampled behind each card.
"""
from array import array
import logging
import math
import os
import sys

import cairo
import gi

gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk  # noqa: E402

log = logging.getLogger(__name__)


def gaussian_kernel(sigma):
    """Normalized Gaussian weights, truncated at three standard deviations."""
    if sigma <= 0:
        return (1.0,)
    radius = max(1, math.ceil(3 * sigma))
    weights = [math.exp(-(offset * offset) / (2 * sigma * sigma))
               for offset in range(-radius, radius + 1)]
    total = sum(weights)
    return tuple(weight / total for weight in weights)


def gaussian_blur(surface, sigma_x, sigma_y):
    """Separable RGB convolution with padded edges and a float intermediate.

    Float intermediates avoid banding from rounding each weighted sample. No extra
    image library is needed; the caller bounds both image dimensions and sigma.
    """
    width, height = surface.get_width(), surface.get_height()
    surface.flush()
    pixels, stride = surface.get_data(), surface.get_stride()
    channels = (0, 1, 2) if sys.byteorder == "little" else (1, 2, 3)
    horizontal, vertical = gaussian_kernel(sigma_x), gaussian_kernel(sigma_y)
    rx, ry = len(horizontal) // 2, len(vertical) // 2
    x_taps = [[(max(0, min(width - 1, x + i - rx)) * 4, weight)
               for i, weight in enumerate(horizontal)] for x in range(width)]
    y_taps = [[(max(0, min(height - 1, y + i - ry)) * width * 3, weight)
               for i, weight in enumerate(vertical)] for y in range(height)]
    intermediate = array("f", [0.0]) * (width * height * 3)
    for y in range(height):
        source_row, target_row = y * stride, y * width * 3
        for x, taps in enumerate(x_taps):
            a = b = c = 0.0
            for offset, weight in taps:
                offset += source_row
                a += pixels[offset + channels[0]] * weight
                b += pixels[offset + channels[1]] * weight
                c += pixels[offset + channels[2]] * weight
            offset = target_row + x * 3
            intermediate[offset], intermediate[offset + 1], intermediate[offset + 2] = a, b, c
    result = cairo.ImageSurface(cairo.FORMAT_RGB24, width, height)
    output, output_stride = result.get_data(), result.get_stride()
    for y, taps in enumerate(y_taps):
        for x in range(width):
            a = b = c = 0.0
            for row, weight in taps:
                offset = row + x * 3
                a += intermediate[offset] * weight
                b += intermediate[offset + 1] * weight
                c += intermediate[offset + 2] * weight
            offset = y * output_stride + x * 4
            output[offset + channels[0]] = max(0, min(255, round(a)))
            output[offset + channels[1]] = max(0, min(255, round(b)))
            output[offset + channels[2]] = max(0, min(255, round(c)))
            output[offset + (3 if sys.byteorder == "little" else 0)] = 255
    result.mark_dirty()
    return result


class WallpaperGlass:
    def __init__(self):
        self.surface = None
        self.signature = None
        self.width = self.height = 0

    def clear(self):
        self.surface = None
        self.signature = None

    def load(self, path, width, height, radius=24):
        if not path or radius <= 0 or width <= 0 or height <= 0:
            self.clear()
            return False
        try:
            stat = os.stat(path)
            signature = (os.path.realpath(path), stat.st_mtime_ns, stat.st_size, width, height, radius)
            if signature == self.signature:
                return True
            _format, source_width, source_height = GdkPixbuf.Pixbuf.get_file_info(path)
            if not source_width or not source_height:
                raise ValueError("Wallpaper cannot be decoded")
            # Retain three samples per blur sigma instead of enlarging a tiny,
            # unfiltered thumbnail. Bound work even on large or multi-monitor desktops.
            downsample = max(1, radius / 3, max(width, height) / 640)
            small_width = max(1, math.ceil(width / downsample))
            small_height = max(1, math.ceil(height / downsample))
            scale = max(small_width / source_width, small_height / source_height)
            scaled_width = max(small_width, math.ceil(source_width * scale))
            scaled_height = max(small_height, math.ceil(source_height * scale))
            image = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, scaled_width, scaled_height, False)
            surface = cairo.ImageSurface(cairo.FORMAT_RGB24, small_width, small_height)
            context = cairo.Context(surface)
            Gdk.cairo_set_source_pixbuf(context, image, -(image.get_width() - small_width) // 2,
                                       -(image.get_height() - small_height) // 2)
            context.paint()
            self.surface = gaussian_blur(surface, radius * small_width / width, radius * small_height / height)
            self.signature = signature
            self.width, self.height = width, height
            return True
        except (OSError, ValueError, GLib.Error) as error:
            log.warning("Cannot prepare widget wallpaper blur: %s", error)
            self.clear()
            return False

    def draw(self, widget, context, root_x, root_y):
        if self.surface is None:
            return False
        width, height = widget.get_allocated_width(), widget.get_allocated_height()
        if width <= 0 or height <= 0:
            return False
        context.save()
        # Reuse GTK's CSS shape for the mask, including custom border radii.
        context.push_group()
        style = widget.get_style_context()
        style.save()
        try:
            style.add_class("glass-mask")
            Gtk.render_background(style, context, 0, 0, width, height)
        finally:
            style.restore()
        mask = context.pop_group()
        pattern = cairo.SurfacePattern(self.surface)
        pattern.set_filter(cairo.FILTER_BILINEAR)
        pattern.set_extend(cairo.EXTEND_PAD)
        sx, sy = self.surface.get_width() / self.width, self.surface.get_height() / self.height
        pattern.set_matrix(cairo.Matrix(xx=sx, yy=sy, x0=root_x * sx, y0=root_y * sy))
        context.set_source(pattern)
        context.mask(mask)
        context.restore()
        return False

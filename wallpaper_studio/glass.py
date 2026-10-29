"""Small cached wallpaper backdrop for frosted GTK cards; no compositor extension needed.

The image is downsampled and sampled bilinearly while drawing. This softens the wallpaper
behind a card, rather than attempting an unsupported GTK CSS backdrop-filter.
"""
import logging
import math
import os

import cairo
import gi

gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk  # noqa: E402

log = logging.getLogger(__name__)


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
            small_width, small_height = max(2, math.ceil(width / radius)), max(2, math.ceil(height / radius))
            scale = max(small_width / source_width, small_height / source_height)
            scaled_width = max(small_width, math.ceil(source_width * scale))
            scaled_height = max(small_height, math.ceil(source_height * scale))
            image = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, scaled_width, scaled_height, False)
            surface = cairo.ImageSurface(cairo.FORMAT_RGB24, small_width, small_height)
            context = cairo.Context(surface)
            Gdk.cairo_set_source_pixbuf(context, image, -(image.get_width() - small_width) // 2,
                                       -(image.get_height() - small_height) // 2)
            context.paint()
            self.surface, self.signature = surface, signature
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

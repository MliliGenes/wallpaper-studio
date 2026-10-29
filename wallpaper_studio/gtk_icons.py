"""GTK 3 SVG icons, recoloured by CSS and rasterized at the display scale."""
from functools import lru_cache

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GdkPixbuf, Gtk

from .icons import svg_data, validate_icon


@lru_cache(maxsize=128)
def raster_icon(name, pixels):
    loader = GdkPixbuf.PixbufLoader.new_with_type("svg")
    def size_prepared(loader, width, height):
        ratio = pixels / max(width, height)
        loader.set_size(max(1, round(width * ratio)), max(1, round(height * ratio)))
    loader.connect("size-prepared", size_prepared)
    loader.write(svg_data(name))
    loader.close()
    return loader.get_pixbuf()


class SvgIcon(Gtk.DrawingArea):
    def __init__(self, name):
        super().__init__(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.icon_name = validate_icon(name)
        self.get_style_context().add_class("widget-icon")
        self.connect("style-updated", self.update_size)
        self.connect("state-flags-changed", lambda *_: self.queue_draw())
        self.connect("notify::scale-factor", lambda *_: self.queue_draw())
        self.connect("draw", self.draw_icon)
        self.update_size()

    def set_icon_name(self, name):
        name = validate_icon(name)
        if name != self.icon_name:
            self.icon_name = name
            self.queue_draw()

    def update_size(self, *_args):
        style, state = self.get_style_context(), self.get_state_flags()
        size = (max(1, style.get_property("min-width", state) or 16),
                max(1, style.get_property("min-height", state) or 16))
        if self.get_size_request() != size:
            self.set_size_request(*size)
        self.queue_draw()

    def draw_icon(self, widget, cr):
        width, height = self.get_allocated_width(), self.get_allocated_height()
        factor = self.get_scale_factor()
        pixels = max(1, min(512, round(min(width, height) * factor)))
        pixbuf = raster_icon(self.icon_name, pixels)
        ratio = min(width / pixbuf.get_width(), height / pixbuf.get_height())
        cr.save()
        cr.translate((width - pixbuf.get_width() * ratio) / 2,
                     (height - pixbuf.get_height() * ratio) / 2)
        cr.scale(ratio, ratio)
        cr.push_group()
        Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
        cr.paint()
        mask = cr.pop_group()
        color = self.get_style_context().get_color(self.get_state_flags())
        cr.set_source_rgba(color.red, color.green, color.blue, color.alpha)
        cr.mask(mask)
        cr.restore()
        return False

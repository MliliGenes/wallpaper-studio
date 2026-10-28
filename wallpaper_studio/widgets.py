"""GTK 3 desktop widgets, hosted by the X11 helper independently of wallpaper rendering.

The control panel uses GTK 4 in a separate process. Keep GTK versions separate.
"""
import logging
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import core, styles  # noqa: E402

log = logging.getLogger(__name__)


class Clock(Gtk.Box):
    """A widget owns its GTK subtree and updates it on the main loop."""
    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.get_style_context().add_class("desktop-clock")
        self.time_label = Gtk.Label()
        self.time_label.get_style_context().add_class("clock-time")
        self.date_label = Gtk.Label()
        self.date_label.get_style_context().add_class("clock-date")
        self.pack_start(self.time_label, False, False, 0)
        self.pack_start(self.date_label, False, False, 0)

    def update(self, config):
        now = time.localtime()
        self.time_label.set_text(time.strftime(config["clock_format"], now))
        self.date_label.set_text(time.strftime(config["clock_date_format"], now))
        self.date_label.set_visible(bool(config["clock_date_format"]))


class DesktopWidgets:
    """Transparent, click-through desktop window with live user CSS."""
    def __init__(self, is_locked):
        styles.ensure_user_styles()
        self.is_locked = is_locked
        self.config = core.load_config()
        self.window = Gtk.Window(title="Wallpaper Studio widgets")
        self.window.set_name("ws-desktop-widgets")
        self.window.get_style_context().add_class("desktop-widgets")
        self.window.set_decorated(False)
        self.window.set_resizable(False)
        self.window.set_accept_focus(False)
        self.window.set_focus_on_map(False)
        self.window.set_skip_taskbar_hint(True)
        self.window.set_skip_pager_hint(True)
        self.window.set_type_hint(Gdk.WindowTypeHint.DESKTOP)
        self.window.set_keep_below(True)
        self.window.stick()
        self.window.set_app_paintable(True)
        screen = self.window.get_screen()
        visual = screen.get_rgba_visual()
        if visual is not None:
            self.window.set_visual(visual)
        self.window.connect("realize", lambda window: window.get_window().set_pass_through(True))
        self.window.connect("size-allocate", lambda *_: self.position())
        screen.connect("monitors-changed", lambda *_: self.position())
        self.clock = Clock()
        self.window.add(self.clock)
        self.provider = None
        self.reload()
        self.timer = GLib.timeout_add_seconds(1, self.update)

    def reload(self):
        self.config = core.load_config()
        # A fresh provider prevents old rules lingering after a file is emptied or deleted.
        provider = Gtk.CssProvider()
        fallback = "@define-color ws_paper #171A21; @define-color ws_ink #F4F5F7; " \
                   "@define-color ws_muted #BAC0CE; @define-color ws_accent #91B9FF;\n"
        try:
            theme = Path(core.THEME_CSS).read_text() if Path(core.THEME_CSS).exists() else ""
            custom = Path(core.WIDGETS_CSS).read_text() if Path(core.WIDGETS_CSS).exists() else ""
            provider.load_from_data((fallback + theme + styles.DIRECTORY.joinpath("widgets.css").read_text() + custom).encode())
        except (OSError, GLib.Error) as error:
            log.warning("Cannot reload widget CSS; keeping previous style: %s", error)
            if self.provider is None:
                provider = Gtk.CssProvider()
                provider.load_from_data((fallback + styles.DIRECTORY.joinpath("widgets.css").read_text()).encode())
            else:
                provider = None
        if provider is not None:
            screen = self.window.get_screen()
            Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_USER + 2)
            if self.provider:
                Gtk.StyleContext.remove_provider_for_screen(screen, self.provider)
            self.provider = provider
        self.update()

    def position(self):
        display = self.window.get_display()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        if monitor is not None:
            area = monitor.get_workarea()
            width, _height = self.window.get_size()
            self.window.move(area.x + max(0, (area.width - width) // 2), area.y + self.config["clock_top"])

    def update(self):
        if self.config["clock"] and not self.is_locked():
            if not self.window.get_visible():
                self.window.show_all()
            self.clock.update(self.config)
            self.position()
        else:
            self.window.hide()
        return True

    def close(self):
        GLib.source_remove(self.timer)
        if self.provider:
            Gtk.StyleContext.remove_provider_for_screen(self.window.get_screen(), self.provider)
        self.window.destroy()

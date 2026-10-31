"""A small, theme-aware cover overlay for kiosk and presentation use.

This is an ordinary fullscreen window, not a session lock: it does not stop
VT switching, killing the process, or other ways around it. Use the desktop's own
lock (for example ``loginctl lock-session``) when real protection is needed.
"""
import fcntl
import hmac

import gi
gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk

from . import core
from . import storage


class LockScreen:
    def __init__(self):
        self.lock_file = open(storage.LOCKSCREEN_LOCK, "w")
        try:
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock_file.close()
            raise RuntimeError("a lock screen is already active")
        provider = Gtk.CssProvider()
        try:
            provider.load_from_path(storage.THEME_CSS)
        except GLib.Error:
            pass
        css = Gtk.CssProvider()
        css.load_from_data(b"""
        .wallpaper-lock-card { padding: 2em 3em 3em; border-radius: 1.2em; background-color: transparent; color: @ws_ink; }
        .wallpaper-lock-title { font-size: 1.2em; color: @ws_accent_text; }
        .wallpaper-lock-clock { font-size: 5em; font-weight: 300; color: @ws_accent_text; }
        .wallpaper-lock-date { font-size: 1.1em; color: @ws_ink; }
        .wallpaper-lock-avatar-frame { border-radius: 999px; min-width: 96px; min-height: 96px; margin-top: .5em; }
        .wallpaper-lock-card entry { min-width: 18em; border-radius: 999px; padding: .7em 16px; }
        """)
        screen = Gdk.Screen.get_default()
        Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        Gtk.StyleContext.add_provider_for_screen(screen, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.window.set_decorated(False)
        self.window.set_keep_above(True)
        self.window.fullscreen()
        self.window.connect("key-press-event", self.key)
        self.window.connect("delete-event", lambda *_: True)
        self.entry = Gtk.Entry(visibility=False, max_length=128)
        self.entry.set_placeholder_text("Password")
        self.entry.connect("activate", self.unlock)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                      halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        box.get_style_context().add_class("wallpaper-lock-card")
        title = Gtk.Label(label="Screen locked")
        title.get_style_context().add_class("wallpaper-lock-title")
        box.pack_start(title, False, False, 0)
        now = GLib.DateTime.new_now_local()
        clock = Gtk.Label(label=now.format("%H\n%M"))
        clock.get_style_context().add_class("wallpaper-lock-clock")
        box.pack_start(clock, False, False, 0)
        date = Gtk.Label(label=now.format("%d %b  %A"))
        date.get_style_context().add_class("wallpaper-lock-date")
        box.pack_start(date, False, False, 0)
        box.pack_start(self.entry, False, False, 0)
        overlay = Gtk.Overlay()
        state = core.load_state()
        still = state.get("still")
        if still:
            try:
                screen = Gdk.Screen.get_default()
                width, height = screen.get_width(), screen.get_height()
                _fmt, sw, sh = GdkPixbuf.Pixbuf.get_file_info(still)
                scale = max(width / sw, height / sh)
                # Blur only the display-sized frame; filtering the full source image
                # makes lock activation noticeably slow on large wallpapers.
                scaled = GdkPixbuf.Pixbuf.new_from_file_at_scale(still, width, height, True)
                image = Gtk.Image.new_from_pixbuf(scaled)
                image.set_size_request(width, height)
                image.set_halign(Gtk.Align.CENTER)
                image.set_valign(Gtk.Align.CENTER)
                overlay.add(image)
            except Exception:
                # A broken/unsupported wallpaper must never prevent the lock UI
                # from appearing; the themed card still works without its image.
                pass
        overlay.add_overlay(box)
        self.window.add(overlay)
        self.message = Gtk.Label()
        box.pack_start(self.message, False, False, 0)

    def key(self, _window, event):
        if event.keyval == Gdk.KEY_Escape:
            return True
        return False

    def unlock(self, *_args):
        expected = core.load_config().get("lock_password", "")
        if expected and hmac.compare_digest(self.entry.get_text().encode(), expected.encode()):
            self.window.hide()
            self.window.destroy()
            fcntl.flock(self.lock_file, fcntl.LOCK_UN)
            self.lock_file.close()
            Gtk.main_quit()
            return
        self.message.set_text("Incorrect password")
        self.entry.set_text("")

    def show(self):
        self.entry.grab_focus()
        self.window.show_all()


def run():
    if not core.load_config().get("lock_password"):
        return
    Gtk.init([])
    try:
        lock = LockScreen()
    except RuntimeError:
        return
    lock.show()
    Gtk.main()

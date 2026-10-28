"""The desktop helper: draws the wallpaper behind every window, and changes it on schedule.

GNOME's own desktop picture can be locked by the administrator (it is at 42), so the helper
shows the wallpaper in a desktop-level window of its own:
- pictures are decoded once at screen size and handed to the X server as the window's
  background, so the server repaints it by itself and this process keeps no image in memory;
- videos play through VLC inside the same window: silent, looping, cropped to fill the screen,
  decoded on the GPU where possible, and paused whenever nobody can see the desktop.

It wakes only when state.json changes, and once a minute for rotation and light/dark.
"""
import ctypes
import ctypes.util
import fcntl
import gc
import logging
import math
import os
import signal
import socket
import subprocess
import sys
import time

import cairo
import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

from . import core  # noqa: E402
from .awake import KeyTap  # noqa: E402
from .widgets import DesktopWidgets  # noqa: E402

VLC_SOCKET = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "wallpaper-studio-vlc.sock")

# --- just enough Xlib ---------------------------------------------------------------

X = ctypes.CDLL(ctypes.util.find_library("X11"))
XID = ctypes.c_ulong
P = ctypes.c_void_p


def _sig(name, res, *args):
    fn = getattr(X, name)
    fn.restype, fn.argtypes = res, list(args)
    return fn


XOpenDisplay = _sig("XOpenDisplay", P, ctypes.c_char_p)
XDefaultScreen = _sig("XDefaultScreen", ctypes.c_int, P)
XRootWindow = _sig("XRootWindow", XID, P, ctypes.c_int)
XDefaultDepth = _sig("XDefaultDepth", ctypes.c_int, P, ctypes.c_int)
XDefaultVisual = _sig("XDefaultVisual", P, P, ctypes.c_int)
XDisplayWidth = _sig("XDisplayWidth", ctypes.c_int, P, ctypes.c_int)
XDisplayHeight = _sig("XDisplayHeight", ctypes.c_int, P, ctypes.c_int)
XCreateSimpleWindow = _sig("XCreateSimpleWindow", XID, P, XID, ctypes.c_int, ctypes.c_int,
                           ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, ctypes.c_ulong, ctypes.c_ulong)
XInternAtom = _sig("XInternAtom", XID, P, ctypes.c_char_p, ctypes.c_int)
XChangeProperty = _sig("XChangeProperty", ctypes.c_int, P, XID, XID, XID, ctypes.c_int, ctypes.c_int,
                       P, ctypes.c_int)
XStoreName = _sig("XStoreName", ctypes.c_int, P, XID, ctypes.c_char_p)
XMapWindow = _sig("XMapWindow", ctypes.c_int, P, XID)
XUnmapWindow = _sig("XUnmapWindow", ctypes.c_int, P, XID)
XLowerWindow = _sig("XLowerWindow", ctypes.c_int, P, XID)
XMoveResizeWindow = _sig("XMoveResizeWindow", ctypes.c_int, P, XID, ctypes.c_int, ctypes.c_int,
                         ctypes.c_uint, ctypes.c_uint)
XCreatePixmap = _sig("XCreatePixmap", XID, P, XID, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint)
XFreePixmap = _sig("XFreePixmap", ctypes.c_int, P, XID)
XCreateGC = _sig("XCreateGC", P, P, XID, ctypes.c_ulong, P)
XFreeGC = _sig("XFreeGC", ctypes.c_int, P, P)
XCreateImage = _sig("XCreateImage", P, P, P, ctypes.c_uint, ctypes.c_int, ctypes.c_int, P,
                    ctypes.c_uint, ctypes.c_uint, ctypes.c_int, ctypes.c_int)
XPutImage = _sig("XPutImage", ctypes.c_int, P, XID, P, P, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                 ctypes.c_int, ctypes.c_uint, ctypes.c_uint)
XFree = _sig("XFree", ctypes.c_int, P)
XSetWindowBackgroundPixmap = _sig("XSetWindowBackgroundPixmap", ctypes.c_int, P, XID, XID)
XClearWindow = _sig("XClearWindow", ctypes.c_int, P, XID)
XFlush = _sig("XFlush", ctypes.c_int, P)
XSync = _sig("XSync", ctypes.c_int, P, ctypes.c_int)
XPending = _sig("XPending", ctypes.c_int, P)
XNextEvent = _sig("XNextEvent", ctypes.c_int, P, P)
XConnectionNumber = _sig("XConnectionNumber", ctypes.c_int, P)
XGetWindowProperty = _sig("XGetWindowProperty", ctypes.c_int, P, XID, XID, ctypes.c_long, ctypes.c_long,
                          ctypes.c_int, XID, ctypes.POINTER(XID), ctypes.POINTER(ctypes.c_int),
                          ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
                          ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)))


class XClientMessageEvent(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
                ("display", P), ("window", XID), ("message_type", XID), ("format", ctypes.c_int),
                ("data", ctypes.c_long * 5)]


class XPropertyEvent(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
                ("display", P), ("window", XID), ("atom", XID), ("time", ctypes.c_ulong), ("state", ctypes.c_int)]


class XEvent(ctypes.Union):
    _fields_ = [("type", ctypes.c_int), ("xclient", XClientMessageEvent), ("xproperty", XPropertyEvent),
                ("pad", ctypes.c_long * 24)]


XSendEvent = _sig("XSendEvent", ctypes.c_int, P, XID, ctypes.c_int, ctypes.c_long, ctypes.POINTER(XEvent))
XSelectInput = _sig("XSelectInput", ctypes.c_int, P, XID, ctypes.c_long)
CLIENT_MESSAGE = 33
PROPERTY_NOTIFY = 28
PROPERTY_CHANGE_MASK = 1 << 22
SUBSTRUCTURE_MASKS = (1 << 19) | (1 << 20)   # SubstructureNotify | SubstructureRedirect
ZPIXMAP = 2
XA_ATOM, XA_CARDINAL = 4, 6
PROP_REPLACE = 0


def die_with_parent():
    """Runs in the VLC child: if the helper goes away, so does the player."""
    try:
        ctypes.CDLL("libc.so.6").prctl(1, signal.SIGTERM)   # PR_SET_PDEATHSIG
    except OSError:
        pass


def release_memory():
    gc.collect()
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except OSError:
        pass


def render_cover(path, width, height):
    """Decode only as many pixels as the screen needs, centre-cropped, as native 32-bit BGRX."""
    _fmt, src_w, src_h = GdkPixbuf.Pixbuf.get_file_info(path)
    if not src_w or not src_h:
        return None
    k = max(width / src_w, height / src_h)
    w, h = max(width, round(src_w * k)), max(height, round(src_h * k))
    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, w, h, False)
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, width, height)
    cr = cairo.Context(surface)
    Gdk.cairo_set_source_pixbuf(cr, pixbuf, -((w - width) // 2), -((h - height) // 2))
    cr.paint()
    del cr, pixbuf
    surface.flush()
    return surface


class Desktop:
    def __init__(self):
        self.dpy = XOpenDisplay(None)
        if not self.dpy:
            raise SystemExit("wallpaper-studio: no X display (Wayland sessions aren't supported)")
        self.screen = XDefaultScreen(self.dpy)
        self.root = XRootWindow(self.dpy, self.screen)
        self.depth = XDefaultDepth(self.dpy, self.screen)
        self.visual = XDefaultVisual(self.dpy, self.screen)
        self.win = None
        self.shown = None
        self.mapped = False
        self.player = None
        self.video = None
        self.paused = False
        self.pending = 0
        self.busy = None             # a rotation or light/dark change running in the background
        self.inhibit_cookie = None   # held while "keep screen awake" is on
        self.awake_timer = 0
        self.pulse_timer = 0
        self.key_tap = None
        self.awake_signature = None
        self.warned_session = False
        try:
            self.session = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SYSTEM, Gio.DBusProxyFlags.NONE, None, "org.freedesktop.login1",
                "/org/freedesktop/login1/session/auto", "org.freedesktop.login1.Session", None)
        except GLib.Error:
            self.session = None

        self.widgets = DesktopWidgets(self.session_locked)

        os.makedirs(core.CONFIG_DIR, exist_ok=True)
        self.monitor = Gio.File.new_for_path(core.CONFIG_DIR).monitor_directory(Gio.FileMonitorFlags.NONE, None)
        self.monitor.connect("changed", self.on_change)
        self.awake_monitor = Gio.File.new_for_path(core.AWAKE).monitor_file(Gio.FileMonitorFlags.NONE, None)
        self.awake_monitor.connect("changed", lambda *_: GLib.timeout_add(200, self.sync_awake))
        GLib.idle_add(self.sync_awake)
        # the desktop-icons extension lowers its window under everything whenever any window (even a
        # tooltip) opens or closes, which hides the icons under the wallpaper; watch the stacking order
        # and step back under the icons the moment that happens, instead of on the next poll
        self.stacking = self.atom("_NET_CLIENT_LIST_STACKING")
        self.restacks = []           # recent restack times, to back off if something fights back
        self.restack_pending = 0
        XSelectInput(self.dpy, self.root, PROPERTY_CHANGE_MASK)
        GLib.io_add_watch(XConnectionNumber(self.dpy), GLib.IO_IN, self.drain)
        GLib.idle_add(self.refresh)
        GLib.timeout_add_seconds(2, self.watch_video)
        GLib.timeout_add_seconds(60, self.tick)
        GLib.idle_add(lambda: self.tick() and False)     # once at start; an idle that returns True spins

    def drain(self, *_):
        ev = XEvent()
        while XPending(self.dpy):
            XNextEvent(self.dpy, ctypes.byref(ev))
            if ev.type == PROPERTY_NOTIFY and ev.xproperty.atom == self.stacking and not self.restack_pending:
                self.restack_pending = GLib.idle_add(self.on_restacked)
        return True

    def on_restacked(self):
        self.restack_pending = 0
        now = time.monotonic()
        self.restacks = [t for t in self.restacks if now - t < 2]
        if len(self.restacks) < 10:      # more than that in 2 s means a fight: leave it to the 2 s check
            if self.stay_at_bottom():
                self.restacks.append(now)
        return False

    def on_change(self, _monitor, file, _other, _event):
        if file.get_basename() not in ("state.json", "config.json", "theme.css", "widgets.css"):
            return
        # a change arrives as several file events; act once they settle
        if self.pending:
            GLib.source_remove(self.pending)
        self.pending = GLib.timeout_add(300, self.sync)

    def sync(self):
        self.pending = 0
        self.widgets.reload()
        self.sync_awake()
        self.refresh()
        self.tick()
        return False

    # --- keep screen awake -----------------------------------------------------------------

    def sync_awake(self):
        """Hold GNOME's idle inhibitor exactly while "keep screen awake" is on; release it when it ends."""
        until = core.awake_until()
        config = core.load_config()
        signature = (until, config["awake_method"], config["awake_interval"])
        if signature == self.awake_signature:
            return False
        self.awake_signature = signature
        if self.awake_timer:
            GLib.source_remove(self.awake_timer)
            self.awake_timer = 0
        if self.pulse_timer:
            GLib.source_remove(self.pulse_timer)
            self.pulse_timer = 0
        if until is None:
            self.uninhibit()
            return False
        self.inhibit()
        if config["awake_method"] == "key":
            if self.key_tap is None:
                self.key_tap = KeyTap(self.dpy)
            if self.key_tap.available:
                if (self.session is None or self.session.get_cached_property("Active") is None
                        or self.session.get_cached_property("LockedHint") is None) and not self.warned_session:
                    logging.getLogger(__name__).warning("Cannot confirm session lock state; key taps disabled until logind reports it")
                    self.warned_session = True
                self.pulse_timer = GLib.timeout_add_seconds(config["awake_interval"], self.pulse_awake)
                self.pulse_awake()
        if until != core.FOREVER:
            self.awake_timer = GLib.timeout_add_seconds(max(1, int(until - time.time()) + 1), self.sync_awake)
        return False

    def pulse_awake(self):
        if core.awake_until() is None:
            self.pulse_timer = 0
            return False
        # Require a known active, unlocked session before sending input.
        # Logind's Active flag alone does not mean the screen is unlocked.
        if self.session is not None:
            active = self.session.get_cached_property("Active")
            locked = self.session.get_cached_property("LockedHint")
            if active is not None and active.unpack() and locked is not None and not locked.unpack():
                self.key_tap.pulse()
        return True

    def session_manager(self):
        return Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SESSION, Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES, None, "org.gnome.SessionManager",
            "/org/gnome/SessionManager", "org.gnome.SessionManager", None)

    def inhibit(self):
        if self.inhibit_cookie is not None:
            return
        try:
            # flag 8 = "idle": the session isn't marked idle, so the screen doesn't blank or lock by itself.
            # GNOME drops it on its own if this process ever goes away.
            reply = self.session_manager().call_sync(
                "Inhibit", GLib.Variant("(susu)", ("io.github.WallpaperStudio", 0, "Keeping the screen awake", 8)),
                Gio.DBusCallFlags.NONE, -1, None)
            self.inhibit_cookie = reply.unpack()[0]
        except GLib.Error as error:
            logging.getLogger(__name__).warning("GNOME idle inhibition failed: %s", error)
            self.inhibit_cookie = None

    def uninhibit(self):
        if self.inhibit_cookie is None:
            return
        try:
            self.session_manager().call_sync("Uninhibit", GLib.Variant("(u)", (self.inhibit_cookie,)),
                                             Gio.DBusCallFlags.NONE, -1, None)
        except GLib.Error:
            pass
        self.inhibit_cookie = None

    # --- schedule ----------------------------------------------------------------------

    def tick(self):
        """Once a minute: time for the next wallpaper, or for light/dark to flip?"""
        if self.busy is not None and self.busy.poll() is None:
            return True
        config, state = core.load_config(), core.load_state()
        hours = config["rotate_hours"]
        # rotation counts from the last change; nothing chosen yet means nothing to rotate from
        if hours and state.get("changed") and time.time() - state["changed"] >= hours * 3600:
            self.run("next")
        elif state.get("palette") and state.get("mode") != core.effective_mode(config):
            self.run("apply")
        return True

    def run(self, command):
        # in a child process: a video's still frame can take a few seconds to read
        self.busy = subprocess.Popen([sys.executable, "-m", "wallpaper_studio", command],
                                     cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # --- the desktop window ------------------------------------------------------------

    def atom(self, name):
        return XInternAtom(self.dpy, name.encode(), 0)

    def set_atoms(self, prop, names, kind=XA_ATOM):
        vals = (ctypes.c_long * len(names))(*[self.atom(n) if isinstance(n, str) else n for n in names])
        XChangeProperty(self.dpy, self.win, self.atom(prop), kind, 32, PROP_REPLACE,
                        ctypes.cast(vals, P), len(names))

    def ensure_window(self, width, height):
        if self.win is None:
            self.win = XCreateSimpleWindow(self.dpy, self.root, 0, 0, width, height, 0, 0, 0)
            XStoreName(self.dpy, self.win, b"wallpaper-studio")
            self.set_atoms("_NET_WM_WINDOW_TYPE", ["_NET_WM_WINDOW_TYPE_DESKTOP"])
            self.set_atoms("_NET_WM_STATE", ["_NET_WM_STATE_STICKY", "_NET_WM_STATE_BELOW",
                                             "_NET_WM_STATE_SKIP_TASKBAR", "_NET_WM_STATE_SKIP_PAGER"])
            self.set_atoms("_NET_WM_DESKTOP", [0xFFFFFFFF], XA_CARDINAL)
        else:
            XMoveResizeWindow(self.dpy, self.win, 0, 0, width, height)

    def refresh(self):
        self.pending = 0
        state = core.load_state()
        target, still = state.get("wallpaper"), state.get("still")
        width, height = XDisplayWidth(self.dpy, self.screen), XDisplayHeight(self.dpy, self.screen)
        if target and not os.path.exists(target):
            target = None
        if (target, still, width, height) == self.shown:
            return False
        self.shown = (target, still, width, height)

        if target is None:
            self.stop_video()
            if self.win is not None and self.mapped:
                XUnmapWindow(self.dpy, self.win)
                self.mapped = False
                XFlush(self.dpy)
            return False

        if core.is_video(target):
            if still and os.path.exists(still):
                self.show_picture(still, width, height)      # the still as a poster while VLC starts
            else:
                self.ensure_window(width, height)
                self.map_lowered()
            self.start_video(target, width, height)
        else:
            self.stop_video()
            self.show_picture(target, width, height)
        return False

    def map_lowered(self):
        if not self.mapped:
            XMapWindow(self.dpy, self.win)
            self.mapped = True
        XLowerWindow(self.dpy, self.win)
        XSync(self.dpy, 0)
        self.stay_at_bottom()

    def stay_at_bottom(self):
        """Keep under the other desktop windows (desktop icons): ask the window manager to restack.

        XLowerWindow alone isn't enough once VLC attaches to the window and raises it."""
        if self.win is None or not self.mapped:
            return False
        stack = [w for w in self.window_atoms(self.root, "_NET_CLIENT_LIST_STACKING") if w]
        if not stack or stack[0] == self.win:
            return False
        desktop = self.atom("_NET_WM_WINDOW_TYPE_DESKTOP")
        others = [w for w in stack if w != self.win and desktop in self.window_atoms(w, "_NET_WM_WINDOW_TYPE")]
        if not others:
            return False
        ev = XEvent()
        m = ev.xclient
        m.type, m.send_event, m.display, m.window = CLIENT_MESSAGE, 1, self.dpy, self.win
        m.message_type, m.format = self.atom("_NET_RESTACK_WINDOW"), 32
        m.data[0], m.data[1], m.data[2] = 2, others[0], 1          # from a pager, below the lowest one
        XSendEvent(self.dpy, self.root, 0, SUBSTRUCTURE_MASKS, ctypes.byref(ev))
        XFlush(self.dpy)
        return True

    def show_picture(self, path, width, height):
        try:
            surface = render_cover(path, width, height)
        except GLib.Error:
            return
        if surface is None:
            return
        self.ensure_window(width, height)

        # upload with plain XPutImage (no shared-memory buffer left behind), then let go
        data = surface.get_data()
        buf = (ctypes.c_char * len(data)).from_buffer(data)
        image = XCreateImage(self.dpy, self.visual, self.depth, ZPIXMAP, 0, ctypes.cast(buf, P),
                             width, height, 32, surface.get_stride())
        pixmap = XCreatePixmap(self.dpy, self.win, width, height, self.depth)
        gc_ = XCreateGC(self.dpy, pixmap, 0, None)
        XPutImage(self.dpy, pixmap, gc_, image, 0, 0, 0, 0, width, height)
        XFreeGC(self.dpy, gc_)
        XFree(image)                      # the struct only; the pixels belong to the cairo surface
        XSetWindowBackgroundPixmap(self.dpy, self.win, pixmap)
        XFreePixmap(self.dpy, pixmap)     # the window keeps its own reference on the server
        XClearWindow(self.dpy, self.win)
        self.map_lowered()
        del buf, data
        surface.finish()
        del surface
        release_memory()

    # --- video ---------------------------------------------------------------------------

    def start_video(self, path, width, height):
        self.stop_video()
        g = math.gcd(width, height)
        try:
            os.unlink(VLC_SOCKET)
        except OSError:
            pass
        try:
            self.player = subprocess.Popen(
                ["cvlc", "--intf", "dummy", "--extraintf", "oldrc", "--rc-unix", VLC_SOCKET, "--rc-fake-tty",
                 "--no-audio", "--loop", "--no-video-title-show", "--no-osd", "--no-spu", "--no-dbus",
                 "--no-mouse-events", "--no-keyboard-events", "--avcodec-hw", "any",
                 "--crop", f"{width // g}:{height // g}", "--drawable-xid", str(self.win), path],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                preexec_fn=die_with_parent)
        except OSError:          # no VLC: the still stays up
            return
        self.video, self.paused = path, False
        GLib.timeout_add(1500, lambda: self.stay_at_bottom() and False)   # after VLC has attached

    def stop_video(self):
        if self.player and self.player.poll() is None:
            self.player.terminate()
            try:
                self.player.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.player.kill()
        self.player = self.video = None

    def tell_vlc(self, command):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(1)
                sock.connect(VLC_SOCKET)
                sock.sendall(command.encode() + b"\n")
            return True
        except OSError:
            return False

    def watch_video(self):
        """Every couple of seconds: pause while nobody can see the desktop, resume when they can."""
        if self.player is None:
            return True
        if self.player.poll() is not None:          # the player died: start it again
            width, height = XDisplayWidth(self.dpy, self.screen), XDisplayHeight(self.dpy, self.screen)
            self.start_video(self.video, width, height)
            return True
        self.stay_at_bottom()
        hidden = self.desktop_covered() or self.session_locked()
        if hidden and not self.paused and self.tell_vlc("pause"):
            self.paused = True
        elif not hidden and self.paused and self.tell_vlc("pause"):   # VLC's pause toggles
            self.paused = False
        return True

    def session_locked(self):
        if not self.session:
            return False
        active = self.session.get_cached_property("Active")
        locked = self.session.get_cached_property("LockedHint")
        return bool((active is not None and not active.unpack()) or (locked is not None and locked.unpack()))

    def close(self):
        self.stop_video()
        self.uninhibit()
        self.widgets.close()

    def window_atoms(self, window, prop):
        actual, fmt = XID(), ctypes.c_int()
        n, after = ctypes.c_ulong(), ctypes.c_ulong()
        data = ctypes.POINTER(ctypes.c_ubyte)()
        ok = XGetWindowProperty(self.dpy, window, self.atom(prop), 0, 64, 0, 0, ctypes.byref(actual),
                                ctypes.byref(fmt), ctypes.byref(n), ctypes.byref(after), ctypes.byref(data))
        if ok != 0 or not data:
            return []
        values = [ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))[i] for i in range(n.value)] if fmt.value == 32 else []
        XFree(ctypes.cast(data, P))
        return values

    def desktop_covered(self):
        """The focused window fills the screen (maximised or fullscreen)."""
        active = self.window_atoms(self.root, "_NET_ACTIVE_WINDOW")
        if not active or not active[0]:
            return False
        state = set(self.window_atoms(active[0], "_NET_WM_STATE"))
        if self.atom("_NET_WM_STATE_HIDDEN") in state:
            return False
        if self.atom("_NET_WM_STATE_FULLSCREEN") in state:
            return True
        return {self.atom("_NET_WM_STATE_MAXIMIZED_VERT"), self.atom("_NET_WM_STATE_MAXIMIZED_HORZ")} <= state


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not Gtk.init_check()[0]:
        raise SystemExit("wallpaper-studio: no GTK X11 display")
    lock = open(core.HELPER_LOCK, "a")
    for _ in range(50):   # a helper that is just shutting down (an update) may still hold it briefly
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            time.sleep(0.1)
    else:
        return 0          # another helper is running
    desktop = Desktop()
    loop = GLib.MainLoop()
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: (loop.quit(), False)[1])
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, lambda: (loop.quit(), False)[1])
    try:
        loop.run()
    finally:
        desktop.close()
    return 0

"""Optional X11 activity pulses. No shell commands, typed characters or pointer movement."""
import ctypes
import ctypes.util
import logging

log = logging.getLogger(__name__)


class KeyTap:
    """Tap F15 through XTEST, skipping pulses while any physical key is held."""
    def __init__(self, display):
        self.display = display
        self.available = False
        try:
            library = ctypes.util.find_library("Xtst")
            if library is None:
                raise OSError("libXtst is unavailable")
            self.xtst = ctypes.CDLL(library)
            self.x11 = ctypes.CDLL(ctypes.util.find_library("X11"))
            self.x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            self.x11.XKeysymToKeycode.restype = ctypes.c_ubyte
            self.x11.XQueryKeymap.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            self.x11.XQueryKeymap.restype = ctypes.c_int
            self.x11.XFlush.argtypes = [ctypes.c_void_p]
            self.x11.XFlush.restype = ctypes.c_int
            self.xtst.XTestQueryExtension.argtypes = [ctypes.c_void_p] + [ctypes.POINTER(ctypes.c_int)] * 4
            self.xtst.XTestQueryExtension.restype = ctypes.c_int
            self.xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
            self.xtst.XTestFakeKeyEvent.restype = ctypes.c_int
            values = [ctypes.c_int() for _ in range(4)]
            if not self.xtst.XTestQueryExtension(display, *(ctypes.byref(v) for v in values)):
                raise OSError("XTEST extension is unavailable")
            self.keycode = self.x11.XKeysymToKeycode(display, 0xFFCC)  # XK_F15
            if not self.keycode:
                raise OSError("F15 has no keycode in this keyboard layout")
            self.available = True
        except (OSError, AttributeError) as error:
            log.warning("Keep-awake key mode unavailable: %s; using GNOME inhibition only", error)

    def pulse(self):
        if not self.available:
            return False
        keys = ctypes.create_string_buffer(32)
        self.x11.XQueryKeymap(self.display, keys)
        if any(keys.raw):
            return False
        pressed = self.xtst.XTestFakeKeyEvent(self.display, self.keycode, 1, 0)
        released = self.xtst.XTestFakeKeyEvent(self.display, self.keycode, 0, 0)
        self.x11.XFlush(self.display)
        return bool(pressed and released)

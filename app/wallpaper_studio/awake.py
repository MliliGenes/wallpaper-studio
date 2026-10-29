"""Optional X11 mouse activity: save the pointer, move to the origin and restore it."""
import ctypes
import ctypes.util
import logging

log = logging.getLogger(__name__)


class MouseMotion:
    """An XTEST pointer round trip, skipped while keys or mouse buttons are held."""
    def __init__(self, display):
        self.display = display
        self.available = False
        try:
            library = ctypes.util.find_library("Xtst")
            if library is None:
                raise OSError("libXtst is unavailable")
            self.xtst = ctypes.CDLL(library)
            self.x11 = ctypes.CDLL(ctypes.util.find_library("X11"))
            self.x11.XDefaultScreen.argtypes = [ctypes.c_void_p]
            self.x11.XDefaultScreen.restype = ctypes.c_int
            self.x11.XRootWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
            self.x11.XRootWindow.restype = ctypes.c_ulong
            self.x11.XQueryPointer.argtypes = [ctypes.c_void_p, ctypes.c_ulong,
                                              ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
                                              *([ctypes.POINTER(ctypes.c_int)] * 4), ctypes.POINTER(ctypes.c_uint)]
            self.x11.XQueryPointer.restype = ctypes.c_int
            self.x11.XQueryKeymap.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            self.x11.XQueryKeymap.restype = ctypes.c_int
            self.x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
            self.x11.XSync.restype = ctypes.c_int
            self.x11.XWarpPointer.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong,
                                             ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint,
                                             ctypes.c_int, ctypes.c_int]
            self.x11.XWarpPointer.restype = ctypes.c_int
            self.xtst.XTestQueryExtension.argtypes = [ctypes.c_void_p] + [ctypes.POINTER(ctypes.c_int)] * 4
            self.xtst.XTestQueryExtension.restype = ctypes.c_int
            self.xtst.XTestFakeMotionEvent.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
            self.xtst.XTestFakeMotionEvent.restype = ctypes.c_int
            values = [ctypes.c_int() for _ in range(4)]
            if not self.xtst.XTestQueryExtension(display, *(ctypes.byref(v) for v in values)):
                raise OSError("XTEST extension is unavailable")
            self.screen = self.x11.XDefaultScreen(display)
            self.root = self.x11.XRootWindow(display, self.screen)
            self.available = True
        except (OSError, AttributeError) as error:
            log.warning("Keep-awake mouse mode unavailable: %s; using GNOME inhibition only", error)

    def pulse(self):
        if not self.available:
            return False
        keys = ctypes.create_string_buffer(32)
        if not self.x11.XQueryKeymap(self.display, keys) or any(keys.raw):
            return False
        root, child = ctypes.c_ulong(), ctypes.c_ulong()
        x, y, window_x, window_y = (ctypes.c_int() for _ in range(4))
        mask = ctypes.c_uint()
        if not self.x11.XQueryPointer(self.display, self.root, ctypes.byref(root), ctypes.byref(child),
                                      ctypes.byref(x), ctypes.byref(y), ctypes.byref(window_x),
                                      ctypes.byref(window_y), ctypes.byref(mask)):
            return False
        if mask.value & 0x1F00:  # Button1Mask .. Button5Mask: never move during a drag
            return False
        # At (0, 0), make a one-pixel excursion so an actual movement still occurs.
        target_x = 1 if x.value == 0 and y.value == 0 else 0
        try:
            moved = self.xtst.XTestFakeMotionEvent(self.display, self.screen, target_x, 0, 0)
        finally:
            restored = self.xtst.XTestFakeMotionEvent(self.display, self.screen, x.value, y.value, 0)
            if not restored:
                self.x11.XWarpPointer(self.display, 0, self.root, 0, 0, 0, 0, x.value, y.value)
            self.x11.XSync(self.display, False)
        if not restored:
            log.warning("XTEST restoration failed; used XWarpPointer to return to (%s, %s)", x.value, y.value)
        return bool(moved and restored)

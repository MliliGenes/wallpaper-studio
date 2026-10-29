"""MPRIS provider. D-Bus work stays off the GTK thread; imports remain headless."""
import threading

PREFIX = "org.mpris.MediaPlayer2."
PLAYER = PREFIX + "Player"
PATH = "/org/mpris/MediaPlayer2"


def select_player(players, previous=None):
    """Prefer playing media, retaining the current player among equal candidates."""
    return min(players, key=lambda p: (
        {"Playing": 0, "Paused": 1}.get(p["properties"].get("PlaybackStatus"), 2),
        p["owner"] != previous, p["name"],
    ), default=None)


def can_control(player, method):
    props = player["properties"] if player else {}
    capability = {"Previous": "CanGoPrevious", "Next": "CanGoNext",
                  "PlayPause": "CanPause" if props.get("PlaybackStatus") == "Playing" else "CanPlay"}
    return bool(props.get("CanControl") and props.get(capability.get(method, "")))


class MprisBus:
    def __init__(self):
        from gi.repository import Gio, GLib
        self.Gio, self.GLib = Gio, GLib
        self.cancel = Gio.Cancellable()
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, self.cancel)

    def call(self, destination, path, interface, method, signature=None, args=()):
        parameters = self.GLib.Variant(signature, args) if signature else None
        return self.bus.call_sync(destination, path, interface, method, parameters, None,
                                  self.Gio.DBusCallFlags.NO_AUTO_START, 1500, self.cancel).unpack()

    def players(self):
        names = self.call("org.freedesktop.DBus", "/org/freedesktop/DBus",
                          "org.freedesktop.DBus", "ListNames")[0]
        result = []
        for name in sorted(n for n in names if n.startswith(PREFIX)):
            if self.cancel.is_cancelled():
                break
            try:
                owner = self.call("org.freedesktop.DBus", "/org/freedesktop/DBus",
                                  "org.freedesktop.DBus", "GetNameOwner", "(s)", (name,))[0]
                props = self.call(owner, PATH, "org.freedesktop.DBus.Properties",
                                  "GetAll", "(s)", (PLAYER,))[0]
                result.append(dict(name=name, owner=owner, properties=props))
            except self.GLib.Error:
                # Players may exit during discovery; one failure must not hide the others.
                continue
        return result

    def command(self, owner, method):
        self.call(owner, PATH, PLAYER, method)

    def close(self):
        self.cancel.cancel()


class NowPlayingModel:
    def __init__(self, backend_factory=MprisBus):
        self._factory = backend_factory
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._closed = threading.Event()
        self._backend = None
        self._player = None
        self._error = ""
        self._pending = None
        self._busy = False
        self._thread = None

    def view(self):
        if self._thread is None and not self._closed.is_set():
            self._thread = threading.Thread(target=self._run, daemon=True, name="now-playing")
            self._thread.start()
        with self._lock:
            return self._player, self._error, self._busy

    def control(self, method):
        with self._lock:
            if self._closed.is_set() or self._busy or not can_control(self._player, method):
                return
            self._pending = (self._player["owner"], method)
            self._busy = True
        self._wake.set()

    def _run(self):
        while not self._closed.is_set():
            self._wake.clear()
            try:
                if self._backend is None:
                    backend = self._factory()
                    with self._lock:
                        self._backend = backend
                        if self._closed.is_set():
                            backend.close()
                            return
                with self._lock:
                    pending, self._pending = self._pending, None
                    previous = self._player["owner"] if self._player else None
                if pending and not self._closed.is_set():
                    self._backend.command(*pending)
                players = self._backend.players()
                with self._lock:
                    self._player = select_player(players, previous)
                    self._error = ""
            except Exception:
                with self._lock:
                    self._player = None
                    self._error = "Media player unavailable"
            finally:
                with self._lock:
                    self._busy = self._pending is not None
            self._wake.wait(1)

    def close(self):
        self._closed.set()
        with self._lock:
            self._pending = None
            if self._backend is not None:
                self._backend.close()
        self._wake.set()

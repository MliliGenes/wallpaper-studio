"""Bounded artwork loading, independent of GTK and playback controls."""
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit, unquote
from urllib.request import Request, urlopen

MAX_BYTES = 5 * 1024 * 1024


def fetch_artwork(url):
    parsed = urlsplit(url)
    if parsed.scheme == "file" and parsed.netloc in ("", "localhost"):
        path = Path(unquote(parsed.path))
        if not path.is_file() or path.stat().st_size > MAX_BYTES:
            return None
        stream = path.open("rb")
    elif parsed.scheme in ("http", "https"):
        stream = urlopen(Request(url, headers={"User-Agent": "WallpaperStudio/1.0"}), timeout=4)
    else:
        return None
    with stream:
        data = stream.read(MAX_BYTES + 1)
    return data if 0 < len(data) <= MAX_BYTES else None


class ArtworkModel:
    def __init__(self, fetch=fetch_artwork):
        self.fetch = fetch
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._closed = threading.Event()
        self._url = ""
        self._data = None
        self._retry_at = 0
        self._thread = None

    def view(self, url):
        url = url if isinstance(url, str) else ""
        with self._lock:
            if self._closed.is_set():
                return None
            if url != self._url:
                self._url, self._data, self._retry_at = url, None, 0
            if url and self._data is None and time.monotonic() >= self._retry_at:
                self._retry_at = float("inf")
                self._wake.set()
                if self._thread is None:
                    self._thread = threading.Thread(target=self._run, daemon=True, name="media-artwork")
                    self._thread.start()
            return self._data

    def _run(self):
        while not self._closed.is_set():
            self._wake.wait()
            self._wake.clear()
            with self._lock:
                url = self._url
            if self._closed.is_set():
                return
            try:
                data = self.fetch(url) if url else None
            except Exception:
                data = None
            with self._lock:
                if url == self._url and not self._closed.is_set():
                    self._data = data
                    self._retry_at = time.monotonic() + 30

    def close(self):
        self._closed.set()
        self._wake.set()

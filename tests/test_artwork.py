import tempfile
import threading
import time
import unittest
from pathlib import Path

from wallpaper_studio.artwork import ArtworkModel, MAX_BYTES, fetch_artwork


class ArtworkTests(unittest.TestCase):
    def test_local_file_and_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cover art.png'
            path.write_bytes(b'picture')
            self.assertEqual(fetch_artwork(path.as_uri()), b'picture')
            path.write_bytes(b'x' * (MAX_BYTES + 1))
            self.assertIsNone(fetch_artwork(path.as_uri()))
        self.assertIsNone(fetch_artwork('ftp://example.com/cover.png'))
        self.assertIsNone(fetch_artwork('file://remote/cover.png'))

    def test_track_change_discards_late_artwork_and_caches_current(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        def fetch(url):
            calls.append(url)
            if url == 'old':
                entered.set()
                release.wait(2)
            return url.encode()
        model = ArtworkModel(fetch)
        self.addCleanup(model.close)
        self.assertIsNone(model.view('old'))
        self.assertTrue(entered.wait(1))
        self.assertIsNone(model.view('new'))
        release.set()
        deadline = time.monotonic() + 2
        while model.view('new') is None and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(model.view('new'), b'new')
        self.assertEqual(calls, ['old', 'new'])
        self.assertIsNone(model.view(''))
        model.close()
        model._thread.join(1)
        self.assertFalse(model._thread.is_alive())

    def test_failure_does_not_retry_each_render(self):
        attempted = threading.Event()
        calls = []
        def fetch(url):
            calls.append(url)
            attempted.set()
            raise OSError('unavailable')
        model = ArtworkModel(fetch)
        self.addCleanup(model.close)
        model.view('missing')
        self.assertTrue(attempted.wait(1))
        for _ in range(10):
            self.assertIsNone(model.view('missing'))
        self.assertEqual(calls, ['missing'])

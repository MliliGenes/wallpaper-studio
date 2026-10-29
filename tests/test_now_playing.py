import threading
import time
import unittest

from wallpaper_studio.components import component_scope, resolve
from wallpaper_studio.now_playing import NowPlayingModel, can_control, select_player
from wallpaper_studio.widgets.now_playing import NowPlaying


def player(name="test", status="Playing", **props):
    return dict(name="org.mpris.MediaPlayer2." + name, owner=":" + name,
                properties=dict(PlaybackStatus=status, CanControl=True, CanPlay=True,
                                CanPause=True, CanGoNext=True, **props))


class NowPlayingTests(unittest.TestCase):
    def test_selection_prefers_playing_and_stays_stable(self):
        paused, playing, other = player("a", "Paused"), player("b"), player("c")
        self.assertIs(select_player([paused, playing], paused["owner"]), playing)
        self.assertIs(select_player([other, playing], other["owner"]), other)
        self.assertIsNone(select_player([]))

    def test_capabilities_and_read_only_players(self):
        current = player()
        self.assertTrue(can_control(current, "PlayPause"))
        self.assertFalse(can_control(current, "Previous"))
        current["properties"]["CanPause"] = False
        self.assertFalse(can_control(current, "PlayPause"))
        current["properties"]["PlaybackStatus"] = "Paused"
        self.assertTrue(can_control(current, "PlayPause"))
        current["properties"]["CanControl"] = False
        self.assertFalse(can_control(current, "Next"))
        self.assertFalse(can_control(None, "PlayPause"))
        self.assertFalse(can_control(player(), "Invalid"))

    def test_component_metadata_empty_state_and_controls(self):
        class Model:
            def view(self):
                return player(Metadata={"xesam:title": "Song", "xesam:artist": ["A", "B"],
                                        "xesam:album": "Album"}), "", False
            def control(self, method):
                self.method = method
        model = Model()
        with component_scope({"now-playing": model}):
            tree = resolve(NowPlaying(config={}))
        self.assertEqual(tree.children[2].props["text"], "Song")
        self.assertEqual(tree.children[3].props["text"], "A, B")
        buttons = tree.children[5].children
        self.assertFalse(buttons[0].props["sensitive"])
        self.assertEqual(buttons[1].props["icon"], "pause")
        self.assertEqual(buttons[1].props["tooltip"], "Pause")
        buttons[2].props["on_click"]()
        self.assertEqual(model.method, "Next")
        model.view = lambda: (None, "", False)
        with component_scope({"now-playing": model}):
            tree = resolve(NowPlaying(config={}))
        self.assertEqual(tree.children[2].props["text"], "Nothing playing")
        self.assertTrue(all(not b.props["sensitive"] for b in tree.children[5].children))

    def test_worker_commands_disappearance_and_close(self):
        class Bus:
            def __init__(self):
                self.items = [player()]
                self.calls = []
                self.closed = False
            def players(self):
                return self.items
            def command(self, *args):
                self.calls.append(args)
            def close(self):
                self.closed = True
        bus = Bus()
        model = NowPlayingModel(lambda: bus)
        self.addCleanup(model.close)
        def wait_for(predicate):
            deadline = time.monotonic() + 2
            while not predicate() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(predicate())
        model.view()
        wait_for(lambda: model.view()[0] is not None)
        model.control("Next")
        wait_for(lambda: bool(bus.calls))
        self.assertEqual(bus.calls, [(":test", "Next")])
        bus.items = []
        model._wake.set()
        wait_for(lambda: model.view()[0] is None)
        model.close()
        model._thread.join(2)
        self.assertFalse(model._thread.is_alive())
        self.assertTrue(bus.closed)

    def test_close_during_connection_cancels_new_backend(self):
        entered, release, cancelled = threading.Event(), threading.Event(), threading.Event()
        class Bus:
            def close(self):
                cancelled.set()
        def connect():
            entered.set()
            release.wait(2)
            return Bus()
        model = NowPlayingModel(connect)
        model.view()
        self.assertTrue(entered.wait(1))
        model.close()
        release.set()
        model._thread.join(2)
        self.assertTrue(cancelled.is_set())
        self.assertFalse(model._thread.is_alive())


if __name__ == "__main__":
    unittest.main()

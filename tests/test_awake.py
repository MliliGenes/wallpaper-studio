import unittest
from unittest.mock import Mock, patch

from wallpaper_studio.awake import MouseMotion


class MouseMotionTests(unittest.TestCase):
    def make_tap(self):
        tap = MouseMotion.__new__(MouseMotion)
        tap.available, tap.display, tap.screen, tap.root = True, 123, 0, 456
        tap.x11, tap.xtst = Mock(), Mock()
        tap.x11.XQueryKeymap.return_value = 1
        def pointer(*args):
            args[4]._obj.value = 800
            args[5]._obj.value = 450
            return 1
        tap.x11.XQueryPointer.side_effect = pointer
        return tap

    def test_mouse_moves_to_origin_and_returns_to_saved_position(self):
        tap = self.make_tap()
        self.assertTrue(tap.pulse())
        self.assertEqual([c.args for c in tap.xtst.XTestFakeMotionEvent.call_args_list],
                         [(123, 0, 0, 0, 0), (123, 0, 800, 450, 0)])

    def test_held_keys_suppress_input(self):
        tap = self.make_tap()
        tap.x11.XQueryKeymap.side_effect = lambda _display, keys: keys.__setitem__(0, b"\x01")
        self.assertFalse(tap.pulse())
        tap.xtst.XTestFakeMotionEvent.assert_not_called()

    def test_dragging_and_failed_pointer_queries_suppress_movement(self):
        tap = self.make_tap()
        def dragging(*args):
            args[8]._obj.value = 1 << 8
            return 1
        tap.x11.XQueryPointer.side_effect = dragging
        self.assertFalse(tap.pulse())
        tap.xtst.XTestFakeMotionEvent.assert_not_called()
        tap.x11.XQueryPointer.side_effect = None
        tap.x11.XQueryPointer.return_value = 0
        self.assertFalse(tap.pulse())
        tap.xtst.XTestFakeMotionEvent.assert_not_called()

    def test_pointer_at_origin_still_moves_and_is_restored(self):
        tap = self.make_tap()
        tap.x11.XQueryPointer.side_effect = lambda *args: 1
        self.assertTrue(tap.pulse())
        self.assertEqual([call.args for call in tap.xtst.XTestFakeMotionEvent.call_args_list],
                         [(123, 0, 1, 0, 0), (123, 0, 0, 0, 0)])

    def test_failed_excursion_still_attempts_restoration(self):
        tap = self.make_tap()
        tap.xtst.XTestFakeMotionEvent.side_effect = [0, 1]
        self.assertFalse(tap.pulse())
        self.assertEqual(tap.xtst.XTestFakeMotionEvent.call_args_list[-1].args, (123, 0, 800, 450, 0))
        tap.x11.XSync.assert_called_once_with(123, False)

    def test_restore_failure_uses_native_pointer_warp_as_fallback(self):
        tap = self.make_tap()
        tap.xtst.XTestFakeMotionEvent.side_effect = [1, 0]
        with self.assertLogs("wallpaper_studio.awake", level="WARNING"):
            self.assertFalse(tap.pulse())
        tap.x11.XWarpPointer.assert_called_once_with(123, 0, 456, 0, 0, 0, 0, 800, 450)

    def test_missing_extension_library_is_optional(self):
        with patch("wallpaper_studio.awake.ctypes.util.find_library", return_value=None):
            with self.assertLogs("wallpaper_studio.awake", level="WARNING"):
                tap = MouseMotion(None)
        self.assertFalse(tap.pulse())


class AwakeSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from wallpaper_studio.desktop import Desktop
        except ImportError:
            raise unittest.SkipTest("GTK 3 unavailable; use /usr/bin/python3 on Ubuntu")
        cls.desktop_class = Desktop

    def desktop(self, active=True, locked=False):
        desktop = self.desktop_class.__new__(self.desktop_class)
        desktop.session = Mock()
        values = {"Active": Mock(unpack=lambda: active), "LockedHint": Mock(unpack=lambda: locked)}
        desktop.session.get_cached_property.side_effect = values.get
        desktop.mouse_motion = Mock()
        desktop.pulse_timer = 1
        desktop.awake_signature = None
        return desktop

    def test_locked_inactive_and_unknown_sessions_never_receive_input(self):
        for active, locked in ((True, True), (False, False), (False, True), (None, None)):
            desktop = self.desktop(active, locked)
            with patch("wallpaper_studio.core.awake_until", return_value=-1):
                desktop.pulse_awake()
            desktop.mouse_motion.pulse.assert_not_called()
        desktop.session = None
        with patch("wallpaper_studio.core.awake_until", return_value=-1):
            desktop.pulse_awake()
        desktop.mouse_motion.pulse.assert_not_called()

    def test_active_unlocked_session_receives_input_only_before_expiry(self):
        desktop = self.desktop()
        with patch("wallpaper_studio.core.awake_until", return_value=-1):
            self.assertTrue(desktop.pulse_awake())
        desktop.mouse_motion.pulse.assert_called_once()
        desktop.mouse_motion.reset_mock()
        with patch("wallpaper_studio.core.awake_until", return_value=None):
            self.assertFalse(desktop.pulse_awake())
        desktop.mouse_motion.pulse.assert_not_called()
        self.assertEqual(desktop.pulse_timer, 0)

    def test_turning_off_removes_pulse_and_expiry_timers(self):
        desktop = self.desktop()
        desktop.awake_timer, desktop.pulse_timer = 10, 11
        desktop.uninhibit = Mock()
        with patch("wallpaper_studio.core.awake_until", return_value=None), \
             patch("wallpaper_studio.desktop.GLib.source_remove") as remove:
            self.assertFalse(desktop.sync_awake())
        self.assertEqual([c.args for c in remove.call_args_list], [(10,), (11,)])
        desktop.uninhibit.assert_called_once()
        self.assertEqual(desktop.pulse_timer, 0)


if __name__ == "__main__":
    unittest.main()

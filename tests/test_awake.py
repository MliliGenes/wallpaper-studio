import unittest
from unittest.mock import Mock, patch

from wallpaper_studio.awake import KeyTap


class KeyTapTests(unittest.TestCase):
    def make_tap(self):
        tap = KeyTap.__new__(KeyTap)
        tap.available, tap.display, tap.keycode = True, 123, 42
        tap.x11, tap.xtst = Mock(), Mock()
        return tap

    def test_balanced_key_press_and_release(self):
        tap = self.make_tap()
        self.assertTrue(tap.pulse())
        self.assertEqual([c.args for c in tap.xtst.XTestFakeKeyEvent.call_args_list],
                         [(123, 42, 1, 0), (123, 42, 0, 0)])

    def test_held_keys_suppress_input(self):
        tap = self.make_tap()
        tap.x11.XQueryKeymap.side_effect = lambda _display, keys: keys.__setitem__(0, b"\x01")
        self.assertFalse(tap.pulse())
        tap.xtst.XTestFakeKeyEvent.assert_not_called()

    def test_missing_extension_library_is_optional(self):
        with patch("wallpaper_studio.awake.ctypes.util.find_library", return_value=None):
            with self.assertLogs("wallpaper_studio.awake", level="WARNING"):
                tap = KeyTap(None)
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
        desktop.key_tap = Mock()
        desktop.pulse_timer = 1
        desktop.awake_signature = None
        return desktop

    def test_locked_inactive_and_unknown_sessions_never_receive_input(self):
        for active, locked in ((True, True), (False, False), (False, True), (None, None)):
            desktop = self.desktop(active, locked)
            with patch("wallpaper_studio.core.awake_until", return_value=-1):
                desktop.pulse_awake()
            desktop.key_tap.pulse.assert_not_called()
        desktop.session = None
        with patch("wallpaper_studio.core.awake_until", return_value=-1):
            desktop.pulse_awake()
        desktop.key_tap.pulse.assert_not_called()

    def test_active_unlocked_session_receives_input_only_before_expiry(self):
        desktop = self.desktop()
        with patch("wallpaper_studio.core.awake_until", return_value=-1):
            self.assertTrue(desktop.pulse_awake())
        desktop.key_tap.pulse.assert_called_once()
        desktop.key_tap.reset_mock()
        with patch("wallpaper_studio.core.awake_until", return_value=None):
            self.assertFalse(desktop.pulse_awake())
        desktop.key_tap.pulse.assert_not_called()
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

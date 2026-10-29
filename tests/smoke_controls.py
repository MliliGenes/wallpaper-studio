"""Manual GTK 4 check for independent widget switches; uses isolated temporary settings."""
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory() as directory:
        os.environ["XDG_CONFIG_HOME"] = directory
        os.environ["XDG_CACHE_HOME"] = directory
        os.environ["GSETTINGS_BACKEND"] = "memory"
        from wallpaper_studio import app, layout, settings, styles
        from gi.repository import Adw, Gio, GLib, Gtk
        if not Gtk.init_check():
            raise SystemExit("Run this check with a GTK 4 display")
        Adw.init()
        styles.ensure_user_styles()
        application = Adw.Application(application_id="io.github.WallpaperStudio.ControlsSmoke", flags=Gio.ApplicationFlags.NON_UNIQUE)
        application.register(None)

        def wait(predicate):
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                while GLib.MainContext.default().pending():
                    GLib.MainContext.default().iteration(False)
                if predicate():
                    return
                time.sleep(.02)
            raise AssertionError("Timed out waiting for the control panel to update")

        with patch.object(app.Window, "load_library"), patch.object(app.core, "start_helper"):
            window = app.Window(application)
            try:
                assert set(window.widget_toggles) == {"clock", "calendar", "system", "notes", "logtime"}
                window.logtime_entries["logtime_username"].set_text("sel-mlil")
                window.logtime_entries["logtime_goal"].set_text("196")
                window.save_logtime()
                assert settings.load_config()["logtime_username"] == "sel-mlil"
                assert settings.load_config()["logtime_goal"] == 196
                window.widget_toggles["logtime"].set_active(False)
                wait(lambda: not layout.load_layout()[4].enabled)
                assert window.widget_toggles["calendar"].get_active()
                window.widget_toggles["calendar"].set_active(False)
                wait(lambda: not layout.load_layout()[1].enabled)
                wait(lambda: not window.widget_toggles["calendar"].get_active())
                assert window.widget_toggles["system"].get_active()
                assert window.widget_toggles["notes"].get_active()
                window.widget_toggles["clock"].set_active(False)
                wait(lambda: not layout.load_layout()[0].enabled)
                assert layout.load_layout()[2].enabled
                window.widget_toggles["calendar"].set_active(True)
                wait(lambda: layout.load_layout()[1].enabled)
                assert not layout.load_layout()[0].enabled
                window.switches["widget_blur"].set_active(False)
                wait(lambda: settings.load_config()["widget_blur"] is False)
                window.switches["widget_blur"].set_active(True)
                wait(lambda: settings.load_config()["widget_blur"] is True)
            finally:
                window.widget_pool.shutdown(wait=True)
                window.pool.shutdown(wait=True)
                window.destroy()
        print("GTK 4 independent widget switches and Logtime settings: passed")


if __name__ == "__main__":
    main()

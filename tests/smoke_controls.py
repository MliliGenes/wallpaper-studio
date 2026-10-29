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
                assert set(window.widget_toggles) == {"clock", "calendar", "system", "cleaner", "notes", "logtime", "now-playing"}
                window.widget_toggles["now-playing"].set_active(False)
                wait(lambda: not next(p for p in layout.load_layout() if p.id == "now-playing").enabled)
                window.widget_toggles["now-playing"].set_active(True)
                wait(lambda: next(p for p in layout.load_layout() if p.id == "now-playing").enabled)
                window.switches["layout_grid"].set_active(False)
                wait(lambda: not settings.load_config()["layout_grid"])
                window.grid_spins["layout_grid_size"].set_value(48)
                window.grid_spins["layout_grid_gap"].set_value(12)
                wait(lambda: settings.load_config()["layout_grid_size"] == 48)
                wait(lambda: settings.load_config()["layout_grid_gap"] == 12)
                window.logtime_entries["logtime_username"].set_text("sel-mlil")
                window.logtime_entries["logtime_goal"].set_text("196")
                window.save_logtime()
                assert settings.load_config()["logtime_username"] == "sel-mlil"
                assert settings.load_config()["logtime_goal"] == 196
                window.widget_toggles["logtime"].set_active(False)
                wait(lambda: not next(p for p in layout.load_layout() if p.id == "logtime").enabled)
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
                assert window.blur_scale.get_value() == settings.load_config()["widget_blur_radius"]
                for radius in (0, 64, 32):
                    window.blur_scale.set_value(radius)
                    wait(lambda: settings.load_config()["widget_blur_radius"] == radius)
                settings.save_config(widget_blur_radius=17)
                with patch.object(app.core, "save_config", wraps=app.core.save_config) as save:
                    window.sync_from_disk()
                    assert window.blur_scale.get_value() == 17
                    save.assert_not_called()
                window.switches["widget_blur"].set_active(False)
                wait(lambda: settings.load_config()["widget_blur"] is False)
                assert not window.blur_scale.get_sensitive()
                assert settings.load_config()["widget_blur_radius"] == 17
                window.switches["widget_blur"].set_active(True)
                wait(lambda: settings.load_config()["widget_blur"] is True)
                assert window.blur_scale.get_sensitive()
                assert window.blur_scale.get_value() == 17
            finally:
                window.widget_pool.shutdown(wait=True)
                window.pool.shutdown(wait=True)
                window.destroy()
        print("GTK 4 independent widget switches and Logtime settings: passed")


if __name__ == "__main__":
    main()

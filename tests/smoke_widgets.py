"""Manual GTK 3 smoke check. Run with a display; all config writes use a temporary folder."""
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory() as directory:
        os.environ["XDG_CONFIG_HOME"] = directory
        from wallpaper_studio.widgets import DesktopWidgets, Gtk, GLib
        from wallpaper_studio import core
        if not Gtk.init_check()[0]:
            raise SystemExit("No GTK display; run this check in a graphical session")
        locked = [False]
        host = DesktopWidgets(lambda: locked[0])
        try:
            for _ in range(20):
                if GLib.MainContext.default().pending():
                    GLib.MainContext.default().iteration(False)
            assert host.window.get_visible()
            assert host.clock.time_label.get_text()
            core.save_config(clock_format="%H:%M:%S", clock_date_format="")
            host.reload()
            assert not host.clock.date_label.get_visible()
            assert len(host.clock.time_label.get_text()) == 8
            Path(core.WIDGETS_CSS).write_text("#ws-desktop-widgets .clock-time { font-size: 80px; }")
            host.reload()
            previous = host.provider
            Path(core.WIDGETS_CSS).write_text("#ws-desktop-widgets { invalid-property: nope; }")
            host.reload()
            assert host.provider is previous, "Invalid CSS must preserve the previous provider"
            Path(core.WIDGETS_CSS).unlink()
            host.reload()
            assert host.provider is not previous, "Deleting CSS should restore defaults"
            locked[0] = True
            host.update()
            assert not host.window.get_visible()
            locked[0] = False
            host.update()
            assert host.window.get_visible()
            core.save_config(clock=False)
            host.reload()
            assert not host.window.get_visible()
        finally:
            host.close()
        print("GTK 3 clock startup, formatting, CSS reload/recovery, lock and hide: passed")


if __name__ == "__main__":
    main()

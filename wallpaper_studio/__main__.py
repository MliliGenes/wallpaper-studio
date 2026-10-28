"""wallpaper-studio — change your wallpaper and recolour your desktop from it.

    wallpaper-studio                 open the window
    wallpaper-studio set FILE        use a picture or video as the wallpaper
    wallpaper-studio next            a random different wallpaper from your folder
    wallpaper-studio light|dark|auto light or dark colours, or follow the clock
    wallpaper-studio awake [MINUTES|on|off]
                                     keep the screen from locking while you read or watch
                                     (default 60 minutes; "on" lasts until you turn it off or log out)
    wallpaper-studio restore         put your desktop back the way it was
    wallpaper-studio desktop         the background helper (started at login)
"""
import os
import sys

# Ghostty's AppImage exports GSETTINGS_BACKEND=keyfile to everything it starts, which sends
# settings to a private file GNOME never reads; always talk to the real settings store
if os.environ.get("GSETTINGS_BACKEND") == "keyfile":
    os.environ["GSETTINGS_BACKEND"] = "dconf"


def main(argv):
    command = argv[1] if len(argv) > 1 else "open"
    if command == "open":
        from . import app
        return app.main()
    if command == "desktop":
        from . import desktop
        return desktop.main()

    from . import core
    try:
        if command == "set" and len(argv) > 2:
            core.set_wallpaper(argv[2])
        elif command == "next":
            if core.next_wallpaper() is None:
                print("wallpaper-studio: no other pictures in", core.load_config()["folder"], file=sys.stderr)
                return 1
        elif command in ("light", "dark", "auto"):
            core.save_config(mode=command)
            core.apply_theme()
        elif command == "apply":
            core.apply_theme()
        elif command == "awake":
            arg = argv[2] if len(argv) > 2 else "60"
            if arg == "off":
                core.keep_awake(None)
                print("Screen locks normally again.")
            elif arg == "on":
                core.keep_awake(core.FOREVER)
                print("Screen stays awake until you run 'wallpaper-studio awake off' or log out.")
            elif arg.isdigit() and int(arg) > 0:
                core.keep_awake(int(arg))
                print(f"Screen stays awake for {arg} minutes.")
            else:
                print("usage: wallpaper-studio awake [MINUTES|on|off]", file=sys.stderr)
                return 1
        elif command == "restore":
            core.restore()
        else:
            print(__doc__.strip())
            return 1
    except ValueError as e:
        print(f"wallpaper-studio: {e}", file=sys.stderr)
        return 1
    return 0


sys.exit(main(sys.argv))

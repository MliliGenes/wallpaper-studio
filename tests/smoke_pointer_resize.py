"""Real pointer regression; run through run_pointer_smoke.py on a graphical session."""
import json
import os
from pathlib import Path
import tempfile
import time
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

with tempfile.TemporaryDirectory() as directory:
    os.environ['XDG_CONFIG_HOME'] = directory
    os.environ['XDG_CACHE_HOME'] = directory
    os.environ['GSETTINGS_BACKEND'] = 'memory'
    from wallpaper_studio import settings, layout, storage
    settings.save_config(layout_edit=True, layout_grid=False, widget_blur=False)
    layout.ensure_layout()
    Path(storage.LAYOUT).write_text(json.dumps({'version': 1, 'widgets': [
        {'id':'notes','component':'Notes','anchor':'top-left','x':100,'y':100,'width':700,'height':400,'props':{'text':'Resize me'}}]}))
    from wallpaper_studio.widget_runtime import DesktopWidgets
    from gi.repository import GLib
    host = DesktopWidgets(lambda: False)
    def pump():
        end=time.monotonic()+.25
        while time.monotonic()<end:
            GLib.MainContext.default().iteration(False)
            time.sleep(.002)
    import ctypes
    x11=ctypes.CDLL('libX11.so.6')
    xtest=ctypes.CDLL('libXtst.so.6')
    x11.XOpenDisplay.argtypes=[ctypes.c_char_p]
    x11.XOpenDisplay.restype=ctypes.c_void_p
    x11.XFlush.argtypes=[ctypes.c_void_p]
    x11.XCloseDisplay.argtypes=[ctypes.c_void_p]
    xtest.XTestFakeMotionEvent.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_ulong]
    xtest.XTestFakeButtonEvent.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_int,ctypes.c_ulong]
    display=x11.XOpenDisplay(os.environ['DISPLAY'].encode())
    assert display
    def mouse(kind,*args):
        if kind=='mousemove':
            xtest.XTestFakeMotionEvent(display,-1,args[0],args[1],0)
        else:
            xtest.XTestFakeButtonEvent(display,args[0],kind=='mousedown',0)
        x11.XFlush(display)
        pump()
    try:
        pump()
        frame=host.frames['notes']
        for edges in ('e', 'w', 'n', 's', 'ne', 'nw', 'se', 'sw'):
            for direction in (1, -1):
                layout.save_placement('notes', x=200, y=200, width=700, height=400)
                host.reload()
                pump()
                frame = host.frames['notes']
                x, y = host.canvas.child_get(frame.container, 'x', 'y')
                w, h = frame.container.get_allocated_width(), frame.container.get_allocated_height()
                px = x + (2 if 'w' in edges else w-2 if 'e' in edges else w//2)
                py = y + (2 if 'n' in edges else h-2 if 's' in edges else h//2)
                dx = direction * (-40 if 'w' in edges else 40 if 'e' in edges else 0)
                dy = direction * (-40 if 'n' in edges else 40 if 's' in edges else 0)
                mouse('mousemove', px, py)
                mouse('mousedown', 1)
                assert host.drag and host.drag['resize'] == edges, (edges, host.drag)
                mouse('mousemove', px+dx, py+dy)
                mouse('mouseup', 1)
                expected = (x + (dx if 'w' in edges else 0), y + (dy if 'n' in edges else 0),
                            w + (-dx if 'w' in edges else dx), h + (-dy if 'n' in edges else dy))
                saved = frame.placement
                assert (saved.x, saved.y, saved.width, saved.height) == expected, (edges, direction, saved, expected)
        # Switching modes must restore child input, then re-enable border input.
        settings.save_config(layout_edit=False)
        host.reload()
        pump()
        assert not frame.container.get_above_child()
        from wallpaper_studio.components import Button, Column
        clicks = []
        frame.component = lambda **_: Column(Button('Test control', on_click=lambda: clicks.append(True)))
        host.update()
        pump()
        button = next(iter(frame.renderer.buttons()))
        bx, by = button.translate_coordinates(host.canvas, 0, 0)
        mouse('mousemove', bx + button.get_allocated_width()//2, by + button.get_allocated_height()//2)
        mouse('mousedown', 1)
        mouse('mouseup', 1)
        assert clicks == [True], clicks
        settings.save_config(layout_edit=True)
        host.reload()
        pump()
        assert frame.container.get_above_child()
        x, y = host.canvas.child_get(frame.container, 'x', 'y')
        mouse('mousemove', x+100, y+100)
        mouse('mousedown', 1)
        assert host.drag and not host.drag['resize']
        mouse('mousemove', x+120, y+130)
        mouse('mouseup', 1)
        assert (frame.placement.x, frame.placement.y) == (x+20, y+30)
        print('Real X11 pointer checks passed: eight borders/corners grow and shrink, move, arrange toggle', flush=True)
    finally:
        x11.XCloseDisplay(display)
        host.close()

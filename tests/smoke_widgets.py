"""Manual GTK 3 smoke check. Run with a display; all config writes use a temporary folder."""
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory() as directory:
        os.environ["XDG_CONFIG_HOME"] = directory
        os.environ["XDG_CACHE_HOME"] = directory
        from wallpaper_studio.widget_runtime import DesktopWidgets
        from wallpaper_studio.components import Button, Column, Icon, IconButton, Image, Progress, Text, component
        from wallpaper_studio.gtk_renderer import Renderer
        from wallpaper_studio.widgets import Clock
        from gi.repository import Gdk, Gtk, GLib
        from wallpaper_studio import core, layout, palette, storage
        import cairo
        import json
        if not Gtk.init_check()[0]:
            raise SystemExit("No GTK display; run this check in a graphical session")
        # Broadway has no monitor dimensions until a browser connects; supply a test work area.
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        if monitor is not None and monitor.get_workarea().width == 0:
            rectangle = Gdk.Rectangle()
            rectangle.x, rectangle.y, rectangle.width, rectangle.height = 0, 0, 1280, 900
            Gdk.Monitor.get_workarea = lambda _monitor: rectangle
        wallpaper_path = Path(directory) / "wallpaper.png"
        wallpaper = cairo.ImageSurface(cairo.FORMAT_RGB24, 1280, 900)
        background = cairo.Context(wallpaper)
        gradient = cairo.LinearGradient(0, 0, 1280, 900)
        gradient.add_color_stop_rgb(0, .13, .23, .42)
        gradient.add_color_stop_rgb(.5, .50, .20, .43)
        gradient.add_color_stop_rgb(1, .11, .43, .51)
        background.set_source(gradient)
        background.paint()
        for x in range(0, 1280, 28):
            background.set_source_rgba(.85, .90, 1, .18)
            background.rectangle(x, 0, 3, 900)
            background.fill()
        wallpaper.write_to_png(str(wallpaper_path))
        colors = palette.build([(215, .65, .4), (330, .65, .4)] * 10)
        core._save_state({"still": str(wallpaper_path), "palette": colors, "mode": "dark"})
        core._write(core.THEME_CSS, palette.gtk_css(colors["dark"], True, False))
        core.save_config(layout_grid=False)
        locked = [False]
        host = DesktopWidgets(lambda: locked[0])
        def settle():
            for _ in range(30):
                while GLib.MainContext.default().pending():
                    GLib.MainContext.default().iteration(False)
                # A Broadway display without a browser has no frame clock to flush layout.
                host.window.check_resize()
                time.sleep(.01)

        def pointer_click(button):
            """Dispatch pointer events through GTK, including ancestor controllers."""
            native = button.get_event_window()
            device = host.window.get_display().get_default_seat().get_pointer()
            for kind in (Gdk.EventType.ENTER_NOTIFY, Gdk.EventType.BUTTON_PRESS, Gdk.EventType.BUTTON_RELEASE):
                event = Gdk.Event.new(kind)
                event.window = native
                event.send_event = True
                event.time = Gdk.CURRENT_TIME
                event.x, event.y = button.get_allocated_width() / 2, button.get_allocated_height() / 2
                event.set_device(device)
                if kind == Gdk.EventType.ENTER_NOTIFY:
                    event.mode = Gdk.CrossingMode.NORMAL
                    event.detail = Gdk.NotifyType.ANCESTOR
                else:
                    event.button = 1
                    event.state = Gdk.ModifierType.BUTTON1_MASK if kind == Gdk.EventType.BUTTON_RELEASE else 0
                Gtk.main_do_event(event)
            settle()
        try:
            settle()
            assert host.window.get_visible()
            assert host.window.get_type_hint() == Gdk.WindowTypeHint.NORMAL
            assert host.backdrop.surface is not None
            assert host.window.get_style_context().has_class("glass-ready")
            assert set(host.frames) == {"clock", "calendar", "system", "cleaner", "notes", "logtime", "now-playing"}
            media = host.frames["now-playing"]
            assert media.renderer.find("title").get_text()
            assert len(media.renderer.buttons()) == 3
            assert media.renderer.find("Previous").get_child().icon_name == "backward-step"
            assert media.renderer.find("Previous").get_tooltip_text() == "Previous"
            assert media.renderer.find("artwork").get_allocated_width() > 20
            media_model = media.models["now-playing"]
            layout.set_enabled("now-playing", False)
            layout.set_enabled("cleaner", False)
            host.reload()
            assert media_model._closed.is_set()
            logtime = host.frames["logtime"]
            model = logtime.models["logtime"]
            from datetime import date
            model.today = lambda: date(2026, 10, 29)
            model.fetch = lambda *_: 196
            core.save_config(logtime_username="sel-mlil", logtime_goal=196)
            host.reload()
            settle()
            host.update()
            settle()
            assert logtime.renderer.find("hours").get_text() == "196"
            assert logtime.renderer.find("percent").get_text() == "100%"
            ring = logtime.renderer.find("ring")
            assert ring.get_allocated_height() > 150, "The ring must reserve space for its arc and labels"
            assert logtime.renderer.find("hours").get_mapped()
            assert logtime.renderer.find("month").get_text() == "October 2026"
            assert logtime.renderer.find("period").get_text() == "Oct 28, 2026 – Nov 27, 2026"
            assert len(logtime.renderer.buttons()) == 3
            next_button = logtime.renderer.find("next")
            assert next_button.get_child().get_mapped(), "Button labels must be visible"
            assert not host.window.get_window().get_pass_through(), "Buttons must receive normal-mode input"
            input_region = host.input_region()
            bx, by = next_button.translate_coordinates(host.canvas, 0, 0)
            assert input_region.contains_point(bx + 3, by + 3)
            hx, hy = logtime.renderer.find("hours").translate_coordinates(host.canvas, 0, 0)
            assert not input_region.contains_point(hx + 3, hy + 3), "Non-button areas must pass input to the desktop"
            assert logtime.gesture.get_propagation_phase() == Gtk.PropagationPhase.NONE
            pointer_click(next_button)
            assert model.offset == 1
            assert logtime.renderer.find("month").get_text() == "November 2026"
            assert logtime.renderer.find("period").get_text() == "Nov 28, 2026 – Dec 27, 2026"
            pointer_click(logtime.renderer.find("prev"))
            assert model.offset == 0
            settle()
            host.update()
            settle()
            refresh = logtime.renderer.find("refresh")
            refresh_label = refresh.get_child()
            assert refresh_label.get_text() == "Refresh"
            assert refresh_label.get_mapped() and refresh_label.get_allocated_width() > 10
            # Keep the loading state visible long enough to inspect its native label.
            import threading
            release_refresh = threading.Event()
            model.fetch = lambda *_: (release_refresh.wait(3), 196)[1]
            try:
                pointer_click(refresh)
                assert refresh.get_child() is refresh_label, "Changing button text must retain its label widget"
                assert refresh_label.get_text() == "Updating…"
                assert refresh_label.get_mapped() and refresh_label.get_allocated_width() > 10
                assert not refresh.get_sensitive()
            finally:
                release_refresh.set()
            settle()
            host.update()
            settle()
            assert refresh.get_child() is refresh_label
            assert refresh_label.get_text() == "Refresh"
            assert refresh_label.get_mapped() and refresh_label.get_allocated_width() > 10
            assert refresh.get_sensitive()
            clock = host.frames["clock"].renderer
            original_time = clock.find("time")
            assert original_time.get_text()
            if os.environ.get("WS_WIDGET_PREVIEW"):
                settle()
                hours_label = logtime.renderer.find("hours")
                assert hours_label.get_allocated_width() >= hours_label.get_preferred_width()[0], (
                    f"Hours must fit: allocated={hours_label.get_allocated_width()}, preferred={hours_label.get_preferred_width()}, "
                    f"content={ring.content.get_allocated_width()}, ring={ring.get_allocated_width()}, "
                    f"area={ring.get_child().get_allocated_width()}")
                assert next_button.get_child().get_allocated_width() > 10
                surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, host.window.get_allocated_width(), host.window.get_allocated_height())
                cr = cairo.Context(surface)
                cr.set_source_surface(wallpaper, 0, 0)
                cr.paint()
                host.window.draw(cr)
                surface.write_to_png(os.environ["WS_WIDGET_PREVIEW"])
            core.save_config(widget_blur=False)
            host.reload()
            assert host.backdrop.surface is None
            assert not host.window.get_style_context().has_class("glass-ready")
            core.save_config(widget_blur=True)
            host.reload()
            assert host.backdrop.surface is not None
            core.save_config(clock_format="%H:%M:%S", clock_date_format="")
            host.reload()
            assert not clock.find("date").get_visible()
            assert clock.find("time") is original_time
            assert len(original_time.get_text()) == 8
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
            assert host.window.get_visible(), "Other widgets stay visible when the clock is hidden"
            core.save_config(widgets_enabled=False)
            host.reload()
            assert not host.window.get_visible()
            core.save_config(widgets_enabled=True, clock=True, layout_edit=True)
            host.reload()
            settle()
            assert host.window.get_type_hint() == Gdk.WindowTypeHint.UTILITY
            assert logtime.gesture.get_propagation_phase() == Gtk.PropagationPhase.CAPTURE
            selected_period = model.offset
            next_button.clicked()
            assert model.offset == selected_period, "Arrange mode must not activate navigation"
            ring_width = ring.get_allocated_width()
            layout.save_placement("logtime", scale=1.2)
            host.reload()
            settle()
            assert ring.get_preferred_width()[1] > ring_width, "The ring must scale with its card"
            frame = host.frames["clock"]
            x, y = host.canvas.child_get(frame.container, "x", "y")
            start = SimpleNamespace(button=1, x_root=host.area[0] + x + 20, y_root=host.area[1] + y + 20)
            assert host.begin_drag("clock", start)
            frame.gesture.emit("drag-update", 80.0, 40.0)
            live = frame.container.get_allocation()
            assert (live.x, live.y) == (x + 80, y + 40), "The card must move before the button is released"
            host.update()  # periodic refresh must not snap an active drag back to its saved placement
            settle()
            live = frame.container.get_allocation()
            assert (live.x, live.y) == (x + 80, y + 40)
            assert host.end_drag(SimpleNamespace(button=1))
            assert host.frames["clock"].placement.anchor == "top-left"
            assert host.frames["clock"].placement.x == x + 80
            assert host.frames["clock"].placement.y == y + 40
            settle()
            frame = host.frames["clock"]
            width, height = frame.container.get_allocated_width(), frame.container.get_allocated_height()
            x, y = host.canvas.child_get(frame.container, "x", "y")
            corner = SimpleNamespace(button=1, x_root=host.area[0] + x + width - 2, y_root=host.area[1] + y + height - 2)
            assert host.begin_drag("clock", corner) and host.drag["resize"]
            host.drag_motion(SimpleNamespace(x_root=corner.x_root + width * .25, y_root=corner.y_root + height * .25))
            settle()  # The chosen rectangle must remain stable while the pointer is held.
            assert frame.container.get_allocated_width() > width, "Resize must be visible before release"
            host.end_drag(SimpleNamespace(button=1))
            settle()
            assert host.frames["clock"].placement.scale == 1, "Border resize must not change text scale"
            assert host.frames["clock"].container.get_preferred_size()[1].width > width
            scale = host.frames["clock"].placement.scale
            assert host.scroll_scale("clock", SimpleNamespace(direction=Gdk.ScrollDirection.UP))
            assert host.frames["clock"].placement.scale > scale
            # Grid geometry survives movement, resize, reload, and leaving arrange mode.
            core.save_config(layout_grid=True, layout_grid_size=32, layout_grid_gap=8)
            host.reload()
            settle()
            frame = host.frames["clock"]
            def assert_grid():
                x, y = host.canvas.child_get(frame.container, "x", "y")
                w, h = frame.container.get_allocated_width(), frame.container.get_allocated_height()
                assert (x - 8) % 40 == 0 and (y - 8) % 40 == 0, (x, y)
                assert (w + 8) % 40 == 0 and (h + 8) % 40 == 0, (w, h, frame.container.get_size_request(), host.card_size(frame))
                return x, y, w, h
            x, y, w, h = assert_grid()
            start = SimpleNamespace(button=1, x_root=host.area[0] + x + 20, y_root=host.area[1] + y + 20)
            assert host.begin_drag("clock", start)
            host.drag_motion(SimpleNamespace(x_root=start.x_root + 63, y_root=start.y_root + 57))
            host.end_drag(SimpleNamespace(button=1))
            settle()
            x, y, w, h = assert_grid()
            assert (frame.placement.x, frame.placement.y) == (x, y)
            corner = SimpleNamespace(button=1, x_root=host.area[0] + x + w - 2, y_root=host.area[1] + y + h - 2)
            assert host.begin_drag("clock", corner) and host.drag["resize"]
            host.drag_motion(SimpleNamespace(x_root=corner.x_root + 80, y_root=corner.y_root + 40))
            settle()
            assert_grid()
            host.end_drag(SimpleNamespace(button=1))
            settle()
            assert_grid()
            previous_width = frame.container.get_allocated_width()
            previous_scale = frame.placement.scale
            host.scroll_scale("clock", SimpleNamespace(direction=Gdk.ScrollDirection.DOWN))
            settle()
            assert_grid()
            assert frame.container.get_allocated_width() == previous_width, "Text scaling preserves explicit width"
            assert frame.placement.scale < previous_scale
            host.reload()
            settle()
            assert_grid()
            core.save_config(layout_edit=False)
            host.reload()
            settle()
            assert_grid()
            assert host.window.get_type_hint() == Gdk.WindowTypeHint.NORMAL
            assert logtime.gesture.get_propagation_phase() == Gtk.PropagationPhase.NONE
            assert not host.window.get_window().get_pass_through(), "Only button rectangles accept input"
            layout.set_enabled("logtime", False)
            host.reload()
            settle()
            assert host.window.get_window().get_pass_through(), "Layouts without buttons stay click-through"
            assert model.closed.is_set(), "Disabling a widget closes its model"
            previous_layout = tuple(host.frames)
            Path(storage.LAYOUT).write_text("broken layout {")
            host.reload()
            assert tuple(host.frames) == previous_layout
        finally:
            host.close()

        # Native reconciliation: reorder/update keyed children without replacing their GTK widgets.
        renderer = Renderer()
        root = renderer.render(Column(Text("A", key="a", class_name="old"), Text("B", key="b")))
        a, b = renderer.find("a"), renderer.find("b")
        destroyed = []
        a.connect("destroy", lambda *_: destroyed.append("a"))
        assert renderer.render(Column(Text("B2", key="b"), Text("A2", key="a", class_name="new"))) is root
        assert root.get_children() == [b, a]
        assert a.get_text() == "A2" and b.get_text() == "B2"
        assert a.get_style_context().has_class("new")
        assert not a.get_style_context().has_class("old")
        renderer.render(Column(Text("B3", key="b"), Progress(.5, text="50%", key="progress")))
        assert destroyed == ["a"]
        assert renderer.find("b") is b
        assert renderer.find("progress").get_fraction() == .5
        # Failed component evaluation must leave the existing native tree intact.
        try:
            renderer.render(Column(Text("x", key="same"), Text("y", key="same")))
        except ValueError:
            pass
        else:
            raise AssertionError("Duplicate keys should fail")
        assert renderer.find("b") is b and b.get_text() == "B3"
        renderer.close()

        # Image decoding is bounded, and invalid or missing artwork clears the old image.
        artwork_renderer = Renderer()
        artwork = artwork_renderer.render(Image(wallpaper_path.read_bytes(), key="cover"))
        assert artwork.artwork is not None
        assert max(artwork.artwork.get_width(), artwork.artwork.get_height()) <= 512
        assert artwork_renderer.render(Image(b"invalid image", key="cover")) is artwork
        assert artwork.artwork is None
        artwork_renderer.render(Image(None, key="cover"))
        artwork_renderer.close()

        # All bundled SVGs decode locally; controls retain their native child on icon changes.
        from wallpaper_studio.gtk_icons import SvgIcon, raster_icon
        from wallpaper_studio.icons import available_icons
        for name in available_icons():
            pb = raster_icon(name, 32)
            assert max(pb.get_width(), pb.get_height()) == 32
            assert pb.get_has_alpha()
        icons = Renderer()
        button = icons.render(IconButton("play", label="Play", on_click=lambda: None, key="control"))
        child = button.get_child()
        assert isinstance(child, SvgIcon)
        assert button.get_accessible().get_name() == "Play"
        icons.render(IconButton("pause", label="Pause", on_click=lambda: None, sensitive=False, key="control"))
        assert button.get_child() is child and child.icon_name == "pause"
        assert button.get_tooltip_text() == "Pause"
        assert child.get_state_flags() & Gtk.StateFlags.INSENSITIVE
        icons.render(Button("Resume", on_click=lambda: None, key="control"))
        assert button.get_child().get_text() == "Resume"
        standalone = icons.render(Icon("music", label="Music", key="music"))
        assert standalone.get_accessible().get_name() == "Music"
        # Exercise the drawing path at display scale, including CSS tinting.
        allocation = Gdk.Rectangle()
        allocation.x = allocation.y = 0
        allocation.width = allocation.height = 32
        standalone.size_allocate(allocation)
        icon_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 32, 32)
        standalone.draw_icon(standalone, cairo.Context(icon_surface))
        assert any(icon_surface.get_data())
        icons.close()

        # User widgets load from the config folder without app/core registration.
        Path(storage.CUSTOM_WIDGETS, "greeting.py").write_text(
            'from wallpaper_studio.components import Text, component\n@component\ndef Widget(config, name="world"):\n    return Text("Hello " + name, wrap=True, max_width_chars=80, key="custom")\n')
        Path(storage.LAYOUT).write_text(json.dumps({"version": 1, "widgets": [
            {"id": "greeting", "component": "greeting", "anchor": "bottom-left", "props": {"name": "sel-mlil"}}]}))
        custom = DesktopWidgets(lambda: False)
        try:
            assert custom.window.get_visible()
            assert custom.frames["greeting"].renderer.find("custom").get_text() == "Hello sel-mlil"
            host = custom  # Reuse the settle helper with this isolated test layout.
            core.save_config(layout_edit=True, layout_grid=True, layout_grid_size=32, layout_grid_gap=8)
            for edge in ("n", "s", "w", "e", "nw", "ne", "sw", "se"):
                layout.save_placement("greeting", anchor="top-left", x=168, y=168, width=312, height=192)
                custom.reload()
                settle()
                frame = custom.frames["greeting"]
                x, y = custom.canvas.child_get(frame.container, "x", "y")
                w, h = frame.container.get_allocated_width(), frame.container.get_allocated_height()
                assert (x, y, w, h) == (168, 168, 312, 192)
                px = 2 if "w" in edge else w - 2 if "e" in edge else w / 2
                py = 2 if "n" in edge else h - 2 if "s" in edge else h / 2
                start = SimpleNamespace(button=1, x_root=custom.area[0] + x + px, y_root=custom.area[1] + y + py)
                assert custom.begin_drag("greeting", start)
                assert custom.drag["resize"] == edge
                dx = -40 if "w" in edge else 40 if "e" in edge else 0
                dy = -40 if "n" in edge else 40 if "s" in edge else 0
                custom.drag_motion(SimpleNamespace(x_root=start.x_root + dx, y_root=start.y_root + dy))
                expected = (x + min(0, dx), y + min(0, dy), w + abs(dx), h + abs(dy))
                custom.update()
                settle()
                allocation = frame.container.get_allocation()
                assert (allocation.x, allocation.y, allocation.width, allocation.height) == expected
                custom.end_drag(SimpleNamespace(button=1))
                custom.reload()
                settle()
                assert (frame.placement.x, frame.placement.y, frame.placement.width, frame.placement.height) == expected
                assert frame.placement.scale == 1
            # Cancellation restores the saved rectangle, including width and height.
            x, y = custom.canvas.child_get(frame.container, "x", "y")
            w, h = frame.container.get_allocated_width(), frame.container.get_allocated_height()
            before = Path(storage.LAYOUT).read_text()
            start = SimpleNamespace(button=1, x_root=custom.area[0] + x + w - 2,
                                    y_root=custom.area[1] + y + h / 2)
            custom.begin_drag("greeting", start)
            custom.drag_motion(SimpleNamespace(x_root=start.x_root - 80, y_root=start.y_root))
            custom.cancel_drag("greeting")
            settle()
            assert (frame.container.get_allocated_width(), frame.container.get_allocated_height()) == (w, h)
            assert Path(storage.LAYOUT).read_text() == before
            # Narrow wrapping text without changing text scale, and measure its new height.
            layout.save_placement("greeting", width=472, height=None, props={"name": "wrapping words " * 35})
            custom.reload()
            settle()
            wide_height = frame.container.get_allocated_height()
            layout.save_placement("greeting", width=232, height=None)
            custom.reload()
            settle()
            assert frame.container.get_allocated_width() == 232
            assert frame.container.get_allocated_height() > wide_height
            label = frame.renderer.find("custom")
            assert label.get_allocated_height() >= label.get_preferred_height_for_width(label.get_allocated_width())[0]
            assert frame.placement.scale == 1
            Path(storage.LAYOUT).write_text('{"version":1,"widgets":[]}')
            custom.reload()
            assert not custom.window.get_visible()
            Path(storage.LAYOUT).write_text('broken')
            custom.reload()
            assert not custom.window.get_visible(), "A bad edit must preserve a valid empty layout"
        finally:
            custom.close()
        print("GTK cards, desktop layout, drag/resize/scale, user components, CSS, lock and cleanup: passed")


if __name__ == "__main__":
    main()

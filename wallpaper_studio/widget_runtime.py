"""Framework runtime: desktop window, CSS and refresh lifecycle for component trees.

The control panel uses GTK 4 in a separate process. Keep GTK versions separate.
"""
import logging
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from . import core, layout, storage, styles  # noqa: E402
from .components import Column, component_scope, close_models  # noqa: E402
from .gtk_renderer import Renderer  # noqa: E402
from .glass import WallpaperGlass  # noqa: E402

log = logging.getLogger(__name__)


@dataclass
class LayoutWidget:
    placement: object
    component: object
    renderer: Renderer
    container: object = None
    overlay: object = None
    grip: object = None
    preview_scale: object = None
    gesture: object = None
    models: dict = field(default_factory=dict)


class DesktopWidgets:
    """Transparent, click-through desktop window with live user CSS."""
    def __init__(self, is_locked):
        styles.ensure_user_styles()
        self.is_locked = is_locked
        self.loader = layout.ComponentLoader()
        self.frames = {}
        self.has_layout = False
        self.area = None
        self.positioning = False
        self.geometry_timer = 0
        self.closed = False
        self.module_timer = 0
        self.drag = None
        self.drag_timer = 0
        self.edit_mode = None
        self.scale_provider = None
        self.backdrop = WallpaperGlass()
        self.drawn_widgets = set()
        self.config = core.load_config()
        self.window = Gtk.Window(title="Wallpaper Studio widgets")
        self.window.set_name("ws-desktop-widgets")
        self.window.get_style_context().add_class("desktop-widgets")
        self.window.set_decorated(False)
        self.window.set_resizable(False)
        self.window.set_accept_focus(False)
        self.window.set_focus_on_map(False)
        self.window.set_skip_taskbar_hint(True)
        self.window.set_skip_pager_hint(True)
        # GNOME's full-screen desktop-icons window sits above other DESKTOP windows
        # and intercepts clicks even where it is transparent. A BELOW normal window
        # stays above that desktop layer while remaining beneath application windows.
        self.window.set_type_hint(Gdk.WindowTypeHint.NORMAL)
        self.window.set_keep_below(True)
        self.window.stick()
        self.window.set_app_paintable(True)
        self.canvas = Gtk.Fixed()
        self.canvas.set_name("desktop-layout")
        self.canvas.connect("draw", self.draw_grid)
        self.window.add(self.canvas)
        self.canvas.show()
        screen = self.window.get_screen()
        visual = screen.get_rgba_visual()
        if visual is not None:
            self.window.set_visual(visual)
        self.window.connect("realize", lambda *_: self.input_region())
        self.window.connect("size-allocate", lambda *_: self.position())
        self.screen_handler = screen.connect("monitors-changed", lambda *_: self.position())
        self.module_monitor = Gio.File.new_for_path(storage.CUSTOM_WIDGETS).monitor_directory(Gio.FileMonitorFlags.NONE, None)
        self.module_monitor.connect("changed", self.on_module_change)
        self.provider = None
        self.reload()
        self.timer = GLib.timeout_add_seconds(1, self.update)

    def reload(self):
        self.config = core.load_config()
        self.reload_layout()
        # A fresh provider prevents old rules lingering after a file is emptied or deleted.
        provider = Gtk.CssProvider()
        fallback = "@define-color ws_paper #171A21; @define-color ws_ink #F4F5F7; " \
                   "@define-color ws_muted #BAC0CE; @define-color ws_accent #91B9FF; " \
                   "@define-color ws_sheet #232833; @define-color ws_on_accent #111827; " \
                   "@define-color ws_accent_text #A3C8FF; @define-color ws_shadow #000000;\n"
        try:
            theme = Path(core.THEME_CSS).read_text() if Path(core.THEME_CSS).exists() else ""
            custom = Path(core.WIDGETS_CSS).read_text() if Path(core.WIDGETS_CSS).exists() else ""
            provider.load_from_data((fallback + theme + styles.DIRECTORY.joinpath("widgets.css").read_text() + custom).encode())
        except (OSError, GLib.Error) as error:
            log.warning("Cannot reload widget CSS; keeping previous style: %s", error)
            if self.provider is None:
                provider = Gtk.CssProvider()
                provider.load_from_data((fallback + styles.DIRECTORY.joinpath("widgets.css").read_text()).encode())
            else:
                provider = None
        if provider is not None:
            screen = self.window.get_screen()
            Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_USER + 2)
            if self.provider:
                Gtk.StyleContext.remove_provider_for_screen(screen, self.provider)
            self.provider = provider
        self.refresh_backdrop()
        self.update()

    def refresh_backdrop(self):
        state = core.load_state()
        screen = self.window.get_screen()
        width, height = screen.get_width(), screen.get_height()
        if self.area is not None:
            width, height = max(width, self.area[0] + self.area[2]), max(height, self.area[1] + self.area[3])
        radius = self.config["widget_blur_radius"] if self.config["widget_blur"] else 0
        ready = self.backdrop.load(state.get("still"), width, height, radius)
        style = self.window.get_style_context()
        (style.add_class if ready else style.remove_class)("glass-ready")
        self.canvas.queue_draw()

    def draw_glass(self, name, widget, context):
        frame = self.frames.get(name)
        if widget.get_style_context().has_class("no-blur"):
            return False
        if frame is not None and frame.container is not None and self.area is not None:
            x, y = self.canvas.child_get(frame.container, "x", "y")
            return self.backdrop.draw(widget, context, self.area[0] + x, self.area[1] + y)
        return False

    def draw_grid(self, canvas, cr):
        if not self.edit_mode or not self.config["layout_grid"]:
            return False
        gap = self.config["layout_grid_gap"]
        pitch = self.config["layout_grid_size"] + gap
        color = self.window.get_style_context().get_color(Gtk.StateFlags.NORMAL)
        cr.set_source_rgba(color.red, color.green, color.blue, .22)
        for x in range(gap, canvas.get_allocated_width(), pitch):
            for y in range(gap, canvas.get_allocated_height(), pitch):
                cr.rectangle(x, y, 2, 2)
        cr.fill()
        return False

    def queue_geometry(self, *_args):
        # GTK resolves inherited font/CSS sizes lazily. Remeasure after style changes
        # even when the old minimum request prevents a window size-allocate signal.
        if not self.closed and not self.geometry_timer:
            self.geometry_timer = GLib.idle_add(self.refresh_geometry)

    def refresh_geometry(self):
        self.geometry_timer = 0
        self.position()
        if self.drag:
            self.drag_frame()
        return False

    def card_size(self, frame):
        # Measure the content, not the container's previous grid request: otherwise
        # every resize would feed its own padding back into the next measurement.
        _minimum, natural = frame.renderer.root.widget.get_preferred_size()
        width, height = natural.width, natural.height
        if self.config["layout_grid"]:
            cell, gap = self.config["layout_grid_size"], self.config["layout_grid_gap"]
            width, height = layout.grid_extent(width, cell, gap), layout.grid_extent(height, cell, gap)
            request = (width, height)
        else:
            request = (-1, -1)
        if frame.container.get_size_request() != request:
            frame.container.set_size_request(*request)
        return width, height

    def snap_position(self, x, y, width, height):
        if self.config["layout_grid"]:
            cell, gap = self.config["layout_grid_size"], self.config["layout_grid_gap"]
            return (layout.grid_coordinate(x, width, self.area[2], cell, gap),
                    layout.grid_coordinate(y, height, self.area[3], cell, gap))
        return (max(0, min(max(0, self.area[2] - width), round(x))),
                max(0, min(max(0, self.area[3] - height), round(y))))

    def on_module_change(self, _monitor, file, _other, _event):
        if file.get_basename().endswith(".py"):
            if self.module_timer:
                GLib.source_remove(self.module_timer)
            self.module_timer = GLib.timeout_add(300, self.reload_modules)

    def reload_modules(self):
        self.module_timer = 0
        self.reload_layout()
        self.update()
        return False

    def reload_layout(self):
        try:
            placements = layout.load_layout()
        except (OSError, ValueError) as error:
            log.warning("Cannot reload layout.json; keeping the previous layout: %s", error)
            if self.has_layout:
                return
            placements = layout.load_layout(layout.DEFAULT_FILE)
        updated = {}
        for placement in placements:
            previous = self.frames.get(placement.id)
            try:
                factory = self.loader.load(placement.component) if placement.enabled else None
            except Exception:
                log.exception("Cannot load widget %s (%s)", placement.id, placement.component)
                if previous:
                    updated[placement.id] = previous
                continue
            if previous:
                if previous.component is not factory:
                    close_models(previous.models)
                previous.placement, previous.component = placement, factory
                if not self.drag or self.drag["id"] != placement.id:
                    previous.preview_scale = None
                updated[placement.id] = previous
            else:
                updated[placement.id] = LayoutWidget(placement, factory, Renderer(on_action=self.update))
        for name, frame in self.frames.items():
            if name not in updated:
                close_models(frame.models)
                frame.renderer.close()
                if frame.container is not None:
                    frame.container.destroy()
        self.frames = updated
        self.has_layout = True
        self.scale_styles()

    def scale_styles(self):
        provider = Gtk.CssProvider()
        css = "\n".join(f"#widget-{name} {{ font-size: {14 * (frame.preview_scale if frame.preview_scale is not None else frame.placement.scale):.3f}px; }}"
                        for name, frame in self.frames.items())
        provider.load_from_data(css.encode())
        screen = self.window.get_screen()
        Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_USER + 3)
        if self.scale_provider is not None:
            Gtk.StyleContext.remove_provider_for_screen(screen, self.scale_provider)
        self.scale_provider = provider

    def arrange_mode(self):
        enabled = self.config["layout_edit"]
        if enabled == self.edit_mode:
            return
        self.edit_mode = enabled
        self.stop_drag_timer()
        self.drag = None
        context = self.window.get_style_context()
        (context.add_class if enabled else context.remove_class)("layout-edit")
        # In arrange mode the cards sit above desktop icons and accept input only in their rectangles.
        self.window.hide()
        self.window.set_keep_below(not enabled)
        self.window.set_keep_above(enabled)
        self.window.set_type_hint(Gdk.WindowTypeHint.UTILITY if enabled else Gdk.WindowTypeHint.NORMAL)
        for frame in self.frames.values():
            if frame.gesture is not None:
                self.drag_phase(frame.gesture)

    def drag_phase(self, gesture):
        # A capture-phase recognizer must not compete with child button gestures.
        gesture.set_propagation_phase(Gtk.PropagationPhase.CAPTURE if self.edit_mode else Gtk.PropagationPhase.NONE)

    def input_region(self):
        native = self.window.get_window()
        if native is None:
            return
        rectangles = []
        if self.edit_mode:
            for frame in self.frames.values():
                if frame.container is not None and frame.renderer.visible:
                    x, y = self.canvas.child_get(frame.container, "x", "y")
                    width, height = frame.container.get_allocated_width(), frame.container.get_allocated_height()
                    rectangles.append(cairo.RectangleInt(x, y, max(1, width), max(1, height)))
        else:
            for frame in self.frames.values():
                if frame.container is None or not frame.renderer.visible:
                    continue
                for button in frame.renderer.buttons():
                    point = button.translate_coordinates(self.canvas, 0, 0)
                    if point is not None:
                        rectangles.append(cairo.RectangleInt(point[0], point[1],
                                          button.get_allocated_width(), button.get_allocated_height()))
        native.set_pass_through(not rectangles)
        region = cairo.Region(rectangles)
        native.input_shape_combine_region(region, 0, 0)
        return region

    def mount(self, name, frame, widget):
        if frame.container is None:
            frame.container = Gtk.EventBox()
            frame.container.set_visible_window(False)
            frame.container.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                                       | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.SCROLL_MASK)
            frame.gesture = Gtk.GestureDrag.new(frame.container)
            frame.gesture.set_button(1)
            self.drag_phase(frame.gesture)
            frame.gesture.connect("drag-begin", lambda gesture, x, y: self.gesture_begin(name, gesture, x, y))
            frame.gesture.connect("drag-update", self.gesture_motion)
            frame.gesture.connect("drag-end", self.gesture_end)
            frame.gesture.connect("cancel", lambda *_: self.cancel_drag(name))
            frame.container.connect("scroll-event", lambda _box, event: self.scroll_scale(name, event))
            frame.overlay = Gtk.Overlay()
            frame.container.add(frame.overlay)
            frame.grip = Gtk.Label(label="↘", halign=Gtk.Align.END, valign=Gtk.Align.END)
            frame.grip.get_style_context().add_class("resize-grip")
            frame.overlay.add_overlay(frame.grip)
            frame.overlay.set_overlay_pass_through(frame.grip, True)
            frame.overlay.show()
            self.canvas.put(frame.container, 0, 0)
        if widget.get_parent() is None:
            frame.overlay.add(widget)
        if widget not in self.drawn_widgets:
            widget.connect("draw", lambda current, context: self.draw_glass(name, current, context))
            widget.connect("style-updated", self.queue_geometry)
            self.drawn_widgets.add(widget)
            widget.connect("destroy", lambda current: self.drawn_widgets.discard(current))
        frame.grip.set_visible(bool(self.edit_mode))
        frame.container.set_visible(frame.renderer.visible)

    def begin_drag(self, name, event):
        if not self.edit_mode or event.button != 1 or self.area is None:
            return False
        frame = self.frames[name]
        x, y = self.canvas.child_get(frame.container, "x", "y")
        width, height = frame.container.get_allocated_width(), frame.container.get_allocated_height()
        local_x, local_y = event.x_root - self.area[0] - x, event.y_root - self.area[1] - y
        self.drag = dict(id=name, root_x=event.x_root, root_y=event.y_root, x=x, y=y,
                         width=max(1, width), height=max(1, height), scale=frame.placement.scale,
                         resize=local_x >= width - 24 and local_y >= height - 24)
        self.stop_drag_timer()
        self.drag_timer = GLib.timeout_add(16, self.drag_frame)
        return True

    def stop_drag_timer(self):
        if self.drag_timer:
            GLib.source_remove(self.drag_timer)
            self.drag_timer = 0

    def drag_frame(self):
        if not self.drag or self.drag["id"] not in self.frames:
            self.drag_timer = 0
            return False
        frame = self.frames[self.drag["id"]]
        if self.drag["resize"]:
            width, height = self.card_size(frame)
            allocation = frame.container.get_allocation()
            if (allocation.width, allocation.height) != (width, height):
                allocation.width, allocation.height = width, height
                frame.container.size_allocate(allocation)
                x, y = self.canvas.child_get(frame.container, "x", "y")
                self.move_card(frame, *self.snap_position(x, y, width, height))
                self.canvas.queue_draw()
        self.input_region()
        return True

    def gesture_begin(self, name, gesture, x, y):
        if not self.edit_mode or self.area is None:
            return
        frame = self.frames[name]
        left, top = self.canvas.child_get(frame.container, "x", "y")
        root_x, root_y = self.gesture_point(gesture, self.area[0] + left + x, self.area[1] + top + y)
        event = SimpleNamespace(button=1, x_root=root_x, y_root=root_y)
        if self.begin_drag(name, event):
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)

    @staticmethod
    def gesture_point(gesture, fallback_x, fallback_y):
        event = gesture.get_last_event(gesture.get_last_updated_sequence())
        if event is not None:
            valid, x, y = event.get_root_coords()
            if valid:
                return x, y
        return fallback_x, fallback_y

    def gesture_motion(self, gesture, dx, dy):
        if self.drag:
            x, y = self.gesture_point(gesture, self.drag["root_x"] + dx, self.drag["root_y"] + dy)
            self.drag_motion(SimpleNamespace(x_root=x, y_root=y))

    def gesture_end(self, gesture, dx, dy):
        if self.drag:
            self.gesture_motion(gesture, dx, dy)
            self.end_drag(SimpleNamespace(button=1))

    def cancel_drag(self, name):
        if self.drag and self.drag["id"] == name:
            self.stop_drag_timer()
            self.drag = None
            if name in self.frames:
                self.frames[name].preview_scale = None
            self.scale_styles()
            self.position()

    def move_card(self, frame, x, y):
        """Apply native allocation now; queued Gtk.Fixed layout alone can lag under motion."""
        self.canvas.move(frame.container, x, y)
        allocation = frame.container.get_allocation()
        allocation.x, allocation.y = x, y
        frame.container.size_allocate(allocation)
        self.canvas.queue_draw()

    def drag_motion(self, event):
        if not self.drag or self.drag["id"] not in self.frames:
            return False
        drag = self.drag
        frame = self.frames[drag["id"]]
        dx, dy = event.x_root - drag["root_x"], event.y_root - drag["root_y"]
        if drag["resize"]:
            horizontal, vertical = dx / drag["width"], dy / drag["height"]
            ratio = 1 + (horizontal if abs(horizontal) > abs(vertical) else vertical)
            frame.preview_scale = max(.5, min(2.5, drag["scale"] * ratio))
            if self.config["layout_grid"]:
                frame.preview_scale = layout.grid_scale(drag["scale"], drag["width"], drag["height"],
                                                       dx, dy, self.config["layout_grid_size"],
                                                       self.config["layout_grid_gap"])
            self.scale_styles()
            frame.container.queue_resize()
            self.canvas.queue_draw()
        else:
            width, height = frame.container.get_allocated_width(), frame.container.get_allocated_height()
            x, y = self.snap_position(drag["x"] + dx, drag["y"] + dy, width, height)
            self.move_card(frame, x, y)
        self.input_region()
        return True

    def end_drag(self, event):
        if not self.drag or event.button != 1:
            return False
        name = self.drag["id"]
        self.drag_frame()
        self.stop_drag_timer()
        self.drag = None
        frame = self.frames.get(name)
        if frame is None:
            return True
        x, y = self.canvas.child_get(frame.container, "x", "y")
        try:
            layout.save_placement(name, anchor="top-left", x=x, y=y,
                                  scale=frame.preview_scale if frame.preview_scale is not None else frame.placement.scale)
            self.reload_layout()
        except (OSError, ValueError):
            log.exception("Could not save placement for %s", name)
        self.update()
        return True

    def scroll_scale(self, name, event):
        if not self.edit_mode or self.drag:
            return False
        direction = event.direction
        if direction not in (Gdk.ScrollDirection.UP, Gdk.ScrollDirection.DOWN):
            return False
        frame = self.frames[name]
        scale = round(max(.5, min(2.5, frame.placement.scale + (.1 if direction == Gdk.ScrollDirection.UP else -.1))), 2)
        if self.config["layout_grid"]:
            width, height = self.card_size(frame)
            step = self.config["layout_grid_size"] + self.config["layout_grid_gap"]
            delta = step if direction == Gdk.ScrollDirection.UP else -step
            scale = layout.grid_scale(frame.placement.scale, width, height, delta, 0,
                                      self.config["layout_grid_size"], self.config["layout_grid_gap"])
        try:
            layout.save_placement(name, scale=scale)
            self.reload_layout()
            self.update()
        except (OSError, ValueError):
            log.exception("Could not save scale for %s", name)
        return True

    def position(self):
        if self.positioning:
            return
        display = self.window.get_display()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        if monitor is None:
            return
        self.positioning = True
        try:
            area = monitor.get_workarea()
            if area.width <= 0 or area.height <= 0:
                return
            geometry = (area.x, area.y, area.width, area.height)
            if geometry != self.area:
                self.area = geometry
                self.canvas.set_size_request(area.width, area.height)
                self.window.resize(area.width, area.height)
                self.window.move(area.x, area.y)
                self.refresh_backdrop()
            for frame in self.frames.values():
                if frame.renderer.root is None or not frame.renderer.visible:
                    continue
                if frame.container is None:
                    continue
                widget = frame.container
                width, height = self.card_size(frame)
                x, y = layout.coordinates(frame.placement, area.width, area.height,
                                           width, height, self.config["clock_top"])
                x, y = self.snap_position(x, y, width, height)
                if not self.drag or self.drag["id"] != frame.placement.id:
                    self.canvas.move(widget, x, y)
                    if self.config["layout_grid"]:
                        allocation = widget.get_allocation()
                        if (allocation.x, allocation.y, allocation.width, allocation.height) != (x, y, width, height):
                            allocation.x, allocation.y = x, y
                            allocation.width, allocation.height = width, height
                            widget.size_allocate(allocation)
            self.input_region()
        finally:
            self.positioning = False

    def update(self):
        self.arrange_mode()
        if self.config["widgets_enabled"] and not self.is_locked():
            for name, frame in self.frames.items():
                placement = frame.placement
                try:
                    enabled = placement.enabled and frame.component is not None
                    tree = frame.component(config=self.config, **placement.props) if enabled else None
                    frame.renderer.interactive = not self.edit_mode
                    with component_scope(frame.models):
                        widget = frame.renderer.render(Column(tree, visible=enabled,
                                                              class_name=f"desktop-widget {placement.class_name}"))
                    widget.set_name(f"widget-{name}")
                    self.mount(name, frame, widget)
                except Exception:
                    log.exception("Cannot render desktop widget %s", name)
            self.window.set_visible(any(frame.renderer.visible for frame in self.frames.values()))
            self.position()
        else:
            self.stop_drag_timer()
            self.drag = None
            self.window.hide()
        return True

    def close(self):
        self.closed = True
        self.stop_drag_timer()
        GLib.source_remove(self.timer)
        if self.module_timer:
            GLib.source_remove(self.module_timer)
        if self.geometry_timer:
            GLib.source_remove(self.geometry_timer)
        self.module_monitor.cancel()
        self.window.get_screen().disconnect(self.screen_handler)
        if self.provider:
            Gtk.StyleContext.remove_provider_for_screen(self.window.get_screen(), self.provider)
        for frame in self.frames.values():
            close_models(frame.models)
            frame.renderer.close()
        self.backdrop.clear()
        if self.scale_provider:
            Gtk.StyleContext.remove_provider_for_screen(self.window.get_screen(), self.scale_provider)
        self.window.destroy()

"""Translate component elements to GTK 3, reusing widgets between renders."""
from dataclasses import dataclass, field
import math

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from .components import resolve  # noqa: E402


@dataclass
class Mounted:
    element: object
    widget: object
    children: list = field(default_factory=list)

    @property
    def visible(self):
        if not self.element.props["visible"]:
            return False
        return any(child.visible for child in self.children) if self.children else True


class Renderer:
    """Render props into native GTK widgets. Use only on the GTK main thread."""
    def __init__(self, on_action=None):
        self.root = None
        self.on_action = on_action
        self.interactive = True

    def click(self, mounted):
        if self.interactive:
            mounted.element.props["on_click"]()
            if self.on_action is not None:
                self.on_action()

    @staticmethod
    def size_ring(area):
        # GtkDrawingArea does not include CSS minimum dimensions in its preferred size.
        style = area.get_style_context()
        width = max(1, style.get_property("min-width", Gtk.StateFlags.NORMAL))
        height = max(1, style.get_property("min-height", Gtk.StateFlags.NORMAL))
        if area.get_size_request() != (width, height):
            area.set_size_request(width, height)

    @staticmethod
    def draw_ring(area, cr, mounted):
        width, height = area.get_allocated_width(), area.get_allocated_height()
        radius = min(width, height) * .44
        style = area.get_style_context()
        color = style.get_color(Gtk.StateFlags.NORMAL)
        cr.set_line_width(max(1, radius * .10))
        cr.set_line_cap(1)  # Cairo ROUND
        start, sweep = math.pi * .75, math.pi * 1.5
        cr.set_source_rgba(color.red, color.green, color.blue, .15)
        cr.arc(width / 2, height / 2, radius, start, start + sweep)
        cr.stroke()
        value = mounted.element.props["value"]
        if value:
            cr.set_source_rgba(color.red, color.green, color.blue, color.alpha)
            cr.arc(width / 2, height / 2, radius, start, start + sweep * value)
            cr.stroke()
        return False

    @property
    def visible(self):
        return self.root is not None and self.root.visible

    def render(self, element):
        tree = resolve(element)
        self.root = self._reconcile(tree, self.root)
        return self.root.widget

    def _reconcile(self, element, mounted=None):
        if mounted is not None:
            old = mounted.element
            if (old.kind, old.key, old.identity) != (element.kind, element.key, element.identity):
                mounted.widget.destroy()
                mounted = None
        previous = mounted.element.props if mounted is not None else {}
        if mounted is None:
            if element.kind in ("column", "row"):
                widget = Gtk.Box(orientation=Gtk.Orientation.VERTICAL if element.kind == "column" else Gtk.Orientation.HORIZONTAL)
            elif element.kind == "text":
                widget = Gtk.Label()
            elif element.kind == "button":
                widget = Gtk.Button()
                widget.set_focus_on_click(False)
                # Keep one child across loading/ready transitions. GtkButton.set_label()
                # reconstructs its child, which can remain unallocated in the fixed canvas.
                label = Gtk.Label()
                label.show()
                widget.add(label)
            elif element.kind == "ring":
                widget = Gtk.Overlay()
                area = Gtk.DrawingArea()
                area.get_style_context().add_class("progress-ring")
                area.connect("style-updated", self.size_ring)
                area.show()
                widget.add(area)
                widget.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
                widget.content.show()
                widget.add_overlay(widget.content)
                widget.set_overlay_pass_through(widget.content, True)
            else:
                widget = Gtk.ProgressBar()
            widget.set_no_show_all(True)
            mounted = Mounted(element, widget)
            if element.kind == "button":
                widget.connect("clicked", lambda *_: self.click(mounted))
            elif element.kind == "ring":
                area.connect("draw", lambda area, cr: self.draw_ring(area, cr, mounted))
        widget = mounted.widget
        props = element.props
        if props != previous:
            context = widget.get_style_context()
            old_classes = set(previous.get("class_name", "").split())
            new_classes = set(props["class_name"].split())
            for name in old_classes - new_classes:
                context.remove_class(name)
            for name in new_classes - old_classes:
                context.add_class(name)
            widget.set_halign(getattr(Gtk.Align, props["align"].upper()))
            widget.set_hexpand(props["expand"])
            widget.set_visible(props["visible"])
            if element.kind in ("column", "row"):
                widget.set_spacing(props["spacing"])
            elif element.kind == "text":
                widget.set_text(props["text"])
                widget.set_line_wrap(props["wrap"])
                widget.set_max_width_chars(props["max_width_chars"])
                widget.set_xalign({"start": 0.0, "center": 0.5, "end": 1.0, "fill": 0.5}[props["align"]])
            elif element.kind == "button":
                if props["text"] != previous.get("text"):
                    widget.get_child().set_text(props["text"])
                    widget.queue_resize()
                    if widget.get_realized():
                        widget.size_allocate(widget.get_allocation())
                widget.set_sensitive(props["sensitive"])
            elif element.kind == "ring":
                widget.queue_draw()
            else:
                widget.set_fraction(props["value"])
                widget.set_show_text(props["text"] is not None)
                widget.set_text(props["text"])
        if element.kind in ("column", "row", "ring"):
            container = widget.content if element.kind == "ring" else widget
            old_children = mounted.children
            keyed = {child.element.key: child for child in old_children if child.element.key is not None}
            children, used = [], set()
            for index, child in enumerate(element.children):
                old = keyed.get(child.key) if child.key is not None else (
                    old_children[index] if index < len(old_children) and old_children[index].element.key is None else None)
                if old is not None:
                    used.add(id(old))
                rendered = self._reconcile(child, old)
                expand = child.props["expand"]
                if rendered.widget.get_parent() is None:
                    container.pack_start(rendered.widget, expand, expand, 0)
                container.set_child_packing(rendered.widget, expand, expand, 0, Gtk.PackType.START)
                container.reorder_child(rendered.widget, index)
                children.append(rendered)
            for child in old_children:
                if id(child) not in used:
                    child.widget.destroy()
            mounted.children = children
            if element.kind == "ring":
                # Overlay child requisitions don't change the ring's outer size. Allocate
                # its box again so a wider hours value gets its new natural width.
                container.queue_resize()
                if container.get_realized():
                    container.size_allocate(container.get_allocation())
        mounted.element = element
        return mounted

    def find(self, key):
        """Return a native widget by its key, for inspection or native GTK integration."""
        def walk(node):
            if node.element.key == key:
                return node.widget
            for child in node.children:
                found = walk(child)
                if found is not None:
                    return found
            return None
        return walk(self.root) if self.root is not None else None

    def buttons(self):
        def walk(node):
            if node.element.kind == "button" and node.widget.get_mapped():
                yield node.widget
            for child in node.children:
                yield from walk(child)
        return tuple(walk(self.root)) if self.root is not None else ()

    def close(self):
        if self.root is not None:
            self.root.widget.destroy()
            self.root = None

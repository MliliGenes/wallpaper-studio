"""User-editable desktop layout and component discovery. No GTK dependency."""
from dataclasses import dataclass, field
import importlib.util
import json
import logging
import math
from pathlib import Path
import re
import sys

from . import storage
from .widgets import WIDGETS
from . import settings

DEFAULT_FILE = Path(__file__).with_name("desktop_layout.json")
ANCHORS = tuple(f"{vertical}-{horizontal}" for vertical in ("top", "center", "bottom")
                for horizontal in ("left", "center", "right"))
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*\Z")
MODULE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Placement:
    id: str
    component: str
    anchor: str = "top-left"
    x: int = 0
    y: object = None
    enabled: bool = True
    class_name: str = ""
    props: dict = field(default_factory=dict)
    scale: float = 1


def parse_layout(document):
    if not isinstance(document, dict) or document.get("version") != 1:
        raise ValueError("layout.json must be an object with version: 1")
    if set(document) - {"version", "widgets"}:
        raise ValueError("Unknown desktop layout option")
    entries = document.get("widgets")
    if not isinstance(entries, list):
        raise ValueError("layout.json needs a widgets list")
    result, ids = [], set()
    allowed = set(Placement.__dataclass_fields__)
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) - allowed:
            raise ValueError("Each layout widget must be an object with supported placement options")
        for key in ("id", "component"):
            value = entry.get(key)
            if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
                raise ValueError(f"Widget {key} must be a simple name, for example 'clock'")
        if entry["id"] in ids:
            raise ValueError(f"Duplicate widget id: {entry['id']}")
        ids.add(entry["id"])
        placement = Placement(**entry)
        if placement.anchor not in ANCHORS:
            raise ValueError(f"Unknown anchor: {placement.anchor}; use one of {', '.join(ANCHORS)}")
        for name, value in (("x", placement.x), ("y", placement.y)):
            if name == "y" and value is None:
                continue
            if type(value) is not int or not -20000 <= value <= 20000:
                raise ValueError(f"Widget {name} must be an integer between -20000 and 20000")
        if type(placement.enabled) is not bool:
            raise ValueError("Widget enabled must be true or false")
        if type(placement.scale) not in (int, float) or not math.isfinite(placement.scale) or not .5 <= placement.scale <= 2.5:
            raise ValueError("Widget scale must be between 0.5 and 2.5")
        if not isinstance(placement.class_name, str) or any(not IDENTIFIER.fullmatch(name) for name in placement.class_name.split()):
            raise ValueError("class_name must contain simple space-separated CSS classes")
        if not isinstance(placement.props, dict) or "config" in placement.props or "key" in placement.props:
            raise ValueError("Widget props must be an object; config and key are supplied by the runtime")
        result.append(placement)
    return tuple(result)


def load_layout(path=None):
    with open(path or storage.LAYOUT) as source:
        return parse_layout(json.load(source))


def ensure_layout():
    Path(storage.CONFIG_DIR).mkdir(parents=True, exist_ok=True)
    Path(storage.CUSTOM_WIDGETS).mkdir(parents=True, exist_ok=True)
    try:
        with open(storage.LAYOUT, "x") as target:
            target.write(DEFAULT_FILE.read_text())
    except FileExistsError:
        # Upgrade only the exact former starter layout; never overwrite custom placements.
        legacy = {"version": 1, "widgets": [{"id": "clock", "component": "Clock", "anchor": "top-center",
                  "x": 0, "enabled": True, "class_name": "clock-placement", "props": {}}]}
        if storage.read_json(storage.LAYOUT, {}) == legacy:
            storage.write(storage.LAYOUT, DEFAULT_FILE.read_text())
        else:
            current_default = json.loads(DEFAULT_FILE.read_text())
            for omitted in ({"NowPlaying"}, {"Logtime"}, {"NowPlaying", "Logtime"}):
                previous_default = {**current_default, "widgets": [entry for entry in current_default["widgets"]
                                                                  if entry["component"] not in omitted]}
                if storage.read_json(storage.LAYOUT, {}) == previous_default:
                    storage.write(storage.LAYOUT, DEFAULT_FILE.read_text())
                    break

    # Make the new built-in discoverable in both control panels without moving existing cards.
    with storage.locked():
        document = storage.read_json(storage.LAYOUT, {})
        try:
            placements = parse_layout(document)
        except ValueError:
            return  # Leave malformed user edits for the normal reload/error handling.
        if placements and not any(item.component == "NowPlaying" for item in placements):
            entry = next(item.copy() for item in json.loads(DEFAULT_FILE.read_text())["widgets"]
                         if item["component"] == "NowPlaying")
            ids = {item.id for item in placements}
            base, suffix = entry["id"], 2
            while entry["id"] in ids:
                entry["id"] = f"{base}-{suffix}"
                suffix += 1
            document["widgets"].append(entry)
            storage.write(storage.LAYOUT, json.dumps(document, indent=2) + "\n")


def save_placement(widget_id, **changes):
    """Persist one drag/resize against the latest document without discarding other edits."""
    with storage.locked():
        with open(storage.LAYOUT) as source:
            document = json.load(source)
        parse_layout(document)
        entry = next((entry for entry in document["widgets"] if entry["id"] == widget_id), None)
        if entry is None:
            raise ValueError(f"Widget no longer exists in the layout: {widget_id}")
        entry.update(changes)
        parse_layout(document)
        storage.write(storage.LAYOUT, json.dumps(document, indent=2) + "\n")


def widget_enabled(placement, config):
    return placement.enabled and (placement.component != "Clock" or config["clock"])


def set_enabled(widget_id, enabled):
    if type(enabled) is not bool:
        raise ValueError("Widget enabled must be true or false")
    placement = next((item for item in load_layout() if item.id == widget_id), None)
    if placement is None:
        raise ValueError(f"Unknown widget: {widget_id}")
    if enabled and placement.component == "Clock" and not settings.load_config()["clock"]:
        # Enabling one clock must not also wake other instances hidden by the legacy clock preference.
        for other in load_layout():
            if other.component == "Clock" and other.id != widget_id:
                save_placement(other.id, enabled=False)
        settings.save_config(clock=True)
    save_placement(widget_id, enabled=enabled)


def widget_title(placement):
    title = placement.props.get("title") or {"Clock": "Clock", "Calendar": "Calendar", "System": "System stats", "Notes": "Notes", "NowPlaying": "Now playing"}.get(placement.component, placement.component)
    return str(title) if placement.id.replace("-", "").lower() == placement.component.lower() else f"{title} ({placement.id})"


def coordinates(placement, area_width, area_height, widget_width, widget_height, clock_top=32):
    """Offsets are inward from the selected edge; centred offsets move right/down."""
    vertical, horizontal = placement.anchor.split("-")
    free_x, free_y = max(0, area_width - widget_width), max(0, area_height - widget_height)
    offset_y = placement.y if placement.y is not None else clock_top if placement.component == "Clock" else 0
    x = placement.x if horizontal == "left" else free_x - placement.x if horizontal == "right" else free_x // 2 + placement.x
    y = offset_y if vertical == "top" else free_y - offset_y if vertical == "bottom" else free_y // 2 + offset_y
    return max(0, min(free_x, x)), max(0, min(free_y, y))


def grid_extent(size, cell, gap):
    """Smallest whole-cell footprint containing the content, excluding its last gutter."""
    return max(1, math.ceil((size + gap) / (cell + gap))) * (cell + gap) - gap


def grid_coordinate(value, extent, available, cell, gap):
    """Snap to the nearest origin that fits, with a gutter at the work-area edges."""
    pitch = cell + gap
    last = math.floor((available - extent - 2 * gap) / pitch)
    if last < 0:
        return max(0, min(max(0, available - extent), gap))
    index = math.floor((value - gap) / pitch + .5)
    return gap + max(0, min(last, index)) * pitch


def grid_scale(scale, width, height, dx, dy, cell, gap):
    """Resize uniformly, snapping the dominant edge to a whole grid span."""
    size, delta = (width, dx) if abs(dx / width) >= abs(dy / height) else (height, dy)
    pitch = cell + gap
    cells = max(1, math.floor((size + delta + gap) / pitch + .5))
    return max(.5, min(2.5, scale * (cells * pitch - gap) / size))


class ComponentLoader:
    """Resolve built-ins or user modules exporting a callable named Widget."""
    def __init__(self):
        self.builtins = {widget.__name__: widget for widget in WIDGETS}
        self.cache = {}

    def load(self, name):
        if name in self.builtins:
            return self.builtins[name]
        if not MODULE_NAME.fullmatch(name):
            raise ValueError(f"Custom component names must be Python module names: {name}")
        path = Path(storage.CUSTOM_WIDGETS) / f"{name}.py"
        previous = self.cache.get(name)
        try:
            stat = path.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
            if previous and previous[0] == signature:
                return previous[1]
            module_name = f"wallpaper_studio_custom_{name}"
            spec = importlib.util.spec_from_file_location(module_name, path)
            module = importlib.util.module_from_spec(spec)
            old_module = sys.modules.get(module_name)
            sys.modules[module_name] = module
            try:
                # Compile the current source directly; rapid edits must not reuse stale bytecode.
                exec(compile(path.read_text(), str(path), "exec"), module.__dict__)
                factory = getattr(module, "Widget", None)
                if not callable(factory):
                    raise ValueError(f"{path.name} must export a @component function named Widget")
            except Exception:
                if old_module is None:
                    sys.modules.pop(module_name, None)
                else:
                    sys.modules[module_name] = old_module
                raise
            self.cache[name] = (signature, factory)
            return factory
        except Exception:
            if previous:
                log.exception("Cannot reload %s; keeping its last working component", name)
                return previous[1]
            raise

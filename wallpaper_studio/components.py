"""Small declarative widget vocabulary. Components are ordinary Python functions.

This module has no GTK dependency: component trees can be composed and tested headlessly.
"""
from dataclasses import dataclass, field, replace
from functools import wraps
from contextlib import contextmanager
from contextvars import ContextVar
import math

_models = ContextVar("widget_models", default=None)


@contextmanager
def component_scope(models):
    """Give one layout instance its own persistent models during rendering."""
    token = _models.set(models)
    try:
        yield
    finally:
        _models.reset(token)


def use_model(factory, key="model"):
    """Keep a model across renders; the runtime calls close() when it unmounts."""
    models = _models.get()
    if models is None:
        raise RuntimeError("use_model requires a desktop component scope")
    if key not in models:
        models[key] = factory()
    return models[key]


def close_models(models):
    for model in models.values():
        close = getattr(model, "close", None)
        if close is not None:
            close()
    models.clear()


@dataclass(frozen=True)
class Element:
    kind: object
    props: dict = field(default_factory=dict)
    children: tuple = ()
    key: object = None
    identity: tuple = ()


def component(function):
    """Defer a function component until rendering, passing its keyword props."""
    @wraps(function)
    def element(*, key=None, **props):
        return Element(function, props, key=key)
    return element


def _children(values):
    for value in values:
        if value is None or value is False:
            continue
        if isinstance(value, (tuple, list)):
            yield from _children(value)
        elif isinstance(value, Element):
            yield value
        else:
            raise TypeError("Children must be components, Text/Row/Column/Progress elements, or None.")


def _props(class_name, visible, expand, align):
    if not isinstance(class_name, str):
        raise TypeError("class_name must be a space-separated string of CSS classes")
    if type(visible) is not bool or type(expand) is not bool:
        raise TypeError("visible and expand must be booleans")
    if align not in ("fill", "start", "center", "end"):
        raise ValueError("align must be fill, start, center or end")
    return dict(class_name=class_name, visible=visible, expand=expand, align=align)


def _box(kind, children, spacing, class_name, visible, expand, align, key):
    if type(spacing) is not int or spacing < 0:
        raise ValueError("spacing must be a nonnegative integer")
    props = _props(class_name, visible, expand, align)
    props["spacing"] = spacing
    return Element(kind, props, tuple(_children(children)), key)


def Column(*children, spacing=0, class_name="", visible=True, expand=False, align="fill", key=None):
    return _box("column", children, spacing, class_name, visible, expand, align, key)


def Row(*children, spacing=0, class_name="", visible=True, expand=False, align="fill", key=None):
    return _box("row", children, spacing, class_name, visible, expand, align, key)


def Text(text="", *, class_name="", visible=True, expand=False, align="center", wrap=False, max_width_chars=-1, key=None):
    props = _props(class_name, visible, expand, align)
    props["text"] = str(text)
    if type(wrap) is not bool or type(max_width_chars) is not int or max_width_chars < -1:
        raise ValueError("wrap must be a boolean and max_width_chars must be -1 or a nonnegative integer")
    props.update(wrap=wrap, max_width_chars=max_width_chars)
    return Element("text", props, key=key)


def Progress(value=0, *, text=None, class_name="", visible=True, expand=False, align="fill", key=None):
    value = float(value)
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError("Progress value must be between 0 and 1")
    props = _props(class_name, visible, expand, align)
    props.update(value=value, text=None if text is None else str(text))
    return Element("progress", props, key=key)


def Button(text, *, on_click, sensitive=True, tooltip="", class_name="", visible=True, expand=False, align="fill", key=None):
    if not callable(on_click) or type(sensitive) is not bool:
        raise TypeError("Button needs an on_click callback and boolean sensitive")
    props = _props(class_name, visible, expand, align)
    props.update(text=str(text), on_click=on_click, sensitive=sensitive, tooltip=str(tooltip))
    return Element("button", props, key=key)


def Image(data=None, *, class_name="", visible=True, expand=False, align="center", key=None):
    """Encoded image bytes; loading belongs in a scoped background model."""
    if data is not None and not isinstance(data, bytes):
        raise TypeError("Image data must be bytes or None")
    props = _props(class_name, visible, expand, align)
    props["data"] = data
    return Element("image", props, key=key)


def Ring(value, *children, class_name="", visible=True, expand=False, align="center", key=None):
    """A 270-degree progress arc surrounding ordinary component children."""
    props = Progress(value, class_name=class_name, visible=visible, expand=expand, align=align).props
    return Element("ring", props, tuple(_children(children)), key)


def resolve(element, _depth=0):
    """Evaluate function components and validate the whole tree before touching GTK."""
    if _depth > 64:
        raise ValueError("Component tree is too deep; check for a component rendering itself.")
    if element is None:
        return Column(visible=False)
    if not isinstance(element, Element):
        raise TypeError("A component must return an element or None")
    if element.key is not None and type(element.key) not in (str, int):
        raise TypeError("Element keys must be strings or integers")
    if callable(element.kind):
        result = resolve(element.kind(**element.props), _depth + 1)
        return replace(result, key=element.key if element.key is not None else result.key,
                       identity=(element.kind, *result.identity))
    if element.kind not in ("column", "row", "text", "progress", "button", "ring", "image"):
        raise ValueError(f"Unknown element: {element.kind}")
    children = tuple(resolve(child, _depth + 1) for child in element.children)
    keys = [child.key for child in children if child.key is not None]
    if len(keys) != len(set(keys)):
        raise ValueError("Sibling components must have unique keys")
    return replace(element, children=children)

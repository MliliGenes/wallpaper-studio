"""Clock component: data and layout only; GTK rendering is handled by the framework."""
import time

from ..components import Column, Text, component


@component
def Clock(config):
    now = time.localtime()
    return Column(
        Text(time.strftime(config["clock_format"], now), class_name="clock-time", key="time"),
        Text(time.strftime(config["clock_date_format"], now), class_name="clock-date",
             visible=bool(config["clock_date_format"]), key="date"),
        spacing=10,
        class_name="desktop-clock",
        visible=config["clock"],
    )

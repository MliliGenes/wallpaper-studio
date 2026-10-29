"""Logtime card: a scoped model supplies data; reusable elements describe its UI."""
from ..components import Button, Column, Ring, Row, Text, component, use_model
from ..logtime import LogtimeModel


@component
def Logtime(config, username=None, goal=None):
    model = use_model(LogtimeModel, key="logtime")
    username = config["logtime_username"] if username is None else username
    goal = config["logtime_goal"] if goal is None else goal
    from ..settings import validate
    username = validate("logtime_username", username)
    goal = validate("logtime_goal", goal)
    data = model.view(username)
    hours = data["hours"]
    fraction = min(1, hours / goal) if hours is not None else 0
    status = ("Set logtime_username in settings" if not username else data["error"] or
              ("Updating…" if data["loading"] and hours is not None else "Loading…" if data["loading"] else f"Goal · {goal:g} hours"))
    return Column(
        Text(username.upper() if username else "LOGTIME", class_name="logtime-login", key="login"),
        Ring(fraction,
             Text(f"{fraction:.0%}" if hours is not None else "—", class_name="logtime-percent", key="percent"),
             Text(f"{hours:g}" if hours is not None else "—", class_name="logtime-hours", key="hours"),
             Text("Hours", class_name="logtime-unit"), class_name="logtime-ring", key="ring"),
        Text(data["start"].strftime("%B %Y"), class_name="widget-label", key="month"),
        Text(f'{data["start"]:%b %d, %Y} – {data["end"]:%b %d, %Y}', class_name="logtime-period", key="period"),
        Row(Button("Prev", on_click=lambda: model.shift(-1), expand=True, key="prev"),
            Button("Next", on_click=lambda: model.shift(1), expand=True, key="next"), spacing=8),
        Button("Updating…" if data["loading"] else "Refresh", on_click=model.refresh,
               sensitive=bool(username) and not data["loading"], key="refresh"),
        Text(status, wrap=True, max_width_chars=30, class_name="logtime-status", key="status"),
        spacing=8, class_name="logtime-card",
    )

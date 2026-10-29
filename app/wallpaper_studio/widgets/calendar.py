"""A live month calendar with today's date highlighted."""
import calendar
from datetime import date

from ..components import Column, Row, Text, component


@component
def Calendar(config):
    today = date.today()
    weeks = calendar.monthcalendar(today.year, today.month)
    return Column(
        Text(today.strftime("%B %Y").upper(), class_name="widget-label", align="start"),
        Text(str(today.day), class_name="calendar-day", align="start"),
        Row([Text(day, class_name="calendar-weekday", expand=True, key=day)
             for day in ("M", "T", "W", "Th", "F", "S", "Su")], spacing=2),
        [Row([Text(str(day) if day else "", key=column, expand=True,
                   class_name="calendar-cell today" if day == today.day else "calendar-cell")
              for column, day in enumerate(week)], key=index, spacing=2)
         for index, week in enumerate(weeks)],
        spacing=4,
        class_name="calendar-card",
    )

"""Built-in components. layout.json composes these and user-defined widgets."""
from .clock import Clock
from .calendar import Calendar
from .notes import Notes
from .system import System
from .logtime import Logtime
from .cleaner import Cleaner

WIDGETS = (Clock, Calendar, System, Notes, Logtime, Cleaner)


__all__ = ["Clock", "Calendar", "System", "Notes", "Logtime", "Cleaner", "WIDGETS"]

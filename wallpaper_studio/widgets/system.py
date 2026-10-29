"""Actual Linux CPU/memory and home-filesystem usage, sampled once per second."""
from pathlib import Path
import shutil
import time

from ..components import Column, Progress, Row, Text, component


class SystemStats:
    def __init__(self):
        self.previous_cpu = None
        self.cached_at = 0
        self.cached = {}

    def sample(self):
        now = time.monotonic()
        if self.cached and now - self.cached_at < .9:
            return self.cached
        values = {"CPU": None, "Memory": None, "Disk": None}
        try:
            cpu = [int(value) for value in Path("/proc/stat").read_text().splitlines()[0].split()[1:9]]
            total, idle = sum(cpu), cpu[3] + cpu[4]
            if self.previous_cpu:
                previous_total, previous_idle = self.previous_cpu
                if total > previous_total:
                    values["CPU"] = max(0, min(1, 1 - (idle - previous_idle) / (total - previous_total)))
            self.previous_cpu = total, idle
        except (OSError, ValueError, IndexError):
            pass
        try:
            memory = {line.split(":")[0]: int(line.split()[1]) for line in Path("/proc/meminfo").read_text().splitlines()}
            values["Memory"] = max(0, min(1, 1 - memory["MemAvailable"] / memory["MemTotal"]))
        except (OSError, ValueError, KeyError, ZeroDivisionError, IndexError):
            pass
        try:
            disk = shutil.disk_usage(Path.home())
            values["Disk"] = disk.used / disk.total
        except (OSError, ZeroDivisionError):
            pass
        self.cached_at, self.cached = now, values
        return values


STATS = SystemStats()


@component
def System(config):
    values = STATS.sample()
    return Column(
        Text("SYSTEM", class_name="widget-label", align="start"),
        [Column(
            Row(Text(name, align="start", expand=True),
                Text(f"{value:.0%}" if value is not None else "Measuring…", class_name="metric-value")),
            Progress(value or 0, visible=value is not None),
            spacing=5, key=name,
        ) for name, value in values.items()],
        spacing=12,
        class_name="system-card",
    )

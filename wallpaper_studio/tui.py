"""Interactive terminal control panel. Uses curses and the existing CLI, never GTK."""
import curses
from dataclasses import dataclass
import locale
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import textwrap
import time

from . import layout, media, settings, storage, styles

PAGES = ("Wallpapers", "Appearance", "Widgets", "Screen", "Tools")
LABELS = {
    "mode": "Colour mode", "light_from": "Light from (hour)", "dark_from": "Dark from (hour)",
    "glass": "Transparent windows", "terminal": "Recolour Terminal", "lock_screen": "Lock-screen picture",
    "clock": "Desktop clock", "clock_format": "Time format", "clock_date_format": "Date format",
    "clock_top": "Distance below top panel", "folder": "Wallpaper folder", "rotate_hours": "Rotate every (hours)",
    "awake_method": "Keep-awake method", "awake_interval": "Movement interval (seconds)",
    "widgets_enabled": "Show all widgets", "layout_edit": "Arrange widgets with mouse",
    "widget_blur": "Frosted widget glass", "widget_blur_radius": "Glass blur radius",
    "logtime_username": "Logtime username", "logtime_goal": "Logtime goal (hours)",
}
CHOICES = {"mode": ("light", "dark", "auto"), "awake_method": ("mouse", "inhibit")}


@dataclass
class Item:
    label: str
    value: str = ""
    detail: str = ""
    setting: str = ""
    command: tuple = ()
    action: str = ""


def awake_status(request, now=None):
    until = request.get("until")
    now = time.time() if now is None else now
    if until == -1:
        return "On until logout / turned off"
    if isinstance(until, (int, float)) and until > now:
        minutes = max(1, int((until - now + 59) // 60))
        return f"On for {minutes} more min (until {time.strftime('%H:%M', time.localtime(until))})"
    return "Off"


class CommandJob:
    """Capture child output in a file so it cannot corrupt curses or block on a full pipe."""
    def __init__(self, command):
        self.output = tempfile.TemporaryFile(mode="w+t", encoding="utf-8", errors="replace")
        launcher = str(Path(__file__).resolve().parents[1] / "wallpaper-studio")
        try:
            self.process = subprocess.Popen([sys.executable, launcher, *command],
                                            stdin=subprocess.DEVNULL, stdout=self.output,
                                            stderr=subprocess.STDOUT, start_new_session=True)
        except OSError:
            self.output.close()
            raise

    def result(self):
        code = self.process.poll()
        if code is None:
            return None
        self.process.wait()
        self.output.seek(0)
        return code, self.output.read(16000).strip()

    def close(self):
        # A requested change may finish after the panel closes; the desktop helper is independent.
        self.output.close()


class Panel:
    def __init__(self, screen):
        self.screen = screen
        self.page = self.selected = self.offset = 0
        self.focus = "list"
        self.preview_offset = 0
        self.selections = [0] * len(PAGES)
        self.offsets = [0] * len(PAGES)
        self.search = ""
        self.message = "Choose a section, then select a setting or wallpaper."
        self.last_result = self.message
        self.job = None
        self.files = []
        self.folder = None
        self.refresh_at = 0
        self.accent = curses.A_BOLD
        self.screen.keypad(True)
        self.screen.timeout(200)
        self.cursor(False)
        if curses.has_colors():
            try:
                curses.use_default_colors()
                curses.init_pair(1, curses.COLOR_GREEN, -1)
                self.accent |= curses.color_pair(1)
            except curses.error:
                pass
        self.refresh()

    @staticmethod
    def cursor(visible):
        try:
            curses.curs_set(int(visible))
        except curses.error:
            pass

    def refresh(self, scan=False):
        self.config = settings.load_config()
        self.state = storage.read_json(storage.STATE, {})
        self.awake = storage.read_json(storage.AWAKE, {})
        try:
            self.placements = layout.load_layout()
        except (OSError, ValueError):
            self.placements = getattr(self, "placements", layout.load_layout(layout.DEFAULT_FILE))
        self.clock_active = any(item.component == "Clock" and layout.widget_enabled(item, self.config) for item in self.placements)
        if scan or self.folder != self.config["folder"]:
            self.folder = self.config["folder"]
            self.files = media.wallpapers(self.folder)
        self.refresh_at = time.monotonic() + 1

    def preference(self, key):
        value = self.config[key]
        display = ("On" if value else "Off") if isinstance(value, bool) else str(value)
        if display == "":
            display = "(hidden)"
        return Item(LABELS[key], display, settings.DESCRIPTIONS[key], setting=key)

    def items(self):
        if self.page == 0:
            rows = [Item("Next random wallpaper", detail="Choose a different image or video from your folder.", command=("next",)),
                    Item("Open a file...", detail="Enter a full image or video path.", action="file"),
                    self.preference("folder"), self.preference("rotate_hours")]
            current = self.state.get("wallpaper", "")
            for path in self.files:
                name = Path(path).name
                if self.search.casefold() not in name.casefold():
                    continue
                rows.append(Item(name, "Current" if os.path.realpath(path) == current else "Video" if media.is_video(path) else "Picture",
                                 path, command=("set", path)))
            if len(rows) == 4:
                rows.append(Item("No matching wallpapers", detail="Change folder, open a file, or clear the search."))
            return rows
        keys = {
            1: ("mode", "glass", "terminal", "lock_screen", "light_from", "dark_from"),
            2: ("clock", "clock_format", "clock_date_format", "clock_top", "widgets_enabled", "layout_edit", "widget_blur", "widget_blur_radius", "logtime_username", "logtime_goal"),
            3: ("awake_method", "awake_interval"),
        }
        if self.page in keys:
            rows = [self.preference(key) for key in keys[self.page]]
            if self.page == 2:
                placements = self.placements
                clock = next((item for item in placements if item.component == "Clock"), None)
                if clock:
                    rows[0] = Item(layout.widget_title(clock), "On" if layout.widget_enabled(clock, self.config) else "Off",
                                   "Toggle this clock independently", command=("layout", "toggle", clock.id))
                rows.extend(Item(layout.widget_title(placement),
                                 "On" if layout.widget_enabled(placement, self.config) else "Off",
                                 f"Toggle this widget independently · {placement.anchor} · {placement.scale:g}×",
                                 command=("layout", "toggle", placement.id)) for placement in placements if placement is not clock)
                rows.append(Item("Edit widget CSS", detail=storage.WIDGETS_CSS, action="widgets_css"))
                rows.append(Item("Edit desktop layout", detail=storage.LAYOUT, action="layout"))
            if self.page == 3:
                rows.insert(0, Item("Keep screen awake...", awake_status(self.awake),
                                    "Enter minutes, 'on' until logout, or 'off'.", action="awake"))
                rows.extend([Item("Keep awake for one hour", command=("awake", "60")),
                             Item("Turn keep-awake off", command=("awake", "off"))])
            return rows
        return [Item("Reapply current colours", command=("apply",)),
                Item("Edit widget CSS", detail=storage.WIDGETS_CSS, action="widgets_css"),
                Item("Edit control-panel CSS", detail=storage.APP_CSS, action="app_css"),
                Item("View helper log", detail="Recent desktop helper diagnostics.", action="log"),
                Item("Restore original desktop", detail="Undo the wallpaper/theme; hide the clock and stop keep-awake.", action="restore"),
                Item("Reset all preferences", detail="Reset preferences to defaults and apply them.", action="reset"),
                Item("Preferences file", storage.CONFIG, "Preferences and changes are shared with the graphical control panel."),
                Item("Edit desktop layout", detail=storage.LAYOUT, action="layout")]

    def text(self, row, col, value, attr=0, limit=None):
        height, width = self.screen.getmaxyx()
        if 0 <= row < height and 0 <= col < width:
            clean = "".join(char if char.isprintable() else " " for char in str(value))
            try:
                size = max(0, width - col)
                self.screen.addnstr(row, col, clean, size if limit is None else min(size, max(0, limit)), attr)
            except curses.error:
                pass  # resizing and wide Unicode characters can hit the bottom-right cell

    def frame(self, y, x, height, width, title, active=False):
        attr = self.accent if active else curses.A_DIM
        if height == 1:
            self.text(y, x, f"─ {title} " + "─" * width, attr, width)
            return
        self.text(y, x, "┌" + "─" * (width - 2) + "┐", attr, width)
        for row in range(y + 1, y + height - 1):
            self.text(row, x, "│", attr)
            self.text(row, x + width - 1, "│", attr)
        self.text(y + height - 1, x, "└" + "─" * (width - 2) + "┘", attr, width)
        self.text(y, x + 2, f" {title} ", attr, width - 4)

    def layout(self):
        height, width = self.screen.getmaxyx()
        body = height - 3
        left = max(26, min(44, width * 36 // 100))
        compact = body < 20
        status = 2 if compact else 3
        collapsed = 1 if compact else 2
        active = body - status - collapsed * (len(PAGES) - 1)
        log = max(4, min(8, body // 4))
        return left, body, status, collapsed, active, log

    def switch_page(self, page):
        self.selections[self.page], self.offsets[self.page] = self.selected, self.offset
        self.page = page % len(PAGES)
        self.selected, self.offset = self.selections[self.page], self.offsets[self.page]
        self.focus = "list"
        self.preview_offset = 0

    @staticmethod
    def wrapped(lines, width):
        result = []
        for line in lines:
            result.extend(textwrap.wrap(str(line), max(1, width), replace_whitespace=True) or [""])
        return result

    def details(self, item):
        lines = [item.label, ""]
        if self.page == 2:
            lines += ["── CLOCK PREVIEW ──", "", time.strftime(self.config["clock_format"]),
                      time.strftime(self.config["clock_date_format"]), ""]
        if item.value:
            lines += [f"Current: {item.value}", ""]
        if item.detail:
            lines += [item.detail, ""]
        if item.setting:
            key = item.setting
            lines += [f"Setting: {key}", f"Default: {settings.DEFAULT_CONFIG[key]}"]
            if key in CHOICES:
                lines.append("Options: " + " / ".join(CHOICES[key]))
            lines += ["", "Enter / e: toggle or edit this setting."]
        elif item.command and item.command[0] == "set":
            path = Path(item.command[1])
            try:
                lines.append(f"Size: {path.stat().st_size / 1024 / 1024:.2f} MiB")
            except OSError:
                lines.append("This file is no longer available.")
            lines += ["", "Enter / Space: apply this wallpaper."]
        elif item.action or item.command:
            lines += ["Enter / e: open or apply."]
        if self.page == 2:
            lines += ["", f"Placement: top centre, offset {self.config['clock_top']} px",
                      "Style: widgets.css (.desktop-clock / .clock-time / .clock-date)"]
        if self.page == 0:
            lines += ["", f"Library: {len(self.files)} files", f"Folder: {self.folder}",
                      f"Filter: {self.search or '(all)'}", "", "/ filter filenames   n next random wallpaper"]
        if self.page == 3:
            lines += ["", "── SCREEN STATUS ──", awake_status(self.awake),
                      "The pointer moves to (0, 0) and back only while keep-awake is enabled and the session is unlocked."]
        state_path = self.state.get("wallpaper")
        lines += ["", "── DESKTOP ──", Path(state_path).name if state_path else "No wallpaper selected",
                  f"Colour mode: {self.config['mode']}", f"Clock: {'on' if self.clock_active else 'off'}"]
        if not os.environ.get("DISPLAY"):
            lines += ["", "No X11 display. Saved preferences apply at your next desktop session."]
        return lines

    def draw(self):
        self.screen.erase()
        height, width = self.screen.getmaxyx()
        self.text(0, 1, "WALLPAPER STUDIO", self.accent)
        if height < 16 or width < 60:
            self.text(2, 1, "Resize to at least 60 columns x 16 rows. Q quits.")
            self.screen.refresh()
            return
        self.text(0, max(20, width - 34), "GNOME / X11" if os.environ.get("DISPLAY") else "configuration only", curses.A_DIM)
        left, body, status, collapsed, active, log = self.layout()
        rows = self.items()
        self.selected = max(0, min(self.selected, len(rows) - 1))
        available = max(1, active - 2)
        self.offset = max(0, min(self.offset, self.selected))
        if self.selected >= self.offset + available:
            self.offset = self.selected - available + 1
        self.frame(1, 0, status, left, "Session")
        if status > 2:
            self.text(2, 2, f"{self.config['mode']}  |  clock {'on' if self.clock_active else 'off'}", limit=left - 4)
        y = 1 + status
        for index, title in enumerate(PAGES):
            current = index == self.page
            panel_height = active if current else collapsed
            heading = f"[{index + 1}] {title}"
            if current:
                heading += f" {self.selected + 1}/{len(rows)}"
            self.frame(y, 0, panel_height, left, heading, current and self.focus == "list")
            if current:
                for row, item in enumerate(rows[self.offset:self.offset + available]):
                    selected = self.offset + row == self.selected
                    value = f"  {item.value}" if item.value else ""
                    label = f"{'›' if selected else ' '} {item.label}{value}"
                    self.text(y + 1 + row, 1, label.ljust(left - 2),
                              curses.A_REVERSE if selected else 0, left - 2)
            y += panel_height
        right_x, right_width = left, width - left
        detail_height = body - log
        self.frame(1, right_x, detail_height, right_width, "[6] Preview / details", self.focus == "detail")
        lines = self.wrapped(self.details(rows[self.selected]), right_width - 4)
        count = max(1, detail_height - 2)
        self.preview_offset = max(0, min(self.preview_offset, max(0, len(lines) - count)))
        for index, line in enumerate(lines[self.preview_offset:self.preview_offset + count]):
            self.text(index + 2, right_x + 2, line, self.accent if index == 0 and self.preview_offset == 0 else 0, right_width - 4)
        if len(lines) > count:
            self.text(detail_height, right_x + 3, f" {self.preview_offset + 1}-{min(len(lines), self.preview_offset + count)}/{len(lines)} · l focus, j/k scroll ", curses.A_DIM, right_width - 6)
        self.frame(1 + detail_height, right_x, log, right_width, "Command output")
        output = self.wrapped((self.message if self.job else self.last_result).splitlines(), right_width - 4)
        for index, line in enumerate(output[:log - 2]):
            self.text(2 + detail_height + index, right_x + 2, line, limit=right_width - 4)
        self.text(height - 2, 1, ("Working... " if self.job else "") + self.message, self.accent)
        hints = "1-5/Tab panels  h/l focus  j/k move  Enter edit  / filter  n next  ? help  q quit"
        if width < 82:
            hints = "1-5 panels  h/l focus  j/k move  Enter edit  ? help  q quit"
        self.text(height - 1, 1, hints, curses.A_DIM)
        self.screen.refresh()

    def popup(self, title, height=8, width=76):
        screen_height, screen_width = self.screen.getmaxyx()
        height = min(height, screen_height)
        width = min(width, screen_width - 2)
        y, x = max(0, (screen_height - height) // 2), max(0, (screen_width - width) // 2)
        for row in range(y, y + height):
            self.text(row, x, " " * width, limit=width)
        self.frame(y, x, height, width, title, True)
        return y, x, height, width

    def prompt(self, title, value=""):
        value = str(value)
        position = len(value)
        self.screen.timeout(-1)
        self.cursor(True)
        try:
            while True:
                self.draw()
                y, x, height, width = self.popup("Edit / confirm", height=9)
                for index, line in enumerate(self.wrapped([title], width - 4)[:2]):
                    self.text(y + 1 + index, x + 2, line, self.accent, width - 4)
                room = max(1, width - 4)
                start = max(0, position - room + 1)
                self.text(y + 4, x + 2, value[start:start + room].ljust(room), curses.A_REVERSE, room)
                self.text(y + height - 2, x + 2, "Enter save | Esc cancel | Ctrl-U clear", curses.A_DIM, room)
                try:
                    self.screen.move(y + 4, x + min(width - 2, 2 + position - start))
                except curses.error:
                    pass
                self.screen.refresh()
                key = self.screen.get_wch()
                if key in ("\n", "\r", curses.KEY_ENTER):
                    return value
                if key == "\x1b":
                    return None
                if key == "\x15":
                    value, position = "", 0
                elif key in (curses.KEY_BACKSPACE, "\x7f", "\b"):
                    if position:
                        value = value[:position - 1] + value[position:]
                        position -= 1
                elif key == curses.KEY_DC:
                    value = value[:position] + value[position + 1:]
                elif key == curses.KEY_LEFT:
                    position = max(0, position - 1)
                elif key == curses.KEY_RIGHT:
                    position = min(len(value), position + 1)
                elif key == curses.KEY_HOME:
                    position = 0
                elif key == curses.KEY_END:
                    position = len(value)
                elif isinstance(key, str) and key.isprintable():
                    value = value[:position] + key + value[position:]
                    position += 1
        finally:
            self.cursor(False)
            self.screen.timeout(200)

    def choose(self, title, choices, current):
        selected = choices.index(current)
        while True:
            self.draw()
            y, x, height, width = self.popup(title, height=len(choices) + 5, width=52)
            for index, value in enumerate(choices):
                label = f"{'›' if index == selected else ' '} {value}"
                self.text(y + 2 + index, x + 2, label.ljust(width - 4),
                          curses.A_REVERSE if index == selected else 0, width - 4)
            self.text(y + height - 2, x + 2, "j/k choose | Enter save | Esc cancel", curses.A_DIM, width - 4)
            self.screen.refresh()
            key = self.screen.getch()
            if key in (curses.KEY_LEFT, curses.KEY_UP, ord('h'), ord('k')):
                selected = (selected - 1) % len(choices)
            elif key in (curses.KEY_RIGHT, curses.KEY_DOWN, ord('j'), ord('l')):
                selected = (selected + 1) % len(choices)
            elif key in (10, 13, curses.KEY_ENTER):
                return choices[selected]
            elif key == 27:
                return None

    def submit(self, command):
        if self.job:
            self.message = "A change is still running. You can continue browsing."
            return
        self.job = CommandJob(command)
        self.message = "Applying change..."

    def poll(self):
        if self.job:
            result = self.job.result()
            if result is not None:
                code, output = result
                self.job.close()
                self.job = None
                self.last_result = output or ("Change applied." if code == 0 else "Change failed.")
                self.message = ("Error: " if code else "") + self.last_result.splitlines()[-1]
                self.refresh(scan=True)
        if time.monotonic() >= self.refresh_at:
            self.refresh()

    def view(self, title, content):
        offset = 0
        while True:
            self.draw()
            screen_height, screen_width = self.screen.getmaxyx()
            y, x, height, width = self.popup(title, height=screen_height - 2, width=screen_width - 6)
            lines = self.wrapped(content.splitlines() or ["No entries yet."], width - 4)
            count = max(1, height - 4)
            offset = max(0, min(offset, max(0, len(lines) - count)))
            for index, line in enumerate(lines[offset:offset + count]):
                self.text(y + index + 1, x + 2, line, limit=width - 4)
            self.text(y + height - 2, x + 2, "j/k scroll | q/Esc/Enter return", curses.A_DIM, width - 4)
            self.screen.refresh()
            key = self.screen.getch()
            if key in (ord('q'), 27, 10, 13):
                return
            if key in (curses.KEY_UP, ord('k')):
                offset -= 1
            elif key in (curses.KEY_DOWN, ord('j')):
                offset += 1

    def edit_css(self, path):
        styles.ensure_user_styles()
        editor = shlex.split(os.environ.get("VISUAL") or os.environ.get("EDITOR") or "nano")
        if not editor:
            raise ValueError("Set EDITOR to your preferred terminal editor.")
        curses.def_prog_mode()
        curses.endwin()
        try:
            result = subprocess.run([*editor, path], check=False)
            self.message = "Saved; the desktop reloads it automatically." if result.returncode == 0 else "Editor exited with an error."
        finally:
            curses.reset_prog_mode()
            self.screen.clear()
            self.screen.refresh()
            self.cursor(False)

    def activate(self, item):
        if self.job:
            self.message = "A change is still running. You can continue browsing."
            return
        if item.setting:
            key = item.setting
            current = self.config[key]
            if isinstance(current, bool):
                value = "false" if current else "true"
            elif key in CHOICES:
                value = self.choose(item.label, CHOICES[key], current)
            else:
                value = self.prompt(f"{item.label}: {item.detail}", current)
            if value is not None:
                settings.validate(key, value)
                self.submit(("config", "set", key, value))
        elif item.command:
            self.submit(item.command)
        elif item.action == "file":
            path = self.prompt("Image or video path")
            if path:
                self.submit(("set", os.path.abspath(os.path.expanduser(path))))
        elif item.action == "awake":
            value = self.prompt("Minutes, 'on' until logout, or 'off'", "60")
            if value is not None:
                if value not in ("on", "off") and not (value.isdigit() and int(value) > 0):
                    raise ValueError("Enter positive minutes, on, or off.")
                self.submit(("awake", value))
        elif item.action in ("restore", "reset"):
            value = self.prompt(f"{item.label}: type {item.action} to confirm")
            if value == item.action:
                self.submit(("restore",) if value == "restore" else ("config", "reset"))
        elif item.action in ("widgets_css", "app_css", "layout"):
            self.edit_css({"widgets_css": storage.WIDGETS_CSS, "app_css": storage.APP_CSS, "layout": storage.LAYOUT}[item.action])
        elif item.action == "log":
            path = Path(storage.CACHE_DIR) / "helper.log"
            content = "No helper log yet."
            if path.exists():
                with path.open("rb") as log:
                    log.seek(max(0, path.stat().st_size - 32000))
                    content = log.read().decode("utf-8", errors="replace")
            self.view("Helper log (recent entries)", content)

    def run(self):
        try:
            while True:
                self.poll()
                self.draw()
                key = self.screen.getch()
                try:
                    if key == ord('q'):
                        return 0
                    if key == curses.KEY_RESIZE or key == -1:
                        continue
                    height, width = self.screen.getmaxyx()
                    if height < 16 or width < 60:
                        continue
                    if key in (curses.KEY_DOWN, ord('j')):
                        if self.focus == "detail":
                            self.preview_offset += 1
                        else:
                            self.selected = min(len(self.items()) - 1, self.selected + 1)
                            self.preview_offset = 0
                    elif key in (curses.KEY_UP, ord('k')):
                        if self.focus == "detail":
                            self.preview_offset = max(0, self.preview_offset - 1)
                        else:
                            self.selected = max(0, self.selected - 1)
                            self.preview_offset = 0
                    elif key in (curses.KEY_NPAGE, curses.KEY_PPAGE):
                        step = max(1, self.layout()[4] - 2) * (1 if key == curses.KEY_NPAGE else -1)
                        if self.focus == "detail":
                            self.preview_offset = max(0, self.preview_offset + step)
                        else:
                            self.selected = max(0, min(len(self.items()) - 1, self.selected + step))
                            self.preview_offset = 0
                    elif key in (curses.KEY_RIGHT, ord('l'), ord('6')):
                        self.focus = "detail"
                    elif key in (curses.KEY_LEFT, ord('h')):
                        self.focus = "list"
                    elif key in (9, curses.KEY_BTAB) or ord('1') <= key <= ord('5'):
                        self.switch_page(key - ord('1') if ord('1') <= key <= ord('5') else self.page + (-1 if key == curses.KEY_BTAB else 1))
                    elif key in (ord('g'), ord('G')):
                        if self.focus == "detail":
                            self.preview_offset = 0 if key == ord('g') else len(self.details(self.items()[self.selected])) * width
                        else:
                            self.selected = 0 if key == ord('g') else len(self.items()) - 1
                            self.preview_offset = 0
                    elif key in (10, 13, curses.KEY_ENTER, ord(' '), ord('e')):
                        self.activate(self.items()[self.selected])
                    elif key == ord('n'):
                        self.submit(("next",))
                    elif key == ord('r'):
                        self.refresh(scan=True)
                        self.message = "Refreshed."
                    elif key == ord('/') and self.page == 0:
                        value = self.prompt("Filter wallpaper filenames", self.search)
                        if value is not None:
                            self.search = value
                            self.selected = self.offset = 0
                    elif key == 27:
                        self.focus = "list"
                        self.search = ""
                    elif key == ord('v'):
                        self.view("Last action result", self.last_result)
                    elif key == ord('?'):
                        self.view("Wallpaper Studio help", "Select a left panel with 1-5, Tab or Shift-Tab.\n"
                                  "Focus the preview with l/Right/6; return with h/Left/Esc.\n"
                                  "Up/Down or j/k move in the focused panel; g/G jump to top/bottom.\n"
                                  "Enter, Space or e edits/applies the selected item.\n"
                                  "Boolean settings toggle; enums open a choice menu.\n"
                                  "Text fields: Ctrl-U clears; Esc cancels.\n"
                                  "Wallpapers: / searches filenames, Esc clears the filter.\n"
                                  "n picks another wallpaper; r refreshes; v shows action output.\n"
                                  "CSS editing uses VISUAL or EDITOR, falling back to nano.\n"
                                  "Changes are shared with the graphical panel.\n"
                                  "Quit with q. Wallpaper, clock and schedules keep running.\n"
                                  "An in-progress change finishes in the background after quitting.")
                except (OSError, ValueError) as error:
                    self.message = self.last_result = f"Error: {error}"
        finally:
            if self.job:
                self.job.close()


def main():
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("wallpaper-studio tui: open this command in an interactive terminal.", file=sys.stderr)
        return 1
    try:
        locale.setlocale(locale.LC_ALL, "")
        return curses.wrapper(lambda screen: Panel(screen).run())
    except KeyboardInterrupt:
        return 0
    except (curses.error, locale.Error) as error:
        print(f"wallpaper-studio tui: {error}. Check TERM or try another terminal.", file=sys.stderr)
        return 1

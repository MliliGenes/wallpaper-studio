"""Logtime periods and a nonblocking, per-widget data model. No GTK dependency."""
from datetime import date
import hashlib
import json
import math
from pathlib import Path
from queue import Empty, Queue
import re
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import storage

ENDPOINT = "https://logtime-med.1337.ma/api/get_log"
LOGIN = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


def period(marker=None, offset=0):
    """Containing period: the most recent 28th through the following month's 27th."""
    marker = marker or date.today()
    month = marker.year * 12 + marker.month - 1 + offset - (marker.day < 28)
    year, index = divmod(month, 12)
    next_year, next_index = divmod(month + 1, 12)
    return date(year, index + 1, 28), date(next_year, next_index + 1, 27)


def request_body(login, start, end):
    if not isinstance(login, str) or not LOGIN.fullmatch(login):
        raise ValueError("Use a login containing letters, numbers, underscores or hyphens (1–64 characters).")
    return {"login": login, "startDate": start.isoformat() + "T00:00:00.000Z",
            "endDate": end.isoformat() + "T00:00:00.000Z"}


def parse_hours(document, login):
    members = document.get("hydra:member") if isinstance(document, dict) else None
    if not isinstance(members, list):
        raise ValueError("Unexpected response from Logtime.")
    if not members:
        raise ValueError("User not found for this period.")
    member = next((item for item in members if isinstance(item, dict) and item.get("username") == login), None)
    if member is None:
        raise ValueError("Logtime returned a different user.")
    hours = member.get("totalHours")
    if type(hours) not in (int, float) or not math.isfinite(hours) or hours < 0:
        raise ValueError("Logtime returned invalid hours.")
    return float(hours)


def fetch_hours(login, start, end):
    request = Request(ENDPOINT, data=json.dumps(request_body(login, start, end)).encode(),
                      headers={"Content-Type": "application/json", "Accept": "application/ld+json, application/json"},
                      method="POST")
    try:
        with urlopen(request, timeout=12) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("Logtime response is too large.")
        return parse_hours(json.loads(raw), login)
    except HTTPError as error:
        raise ValueError(f"Logtime request failed (HTTP {error.code}).") from None
    except (URLError, TimeoutError, OSError):
        raise ValueError("Cannot reach Logtime. Check your connection and retry.") from None
    except (json.JSONDecodeError, UnicodeError):
        raise ValueError("Logtime returned an unreadable response.") from None


class LogtimeModel:
    """One background request at a time; obsolete responses never replace the selected period."""
    def __init__(self, fetch=fetch_hours, today=date.today, clock=time.time, cache_dir=None):
        self.fetch, self.today, self.clock = fetch, today, clock
        self.cache_dir = Path(cache_dir) if cache_dir is not None else Path(storage.CACHE_DIR) / "logtime"
        self.offset = 0
        self.key = None
        self.hours = None
        self.error = ""
        self.next_refresh = 0
        self.busy = False
        self.results = Queue()
        self.closed = threading.Event()

    def shift(self, direction):
        # Bound navigation to valid datetime years without making an invalid request.
        try:
            period(self.today(), self.offset + direction)
        except ValueError:
            return
        self.offset += direction

    def refresh(self):
        self.next_refresh = 0

    def cache_file(self, key):
        digest = hashlib.sha256("|".join(key).encode()).hexdigest()
        return self.cache_dir / (digest + ".json")

    def read_cache(self, key):
        try:
            data = json.loads(self.cache_file(key).read_text())
            hours, saved = data["hours"], data["saved"]
            if (type(hours) in (int, float) and math.isfinite(hours) and hours >= 0
                    and type(saved) in (int, float) and math.isfinite(saved)):
                self.hours = float(hours)
                # Fresh data lasts five minutes; stale data remains visible while refreshing.
                self.next_refresh = min(saved + 300, self.clock() + 300)
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def work(self, key, login, start, end):
        try:
            hours = self.fetch(login, start, end)
            saved = self.clock()
            if not self.closed.is_set():
                try:
                    storage.write(str(self.cache_file(key)), json.dumps({"hours": hours, "saved": saved}))
                except OSError:
                    pass  # Cache failures must not hide a successful API response.
            self.results.put((key, hours, "", saved))
        except Exception as error:
            self.results.put((key, None, str(error) or "Logtime request failed.", self.clock()))

    def view(self, login):
        start, end = period(self.today(), self.offset)
        key = (login, start.isoformat(), end.isoformat())
        if key != self.key:
            self.key, self.hours, self.error, self.next_refresh = key, None, "", 0
            self.read_cache(key)
        while True:
            try:
                received, hours, error, saved = self.results.get_nowait()
            except Empty:
                break
            self.busy = False
            if received == self.key:
                if not error:
                    self.hours = hours
                self.error = error
                self.next_refresh = saved + (60 if error else 300)
        if login and LOGIN.fullmatch(login) and not self.busy and self.clock() >= self.next_refresh and not self.closed.is_set():
            self.busy = True
            threading.Thread(target=self.work, args=(key, login, start, end), daemon=True).start()
        return dict(start=start, end=end, hours=self.hours, error=self.error,
                    loading=self.busy, login=login)

    def close(self):
        self.closed.set()

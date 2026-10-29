from datetime import date
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from wallpaper_studio.components import component_scope, close_models, resolve
from wallpaper_studio.logtime import LogtimeModel, fetch_hours, parse_hours, period, request_body
from wallpaper_studio.settings import DEFAULT_CONFIG, validate
from wallpaper_studio.widgets.logtime import Logtime


class LogtimeTests(unittest.TestCase):
    def test_period_rolls_over_on_28th_and_navigation_crosses_year_and_leap_year(self):
        self.assertEqual(period(date(2026, 10, 29)), (date(2026, 10, 28), date(2026, 11, 27)))
        self.assertEqual(period(date(2026, 10, 27)), (date(2026, 9, 28), date(2026, 10, 27)))
        self.assertEqual(period(date(2026, 10, 28)), period(date(2026, 10, 29)))
        self.assertEqual(period(date(2026, 10, 1)), period(date(2026, 10, 27)))
        self.assertEqual(period(date(2026, 1, 27)), (date(2025, 12, 28), date(2026, 1, 27)))
        self.assertEqual(period(date(2026, 1, 30)), (date(2026, 1, 28), date(2026, 2, 27)))
        self.assertEqual(period(date(2026, 12, 28)), (date(2026, 12, 28), date(2027, 1, 27)))
        self.assertEqual(period(date(2026, 12, 1), 1), (date(2026, 12, 28), date(2027, 1, 27)))
        self.assertEqual(period(date(2024, 3, 1), -1), (date(2024, 1, 28), date(2024, 2, 27)))
        self.assertEqual(period(date(2024, 2, 29)), (date(2024, 2, 28), date(2024, 3, 27)))

    def test_exact_request_and_response_and_bad_responses(self):
        start, end = period(date(2026, 10, 29))
        self.assertEqual(request_body("sel-mlil", start, end), {
            "login": "sel-mlil", "startDate": "2026-10-28T00:00:00.000Z", "endDate": "2026-11-27T00:00:00.000Z"})
        body = {"hydra:member": [{"username": "other", "totalHours": 10}, {"username": "sel-mlil", "totalHours": 196}]}
        self.assertEqual(parse_hours(body, "sel-mlil"), 196)
        body["hydra:member"][1]["totalHours"] = 0
        self.assertEqual(parse_hours(body, "sel-mlil"), 0)
        for invalid in ({}, [], {"hydra:member": []}, {"hydra:member": [{"username": "other", "totalHours": 196}]},
                        *({"hydra:member": [{"username": "sel-mlil", "totalHours": value}]} for value in (None, True, "196", -1, float("nan")))):
            with self.assertRaises(ValueError):
                parse_hours(invalid, "sel-mlil")

    def test_fetch_uses_post_and_timeout(self):
        with patch("wallpaper_studio.logtime.urlopen") as opening:
            opening.return_value.__enter__.return_value.read.return_value = json.dumps(
                {"hydra:member": [{"username": "sel-mlil", "totalHours": 196}]}).encode()
            self.assertEqual(fetch_hours("sel-mlil", *period(date(2026, 10, 1))), 196)
            request = opening.call_args.args[0]
            self.assertEqual(request.get_method(), "POST")
            self.assertEqual(json.loads(request.data)["startDate"], "2026-09-28T00:00:00.000Z")
            self.assertEqual(opening.call_args.kwargs["timeout"], 12)
        with patch("wallpaper_studio.logtime.urlopen", side_effect=TimeoutError):
            with self.assertRaisesRegex(ValueError, "Cannot reach"):
                fetch_hours("sel-mlil", *period(date(2026, 10, 1)))

    def test_config_validation(self):
        self.assertEqual(validate("logtime_username", " sel-mlil "), "sel-mlil")
        self.assertEqual(validate("logtime_username", ""), "")
        self.assertEqual(validate("logtime_goal", "196"), 196)
        for key, value in (("logtime_username", "bad user"), ("logtime_goal", 0), ("logtime_goal", True), ("logtime_goal", "nan")):
            with self.assertRaises(ValueError):
                validate(key, value)

    def wait_result(self, model):
        deadline = time.monotonic() + 2
        while model.results.empty() and time.monotonic() < deadline:
            time.sleep(.005)
        self.assertFalse(model.results.empty(), "Worker did not complete")

    def test_navigation_does_not_block_and_obsolete_response_is_discarded(self):
        release, entered = threading.Event(), threading.Event()
        calls = []
        def fetch(login, start, end):
            calls.append((login, start, end))
            entered.set()
            release.wait(2)
            return 196 if len(calls) == 1 else 20
        with tempfile.TemporaryDirectory() as directory:
            model = LogtimeModel(fetch=fetch, today=lambda: date(2026, 10, 29), cache_dir=directory)
            self.addCleanup(model.close)
            self.addCleanup(release.set)
            first = model.view("sel-mlil")
            self.assertTrue(first["loading"])
            self.assertTrue(entered.wait(1))
            model.shift(1)
            self.assertIsNone(model.view("sel-mlil")["hours"])
            self.assertEqual(len(calls), 1)
            release.set()
            self.wait_result(model)
            next_view = model.view("sel-mlil")
            self.assertIsNone(next_view["hours"])
            self.wait_result(model)
            self.assertEqual(model.view("sel-mlil")["hours"], 20)
            self.assertEqual(calls[-1][1:], (date(2026, 11, 28), date(2026, 12, 27)))

    def test_running_model_rolls_over_on_28th_and_widget_labels_starting_month(self):
        today = [date(2026, 10, 27)]
        with tempfile.TemporaryDirectory() as directory:
            model = LogtimeModel(today=lambda: today[0], cache_dir=directory)
            models = {"logtime": model}
            self.addCleanup(close_models, models)
            self.assertEqual(model.view("")["start"], date(2026, 9, 28))
            today[0] = date(2026, 10, 28)
            self.assertEqual(model.view("")["start"], date(2026, 10, 28))
            with component_scope(models):
                tree = resolve(Logtime(config=DEFAULT_CONFIG))
            labels = {child.key: child.props.get("text") for child in tree.children}
            self.assertEqual(labels["month"], "October 2026")
            self.assertEqual(labels["period"], "Oct 28, 2026 – Nov 27, 2026")
            model.shift(-1)
            self.assertEqual(model.view("")["start"], date(2026, 9, 28))
            model.shift(1)
            self.assertEqual(model.view("")["start"], date(2026, 10, 28))

    def test_cache_refresh_errors_and_instance_isolation(self):
        now = [1000]
        with tempfile.TemporaryDirectory() as directory:
            model = LogtimeModel(fetch=lambda *_: 196, today=lambda: date(2026, 10, 29), clock=lambda: now[0], cache_dir=directory)
            self.addCleanup(model.close)
            self.assertFalse(model.view("")["loading"])
            model.view("sel-mlil")
            self.wait_result(model)
            self.assertEqual(model.view("sel-mlil")["hours"], 196)
            second = LogtimeModel(fetch=lambda *_: self.fail("Fresh cache should avoid request"), today=model.today, clock=model.clock, cache_dir=directory)
            self.addCleanup(second.close)
            self.assertEqual(second.view("sel-mlil")["hours"], 196)
            self.assertFalse(second.busy)
            model.shift(-1)
            self.assertEqual(second.offset, 0)
            def offline(*_):
                raise ValueError("Offline")
            second.fetch = offline
            now[0] += 301
            self.assertEqual(second.view("sel-mlil")["hours"], 196)
            self.wait_result(second)
            data = second.view("sel-mlil")
            self.assertEqual(data["hours"], 196)
            self.assertEqual(data["error"], "Offline")
            self.assertFalse(data["loading"])
            second.refresh()
            self.assertTrue(second.view("sel-mlil")["loading"])

    def test_component_scope_reuses_model_and_closes_it(self):
        models = {}
        with component_scope(models):
            result = resolve(Logtime(config=DEFAULT_CONFIG))
            original = models["logtime"]
            resolve(Logtime(config=DEFAULT_CONFIG))
            self.assertIs(models["logtime"], original)
        self.assertEqual(result.props["class_name"], "logtime-card")
        close_models(models)
        self.assertTrue(original.closed.is_set())
        self.assertEqual(models, {})


if __name__ == "__main__":
    unittest.main()

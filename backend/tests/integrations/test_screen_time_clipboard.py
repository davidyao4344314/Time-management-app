"""Offline Screen Time parsing tests: no storage, API or model calls."""

import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from unittest.mock import patch

from backend.app.integrations import screen_time_clipboard as parser
from backend.app.infrastructure.clock import LOCAL_TIMEZONE

SAMPLE = """Screen Time
Today

Total: 4h 12m

YouTube
1h 24m

Instagram
52m

Safari
35m
"""


class DurationParserTests(unittest.TestCase):
    def test_supported_duration_formats(self):
        for text, expected in [
            ("4h 12m", 252), ("4 h 12 m", 252), ("52m", 52),
            ("52 min", 52), ("1h", 60), ("1 hour 20 minutes", 80),
            ("4h12m", 252), ("2 hrs 5 mins", 125), ("1 minute", 1),
            (" 1 HOUR 20 MINUTES ", 80), ("0m", 0), ("0h 0m", 0),
            ("4\u00a0h\u00a012\u00a0m", 252),
        ]:
            with self.subTest(text=text):
                self.assertEqual(parser.parse_duration_to_minutes(text), expected)

    def test_invalid_durations_raise_clear_errors(self):
        for text in ["", " ", "-1h", "1.5h", "4:12", "52", "one hour",
                     "1h rubbish", "20 seconds", "1h 2h", "10m 1h", None, 52, True]:
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "Use a duration"):
                parser.parse_duration_to_minutes(text)


class ScreenTimeClipboardTests(unittest.TestCase):
    def parse(self, text, **kwargs):
        return parser.parse_screen_time_text(text, selected_date="2026-10-11", **kwargs)

    def codes(self, result):
        return [warning["code"] for warning in result["warnings"]]

    def test_exact_example_normalizes_multiple_apps(self):
        self.assertEqual(self.parse(SAMPLE), {
            "success": True,
            "data": {"date": "2026-10-11", "total_minutes": 252, "source": "clipboard",
                     "apps": [{"name": "YouTube", "minutes": 84},
                              {"name": "Instagram", "minutes": 52},
                              {"name": "Safari", "minutes": 35}]},
            "warnings": [], "errors": [],
        })

    def test_blank_lines_crlf_and_headings_do_not_change_data(self):
        text = SAMPLE.replace("\n", "\r\n\r\n").replace("YouTube", "Most Used\r\nApps\r\nYouTube")
        self.assertEqual(self.parse(text), self.parse(SAMPLE))

    def test_inline_colon_space_and_tab_rows(self):
        result = self.parse("Total screen time: 4 h 12 m\nYouTube: 1h 24m\nInstagram\t52 min\nSafari 35m")
        self.assertEqual(result["data"], self.parse(SAMPLE)["data"])
        self.assertEqual(result["warnings"], [])

    def test_separate_total_label_and_duration(self):
        self.assertEqual(self.parse(SAMPLE.replace("Total: 4h 12m", "Total:\n4h 12m")), self.parse(SAMPLE))

    def test_missing_total_stays_null_and_is_not_derived(self):
        result = self.parse("YouTube\n1h 24m\nInstagram\n52m")
        self.assertTrue(result["success"])
        self.assertIsNone(result["data"]["total_minutes"])
        self.assertIn("missing_total", self.codes(result))
        self.assertEqual(len(result["data"]["apps"]), 2)

    def test_total_need_not_equal_app_sum(self):
        result = self.parse("Total: 10m\nYouTube: 20m\nSafari: 30m")
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["total_minutes"], 10)
        self.assertEqual(result["warnings"], [])

    def test_unknown_lines_warn_without_crashing_or_inventing_apps(self):
        result = self.parse("Unknown heading\n" + SAMPLE + "\nUnrecognised footer")
        self.assertEqual(result["data"], self.parse(SAMPLE)["data"])
        self.assertEqual(self.codes(result), ["missing_duration", "missing_duration"])
        self.assertEqual(result["warnings"][0]["line"], 1)

    def test_invalid_duration_returns_warning_and_preserves_valid_rows(self):
        for duration in ["-1h", "1.5h", "4:12", "1h rubbish", "unknown"]:
            with self.subTest(duration=duration):
                result = self.parse(f"Total: 4h\nBroken app\n{duration}\nSafari\n35m")
                self.assertTrue(result["success"])
                self.assertEqual(result["data"]["apps"], [{"name": "Safari", "minutes": 35}])
                self.assertTrue(result["warnings"])

    def test_invalid_inline_durations_warn(self):
        result = self.parse("Total: nonsense\nYouTube: bad\nSafari: 35m")
        self.assertTrue(result["success"])
        self.assertIsNone(result["data"]["total_minutes"])
        self.assertEqual(self.codes(result), ["invalid_duration", "invalid_duration", "missing_total"])

    def test_no_usable_data_returns_failure(self):
        for text in ["Screen Time\nToday\nMost Used\nApps", "Total: invalid", "YouTube\n-1h", "unrecognised"]:
            with self.subTest(text=text):
                result = self.parse(text)
                self.assertFalse(result["success"])
                self.assertIsNone(result["data"])
                self.assertTrue(result["errors"])

    def test_empty_and_non_text_input_return_failure(self):
        for text in ["", " \n\t", None, 12, {}, []]:
            with self.subTest(text=text):
                result = self.parse(text)
                self.assertFalse(result["success"])
                self.assertIsNone(result["data"])
                self.assertEqual(result["warnings"], [])

    def test_large_input_is_rejected(self):
        result = self.parse("x" * (parser.MAX_PASTE_CHARACTERS + 1))
        self.assertFalse(result["success"])
        self.assertIn("50,000", result["errors"][0])

    def test_default_date_uses_existing_auckland_clock(self):
        with patch.object(parser, "local_now", return_value=datetime(2026, 10, 11, 0, 1, tzinfo=LOCAL_TIMEZONE)):
            result = parser.parse_screen_time_text(SAMPLE)
        self.assertEqual(result["data"]["date"], "2026-10-11")

    def test_caller_date_wins_over_today_heading(self):
        result = parser.parse_screen_time_text(SAMPLE, "2026-09-30")
        self.assertEqual(result["data"]["date"], "2026-09-30")

    def test_invalid_selected_dates_are_not_replaced_with_today(self):
        for selected in ["", "bad", "2026-02-30", "20261011", "2026-W41-7", 123, True]:
            with self.subTest(selected=selected):
                result = parser.parse_screen_time_text(SAMPLE, selected)
                self.assertFalse(result["success"])
                self.assertIn("YYYY-MM-DD", result["errors"][0])

    def test_yesterday_requires_explicit_date(self):
        text = "Screen Time\nYesterday\nTotal: 1h"
        self.assertFalse(parser.parse_screen_time_text(text)["success"])
        result = parser.parse_screen_time_text(text, "2026-10-10")
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["date"], "2026-10-10")

    def test_aggregate_summaries_are_not_silently_saved_as_one_day(self):
        for heading in ["This Week", "Last Week", "Daily Average", "Weekly Average"]:
            with self.subTest(heading=heading):
                self.assertFalse(self.parse(f"{heading}\nTotal: 4h")["success"])

    def test_orphan_duration_is_not_assumed_to_be_total(self):
        result = self.parse("4h\nSafari\n35m")
        self.assertIsNone(result["data"]["total_minutes"])
        self.assertIn("unlabelled_duration", self.codes(result))

    def test_zero_is_valid_not_missing(self):
        result = self.parse("Total: 0m\nSafari: 0m")
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["total_minutes"], 0)
        self.assertEqual(result["warnings"], [])

    def test_duplicate_rows_keep_first_value_with_warning(self):
        result = self.parse("Total: 4h\nTotal: 5h\nSafari: 35m\nsafari: 45m")
        self.assertEqual(result["data"]["total_minutes"], 240)
        self.assertEqual(result["data"]["apps"], [{"name": "Safari", "minutes": 35}])
        self.assertEqual(self.codes(result), ["duplicate_total", "duplicate_app"])

    def test_numbered_and_unicode_names_survive(self):
        result = self.parse("Total: 2h\n1Password\n1m\nGame 2048 35m\n学习\n10m")
        self.assertEqual([row["name"] for row in result["data"]["apps"]], ["1Password", "Game 2048", "学习"])

    def test_output_is_json_serializable_and_parser_does_not_print_or_perform_io(self):
        output = io.StringIO()
        with redirect_stdout(output), \
                patch("builtins.open", side_effect=AssertionError("Unexpected file access")), \
                patch("sqlite3.connect", side_effect=AssertionError("Unexpected SQLite access")), \
                patch("socket.socket", side_effect=AssertionError("Unexpected network access")):
            result = self.parse(SAMPLE)
        self.assertEqual(json.loads(json.dumps(result)), result)
        self.assertEqual(output.getvalue(), "")


if __name__ == "__main__":
    unittest.main()

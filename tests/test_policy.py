"""Fast, zero-cost policy tests (no Sandbox or Blob API calls)."""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from api.policy import (
    OUTPUT_TTL_HOURS, RequestRejected, approximate_usage,
    canonical_youtube, expired, monthly_cap, validate_job,
)

VIDEO = "https://youtu.be/yWvnOWILFk0"


class LimitsTest(unittest.TestCase):
    def test_youtube_url_canonicalized(self):
        self.assertEqual(canonical_youtube(VIDEO + "?si=abc"), VIDEO)
        self.assertEqual(canonical_youtube("https://www.youtube.com/watch?v=yWvnOWILFk0"), VIDEO)

    def test_rejects_untrusted_or_non_video_urls(self):
        for url in (
            "http://youtu.be/yWvnOWILFk0", "https://youtube.com.evil.test/watch?v=yWvnOWILFk0",
            "https://youtube.com/playlist?list=PL123", "https://127.0.0.1/anything",
            "https://youtu.be/whatever", "file:///etc/passwd",
        ):
            with self.subTest(url=url), self.assertRaises(RequestRejected):
                canonical_youtube(url)

    def test_default_five_clips_45_seconds_720p(self):
        data = validate_job({"url": VIDEO})
        self.assertEqual((data["count"], data["length"], data["resolution"], data["model_name"]),
                         (5, 45, 720, "base"))

    def test_denies_expensive_overrides(self):
        for key, val in (("count", 10), ("resolution", 1080), ("length", 60)):
            with self.subTest(key=key), self.assertRaises(RequestRejected):
                validate_job({"url": VIDEO, key: val})

    def test_facecam_manual_validation(self):
        request = validate_job({"url": VIDEO, "facecam": "superior-esquerdo",
                                "manual_box": [79, 43, 21, 25]})
        self.assertEqual(request["manual_box"], [79, 43, 21, 25])
        for box in ([79, 43, 22, 25], ["nan", 0, 20, 20], [True, 1, 2, 3]):
            with self.subTest(box=box), self.assertRaises(RequestRejected):
                validate_job({"url": VIDEO, "manual_box": box})

    def test_monthly_cap_max_three(self):
        for raw, expected in (("1", 1), ("2", 2), ("9", 3), ("invalid", 3), ("0", 1)):
            with self.subTest(raw=raw), patch.dict(os.environ, {"SHORTFORGE_MAX_JOBS_MONTH": raw}):
                self.assertEqual(monthly_cap(), expected)

    def test_expiration_is_24_hours(self):
        now = datetime(2026, 11, 22, 12, tzinfo=timezone.utc)
        t = (now - timedelta(hours=OUTPUT_TTL_HOURS))
        self.assertTrue(expired(t.isoformat(), now))
        self.assertFalse(expired((t + timedelta(seconds=2)).isoformat(), now))

    def test_metrics_are_clearly_estimated(self):
        data = approximate_usage(900, 900, 120_000_000, 120_000_000)
        self.assertEqual(data["mode"], "estimated_not_billing")
        self.assertEqual(data["cpu_monthly_percent"], 5)
        self.assertEqual(data["memory_monthly_percent"], 0.24)
        self.assertEqual(data["storage_vs_1gb_percent"], 12)


if __name__ == "__main__":
    unittest.main()

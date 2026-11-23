"""Offline tests for the specifically authorized initial YouTube source."""
import unittest
from scripts.preflight_first_preview import validate_metadata


class FirstVideoPreflightTests(unittest.TestCase):
    def test_authorized_short_public_source(self):
        data = validate_metadata({
            "id": "NZRCjPMb0AY",
            "webpage_url": "https://www.youtube.com/watch?v=NZRCjPMb0AY",
            "duration": 72,
            "filesize_approx": 2_000_000,
            "is_live": False,
        })
        self.assertEqual(data["duration_seconds"], 72)
        self.assertTrue(data["source_bounded"])
        self.assertFalse(data["media_downloaded"])
        self.assertFalse(data["sandbox_created"])

    def test_fails_closed_for_long_live_unknown_size_wrong_video(self):
        good = {"id": "NZRCjPMb0AY", "duration": 72}
        for overrides in (
            {"duration": 121}, {"duration": 29}, {"duration": None},
            {"is_live": True}, {"live_status": "is_upcoming"},
            {"filesize_approx": 129*1024*1024}, {"id": "abcdefghijk"},
            {"webpage_url": "https://youtu.be/abcdefghijk"},
            {"_type": "playlist"}, {"duration": float("nan")},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                validate_metadata({**good, **overrides})


if __name__ == "__main__":
    unittest.main()

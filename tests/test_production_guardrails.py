"""Owner-only cloud Production limits; no Vercel requests or Sandbox creations."""
import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from api import sandbox_engine as engine
from api.policy import RequestRejected

PRODUCTION = {
    "VERCEL_ENV": "production",
    "SHORTFORGE_ENGINE": "sandbox",
    "SHORTFORGE_CLOUD_PRODUCTION_APPROVED": "1",
    "SHORTFORGE_MAX_JOBS_MONTH": "1",
    "SHORTFORGE_FRONTEND_ORIGIN": "https://short-clips-tan.vercel.app",
    "SHORTFORGE_PUBLIC_ACCESS_KEY": "user-secret-0123456789-0123456789-abcdef",
    "SHORTFORGE_WORKER_SECRET": "worker-secret-0123456789-0123456789-abc",
    "SHORTFORGE_VERCEL_PROTECTION_BYPASS": "private-production-automation-bypass",
    "BLOB_READ_WRITE_TOKEN": "private-production-blob-token",
    "SHORTFORGE_STORAGE_PREFIX": "shortforge",
}
JOB = {
    "url": "https://youtu.be/NZRCjPMb0AY",
    "count": 1, "length": 30, "resolution": 720,
    "facecam": "auto", "model": "base", "manual_box": None,
    "rights_confirmed": True,
}


class ProductionGuardrailTests(unittest.TestCase):
    def test_production_requires_explicit_single_job_cap_protected_callback(self):
        with patch.dict(os.environ, PRODUCTION, clear=True), patch.object(engine, "ROOT", "shortforge"):
            self.assertTrue(engine.configured())
        for changes in (
            {"SHORTFORGE_CLOUD_PRODUCTION_APPROVED": "0"},
            {"SHORTFORGE_MAX_JOBS_MONTH": "3"},
            {"SHORTFORGE_VERCEL_PROTECTION_BYPASS": ""},
            {"SHORTFORGE_FRONTEND_ORIGIN": "https://evil.invalid"},
        ):
            with self.subTest(changes=changes), patch.dict(os.environ, {**PRODUCTION, **changes}, clear=True), \
                    patch.object(engine, "ROOT", "shortforge"):
                self.assertFalse(engine.configured())

    def test_unapproved_and_oversized_jobs_never_reserve_vm(self):
        with patch.dict(os.environ, PRODUCTION, clear=True), patch.object(engine, "ROOT", "shortforge"), \
                patch.object(engine, "_acquire_lock", new_callable=AsyncMock) as lock:
            for changes in ({"rights_confirmed": False}, {"count": 4}, {"length": 60},
                            {"resolution": 1080}):
                with self.subTest(changes=changes), self.assertRaises(RequestRejected):
                    asyncio.run(engine.submit({**JOB, **changes}))
            lock.assert_not_awaited()

    def test_approved_job_is_bounded_to_one_20_minute_vm(self):
        class Resources:
            def __init__(self, **kwargs): self.__dict__.update(kwargs)
        vm = SimpleNamespace(fs=SimpleNamespace(write_bytes=AsyncMock()), create_command=AsyncMock())
        sdk = SimpleNamespace(create_sandbox=AsyncMock(return_value=vm))
        with patch.dict(os.environ, PRODUCTION, clear=True), patch.object(engine, "ROOT", "shortforge"), \
                patch.object(engine, "_sandbox", return_value=(sdk, Resources)), \
                patch.object(engine, "_acquire_lock", new_callable=AsyncMock), \
                patch.object(engine, "_quota", new_callable=AsyncMock), \
                patch.object(engine, "_write_blob", new_callable=AsyncMock):
            job = asyncio.run(engine.submit(JOB))
        self.assertEqual(job["status"], "queued")
        self.assertEqual(sdk.create_sandbox.await_count, 1)
        settings = sdk.create_sandbox.call_args.kwargs
        self.assertEqual(settings["execution_time_limit"].total_seconds(), 1200)
        self.assertEqual((settings["resources"].vcpus, settings["resources"].memory), (2, 4096))
        worker_env = vm.create_command.call_args.kwargs["env"]
        self.assertEqual(worker_env["SHORTFORGE_PUBLIC_API_URL"],
                         "https://backend-short-clips.vercel.app")
        self.assertEqual(worker_env["SHORTFORGE_VERCEL_PROTECTION_BYPASS"],
                         PRODUCTION["SHORTFORGE_VERCEL_PROTECTION_BYPASS"])
        self.assertNotIn("SHORTFORGE_PREVIEW_AUTHORIZED_YOUTUBE", worker_env)


if __name__ == "__main__":
    unittest.main()

"""No-cost tests for isolated Preview synthetic processing and callbacks."""
import asyncio
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from api import sandbox_engine as engine
from test_sandbox_orchestrator import ENVS
from test_worker import runner

ROOT = "shortforge-preview/active-smoke"
SOURCE = ROOT + "/integration/" + "a" * 32 + "/input.mp4"
URL = "https://backend-short-clips-test123-murilo15.vercel.app"
PREVIEW = {
    **ENVS, "VERCEL_ENV": "preview",
    "SHORTFORGE_PREVIEW_SYNTHETIC_ONLY": "1",
    "SHORTFORGE_PREVIEW_TEST_BLOB": SOURCE,
    "SHORTFORGE_PUBLIC_API_URL": URL,
    "SHORTFORGE_VERCEL_PROTECTION_BYPASS": "fake-preview-only-secret",
}
PAYLOAD = {"url": engine.PREVIEW_SYNTHETIC_URL, "count": 1, "length": 30,
           "resolution": 720, "manual_box": [0, 0, 50, 80]}


class SyntheticPreviewSafetyTests(unittest.TestCase):
    def test_no_implicit_opt_in_or_production_enablement(self):
        with patch.dict(os.environ, ENVS, clear=True):
            self.assertIsNone(engine.preview_synthetic_source())
        with patch.dict(os.environ, {**PREVIEW, "VERCEL_ENV": "production"}, clear=True), \
             patch.object(engine, "ROOT", ROOT):
            self.assertFalse(engine.configured())
            with self.assertRaises(RuntimeError):
                engine.preview_synthetic_source()

    def test_preview_engine_fails_closed_without_synthetic_flag(self):
        with patch.dict(os.environ, {**ENVS, "VERCEL_ENV":"preview"}, clear=True), \
             patch.object(engine, "ROOT", ROOT):
            self.assertFalse(engine.configured())

    def test_source_is_confined_to_single_private_preview_namespace(self):
        with patch.dict(os.environ, PREVIEW, clear=True), patch.object(engine, "ROOT", ROOT):
            self.assertEqual(engine.preview_synthetic_source(), SOURCE)
            self.assertTrue(engine.configured())
        with patch.dict(os.environ, {**PREVIEW, "SHORTFORGE_PREVIEW_TEST_BLOB":
                                     "shortforge/integration/" + "a"*32 + "/input.mp4"}, clear=True), \
             patch.object(engine, "ROOT", ROOT):
            self.assertFalse(engine.configured())

    def test_worker_rejects_foreign_namespace_and_traversal(self):
        runner.validate_synthetic_blob(SOURCE, ROOT, "preview")
        for wrong in (SOURCE.replace(ROOT, "shortforge"),
                      ROOT + "/integration/" + "a"*32 + "/../input.mp4",
                      ROOT + "/integration/" + "a"*32 + "/input.mp4/extra"):
            with self.assertRaises(ValueError):
                runner.validate_synthetic_blob(wrong, ROOT, "preview")
        with self.assertRaises(ValueError):
            runner.validate_synthetic_blob("shortforge/integration/" + "a"*32 + "/input.mp4", "shortforge", "preview")

    def test_launch_enforces_one_media_source_and_ten_minute_vm(self):
        class Resources:
            def __init__(self, vcpus, memory):
                self.vcpus = vcpus
                self.memory = memory
        box = SimpleNamespace(fs=SimpleNamespace(write_bytes=AsyncMock()),
                              create_command=AsyncMock(), stop=AsyncMock(), destroy=AsyncMock())
        sdk = SimpleNamespace(create_sandbox=AsyncMock(return_value=box))
        with patch.dict(os.environ, PREVIEW, clear=True), patch.object(engine, "ROOT", ROOT), \
             patch.object(engine, "_sandbox", return_value=(sdk, Resources)), \
             patch.object(engine, "_acquire_lock", new_callable=AsyncMock), \
             patch.object(engine, "_quota", new_callable=AsyncMock), \
             patch.object(engine, "_write_blob", new_callable=AsyncMock) as put, \
             patch.object(engine, "_release_lock", new_callable=AsyncMock):
            job = asyncio.run(engine.submit(PAYLOAD))
        self.assertEqual(job["count"], 1)
        self.assertEqual(sdk.create_sandbox.await_count, 1)
        self.assertEqual(sdk.create_sandbox.call_args.kwargs["execution_time_limit"].total_seconds(), 600)
        self.assertEqual(sdk.create_sandbox.call_args.kwargs["resources"].vcpus, 2)
        env = box.create_command.call_args.kwargs["env"]
        self.assertEqual(env["SHORTFORGE_TEST_SOURCE_BLOB"], SOURCE)
        self.assertEqual(env["SHORTFORGE_STORAGE_PREFIX"], ROOT)
        self.assertEqual(env["SHORTFORGE_DEPLOY_ENV"], "preview")
        self.assertTrue(any(call.args[0] == ROOT + "/integration/once.json"
                            and call.kwargs.get("overwrite") is False for call in put.await_args_list))

    def test_invalid_test_request_is_rejected_before_lock_or_vm(self):
        with patch.dict(os.environ, PREVIEW, clear=True), patch.object(engine, "ROOT", ROOT), \
             patch.object(engine, "_acquire_lock", new_callable=AsyncMock) as lock:
            for invalid in ({**PAYLOAD, "url": "https://youtu.be/yWvnOWILFk0"},
                            {**PAYLOAD, "count": 2},
                            {**PAYLOAD, "length": 45},
                            {**PAYLOAD, "manual_box": None}):
                with self.assertRaises(ValueError):
                    asyncio.run(engine.submit(invalid))
        lock.assert_not_awaited()


class CallbackProtectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_protected_preview_callback_includes_service_header_and_checks_receipt(self):
        seen = []
        job_id = "a"*32
        class Response:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, count): return json.dumps({"ok": True, "id": job_id}).encode()
        class Opener:
            def open(self, request, timeout):
                seen.append(request)
                return Response()
        with patch.dict(os.environ, {
                "SHORTFORGE_PUBLIC_API_URL": URL,
                "SHORTFORGE_WORKER_SECRET": "worker-test-secret",
                "SHORTFORGE_VERCEL_PROTECTION_BYPASS": "bypass-test-secret",
                "SHORTFORGE_DEPLOY_ENV": "preview",
            }, clear=True), patch.object(runner, "build_opener", return_value=Opener()) as builder:
            self.assertTrue(await runner.callback(job_id))
        self.assertEqual(len(seen), 1)
        headers = {k.lower(): v for k,v in seen[0].header_items()}
        self.assertEqual(headers["x-vercel-protection-bypass"], "bypass-test-secret")
        self.assertEqual(headers["x-shortforge-worker-secret"], "worker-test-secret")
        guard = builder.call_args.args[0]
        self.assertIsNone(guard.redirect_request(None,None,302,"Found",{},"https://other.example/"))

    async def test_production_destination_with_bypass_is_rejected_before_network(self):
        with patch.dict(os.environ, {
                "SHORTFORGE_PUBLIC_API_URL": "https://backend-short-clips.vercel.app",
                "SHORTFORGE_WORKER_SECRET": "worker-test-secret",
                "SHORTFORGE_VERCEL_PROTECTION_BYPASS": "secret",
                "SHORTFORGE_DEPLOY_ENV": "preview",
            }, clear=True), patch.object(runner, "build_opener") as builder:
            self.assertFalse(await runner.callback("a"*32))
            builder.assert_not_called()

if __name__ == "__main__":
    unittest.main()

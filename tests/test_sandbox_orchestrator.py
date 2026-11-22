"""Vercel Sandbox orchestration tests: all cloud services mocked, $0 spent."""
import asyncio
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from api import sandbox_engine as engine

VIDEO = "https://youtu.be/yWvnOWILFk0"
ENVS = {
    "SHORTFORGE_ENGINE": "sandbox",
    "BLOB_READ_WRITE_TOKEN": "fake-private-blob",
    "SHORTFORGE_PUBLIC_ACCESS_KEY": "user-secret-for-hobby-tests-0000000000",
    "SHORTFORGE_WORKER_SECRET": "worker-secret-for-hobby-tests-000000",
    "SHORTFORGE_FRONTEND_ORIGIN": "https://short-clips-tan.vercel.app",
}


class SandboxEngineTest(unittest.TestCase):
    def test_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(engine.configured())
            with self.assertRaises(RuntimeError):
                asyncio.run(engine.submit({"url": VIDEO}))

    def test_requires_storage_and_secrets(self):
        with patch.dict(os.environ, {"SHORTFORGE_ENGINE":"sandbox"}, clear=True):
            self.assertFalse(engine.configured())

    def test_submitting_starts_exactly_one_sandbox_with_fixed_resources(self):
        calls=[]
        class Resources:
            def __init__(self, vcpus, memory):
                self.vcpus=vcpus
                self.memory=memory
        class Box:
            async def create_command(self, executable, args, **kw):
                calls.append((executable,args,kw))
            async def stop(self):
                pass
        obj=SimpleNamespace(create_sandbox=AsyncMock(return_value=Box()))
        with patch.dict(os.environ, ENVS, clear=True), \
             patch.object(engine, "_sandbox", return_value=(obj, Resources)), \
             patch.object(engine, "_acquire_lock", new_callable=AsyncMock) as lock, \
             patch.object(engine, "_quota", new_callable=AsyncMock), \
             patch.object(engine, "_write_blob", new_callable=AsyncMock) as write, \
             patch.object(engine, "_release_lock", new_callable=AsyncMock):
            job = asyncio.run(engine.submit({"url": VIDEO, "count":5,"length":45,
                                             "resolution":720,"manual_box":[79,43,21,25]}))
        self.assertEqual(job["count"],5)
        self.assertEqual(job["resolution"],720)
        self.assertEqual(job["manual_box"],[.79,.43,.21,.25])
        self.assertEqual(job["status"],"queued")
        self.assertEqual(obj.create_sandbox.await_count,1)
        args=obj.create_sandbox.call_args.kwargs
        self.assertEqual(args["resources"].vcpus,2)
        self.assertEqual(args["resources"].memory,4096)
        self.assertEqual(args["execution_time_limit"].total_seconds(),42*60)
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][0],"bash")
        self.assertIn("SHORTFORGE_JOB",calls[0][2]["env"])
        self.assertEqual(lock.await_count,1)
        self.assertGreaterEqual(write.await_count,3)

    def test_invalid_request_does_not_start_sandbox_or_reserve_lock(self):
        with patch.dict(os.environ, ENVS, clear=True),\
             patch.object(engine, "_acquire_lock", new_callable=AsyncMock) as lock,\
             patch.object(engine, "_quota", new_callable=AsyncMock):
            with self.assertRaises(ValueError):
                asyncio.run(engine.submit({"url": VIDEO,"count":10}))
        lock.assert_not_awaited()

    def test_busy_rejection(self):
        async def busy(_):
            from api.policy import RequestRejected
            raise RequestRejected("Já existe um processamento em andamento.")
        with patch.dict(os.environ, ENVS, clear=True),\
             patch.object(engine, "_acquire_lock", side_effect=busy),\
             patch.object(engine, "_quota", new_callable=AsyncMock):
            with self.assertRaisesRegex(ValueError, "andamento"):
                asyncio.run(engine.submit({"url":VIDEO}))

    def test_finish_stops_sandbox_and_releases_lock(self):
        box = SimpleNamespace(stop=AsyncMock())
        runtime = SimpleNamespace(get_sandbox=AsyncMock(return_value=box))
        status={"id":"a"*32,"status":"completed"}
        with patch.object(engine, "get_job", new_callable=AsyncMock, return_value=status),\
             patch.object(engine, "_sandbox", return_value=(runtime,None)),\
             patch.object(engine, "_release_lock", new_callable=AsyncMock) as unlock:
            result=asyncio.run(engine.finalize("a"*32))
        self.assertTrue(result["ok"])
        box.stop.assert_awaited_once()
        unlock.assert_awaited_once()

    def test_finish_refuses_unlock_while_processing(self):
        with patch.object(engine, "get_job", new_callable=AsyncMock,
                          return_value={"id":"a"*32,"status":"running"}),\
             patch.object(engine, "_release_lock", new_callable=AsyncMock) as unlock:
            result=asyncio.run(engine.finalize("a"*32))
        self.assertFalse(result["ok"])
        unlock.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()

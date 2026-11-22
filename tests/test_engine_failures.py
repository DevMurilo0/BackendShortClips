"""State-machine regression; in-memory Blob simulator, no cloud validation."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from api import sandbox_engine as e
from api.policy import RequestRejected
from test_sandbox_orchestrator import ENVS, VIDEO


class BlobNotFoundError(Exception): pass
class BlobPreconditionFailedError(Exception): pass


class Store:
    def __init__(self):
        self.data = {}
        self.counter = 0
        self.fail_upload = False
        self.fail_download = False

    async def put_blob(self, path, data, *, allow_overwrite=False, **kw):
        await asyncio.sleep(0)
        if self.fail_upload: raise OSError('upload failed')
        if path in self.data and not allow_overwrite:
            raise BlobPreconditionFailedError('already exists')
        self.counter += 1
        self.data[path] = (data, str(self.counter))
        return SimpleNamespace(etag=str(self.counter))

    async def get_blob(self, path, **kw):
        if path.startswith('https:'):
            from urllib.parse import urlsplit, unquote
            path = unquote(urlsplit(path).path.lstrip('/'))
        await asyncio.sleep(0)
        if self.fail_download: raise OSError('download failed')
        if path not in self.data: raise BlobNotFoundError()
        body, etag = self.data[path]
        return SimpleNamespace(body=body, metadata=SimpleNamespace(etag=etag))

    async def delete_blob(self, paths, *, if_match=None):
        for path in [paths] if isinstance(paths, str) else paths:
            if if_match and self.data[path][1] != if_match:
                raise BlobPreconditionFailedError()
            self.data.pop(path, None)

    async def query_blobs(self, *, prefix):
        for path, (body, _) in list(self.data.items()):
            if path.startswith(prefix): yield SimpleNamespace(pathname=path, size=len(body))


class DurableEngineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = Store()
        self.box = SimpleNamespace(fs=SimpleNamespace(write_bytes=AsyncMock()),
                                   create_command=AsyncMock(), stop=AsyncMock())
        self.runtime = SimpleNamespace(create_sandbox=AsyncMock(return_value=self.box),
                                       get_sandbox=AsyncMock(return_value=self.box))
        from vercel.sandbox import SandboxResources
        self.patches = [patch.dict(os.environ, ENVS, clear=True),
                        patch.object(e, '_blob', return_value=self.store),
                        patch.object(e, '_sandbox', return_value=(self.runtime, SandboxResources))]
        for patcher in self.patches: patcher.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])

    async def test_simultaneous_requests_only_one_vm(self):
        results = await asyncio.gather(*(e.submit({'url': VIDEO}) for _ in range(12)), return_exceptions=True)
        self.assertEqual(sum(isinstance(r, dict) for r in results), 1)
        self.assertEqual(sum(isinstance(r, RequestRejected) for r in results), 11)
        self.runtime.create_sandbox.assert_awaited_once()

    async def test_last_monthly_slot_is_serialized_and_persists(self):
        for _ in range(3):
            job = await e.submit({'url': VIDEO})
            await e._release_lock(job['id'])
        with self.assertRaisesRegex(RequestRejected, 'mensal'):
            await e.submit({'url': VIDEO})
        self.assertNotIn(e.LOCK, self.store.data)
        self.assertEqual(self.runtime.create_sandbox.await_count, 3)
        # A fresh reader uses the persisted markers, never process memory.
        self.assertEqual((await e.usage())['jobs_month'], 3)

    async def test_uncertain_create_failure_records_error_and_keeps_lock(self):
        self.runtime.create_sandbox.side_effect = OSError('cannot create')
        with self.assertRaises(OSError): await e.submit({'url': VIDEO})
        self.assertIn(e.LOCK, self.store.data)
        states = [json.loads(v[0]) for p, v in self.store.data.items() if p.endswith('/state.json')]
        self.assertEqual(states[0]['status'], 'failed')
        self.assertEqual((await e.usage())['jobs_month'], 1)

    async def test_launch_failure_stops_box(self):
        self.box.create_command.side_effect = OSError('command failure')
        with self.assertRaises(OSError): await e.submit({'url': VIDEO})
        self.box.stop.assert_awaited_once()
        self.assertNotIn(e.LOCK, self.store.data)

    async def test_stop_failure_keeps_lock(self):
        self.box.create_command.side_effect = OSError('command failure')
        self.box.stop.side_effect = OSError('cannot stop')
        with self.assertRaises(OSError): await e.submit({'url': VIDEO})
        self.assertIn(e.LOCK, self.store.data)

    async def test_storage_failure_never_starts_vm(self):
        for name in ('fail_upload', 'fail_download'):
            setattr(self.store, name, True)
            with self.assertRaises(OSError): await e.submit({'url': VIDEO})
            setattr(self.store, name, False)
        self.runtime.create_sandbox.assert_not_awaited()

    async def test_cancel_stops_before_publishing_cancelled(self):
        job = await e.submit({'url': VIDEO})
        result = await e.cancel(job['id'])
        self.assertEqual(result['status'], 'cancelled')
        self.box.stop.assert_awaited_once()
        self.assertNotIn(e.LOCK, self.store.data)

    async def test_timeout_reconciles_state_and_unlocks(self):
        job = await e.submit({'url': VIDEO})
        job['started_at'] = (datetime.now(timezone.utc)-timedelta(minutes=49)).isoformat()
        await e._write_blob(e._path(job['id']), job)
        state = await e.get_job(job['id'])
        self.assertEqual(state['status'], 'failed')
        self.assertNotIn(e.LOCK, self.store.data)

    async def test_expiration_physically_deletes_output_preserves_quota(self):
        job = await e.submit({'url': VIDEO})
        job['started_at'] = (datetime.now(timezone.utc)-timedelta(hours=25)).isoformat()
        job['status'] = 'completed'
        state_path = e._path(job['id'], job['started_at'][:7])
        await e._write_blob(state_path, job)
        artifact = state_path.replace('state.json', 'output/short_01.mp4')
        await self.store.put_blob(artifact, b'video')
        await e.cleanup()
        self.assertNotIn(artifact, self.store.data)
        self.assertEqual(json.loads(self.store.data[state_path][0])['status'], 'expired')
        self.assertEqual((await e.usage())['jobs_month'], 1)

    async def test_unlock_uses_get_etag_not_later_head(self):
        await e._acquire_lock('a'*32)
        original_delete = self.store.delete_blob
        async def raced_delete(path, **kwargs):
            await e._write_blob(e.LOCK, {'id': 'b'*32, 'started_at': e._stamp()})
            await original_delete(path, **kwargs)
        self.store.delete_blob = raced_delete
        await e._release_lock('a'*32)
        self.assertEqual((await e._read_blob(e.LOCK))['id'], 'b'*32)

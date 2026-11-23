"""Controlled YouTube Preview contract; no remote resources are created."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace
from api import sandbox_engine as engine
from api.policy import canonical_youtube, RequestRejected
from test_preview_active_harness import PREVIEW, ROOT, PAYLOAD

VIDEO = 'https://youtu.be/abcdefghijk'  # parser fixture, never downloaded
ENV = {k:v for k,v in PREVIEW.items() if k not in (
    'SHORTFORGE_PREVIEW_SYNTHETIC_ONLY', 'SHORTFORGE_PREVIEW_TEST_BLOB',
    'SHORTFORGE_PUBLIC_API_URL')}
ENV.update(SHORTFORGE_PREVIEW_AUTHORIZED_YOUTUBE=VIDEO,
           SHORTFORGE_PREVIEW_RIGHTS_CONFIRMED='1',
           VERCEL_URL='backend-short-clips-current-murilo15.vercel.app')

class AuthorizedPreviewTests(unittest.TestCase):
    def test_attestation_and_deployment_pin(self):
        with patch.dict(os.environ, ENV, clear=True), patch.object(engine, 'ROOT', ROOT):
            self.assertTrue(engine.configured())
            self.assertEqual(engine.preview_callback_url(), 'https://' + ENV['VERCEL_URL'])
            os.environ['SHORTFORGE_PUBLIC_API_URL'] = 'https://backend-short-clips-old-murilo15.vercel.app'
            self.assertFalse(engine.configured())
        for change in ({'SHORTFORGE_PREVIEW_RIGHTS_CONFIRMED':'0'}, {'VERCEL_ENV':'production'}):
            with patch.dict(os.environ, {**ENV, **change}, clear=True), patch.object(engine, 'ROOT', ROOT):
                self.assertFalse(engine.configured())

    def test_placeholder_is_never_a_credential(self):
        with patch.dict(os.environ, {**ENV, "BLOB_READ_WRITE_TOKEN":"[SENSITIVE]"}, clear=True), patch.object(engine, "ROOT", ROOT):
            self.assertFalse(engine.configured())

    def test_bad_requests_never_acquire_lock(self):
        with patch.dict(os.environ, ENV, clear=True), patch.object(engine, 'ROOT', ROOT), \
             patch.object(engine, '_acquire_lock', new_callable=AsyncMock) as lock:
            for change in ({'url':'https://youtu.be/otherfilm12'}, {'count':2}, {'length':45}, {'manual_box':None}):
                with self.assertRaises(RequestRejected):
                    asyncio.run(engine.submit({**PAYLOAD, 'url':VIDEO, **change}))
            lock.assert_not_awaited()

    def test_one_vm_reservation_and_budget(self):
        class Resources:
            def __init__(self, **kwargs): self.__dict__.update(kwargs)
        box = SimpleNamespace(fs=SimpleNamespace(write_bytes=AsyncMock()), create_command=AsyncMock())
        sdk = SimpleNamespace(create_sandbox=AsyncMock(return_value=box))
        with patch.dict(os.environ, ENV, clear=True), patch.object(engine, 'ROOT', ROOT), \
             patch.object(engine, '_sandbox', return_value=(sdk,Resources)), \
             patch.object(engine, '_acquire_lock', new_callable=AsyncMock), \
             patch.object(engine, '_quota', new_callable=AsyncMock), \
             patch.object(engine, '_write_blob', new_callable=AsyncMock) as put:
            asyncio.run(engine.submit({**PAYLOAD, 'url':VIDEO}))
        self.assertEqual(sdk.create_sandbox.await_count, 1)
        args=sdk.create_sandbox.call_args.kwargs
        self.assertEqual(args['execution_time_limit'].total_seconds(),600)
        self.assertEqual((args['resources'].vcpus,args['resources'].memory),(2,4096))
        env=box.create_command.call_args.kwargs['env']
        self.assertEqual(env['SHORTFORGE_PREVIEW_AUTHORIZED_YOUTUBE'],VIDEO)
        self.assertNotIn('SHORTFORGE_TEST_SOURCE_BLOB',env)
        self.assertEqual(env['SHORTFORGE_PUBLIC_API_URL'],'https://'+ENV['VERCEL_URL'])
        self.assertTrue(any(c.args[0]==ROOT+'/integration/once.json' and c.kwargs.get('overwrite') is False for c in put.await_args_list))

    def test_rejects_playlist_context_and_duplicate_video_ids(self):
        for url in (VIDEO+'?list=abc','https://youtube.com/watch?v=abcdefghijk&v=otherfilm12',VIDEO+'?index=2'):
            with self.assertRaises(RequestRejected): canonical_youtube(url)

class MetadataBudgetTests(unittest.TestCase):
    def test_metadata_rejects_long_live_and_oversized_before_media_download(self):
        import sys, json
        from pathlib import Path
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'worker'))
        from shortforge import media
        with patch.dict(os.environ, {'SHORTFORGE_PREVIEW_AUTHORIZED_YOUTUBE':VIDEO}), patch.object(media,'run') as run:
            for info in ({'duration':121},{'duration':0},{'duration':60,'is_live':True},
                         {'duration':60,'filesize_approx':129*1024**2},{'_type':'playlist'}):
                run.return_value=SimpleNamespace(stdout=json.dumps(info),stderr='')
                with self.assertRaises(RuntimeError):media.metadata_youtube(VIDEO,lambda _:None)
            run.return_value=SimpleNamespace(stdout=json.dumps({'duration':45,'filesize':1024}),stderr='')
            self.assertEqual(media.metadata_youtube(VIDEO,lambda _:None)['duration'],45)
            run.reset_mock()
            with self.assertRaises(RuntimeError):media.metadata_youtube('https://127.0.0.1/',lambda _:None)
            run.assert_not_called()

"""Preview cannot use the Production Blob namespace, even with a valid key."""
import os
import unittest
from unittest.mock import patch
from api import sandbox_engine as engine
from test_sandbox_orchestrator import ENVS

class PreviewNamespaceTests(unittest.TestCase):
    def test_preview_requires_isolated_prefix(self):
        with patch.dict(os.environ,{**ENVS,'VERCEL_ENV':'preview'},clear=True),patch.object(engine,'ROOT','shortforge'):
            self.assertFalse(engine.configured())

    def test_preview_namespace_requires_explicit_bounded_test_profile(self):
        root = 'shortforge-preview/homologation'
        with patch.dict(os.environ,{**ENVS,'VERCEL_ENV':'preview'},clear=True),patch.object(engine,'ROOT',root):
            self.assertFalse(engine.configured())
        scoped = {**ENVS, 'VERCEL_ENV':'preview',
                  'SHORTFORGE_PREVIEW_SYNTHETIC_ONLY':'1',
                  'SHORTFORGE_PREVIEW_TEST_BLOB':root+'/integration/'+'a'*32+'/input.mp4',
                  'SHORTFORGE_PUBLIC_API_URL':'https://backend-short-clips-smoke-murilo15.vercel.app',
                  'SHORTFORGE_VERCEL_PROTECTION_BYPASS':'test-only-not-a-real-secret'}
        with patch.dict(os.environ,scoped,clear=True),patch.object(engine,'ROOT',root):
            self.assertTrue(engine.configured())
            self.assertTrue(engine._path('a'*32).startswith(root+'/jobs/'))

    def test_production_cannot_reset_quota_by_switching_namespace(self):
        with patch.dict(os.environ,{**ENVS,'VERCEL_ENV':'production'},clear=True),patch.object(engine,'ROOT','shortforge-preview/escape'):
            self.assertFalse(engine.configured())

    def test_invalid_prefix_fails_closed(self):
        with patch.dict(os.environ,ENVS,clear=True),patch.object(engine,'ROOT','shortforge/../../elsewhere'):
            self.assertFalse(engine.configured())

    def test_cleanup_rejects_unsafe_preview_namespace(self):
        import asyncio
        with patch.dict(os.environ,{'VERCEL_ENV':'preview'},clear=True),patch.object(engine,'ROOT','shortforge'):
            with self.assertRaisesRegex(RuntimeError,'Namespace'):
                asyncio.run(engine.cleanup())

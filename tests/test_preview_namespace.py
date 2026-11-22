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

    def test_preview_namespace_is_configured(self):
        with patch.dict(os.environ,{**ENVS,'VERCEL_ENV':'preview'},clear=True),patch.object(engine,'ROOT','shortforge-preview/homologation'):
            self.assertTrue(engine.configured())
            self.assertTrue(engine._path('a'*32).startswith('shortforge-preview/homologation/jobs/'))

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

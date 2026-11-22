"""Safety envelope / lifecycle tests, entirely simulated. No cloud operations."""
import asyncio
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import cloud_smoke as smoke

class HarnessTests(unittest.IsolatedAsyncioTestCase):
    def test_compute_envelope_has_margin(self):
        self.assertEqual(smoke.MAX_SESSION_SECONDS,540)
        self.assertLess(smoke.budget_bound(540),.057)
        self.assertAlmostEqual(smoke.budget_bound(600),.0568)

    async def test_stop_failure_still_destroys(self):
        box=SimpleNamespace(stop=AsyncMock(side_effect=OSError()),destroy=AsyncMock())
        runtime=SimpleNamespace(get_sandbox=AsyncMock(return_value=SimpleNamespace(status='deleted')))
        report={}
        with patch.object(smoke,'event'):
            errors=await smoke.cleanup_sandbox(runtime,'test',box,report)
        self.assertFalse(errors)
        box.destroy.assert_awaited_once_with(delete_orphan_snapshots=True)
        self.assertTrue(report['sandbox_destroy_confirmed'])

    async def test_unknown_creation_reconciles_name_without_create(self):
        box=SimpleNamespace(stop=AsyncMock(),destroy=AsyncMock(),status='deleted')
        runtime=SimpleNamespace(get_sandbox=AsyncMock(return_value=box))
        report={}
        errors=await smoke.cleanup_sandbox(runtime,'same-name',None,report)
        self.assertFalse(errors)
        self.assertEqual(runtime.get_sandbox.await_count,2)
        box.stop.assert_awaited_once()
        box.destroy.assert_awaited_once()

    async def test_destroy_failure_is_not_reported_as_success(self):
        box=SimpleNamespace(stop=AsyncMock(),destroy=AsyncMock(side_effect=OSError()))
        report={}
        with patch.object(smoke,'event'):
            errors=await smoke.cleanup_sandbox(None,'test',box,report)
        self.assertTrue(errors)
        self.assertEqual(box.destroy.await_count,3)
        self.assertFalse(report['sandbox_destroy_confirmed'])

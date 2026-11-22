"""Import/signature validation against installed real SDK; no cloud requests."""
import inspect
import unittest
from vercel import blob,sandbox
from vercel.sandbox import SandboxResources
from api.sandbox_engine import worker_archive, private_state_url
from unittest.mock import patch
import os
import io
import tarfile

class SDKContractTests(unittest.TestCase):
    def test_real_sdk_signatures_match_used_arguments(self):
        for arg in ('name','image','resources','execution_time_limit','persistent','region'):
            self.assertIn(arg,inspect.signature(sandbox.create_sandbox).parameters)
        self.assertEqual(SandboxResources(vcpus=2,memory=4096).memory,4096)
        self.assertIn('if_match',inspect.signature(blob.delete_blob).parameters)
        self.assertIn('content_length',inspect.signature(blob.put_blob).parameters)

    def test_archive_contains_worker_not_env_or_videos(self):
        with tarfile.open(fileobj=io.BytesIO(worker_archive())) as archive:
            names=archive.getnames()
            self.assertIn('worker/runner.py',names)
            self.assertIn('worker/shortforge/media.py',names)
            self.assertTrue(all(name.endswith(('.py','.txt','.lock')) for name in names))

    def test_consistent_state_read_wire_format(self):
        with patch.dict(os.environ,{'BLOB_STORE_ID':'store_example123'},clear=True):
            self.assertEqual(private_state_url('shortforge/mutex/active.json'),
                'https://example123.private.blob.vercel-storage.com/shortforge/mutex/active.json?cache=0')

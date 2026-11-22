"""Worker publishing failures with a fake media executor and Blob (no Vercel calls)."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

spec = importlib.util.spec_from_file_location('sf_worker', Path(__file__).resolve().parents[1]/'worker/runner.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def run_worker(self, failed_names=()):
        states=[];uploads=[]
        def execute(job):
            job.destination.mkdir(parents=True, exist_ok=True)
            for i in range(1, 3):
                name=f'short_{i:02d}.mp4'
                (job.destination/name).write_bytes(b'fake-video')
                job.clips.append(dict(number=i, name=name, status='ready'))
            job.status='completed'
        async def save(path,state): states.append(json.loads(json.dumps(state)))
        async def upload(file,path,*args):
            if file.name in failed_names: raise OSError('failed')
            uploads.append(path)
        raw=dict(id='a'*32,url='https://youtu.be/yWvnOWILFk0',count=2,length=45,
                 resolution=720,facecam='auto',started_at='2026-11-22T00:00:00+00:00')
        env={'SHORTFORGE_JOB':json.dumps(raw),'SHORTFORGE_JOB_BLOB_PATH':'shortforge/jobs/2026-11/'+raw['id']+'/state.json'}
        with patch.dict(os.environ,env),patch.object(runner,'execute',execute),patch.object(runner,'save',save),\
             patch.object(runner,'upload',upload),patch.object(runner,'callback',new_callable=AsyncMock) as callback,\
             patch.object(runner.shutil,'which',return_value='/bin/tool'):
            await runner.main()
        self.assertFalse((Path('/tmp/shortforge-job')/raw['id']).exists())
        callback.assert_awaited_once()
        for state in states[:-1]:
            self.assertEqual(state['status'],'running')
            self.assertFalse(any(c['status']=='ready' for c in state.get('clips',[])))
        return states[-1], uploads

    async def test_success_only_after_uploads(self):
        state,uploads=await self.run_worker()
        self.assertEqual(state['status'],'completed')
        self.assertEqual(len(uploads),3)

    async def test_partial_upload_failure_preserves_good_clip(self):
        state,uploads=await self.run_worker(('short_01.mp4',))
        self.assertEqual(state['status'],'partial')
        self.assertEqual(state['clips'][0]['status'],'failed')
        self.assertEqual(len(uploads),2)

    async def test_zip_failure_keeps_mp4s_downloadable(self):
        state,_=await self.run_worker(('shorts_prontos.zip',))
        self.assertEqual(state['status'],'completed')
        self.assertIsNone(state['zip_name'])
        self.assertTrue(state['errors'])


class SpeechSelectionTests(unittest.TestCase):
    def test_no_speech_retries_another_candidate_instead_of_fake_captions(self):
        from shortforge.media import make_srt, UnsuitableScene
        model=type('Model',(),{'transcribe':lambda *_a,**_k:(iter([]),None)})()
        with tempfile.TemporaryDirectory() as directory, patch('shortforge.media.ffprobe',return_value={'duration':30}):
            with self.assertRaises(UnsuitableScene):
                make_srt(model,Path(directory)/'source.mp4',Path(directory)/'out.srt',lambda _:None)

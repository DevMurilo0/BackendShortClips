"""Opt-in real CPU/FFmpeg tests. Never contacts Vercel or YouTube."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'worker'))
from shortforge.media import render_split, run, validate_output


@unittest.skipUnless(os.getenv('SHORTFORGE_RUN_MEDIA_TESTS')=='1', 'set SHORTFORGE_RUN_MEDIA_TESTS=1; FFmpeg required')
class RealMediaTests(unittest.TestCase):
    def test_render_captions_720_vertical_and_max45(self):
        import numpy as np
        with tempfile.TemporaryDirectory(prefix="sf ação d'água [x],: ") as directory:
            root=Path(directory);source=root/'source.mp4';srt=root/'legendas.srt';out=root/'short_01.mp4'
            run(['ffmpeg','-v','error','-nostdin','-y','-f','lavfi','-i','color=c=blue:s=320x180:r=30:d=46',
                 '-f','lavfi','-i','sine=frequency=400:duration=46','-c:v','libx264','-threads','2',
                 '-preset','ultrafast','-c:a','aac','-shortest',str(source)],timeout=30)
            srt.write_text('1\n00:00:00,000 --> 00:00:03,000\nAÇÃO: olá, português!\n')
            data=render_split(source,srt,out,(0,0,160,142),720,lambda _:None)
            self.assertEqual((data['width'],data['height']),(720,1280))
            self.assertLessEqual(data['duration'],45.001)
            self.assertTrue(data['has_audio'])
            pixels=subprocess.run(['ffmpeg','-v','error','-ss','1','-i',str(out),'-frames:v','1',
                '-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,check=True).stdout
            frame=np.frombuffer(pixels,dtype=np.uint8).reshape(1280,720,3)
            self.assertGreater(int(np.all(frame[900:]>210,axis=2).sum()),100)
            self.assertFalse(list(root.glob('render_*')))

    def test_cancel_kills_child_process_group(self):
        import threading
        from shortforge.runtime import cancel_event, Cancelled
        event=threading.Event();token=cancel_event.set(event)
        timer=threading.Timer(.2,event.set);timer.start()
        try:
            with self.assertRaises(Cancelled):
                run([sys.executable,'-c','import time; time.sleep(60)'],timeout=5)
        finally:
            timer.cancel();cancel_event.reset(token)

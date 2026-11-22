"""Real local selection, OCR, manual framing, Whisper, FFmpeg and ZIP validation."""
from pathlib import Path
import json
import sys
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'worker'))
from synthetic_media import generate
from shortforge.pipeline import Job, execute
from shortforge.media import validate_output

with tempfile.TemporaryDirectory(prefix='sf-pipeline-') as directory:
    root=Path(directory);source=root/'synthetic.mp4'
    generate(source)
    job=Job(id='local-synthetic',url='synthetic:local',count=1,length=30,resolution=720,
            facecam='auto',model_name='base',destination=root/'output',
            source_path=source,manual_box=[0,0,.5,.8])
    execute(job)
    if job.status!='completed':
        print(json.dumps({'status':job.status,'errors':job.errors},ensure_ascii=False))
        raise SystemExit(1)
    result=validate_output(job.destination/job.clips[0]['name'],720)
    with zipfile.ZipFile(job.destination/job.zip_name) as archive:
        assert archive.testzip() is None
        assert 'short_01.mp4' in archive.namelist()
        assert 'legendas/short_01.srt' in archive.namelist()
    print(json.dumps({'status':job.status,'clips':len(job.clips),'duration':result['duration'],
                      'width':result['width'],'height':result['height'],'audio':result['has_audio'],
                      'subtitles':job.clips[0]['subtitles'],'mode':'real_local_no_cloud'},ensure_ascii=False))

"""Operator-only smoke test. Costs resources; requires --execute after approval.

Never enables the engine, writes production jobs/quota, or reads other jobs.
Needs vercel-sandbox/blob, python-dotenv, local ffmpeg/espeak and .env.local.
"""
import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from api import sandbox_engine as engine
from synthetic_media import generate


def load_local_env(path):
    # dotenv parsing is data-only; never source an untrusted file as shell code.
    from dotenv import dotenv_values
    for key,value in dotenv_values(path).items():
        if value is not None: os.environ.setdefault(key,value)


def verify_project():
    # Token claims are checked for accidental target mismatch. Actual signature
    # verification/authorization is performed by Vercel, never by this guard.
    token=os.getenv('VERCEL_OIDC_TOKEN','')
    if token:
        import base64
        data=json.loads(base64.urlsafe_b64decode(token.split('.')[1]+'==='))
        if (data.get('owner')!='murilo15' or data.get('project')!='backend-short-clips'
                or data.get('exp',0)<=time.time()+600):
            raise RuntimeError('OIDC deve identificar murilo15/backend-short-clips e durar pelo menos 10 minutos.')
    elif not (os.getenv('VERCEL_TEAM_ID') and os.getenv('VERCEL_PROJECT_ID') and os.getenv('VERCEL_TOKEN')):
        raise RuntimeError('Credenciais Sandbox indisponíveis; não foi criado Sandbox.')


async def check_atomic_blob(prefix):
    """Real simultaneous create-only writes. Abort if service admits >1 winner."""
    from vercel import blob
    path=prefix+'mutex.json'
    async def attempt(number):
        try:
            await blob.put_blob(path,str(number).encode(),access='private',allow_overwrite=False,cache_control_max_age=0)
            return True
        except Exception as error:
            if getattr(error,'status_code',None) in (400,409,412): return False
            raise
    results=await asyncio.gather(*(attempt(i) for i in range(8)))
    if sum(results)!=1: raise RuntimeError('Blob create-only não protege concorrência: teste interrompido.')
    await blob.delete_blob(path)
    return sum(results)


async def main():
    from vercel import blob, sandbox
    from vercel.sandbox import SandboxResources
    verify_project()
    test_id=secrets.token_hex(16)
    prefix=f'shortforge/integration/{test_id}/'
    started=datetime.now(timezone.utc)
    state=dict(id=test_id,url='synthetic:operator',count=1,length=30,resolution=720,
               facecam='auto',manual_box=[0,0,.5,.8],started_at=started.isoformat(),
               expires_at=(started+timedelta(hours=24)).isoformat(),status='queued',clips=[],errors=[])
    box=None
    report={'test_id':test_id,'project':'murilo15/backend-short-clips','mode':'real_cloud',
            'region':'iad1','max_seconds':600,'persistent':False}
    try:
        report['atomic_create_winners']=await check_atomic_blob(prefix)
        with tempfile.TemporaryDirectory(prefix='sf-cloud-') as directory:
            source=Path(directory)/'input.mp4';generate(source)
            await blob.put_blob(prefix+'input.mp4',source.read_bytes(),access='private',content_type='video/mp4')
        await engine._write_blob(prefix+'state.json',state)
        # Hard session cap; no snapshots. Awaited create leaves lifetime to finally.
        box=await sandbox.create_sandbox(name='sf-test-'+test_id,region='iad1',
                image=os.getenv('SHORTFORGE_SANDBOX_IMAGE','vercel/sandbox/python:3.14'),
                resources=SandboxResources(vcpus=2,memory=4096),execution_time_limit=timedelta(minutes=10),persistent=False)
        await box.fs.write_bytes('/tmp/shortforge-worker.tar.gz',engine.worker_archive())
        env={key:os.environ[key] for key in ('BLOB_READ_WRITE_TOKEN','BLOB_STORE_ID','VERCEL_OIDC_TOKEN') if os.getenv(key)}
        env.update(SHORTFORGE_JOB=json.dumps(state),SHORTFORGE_JOB_BLOB_PATH=prefix+'state.json',
                   SHORTFORGE_TEST_SOURCE_BLOB=prefix+'input.mp4',SHORTFORGE_PUBLIC_API_URL='',
                   OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',MKL_NUM_THREADS='2')
        await box.create_command('python3',['-c',engine.BOOTSTRAP],env=env,stdout=-3,stderr=-3)
        deadline=time.monotonic()+570
        stages=[]
        while time.monotonic()<deadline:
            current=await engine._read_blob(prefix+'state.json')
            if current.get('stage') not in stages: stages.append(current.get('stage'))
            if current['status'] in ('completed','partial','failed'): break
            await asyncio.sleep(5)
        else: raise TimeoutError('Worker excedeu limite do teste de 570s.')
        report['status']=current['status'];report['stages']=stages;report['usage']=current.get('usage')
        if current['status']!='completed': raise RuntimeError('Worker não concluiu; verifique dependências/imagem antes de ativar.')
        path=current['clips'][0]['blob_path']
        result=await blob.get_blob(path,access='private')
        with tempfile.TemporaryDirectory(prefix='sf-result-') as directory:
            target=Path(directory)/'short.mp4';target.write_bytes(result.body)
            data=json.loads(__import__('subprocess').check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(target)]))
            video=next(s for s in data['streams'] if s['codec_type']=='video')
            assert (video['width'],video['height'])==(720,1280)
            assert float(data['format']['duration'])<=45.001
            assert any(s['codec_type']=='audio' for s in data['streams'])
        report['mp4_bytes']=len(result.body);report['sha256']=hashlib.sha256(result.body).hexdigest()
        report['zip_bytes']=len((await blob.get_blob(current['zip_path'],access='private')).body)
    finally:
        # Try both cleanups independently. Never print exception text containing tokens.
        cleanup_errors=[]
        if box:
            try:
                await box.stop()
                await box.destroy()
                report['sandbox_destroyed']=True
            except Exception as error:
                cleanup_errors.append(type(error).__name__)
        try:
            paths=[item.pathname async for item in blob.query_blobs(prefix=prefix)]
            if paths: await blob.delete_blob(paths)
            report['deleted_blobs']=len(paths)
            report['remaining_blobs']=len([item async for item in blob.query_blobs(prefix=prefix)])
        except Exception as error:
            cleanup_errors.append(type(error).__name__)
        if cleanup_errors: report['cleanup_errors']=cleanup_errors
        output=ROOT/'docs/cloud-smoke-result.json'
        output.write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,ensure_ascii=False))
        if cleanup_errors: raise RuntimeError('Limpeza incompleta; consultar relatório e prefixo isolado.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true',help='Use somente após autorização de consumo.')
    parser.add_argument('--env-file',default=str(ROOT/'.env.local'))
    args=parser.parse_args()
    if not args.execute: parser.exit(message='Preparado; nenhuma operação remota executada. Requer --execute após autorização.\n')
    load_local_env(args.env_file)
    try: asyncio.run(main())
    except Exception as error:
        print('Teste falhou: '+type(error).__name__+'; sem publicar segredos.',file=sys.stderr)
        raise SystemExit(1)

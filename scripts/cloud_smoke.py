"""One operator-authorized integration attempt; no deploy or Production mutation.

Requires --execute. VM deadline 540s; no retry ever creates another sandbox.
JSON event log and report contain allowlisted diagnostics, never environment.
"""
import argparse
import asyncio
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from api import sandbox_engine as engine
from synthetic_media import generate

MAX_SESSION_SECONDS = 540
MAX_COMPUTE_USD = .057
CPU_HOUR_USD = .128
MEMORY_GB_HOUR_USD = .0212
REPORT_PATH = ROOT / 'docs/cloud-smoke-result.json'
LOG_PATH = ROOT / 'docs/cloud-smoke-events.jsonl'


def event(phase, **data):
    value = dict(at=datetime.now(timezone.utc).isoformat(), phase=phase, **data)
    line = json.dumps(value, ensure_ascii=False)
    with LOG_PATH.open('a') as file:
        file.write(line + '\n')
    print(line, flush=True)


def safe_error(error):
    result = {'type': type(error).__name__}
    status = getattr(error, 'status_code', None)
    code = getattr(error, 'code', None)
    if isinstance(status, int): result['http_status'] = status
    if isinstance(code, str) and re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', code): result['code'] = code
    return result


def load_local_env(path):
    from dotenv import dotenv_values
    for key, value in dotenv_values(path).items():
        if value is not None: os.environ.setdefault(key, value)


def verify_project():
    # Scope guard only; signature/auth is verified by the actual Vercel APIs.
    token = os.getenv('VERCEL_OIDC_TOKEN', '')
    if not token: raise RuntimeError('OIDC local necessário para verificar o escopo do teste.')
    data = json.loads(base64.urlsafe_b64decode(token.split('.')[1] + '==='))
    if (data.get('owner') != 'murilo15' or data.get('project') != 'backend-short-clips'
            or data.get('exp', 0) <= time.time() + 600):
        raise RuntimeError('OIDC fora do escopo ou sem validade de dez minutos.')
    if not os.getenv('BLOB_STORE_ID'): raise RuntimeError('Blob privado não configurado.')


def budget_bound(seconds):
    return 2 * seconds / 3600 * CPU_HOUR_USD + 4 * math.ceil(seconds / 60) / 60 * MEMORY_GB_HOUR_USD


async def check_atomic_blob(prefix):
    from vercel import blob
    path = prefix + 'mutex.json'
    async def attempt(number):
        try:
            await blob.put_blob(path, str(number).encode(), access='private', allow_overwrite=False, cache_control_max_age=60)
            return {'won': True}
        except Exception as error:
            return {'won': False, 'expected_conflict': getattr(error, 'status_code', None) in (409, 412) or 'already exists' in str(error).lower(), 'error': safe_error(error)}
    results = await asyncio.gather(*(attempt(i) for i in range(8)))
    winners = sum(item['won'] for item in results)
    if not winners: raise RuntimeError('Nenhuma escrita Blob foi autorizada; não iniciar VM.')
    await blob.delete_blob(path)
    # Even if mutex fails, this independent one-VM media test stays isolated.
    return {'requests': len(results), 'winners': winners, 'passed': winners == 1 and all(item.get('expected_conflict') for item in results if not item['won']),
            'rejections': [item['error'] for item in results if not item['won']]}


async def cleanup_sandbox(sandbox, name, box, report):
    """Reconcile even an ambiguous creation; stop/destroy are independent."""
    if not box:
        try: box = await asyncio.wait_for(sandbox.get_sandbox(name=name), 20)
        except Exception as error:
            if getattr(error, 'status_code', None) == 404:
                report['sandbox_absent'] = True
                return []
            return [safe_error(error)]
    failures = []
    stopped = False
    destroyed = False
    for attempt in range(3):
        try:
            await asyncio.wait_for(box.stop(), 25)
            stopped = True
        except Exception as error:
            if getattr(error, 'status_code', None) == 404: stopped = True
            else: event('cleanup_stop_error', attempt=attempt + 1, error=safe_error(error))
        try:
            await asyncio.wait_for(box.destroy(delete_orphan_snapshots=True), 25)
            destroyed = True
            break
        except Exception as error:
            if getattr(error, 'status_code', None) == 404:
                destroyed = True
                break
            failures.append(safe_error(error))
            event('cleanup_destroy_error', attempt=attempt + 1, error=safe_error(error))
    report['sandbox_stop_confirmed'] = stopped or destroyed
    report['sandbox_destroy_confirmed'] = destroyed
    if destroyed:
        try:
            result = await asyncio.wait_for(sandbox.get_sandbox(name=name), 15)
            report['sandbox_final_status'] = str(result.status)
            if str(result.status) not in ('deleted', 'destroyed'):
                failures.append({'type': 'SandboxStillExists'})
        except Exception as error:
            if getattr(error, 'status_code', None) == 404:
                report['sandbox_absent_after_destroy'] = True
            else: failures.append(safe_error(error))
    return [] if destroyed and (report.get('sandbox_absent_after_destroy') or report.get('sandbox_final_status') in ('deleted', 'destroyed')) else failures or [{'type': 'SandboxCleanupUnconfirmed'}]


async def main():
    from vercel import blob, sandbox
    from vercel.sandbox import SandboxResources
    verify_project()
    assert budget_bound(MAX_SESSION_SECONDS) < MAX_COMPUTE_USD
    # No create occurs if the public engine is active.
    def health():
        with urlopen('https://backend-short-clips.vercel.app/api/health', timeout=15) as response:
            state = json.loads(response.read(4096))
            return {'mode': state.get('mode'), 'ready': state.get('ready')}
    production = await asyncio.to_thread(health)
    if production['ready'] or production['mode'] == 'sandbox':
        raise RuntimeError('Produção deve permanecer sem motor público ativo.')
    test_id = secrets.token_hex(16)
    prefix = f'shortforge/integration/{test_id}/'
    name = 'sf-test-' + test_id
    started = datetime.now(timezone.utc)
    state = dict(id=test_id, url='synthetic:operator', count=1, length=30, resolution=720,
                 facecam='auto', manual_box=[0, 0, .5, .8], started_at=started.isoformat(),
                 expires_at=(started + timedelta(hours=24)).isoformat(), status='queued', clips=[], errors=[])
    box = None
    creation_attempted = False
    command_done = None
    vm_clock = None
    error_info = None
    report = dict(test_id=test_id, project='murilo15/backend-short-clips', region='iad1',
                  mode='real_cloud', vm_deadline_seconds=MAX_SESSION_SECONDS, vcpus=2, memory_mb=4096,
                  persistent=False, production_health=production,
                  worst_case_compute_usd=round(budget_bound(MAX_SESSION_SECONDS), 6),
                  cost_limit_usd=MAX_COMPUTE_USD, billing_data_available=False, steps={})
    # Persist identity BEFORE any creation for external/operator recovery.
    REPORT_PATH.write_text(json.dumps(report, indent=2) + '\n')
    LOG_PATH.write_text('')
    event('preflight', test_id=test_id, max_compute_usd=report['worst_case_compute_usd'])
    try:
        report['atomic_blob'] = await check_atomic_blob(prefix)
        event('atomic_blob', winners=report['atomic_blob']['winners'])
        with tempfile.TemporaryDirectory(prefix='sf-cloud-') as directory:
            source = Path(directory) / 'input.mp4'
            await asyncio.to_thread(generate, source)
            report['source_bytes'] = source.stat().st_size
            await blob.put_blob(prefix + 'input.mp4', source.read_bytes(), access='private', content_type='video/mp4')
        await engine._write_blob(prefix + 'state.json', state)
        report['steps']['private_input_upload'] = True
        creation_attempted = True
        vm_clock = time.monotonic()
        box = await asyncio.wait_for(sandbox.create_sandbox(name=name, region='iad1',
                    image='vercel/sandbox/python:3.14', resources=SandboxResources(vcpus=2, memory=4096),
                    execution_time_limit=timedelta(seconds=MAX_SESSION_SECONDS), persistent=False), 45)
        report['actual_sandbox'] = dict(name=box.name, project_id=box.project_id, region=box.region,
                                       vcpus=box.vcpus, memory_mb=box.memory, persistent=box.persistent)
        if box.vcpus != 2 or box.memory != 4096 or box.persistent is not False:
            raise RuntimeError('Recursos retornados fora do envelope autorizado.')
        event('sandbox_created', **report['actual_sandbox'])
        bundle=engine.worker_archive()
        report['worker_archive_sha256']=hashlib.sha256(bundle).hexdigest()
        await box.fs.write_bytes('/tmp/shortforge-worker.tar.gz', bundle)
        env = {key: os.environ[key] for key in ('BLOB_READ_WRITE_TOKEN', 'BLOB_STORE_ID', 'VERCEL_OIDC_TOKEN') if os.getenv(key)}
        env.update(SHORTFORGE_JOB=json.dumps(state), SHORTFORGE_JOB_BLOB_PATH=prefix + 'state.json',
                   SHORTFORGE_TEST_SOURCE_BLOB=prefix + 'input.mp4', SHORTFORGE_PUBLIC_API_URL='',
                   SHORTFORGE_DIAGNOSTICS_PATH='/tmp/shortforge-diagnostics.jsonl',
                   OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2', MKL_NUM_THREADS='2', TOKENIZERS_PARALLELISM='false')
        # Fixed-path local log, never secrets passed as command-line arguments.
        log_redirect = "import os\nf=os.open('/tmp/shortforge-test.log',os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)\nos.dup2(f,1)\nos.dup2(f,2)\nos.close(f)\n"
        command = await box.create_command('python3', ['-c', log_redirect + engine.BOOTSTRAP], env=env, stdout=-3, stderr=-3)
        command_done = asyncio.create_task(command.wait())
        report['steps']['worker_launched'] = True
        deadline = vm_clock + 480  # leave a minute for stop/destroy before hard cap
        stages = []
        last_log = 0
        while time.monotonic() < deadline:
            current = await engine._read_blob(prefix + 'state.json')
            stage = current.get('stage', current.get('status'))
            if stage not in stages:
                stages.append(stage)
                event('worker_stage', stage=stage, status=current['status'])
            if current['status'] in ('completed', 'partial', 'failed'): break
            if command_done.done():
                report['worker_exit_code'] = await command_done
                if report['worker_exit_code'] != 0: raise RuntimeError('Worker terminou antes de publicar estado final.')
            if time.monotonic() - last_log >= 30:
                event('worker_wait', vm_seconds=round(time.monotonic() - vm_clock, 1))
                last_log = time.monotonic()
            await asyncio.sleep(5)
        else: raise TimeoutError('Teste interrompido antes do limite de computação.')
        report.update(status=current['status'], stages=stages, usage=current.get('usage'))
        if current['status'] != 'completed': raise RuntimeError('Worker recusou produzir resultado completo.')
        report['steps']['durable_final_state'] = True
        report['worker_exit_code'] = await asyncio.wait_for(asyncio.shield(command_done), 15)
        check = await box.run_command('python3', ['-c',
            "import json,pathlib; print(json.dumps({'worker_temp_removed':not pathlib.Path('/tmp/shortforge-job/" + test_id + "').exists()}))"], capture_output=True, check=True)
        report['steps'].update(json.loads(check.stdout))
        raw_diagnostics = await box.fs.read_text('/tmp/shortforge-diagnostics.jsonl')
        report['worker_diagnostics'] = [json.loads(line) for line in raw_diagnostics.splitlines() if line.strip()]
        # Stop billing before downloading/validating artifacts on the local host.
        await box.stop()
        report['sandbox_stopped_seconds'] = round(time.monotonic() - vm_clock, 2)
        path = current['clips'][0]['blob_path']
        if not path.startswith(prefix + 'output/'): raise RuntimeError('Artefato fora do prefixo do teste.')
        result = await blob.get_blob(path, access='private')
        with tempfile.TemporaryDirectory(prefix='sf-result-') as directory:
            target = Path(directory) / 'short.mp4'
            target.write_bytes(result.body)
            data = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(target)], timeout=20))
            video = next(s for s in data['streams'] if s['codec_type'] == 'video')
            assert (video['width'], video['height']) == (720, 1280)
            assert 29.9 <= float(data['format']['duration']) <= 45.001
            assert any(s['codec_type'] == 'audio' for s in data['streams'])
            subprocess.run(['ffmpeg', '-v', 'error', '-xerror', '-nostdin', '-i', str(target), '-f', 'null', '-'], check=True, timeout=30, capture_output=True)
        report['mp4'] = dict(bytes=len(result.body), sha256=hashlib.sha256(result.body).hexdigest(),
                             width=video['width'], height=video['height'], seconds=float(data['format']['duration']), audio=True, fully_decoded=True)
        archive = (await blob.get_blob(current['zip_path'], access='private')).body
        with zipfile.ZipFile(io.BytesIO(archive)) as package:
            assert package.testzip() is None
            assert hashlib.sha256(package.read('short_01.mp4')).hexdigest() == report['mp4']['sha256']
            report['zip'] = dict(bytes=len(archive), files=package.namelist(), integrity=True)
        report['steps'].update(private_mp4_retrieved=True, private_zip_retrieved=True)
        report['integration_passed'] = True
        event('artifacts_validated', mp4_bytes=report['mp4']['bytes'], zip_bytes=len(archive))
    except BaseException as error:
        error_info = safe_error(error)
        report['error'] = error_info
        event('test_error', error=error_info)
        if box and str(box.status) not in ('stopped', 'deleted', 'destroyed'):
            try:
                # Structured allowlist only. Never dump arbitrary remote output.
                raw = await asyncio.wait_for(box.fs.read_text('/tmp/shortforge-diagnostics.jsonl'), 10)
                report['worker_diagnostics'] = [json.loads(line) for line in raw.splitlines() if line.strip()]
            except Exception: pass
    finally:
        if command_done and not command_done.done():
            command_done.cancel()
            await asyncio.gather(command_done, return_exceptions=True)
        cleanup_errors = []
        if creation_attempted:
            cleanup_errors += await cleanup_sandbox(sandbox, name, box, report)
            if vm_clock:
                report['sandbox_lifetime_upper_seconds'] = round(time.monotonic() - vm_clock, 2)
                elapsed = min(MAX_SESSION_SECONDS, report.get('sandbox_stopped_seconds', report['sandbox_lifetime_upper_seconds']))
                report['compute_upper_estimate_usd'] = round(budget_bound(elapsed), 6)
        try:
            paths = [item.pathname async for item in blob.query_blobs(prefix=prefix)]
            for offset in range(0, len(paths), 1000): await blob.delete_blob(paths[offset:offset + 1000])
            report['deleted_blobs'] = len(paths)
            report['remaining_blobs'] = len([item async for item in blob.query_blobs(prefix=prefix)])
            report['deleted_paths_head_404'] = 0
            for path in paths:
                try: await blob.head_blob(path)
                except Exception as error:
                    if getattr(error, 'status_code', None) == 404:
                        report['deleted_paths_head_404'] += 1
                    else: raise
                else: raise RuntimeError('Blob ainda presente após exclusão.')
            if report['remaining_blobs']: raise RuntimeError('Limpeza incompleta do namespace.')
        except Exception as error: cleanup_errors.append(safe_error(error))
        report['cleanup_errors'] = cleanup_errors
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
        event('cleanup_finished', sandbox_destroyed=report.get('sandbox_destroy_confirmed', False),
              remaining_blobs=report.get('remaining_blobs'), errors=cleanup_errors)
    if error_info or report['cleanup_errors']: raise RuntimeError('Teste falhou; consulte o relatório sanitizado.')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Requer autorização para UMA tentativa.')
    parser.add_argument('--env-file', default=str(ROOT / '.env.local'))
    args = parser.parse_args()
    if not args.execute: parser.exit(message='Preparado; nenhuma operação remota executada.\n')
    load_local_env(args.env_file)
    try: asyncio.run(main())
    except BaseException as error:
        print(json.dumps({'result': 'failed', 'error': safe_error(error)}), file=sys.stderr)
        raise SystemExit(1)

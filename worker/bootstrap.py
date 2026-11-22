"""Bounded setup inside Sandbox. No mutable Git clones, shell input or secret logs."""
from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
VENV = Path('/tmp/sfvenv')


def prepare():
    # Custom images bake this environment in; no apt/pip on each video.
    baked = Path('/opt/shortforge/bin/python')
    if baked.is_file():
        return str(baked)
    subprocess.run([sys.executable, '-m', 'venv', str(VENV)], check=True, timeout=30)
    python = str(VENV / 'bin/python')
    subprocess.run([python, '-m', 'pip', 'install', '--disable-pip-version-check',
                    '--no-cache-dir', 'vercel-blob==0.6.2'],
                   check=True, timeout=120, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    subprocess.run([python, '-m', 'pip', 'install', '--disable-pip-version-check',
                    '--no-cache-dir', '-r', str(ROOT / 'requirements.lock')],
                   check=True, timeout=360, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)
    return python


def main():
    try:
        python = prepare()
    except Exception:
        # The small Blob SDK is installed first so media dependency failures can
        # be published without leaking pip output or environment credentials.
        python = str(VENV / 'bin/python')
        failure = """import asyncio, json, os, sys
sys.path.insert(0, '/tmp/shortforge-backend/worker')
from runner import save, callback
async def fail():
    job=json.loads(os.environ['SHORTFORGE_JOB'])
    job.update(status='failed',stage='failed',message='Falha ao instalar dependências do worker.')
    await save(os.environ['SHORTFORGE_JOB_BLOB_PATH'],job)
    await callback(job['id'])
asyncio.run(fail())
"""
        subprocess.run([python, '-c', failure], timeout=30,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        raise SystemExit(1)
    # Start runner before system setup so bootstrap failures reach durable state.
    os.execve(python, [python, str(ROOT / 'runner.py')], dict(os.environ))


if __name__ == '__main__':
    main()

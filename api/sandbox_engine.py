"""Motor Vercel Sandbox sob demanda, desativado por padrão.

Sandbox só é iniciado após configuração explícita e autenticação. Estado e
mutex ficam num Vercel Blob PRIVADO. MP4s também serão armazenados privadamente,
com downloads assinados por uma função separada.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
import secrets
from .policy import (
    SANDBOX_VCPUS, SANDBOX_MEMORY_MB, SANDBOX_MAX_MINUTES,
    OUTPUT_TTL_HOURS, monthly_cap, period_key, expired,
    validate_job, RequestRejected, approximate_usage,
)

STORE_ACCESS = "private"
ROOT = "shortforge"
LOCK = f"{ROOT}/mutex/active.json"
LATEST = f"{ROOT}/latest.json"
BOOTSTRAP = r"""
set -e
cd /tmp
if ! command -v ffmpeg >/dev/null || ! command -v tesseract >/dev/null; then
  if command -v sudo >/dev/null; then sudo apt-get update -qq && sudo apt-get install -y -qq ffmpeg tesseract-ocr git;
  else apt-get update -qq && apt-get install -y -qq ffmpeg tesseract-ocr git; fi
fi
git clone --depth 1 https://github.com/DevMurilo0/ShortClips.git shortforge-source
git clone --depth 1 https://github.com/DevMurilo0/BackendShortClips.git shortforge-backend
python -m venv /tmp/sfvenv
/tmp/sfvenv/bin/pip install --disable-pip-version-check --no-cache-dir vercel-blob
/tmp/sfvenv/bin/pip install --disable-pip-version-check --no-cache-dir -r /tmp/shortforge-source/requirements.txt
exec /tmp/sfvenv/bin/python /tmp/shortforge-backend/worker/runner.py
""".strip()


def enabled() -> bool:
    return os.getenv("SHORTFORGE_ENGINE", "").lower() == "sandbox"


def configured() -> bool:
    return bool(enabled()
                and os.getenv("BLOB_READ_WRITE_TOKEN")
                and os.getenv("SHORTFORGE_PUBLIC_ACCESS_KEY")
                and os.getenv("SHORTFORGE_WORKER_SECRET")
                and os.getenv("SHORTFORGE_FRONTEND_ORIGIN", "https://short-clips-tan.vercel.app"))


def _blob():
    from vercel import blob
    return blob


def _sandbox():
    from vercel import sandbox
    from vercel.sandbox import SandboxResources
    return sandbox, SandboxResources


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path(job_id: str, when: str | None = None) -> str:
    month = when or period_key()
    return f"{ROOT}/jobs/{month}/{job_id}/state.json"


async def _write_blob(path: str, obj: dict, *, overwrite: bool = True):
    return await _blob().put_blob(
        path, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
        access=STORE_ACCESS, content_type="application/json",
        allow_overwrite=overwrite, cache_control_max_age=0
    )


async def _read_blob(path: str):
    try:
        result = await _blob().get_blob(path, access=STORE_ACCESS)
    except Exception as exc:
        if type(exc).__name__ == "BlobNotFoundError":
            return None
        raise
    return json.loads(result.body)


async def _release_lock(job_id: str):
    current = await _read_blob(LOCK)
    if current and current.get("id") == job_id:
        metadata = await _blob().head_blob(LOCK)
        await _blob().delete_blob(LOCK, if_match=metadata.etag)


async def _acquire_lock(job_id: str):
    active = await _read_blob(LOCK)
    if active:
        # Um Sandbox Hobby termina em até 45min, deixando pequena margem.
        try:
            started = datetime.fromisoformat(active["started_at"])
            stale = datetime.now(timezone.utc) >= started + timedelta(minutes=48)
        except (KeyError, ValueError, TypeError):
            stale = False  # nunca apaga um lock desconhecido sem operador
        if stale:
            await _release_lock(active["id"])
        else:
            raise RequestRejected("Já existe um processamento em andamento. Aguarde terminar.")
    # allow_overwrite=False: criação atômica protege requisições simultâneas.
    try:
        await _write_blob(LOCK, {"id": job_id, "started_at": _stamp()}, overwrite=False)
    except Exception as exc:
        if type(exc).__name__ in ("BlobAlreadyExistsError", "BlobConflictError",
                                  "BlobStoreConflictError"):
            raise RequestRejected("Já existe outro processamento ativo.") from None
        raise


async def _quota():
    # Marcadores de uso ficam durante o mês, independentemente da limpeza dos MP4s.
    prefix = f"{ROOT}/quota/{period_key()}/"
    count = 0
    async for _ in _blob().query_blobs(prefix=prefix):
        count += 1
        if count >= monthly_cap():
            raise RequestRejected(
                "Limite mensal do Hobby atingido. Não foram consumidos recursos de um novo Sandbox."
            )
    return count


async def submit(payload: dict) -> dict:
    if not configured():
        raise RuntimeError("O Sandbox não foi habilitado ou não possui armazenamento/credenciais.")
    opts = validate_job(payload)
    await _quota()
    job_id = secrets.token_hex(16)
    await _acquire_lock(job_id)
    now = _stamp()
    path = _path(job_id)
    job = dict(
        id=job_id, url=opts["url"], count=opts["count"], length=opts["length"],
        resolution=opts["resolution"], facecam=opts["facecam"],
        model_name=opts["model_name"], manual_box=opts["manual_box"],
        title="", status="queued", stage="preparing",
        message="Preparando Sandbox isolado...", clips=[], errors=[],
        progress=0, started_at=now, expires_at=(datetime.now(timezone.utc)
            + timedelta(hours=OUTPUT_TTL_HOURS)).isoformat(),
        sandbox_name="shortforge-" + job_id, usage={"mode":"estimated_not_billing"},
        zip_name=None,
    )
    created = False
    try:
        await _write_blob(path, job)
        await _write_blob(LATEST, {"id":job_id,"month":period_key()})
        sandbox, SandboxResources = _sandbox()
        box = await sandbox.create_sandbox(
            name=job["sandbox_name"], image="vercel/sandbox/python:3.14",
            execution_time_limit=timedelta(minutes=SANDBOX_MAX_MINUTES),
            resources=SandboxResources(vcpus=SANDBOX_VCPUS,
                                       memory=SANDBOX_MEMORY_MB),
            persistent=False,
        )
        created = True
        env = {
            "BLOB_READ_WRITE_TOKEN": os.environ["BLOB_READ_WRITE_TOKEN"],
            "SHORTFORGE_JOB": json.dumps(job, ensure_ascii=False),
            "SHORTFORGE_JOB_BLOB_PATH": path,
            "SHORTFORGE_WORKER_SECRET": os.environ["SHORTFORGE_WORKER_SECRET"],
            "SHORTFORGE_PUBLIC_API_URL": os.getenv(
                "SHORTFORGE_PUBLIC_API_URL",
                "https://backend-short-clips.vercel.app"
            ).rstrip("/"),
        }
        # create_command é detached: a Function responde sem esperar 5 Shorts.
        await box.create_command("bash", ["-lc", BOOTSTRAP],
                                 env=env, stdout=-3, stderr=-3)
        # Não assume que já terminou: o worker publica estados no Blob.
        await _write_blob(f"{ROOT}/quota/{period_key()}/{job_id}.json",
                          {"id":job_id,"started_at":now}, overwrite=False)
        return job
    except Exception:
        if created:
            try:
                await box.stop()
            except Exception:
                pass
        await _release_lock(job_id)
        job.update(status="failed", stage="failed",
                   message="Falha ao inicializar o motor de processamento.")
        await _write_blob(path, job)
        raise


async def get_job(job_id: str, *, month: str | None = None) -> dict | None:
    if not month:
        for offset in (0, -1):
            date = datetime.now(timezone.utc).replace(day=1)
            if offset == -1:
                date -= timedelta(days=1)
            month = date.strftime("%Y-%m")
            job = await _read_blob(_path(job_id, month))
            if job:
                break
    else:
        job = await _read_blob(_path(job_id, month))
    if not job:
        return None
    if expired(job["started_at"]):
        return {"id":job_id,"status":"expired","message":"Arquivos expirados após 24 horas."}
    if job["status"] in ("completed","failed","partial","cancelled"):
        try:
            sandbox,_ = _sandbox()
            box = await sandbox.get_sandbox(name=job["sandbox_name"])
            await box.stop()
        except Exception:
            pass
        try:
            await _release_lock(job_id)
        except Exception:
            pass
    return job


async def latest_job():
    last = await _read_blob(LATEST)
    if not last:
        return None
    return await get_job(last["id"], month=last["month"])


async def cancel(job_id):
    job = await get_job(job_id)
    if not job:
        return None
    if job.get("status") in ("running","queued","preparing"):
        sandbox,_ = _sandbox()
        box = await sandbox.get_sandbox(name=job["sandbox_name"])
        await box.stop()
        job.update(status="cancelled",stage="cancelled",message="Cancelado pelo usuário.")
        await _write_blob(_path(job_id,job["started_at"][:7]), job)
        await _release_lock(job_id)
    return job


async def usage():
    prefix = f"{ROOT}/quota/{period_key()}/"
    count=0
    async for _ in _blob().query_blobs(prefix=prefix):
        count+=1
    return {"active_limit":1,"jobs_month":count,
            "jobs_month_limit":monthly_cap(),
            "remaining_jobs":max(0,monthly_cap()-count),
            "worker_configured":configured(),
            "sandbox":{"vcpus":SANDBOX_VCPUS,"memory_mb":SANDBOX_MEMORY_MB,
                       "max_minutes":SANDBOX_MAX_MINUTES},
            "estimated_one_max_session": approximate_usage(
                SANDBOX_VCPUS * SANDBOX_MAX_MINUTES * 60,
                SANDBOX_MAX_MINUTES * 60, 0, 0),
            "billing_data_available":False,
            "note":"Consumo real deve ser conferido em Vercel Usage."}


async def cleanup():
    """Expira logicamente em 24h; cron diário apaga arquivos físicos em lote."""
    deleted=0
    async for item in _blob().query_blobs(prefix=f"{ROOT}/jobs/"):
        if "/state.json" not in item.pathname:
            continue
        job=await _read_blob(item.pathname)
        if not job or not expired(job["started_at"]):
            continue
        prefix=item.pathname.removesuffix("state.json")
        paths=[]
        async for file in _blob().query_blobs(prefix=prefix):
            paths.append(file.pathname)
        if paths:
            await _blob().delete_blob(paths[:1000])
            deleted+=len(paths[:1000])
    return {"deleted_blobs":deleted}

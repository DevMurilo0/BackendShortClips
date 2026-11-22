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
from api.policy import (
    SANDBOX_VCPUS, SANDBOX_MEMORY_MB, SANDBOX_MAX_MINUTES,
    OUTPUT_TTL_HOURS, monthly_cap, period_key, expired, deletion_due,
    validate_job, RequestRejected, approximate_usage,
)

STORE_ACCESS = "private"
ROOT = os.getenv("SHORTFORGE_STORAGE_PREFIX", "shortforge")
LOCK = f"{ROOT}/mutex/active.json"
LATEST = f"{ROOT}/latest.json"
# The deployed worker is transferred as a trusted archive. Never clone main at runtime.
BOOTSTRAP = """import tarfile, runpy
with tarfile.open('/tmp/shortforge-worker.tar.gz') as archive:
    archive.extractall('/tmp/shortforge-backend', filter='data')
runpy.run_path('/tmp/shortforge-backend/worker/bootstrap.py', run_name='__main__')
"""


def worker_archive() -> bytes:
    import io
    import tarfile
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    content = io.BytesIO()
    with tarfile.open(fileobj=content, mode="w:gz") as archive:
        for path in sorted((root / "worker").rglob("*")):
            if path.is_file() and path.suffix in (".py", ".txt", ".lock"):
                archive.add(path, arcname=str(path.relative_to(root)))
    return content.getvalue()



PREVIEW_SYNTHETIC_URL = "https://youtu.be/00000000000"


def enabled() -> bool:
    return os.getenv("SHORTFORGE_ENGINE", "").lower() == "sandbox"


def preview_synthetic_source() -> str | None:
    """Preview-only, operator-configured private test input; never client-controlled."""
    import re
    flag = os.getenv("SHORTFORGE_PREVIEW_SYNTHETIC_ONLY", "")
    pathname = os.getenv("SHORTFORGE_PREVIEW_TEST_BLOB", "")
    if not flag and not pathname:
        return None
    if flag != "1" or os.getenv("VERCEL_ENV") != "preview" or not namespace_ready():
        raise RuntimeError("Ensaio sintético exige Preview isolado e ativação explícita.")
    if not re.fullmatch(re.escape(ROOT) + r"/integration/[a-f0-9]{32}/input\.mp4", pathname):
        raise RuntimeError("Fonte sintética privada fora do namespace de Preview.")
    return pathname


def preview_callback_url() -> str:
    """Pin callbacks to this team's exact Preview deployment, never Production."""
    from urllib.parse import urlsplit
    url = os.getenv("SHORTFORGE_PUBLIC_API_URL", "").rstrip("/")
    target = urlsplit(url)
    hostname = (target.hostname or "").lower()
    if (target.scheme != "https" or target.username or target.password
            or target.query or target.fragment or target.path
            or not hostname.startswith("backend-short-clips-")
            or not hostname.endswith("-murilo15.vercel.app")):
        raise RuntimeError("O callback do ensaio deve apontar para o deployment Preview exato.")
    return url


def namespace_ready() -> bool:
    import re
    if not re.fullmatch(r"shortforge(?:-preview/[a-z0-9][a-z0-9-]{0,47})?", ROOT):
        return False
    environment = os.getenv("VERCEL_ENV", "")
    if environment == "preview":
        return ROOT.startswith("shortforge-preview/")
    if environment == "production":
        return ROOT == "shortforge"
    return True


def configured() -> bool:
    try:
        test_source = preview_synthetic_source()
        # An active Preview must never fall back to 42-minute YouTube jobs.
        if enabled() and os.getenv("VERCEL_ENV") == "preview":
            if not test_source or not os.getenv("SHORTFORGE_VERCEL_PROTECTION_BYPASS"):
                return False
            preview_callback_url()
    except (RuntimeError, ValueError):
        return False
    user_key = os.getenv("SHORTFORGE_PUBLIC_ACCESS_KEY", "")
    worker_key = os.getenv("SHORTFORGE_WORKER_SECRET", "")
    return bool(enabled() and namespace_ready()
                and os.getenv("BLOB_READ_WRITE_TOKEN")
                and len(user_key) >= 32 and len(worker_key) >= 32
                and user_key != worker_key
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
        allow_overwrite=overwrite, cache_control_max_age=60
    )


def private_state_url(path: str) -> str:
    # Python Blob 0.6.2 has no use_cache flag. The documented ?cache=0 wire
    # option is supported for full private delivery URLs and is required for
    # mutex/state reads after overwrite. SDK still supplies auth; no URL token.
    import re
    from urllib.parse import quote
    store = os.getenv("BLOB_STORE_ID", "").removeprefix("store_")
    if not store:
        match = re.match(r"vercel_blob_rw_([a-zA-Z0-9]+)_", os.getenv("BLOB_READ_WRITE_TOKEN", ""))
        store = match.group(1) if match else ""
    if not re.fullmatch(r"[a-zA-Z0-9]+", store):
        raise RuntimeError("Blob store ID ausente ou inválido.")
    return f"https://{store.lower()}.private.blob.vercel-storage.com/{quote(path, safe='/')}?cache=0"


async def _read_blob(path: str):
    try:
        result = await _blob().get_blob(private_state_url(path), access=STORE_ACCESS)
    except Exception as exc:
        if type(exc).__name__ == "BlobNotFoundError":
            return None
        raise
    return json.loads(result.body)


async def _release_lock(job_id: str):
    # Compare the ID and delete the *same version*, never HEAD after GET.
    try:
        result = await _blob().get_blob(private_state_url(LOCK), access=STORE_ACCESS)
        current = json.loads(result.body)
        if current.get("id") == job_id and result.metadata.etag:
            await _blob().delete_blob(LOCK, if_match=result.metadata.etag)
    except Exception as exc:
        if type(exc).__name__ not in ("BlobNotFoundError", "BlobPreconditionFailedError"):
            raise


async def _acquire_lock(job_id: str):
    active = await _read_blob(LOCK)
    if active:
        try:
            started = datetime.fromisoformat(active["started_at"])
            stale = datetime.now(timezone.utc) >= started + timedelta(minutes=48)
        except (KeyError, ValueError, TypeError):
            stale = False
        if stale:
            # Deadline includes cold-start margin; stop must succeed before reuse.
            await _stop_box("shortforge-" + active["id"])
            await _release_lock(active["id"])
        else:
            raise RequestRejected("Já existe um processamento em andamento. Aguarde terminar.")
    try:
        await _write_blob(LOCK, {"id": job_id, "started_at": _stamp()}, overwrite=False)
    except Exception as exc:
        # Python 0.6.2 maps existing-path responses to BlobError, not a special
        # BlobAlreadyExistsError. Fail closed for storage/network errors too.
        if (getattr(exc, "status_code", None) in (409, 412)
                or "already exists" in str(exc).lower()):
            raise RequestRejected("Já existe outro processamento ativo.") from None
        raise


async def _terminate_box(box):
    # Destroy still runs if stop fails; never leave a named worker/snapshot.
    try:
        await box.stop()
    finally:
        await box.destroy(delete_orphan_snapshots=True)


async def _stop_box(name):
    sandbox, _ = _sandbox()
    try:
        box = await sandbox.get_sandbox(name=name)
        await _terminate_box(box)
    except Exception as exc:
        if getattr(exc, "status_code", None) != 404:
            raise


async def _quota(month=None):
    # Marcadores de uso ficam durante o mês, independentemente da limpeza dos MP4s.
    prefix = f"{ROOT}/quota/{month or period_key()}/"
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
    test_source = preview_synthetic_source()
    opts = validate_job(payload)
    if test_source:
        if (opts["url"] != PREVIEW_SYNTHETIC_URL or opts["count"] != 1
                or opts["length"] != 30 or not opts.get("manual_box")):
            raise RequestRejected("Ensaio isolado: somente 1 Short de 30s com facecam manual.")
        preview_callback_url()
        if not os.getenv("SHORTFORGE_VERCEL_PROTECTION_BYPASS"):
            raise RuntimeError("Falta credencial privada para callback do Preview protegido.")
    if opts.get("manual_box"):
        # O formulário usa porcentagens; Job/identify_facecam esperam 0–1.
        opts["manual_box"] = [float(value)/100 for value in opts["manual_box"]]
    job_id = secrets.token_hex(16)
    await _acquire_lock(job_id)
    now = _stamp()
    month = now[:7]
    path = _path(job_id, month)
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
    creation_attempted = False
    try:
        await _quota(month)  # Serialized by the global lock, including the last monthly slot.
        if test_source:
            # Create-only reservation: one paid synthetic run per isolated Preview namespace.
            try:
                await _write_blob(f"{ROOT}/integration/once.json",
                                  {"id":job_id, "started_at":now}, overwrite=False)
            except Exception as error:
                if (getattr(error, "status_code", None) in (409, 412)
                        or "already exists" in str(error).lower()):
                    raise RequestRejected("Este namespace já consumiu seu ensaio sintético.") from None
                raise
        await _write_blob(path, job)
        await _write_blob(LATEST, {"id":job_id,"month":month})
        # A reservation survives cold starts, failures, deletion and month rollover.
        # Conservatively count initialization failures; never refund a possibly running VM.
        await _write_blob(f"{ROOT}/quota/{month}/{job_id}.json",
                          {"id":job_id,"started_at":now}, overwrite=False)
        sandbox, SandboxResources = _sandbox()
        creation_attempted = True
        box = await asyncio.wait_for(sandbox.create_sandbox(
            name=job["sandbox_name"],
            image=os.getenv("SHORTFORGE_SANDBOX_IMAGE", "vercel/sandbox/python:3.14"),
            region="iad1",
            execution_time_limit=timedelta(minutes=10 if test_source else SANDBOX_MAX_MINUTES),
            resources=SandboxResources(vcpus=SANDBOX_VCPUS,
                                       memory=SANDBOX_MEMORY_MB),
            persistent=False,
        ), timeout=25)
        created = True
        await box.fs.write_bytes("/tmp/shortforge-worker.tar.gz", worker_archive())
        env = {
            "OMP_NUM_THREADS": "2", "OPENBLAS_NUM_THREADS": "2",
            "MKL_NUM_THREADS": "2", "TOKENIZERS_PARALLELISM": "false",
            "BLOB_READ_WRITE_TOKEN": os.environ["BLOB_READ_WRITE_TOKEN"],
            "SHORTFORGE_JOB": json.dumps(job, ensure_ascii=False),
            "SHORTFORGE_JOB_BLOB_PATH": path,
            "SHORTFORGE_WORKER_SECRET": os.environ["SHORTFORGE_WORKER_SECRET"],
            "SHORTFORGE_STORAGE_PREFIX": ROOT,
            "SHORTFORGE_DEPLOY_ENV": os.getenv("VERCEL_ENV", ""),
            "SHORTFORGE_PUBLIC_API_URL": os.getenv(
                "SHORTFORGE_PUBLIC_API_URL",
                "https://backend-short-clips.vercel.app"
            ).rstrip("/"),
        }
        if test_source:
            env["SHORTFORGE_TEST_SOURCE_BLOB"] = test_source
            env["SHORTFORGE_VERCEL_PROTECTION_BYPASS"] = os.environ[
                "SHORTFORGE_VERCEL_PROTECTION_BYPASS"]
        # create_command é detached: a Function responde sem esperar 5 Shorts.
        await box.create_command("python3", ["-c", BOOTSTRAP],
                                 env=env, stdout=-3, stderr=-3)
        return job
    except BaseException as failure:
        # A transport timeout can happen AFTER Vercel accepted creation. Keep
        # the lock for uncertain outcomes; the deterministic name reconciles it.
        definite_rejection = getattr(failure, "status_code", None) in (400, 401, 403, 422)
        stopped = not creation_attempted or definite_rejection
        if created:
            try:
                await _terminate_box(box)
                stopped = True
            except Exception:
                pass  # Keep lock until deadline if VM stop could not be confirmed.
        if stopped:
            await _release_lock(job_id)
        job.update(status="failed", stage="failed",
                   launch_uncertain=creation_attempted and not created and not definite_rejection,
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
        await _expire_job(job)
        return job
    if job["status"] in ("queued","running","preparing"):
        started = datetime.fromisoformat(job["started_at"])
        if datetime.now(timezone.utc) >= started + timedelta(minutes=48):
            job.update(status="failed",stage="failed",
                       message="O Sandbox atingiu o limite de tempo ou foi encerrado.",
                       errors=["Timeout do motor: limite de 42 minutos por tarefa."])
            await _stop_box(job["sandbox_name"])
            await _write_blob(_path(job_id,job["started_at"][:7]),job)
            await _release_lock(job_id)
    if job["status"] in ("completed","failed","partial","cancelled"):
        if job.get("launch_uncertain"):
            started = datetime.fromisoformat(job["started_at"])
            if datetime.now(timezone.utc) < started + timedelta(minutes=48):
                return job  # Do not unlock a creation request whose outcome is unknown.
        await _stop_box(job["sandbox_name"])
        await _release_lock(job_id)
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
        await _stop_box(job["sandbox_name"])
        job.update(status="cancelled",stage="cancelled",message="Cancelado pelo usuário.")
        await _write_blob(_path(job_id,job["started_at"][:7]), job)
        await _release_lock(job_id)
    return job


async def finalize(job_id: str):
    """Callback autenticado: encerra VM somente após arquivo de estado final."""
    job = await get_job(job_id)
    if not job:
        return {"ok":False,"reason":"Tarefa inexistente."}
    if job.get("status") not in ("completed","failed","partial","cancelled","expired"):
        return {"ok":False,"reason":"Tarefa ainda está em execução."}
    await _stop_box("shortforge-" + job_id)
    await _release_lock(job_id)
    return {"ok":True,"id":job_id,"status":job["status"]}



async def usage():
    """Contagem gravada no Blob e estimativas; não é a fatura oficial."""
    month = period_key()
    prefix = f"{ROOT}/quota/{month}/"
    count=0
    cpu_seconds=0.0
    wall_seconds=0.0
    output_bytes=0
    async for mark in _blob().query_blobs(prefix=prefix):
        if not mark.pathname.endswith(".json"):
            continue
        count+=1
        job_id=mark.pathname.rsplit("/",1)[-1].removesuffix(".json")
        if not re_job_id(job_id):
            continue
        state=await _read_blob(_path(job_id,month))
        if not state:
            continue
        metrics=state.get("usage") or {}
        cpu_seconds+=float(metrics.get("cpu_seconds") or 0)
        wall_seconds+=float(metrics.get("wall_seconds") or 0)
        output_bytes+=int(metrics.get("output_bytes") or 0)
    # Estoque atual em Blob, não é armazenamento médio faturável no mês.
    stored_bytes=0
    async for file in _blob().query_blobs(prefix=f"{ROOT}/jobs/"):
        if "/output/" in file.pathname:
            stored_bytes+=file.size
    overview=approximate_usage(cpu_seconds,wall_seconds,stored_bytes,output_bytes)
    return {
        "active_limit":1,
        "jobs_month":count,"jobs_month_limit":monthly_cap(),
        "remaining_jobs":max(0,monthly_cap()-count),
        "worker_configured":configured(),
        "sandbox":{"vcpus":SANDBOX_VCPUS,"memory_mb":SANDBOX_MEMORY_MB,
                   "max_minutes":SANDBOX_MAX_MINUTES},
        "usage":overview,
        "estimated_one_max_session": approximate_usage(
            SANDBOX_VCPUS * SANDBOX_MAX_MINUTES * 60,
            SANDBOX_MAX_MINUTES * 60, 0, 0),
        "billing_data_available":False,
        "note":"CPU e transferência estimadas pelo ShortForge. Valores oficiais em Vercel Usage.",
    }


def re_job_id(job_id):
    return len(job_id)==32 and all(x in "0123456789abcdef" for x in job_id)


async def _expire_job(job):
    if job.get("status") == "expired":
        return
    await _stop_box(job["sandbox_name"])
    prefix = _path(job["id"], job["started_at"][:7]).removesuffix("state.json")
    paths = {item.pathname async for item in _blob().query_blobs(prefix=prefix)
             if item.pathname != prefix + "state.json"}
    # Reconcile the manifest too; a listing alone must not hide a known artifact.
    known = [clip.get("blob_path") for clip in job.get("clips", [])] + [job.get("zip_path")]
    paths.update(path for path in known if isinstance(path, str) and path.startswith(prefix + "output/"))
    paths = sorted(paths)
    for offset in range(0, len(paths), 1000):
        await _blob().delete_blob(paths[offset:offset + 1000])
    # Record success only after private catalog reads confirm physical object
    # removal. If one remains, keep a retryable state for the next cleanup run.
    for path in paths:
        try:
            await _blob().head_blob(path)
        except Exception as error:
            if type(error).__name__ != "BlobNotFoundError" and getattr(error, "status_code", None) != 404:
                raise
        else:
            raise RuntimeError("Exclusão ainda não confirmada no Blob.")
    deleted_at = _stamp()
    job.update(status="expired", stage="expired", clips=[], zip_name=None,
               deletion={"verified": True, "deleted_at": deleted_at,
                         "artifacts": len(paths), "past_24h_deadline": expired(job["started_at"])},
               message="Prazo de armazenamento encerrado. Arquivos removidos.")
    job.pop("zip_path", None)
    # Retain small audit tombstone for durable quota/usage accounting.
    await _write_blob(prefix + "state.json", job)
    await _release_lock(job["id"])


async def cleanup():
    """Delete expired artifacts; retain quota and usage tombstones."""
    if not namespace_ready():
        raise RuntimeError("Namespace inválido para limpeza neste ambiente.")
    cleaned = 0
    paths = [item.pathname async for item in _blob().query_blobs(prefix=f"{ROOT}/jobs/")
             if item.pathname.endswith("/state.json")]
    for path in paths:
        job = await _read_blob(path)
        if not job or job.get("status") == "expired":
            continue
        if deletion_due(job["started_at"]):
            await _expire_job(job)
            cleaned += 1
        elif job["status"] in ("queued", "running", "preparing"):
            await get_job(job["id"], month=job["started_at"][:7])
    return {"expired_jobs": cleaned}


def public_job(job):
    """Only this single-owner API can mint download links. Never expose storage paths."""
    import copy
    result = copy.deepcopy(job)
    result.pop("sandbox_name", None)
    result.pop("launch_uncertain", None)
    for clip in result.get("clips", []):
        path = clip.pop("blob_path", None)
        clip.pop("download_url", None)
        if path and result["status"] in ("completed", "partial"):
            from urllib.parse import urlencode
            clip["download_endpoint"] = "/api/download?" + urlencode({"pathname": path})
    path = result.pop("zip_path", None)
    if path and result["status"] in ("completed", "partial"):
        from urllib.parse import urlencode
        result["zip_download_endpoint"] = "/api/download?" + urlencode({"pathname": path})
    return result

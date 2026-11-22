#!/usr/bin/env python3
"""Executado DENTRO do Vercel Sandbox. Não roda na Function HTTP.

Executa o pipeline existente, escreve progresso no Blob privado e publica
artefatos. Só envia links de blob pathnames para serem assinados pelo backend.
"""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
import resource
import shutil
import sys
import time
from urllib.request import Request, urlopen

from vercel import blob

SOURCE = Path("/tmp/shortforge-source")
sys.path.insert(0, str(SOURCE))

from shortforge.pipeline import Job, execute


def cpu_time():
    """Soma CPU do worker e de processos filhos (incluindo FFmpeg)."""
    self = resource.getrusage(resource.RUSAGE_SELF)
    children = resource.getrusage(resource.RUSAGE_CHILDREN)
    return self.ru_utime + self.ru_stime + children.ru_utime + children.ru_stime


async def save(path, data):
    await blob.put_blob(
        path, json.dumps(data, ensure_ascii=False).encode(),
        access="private", allow_overwrite=True,
        content_type="application/json", cache_control_max_age=0,
    )


async def upload(path: Path, target: str, media_type: str):
    """Upload por streaming: não carrega dezenas de MB de vídeos na RAM."""
    size = path.stat().st_size

    async def chunks():
        with path.open("rb") as file:
            while True:
                data = await asyncio.to_thread(file.read, 64 * 1024)
                if not data:
                    break
                yield data

    return await blob.put_blob(target, chunks(), access="private",
                               content_length=size, content_type=media_type,
                               allow_overwrite=False, cache_control_max_age=0)


async def callback(job_id: str):
    """Solicita encerramento do Sandbox sem expor token ao frontend."""
    url = os.environ.get("SHORTFORGE_PUBLIC_API_URL", "").rstrip("/")
    secret = os.environ.get("SHORTFORGE_WORKER_SECRET", "")
    if not url or not secret:
        return
    req = Request(url + "/api/internal/finished",
                  data=json.dumps({"id":job_id}).encode(),
                  headers={"Content-Type":"application/json",
                           "X-ShortForge-Worker-Secret":secret},
                  method="POST")
    try:
        await asyncio.to_thread(urlopen, req, None, 15)
    except Exception:
        # A próxima consulta e o timeout do Sandbox continuam como fallback.
        pass


async def main():
    raw = json.loads(os.environ["SHORTFORGE_JOB"])
    state_path = os.environ["SHORTFORGE_JOB_BLOB_PATH"]
    output = Path("/tmp/shortforge-job") / raw["id"]
    job = Job(
        id=raw["id"], url=raw["url"], count=5, length=45, resolution=720,
        facecam=raw["facecam"], model_name="base", destination=output,
        manual_box=raw.get("manual_box"), started_at=raw["started_at"],
    )
    state = dict(raw)
    started = time.monotonic()
    initial_cpu = cpu_time()

    try:
        state.update(status="running", stage="analyzing",
                     message="Preparação concluída; analisando vídeo no Sandbox.")
        await save(state_path,state)
        task = asyncio.create_task(asyncio.to_thread(execute, job))
        # Relatório a cada 7 segundos para reduzir operações no Blob.
        while not task.done():
            await asyncio.sleep(7)
            current=job.asdict()
            state.update({k:v for k,v in current.items()
                          if k in ("status","stage","message","progress","title",
                                   "selection_mode","clips","errors","zip_name")})
            # Nunca publica caminho local do worker para o navegador.
            state["zip_name"] = None
            await save(state_path,state)
        await task

        state.update({k:v for k,v in job.asdict().items()
                      if k in ("status","stage","message","progress","title",
                               "selection_mode","clips","errors")})
        state["zip_name"]=None

        if job.status in ("completed","partial"):
            # Cada artefato contém um identificador aleatório criptograficamente forte.
            for clip in state["clips"]:
                if clip.get("status") != "ready":
                    continue
                file=output/clip["name"]
                if not file.is_file() or file.stat().st_size <= 0:
                    clip.update(status="failed",error="MP4 não disponível no armazenamento.")
                    continue
                pathname = f"shortforge/jobs/{raw['started_at'][:7]}/{raw['id']}/output/{file.name}"
                await upload(file,pathname,"video/mp4")
                clip["blob_path"] = pathname
                clip.pop("download_url",None)

            zip_file=output/"shorts_prontos.zip"
            if zip_file.is_file() and zip_file.stat().st_size>0:
                pathname=f"shortforge/jobs/{raw['started_at'][:7]}/{raw['id']}/output/shorts_prontos.zip"
                await upload(zip_file,pathname,"application/zip")
                state["zip_name"]="shorts_prontos.zip"
                state["zip_path"]=pathname
            success=sum(bool(clip.get("blob_path")) for clip in state["clips"])
            state["status"]="completed" if success == 5 else ("partial" if success else "failed")
            state["progress"]=int(100*success/5)
            state["message"]=f"{success} de 5 Shorts armazenados e prontos para download."
        if job.status in ("failed","cancelled"):
            state["status"]=job.status
            state["message"]=job.message
    except Exception as exc:
        state.update(status="failed",stage="failed",progress=0,
                     message=f"Falha no worker: {type(exc).__name__}: {str(exc)[:280]}")
        state.setdefault("errors",[]).append(state["message"])
    finally:
        wall_seconds=time.monotonic()-started
        cpu_seconds=max(0,cpu_time()-initial_cpu)
        saved_bytes=sum((output/name).stat().st_size for name in
                        [c.get("name") for c in state.get("clips",[])
                         if c.get("blob_path")]+
                        ([state["zip_name"]] if state.get("zip_name") else [])
                        if name and (output/name).exists())
        from datetime import datetime, timezone
        state["finished_at"]=datetime.now(timezone.utc).isoformat()
        state["usage"]={
            "mode":"estimated_not_billing",
            "cpu_seconds":round(cpu_seconds,1),
            "wall_seconds":round(wall_seconds,1),
            "output_bytes":saved_bytes,
            "estimated_cpu_monthly_percent":round(cpu_seconds/(5*3600)*100,2),
            "note":"Estimativa do processo; confira Vercel Usage para valores oficiais."
        }
        # Mantém uma linha auditável mesmo se houve falha.
        try:
            await save(state_path,state)
        finally:
            shutil.rmtree(output,ignore_errors=True)
        await callback(raw["id"])


if __name__ == "__main__":
    asyncio.run(main())

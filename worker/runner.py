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

SOURCE = Path(__file__).resolve().parent
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
        def send():
            with urlopen(req, timeout=15) as response:
                response.read(1024)
        await asyncio.to_thread(send)
    except Exception:
        # A próxima consulta e o timeout do Sandbox continuam como fallback.
        pass


async def main():
    raw = json.loads(os.environ["SHORTFORGE_JOB"])
    state_path = os.environ["SHORTFORGE_JOB_BLOB_PATH"]
    output = Path("/tmp/shortforge-job") / raw["id"]
    source_path = os.getenv("SHORTFORGE_TEST_SOURCE_PATH")
    test_blob = os.getenv("SHORTFORGE_TEST_SOURCE_BLOB")
    job = Job(
        id=raw["id"], url=raw["url"], count=raw["count"], length=raw["length"], resolution=720,
        source_path=Path(source_path) if source_path else None,
        facecam=raw["facecam"], model_name="base", destination=output,
        manual_box=raw.get("manual_box"), started_at=raw["started_at"],
    )
    state = dict(raw)
    started = time.monotonic()
    initial_cpu = cpu_time()
    task = None

    try:
        # Synthetic source is an operator-only environment flag, never a client
        # JSON field. The SDK validates the private Blob host/store and does not
        # follow redirects. Keep the transferred file bounded.
        if test_blob:
            if not test_blob.startswith("shortforge/integration/") or not test_blob.endswith("/input.mp4"):
                raise ValueError("Fonte de teste inválida.")
            output.mkdir(parents=True, exist_ok=True)
            job.source_path = output / "synthetic-input.mp4"
            size = 0
            async with blob.stream_blob(test_blob, access="private") as stream:
                with job.source_path.open("wb") as target:
                    async for chunk in stream:
                        size += len(chunk)
                        if size > 16*1024*1024:
                            raise ValueError("Fonte de teste excede 16 MiB.")
                        target.write(chunk)
        # Only trusted bootstrap installs packages; never interpolate user input.
        if not all(shutil.which(tool) for tool in ("ffmpeg", "ffprobe", "tesseract")):
            import subprocess
            def install_system():
                for args in (["apt-get", "update", "-qq"],
                             ["apt-get", "install", "-y", "-qq", "--no-install-recommends",
                              "ffmpeg", "tesseract-ocr", "fonts-dejavu-core"]):
                    subprocess.run(["sudo", "-n", *args] if os.geteuid() else args,
                                   check=True, timeout=240, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
            await asyncio.to_thread(install_system)
        # Bound individual media/temp files; VM enforces the 4 GB memory cap.
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024**3, 1024**3))
        state.update(status="running", stage="analyzing",
                     message="Preparação concluída; verificando metadados do vídeo.")
        await save(state_path,state)
        task = asyncio.create_task(asyncio.to_thread(execute, job))
        # Relatório a cada 7 segundos para reduzir operações no Blob.
        while not task.done():
            await asyncio.wait({task}, timeout=7)
            current=job.asdict()
            state.update({k:v for k,v in current.items()
                          if k in ("status","stage","message","progress","title",
                                   "selection_mode","clips","errors","zip_name")})
            # Local completion precedes uploads; do not stop VM or expose local MP4s yet.
            state["status"] = "running"
            for clip in state.get("clips", []):
                clip.pop("download_url", None)
                if clip.get("status") == "ready":
                    clip["status"] = "uploading"
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
                pathname = state_path.removesuffix("state.json") + "output/" + file.name
                try:
                    await upload(file,pathname,"video/mp4")
                    clip["blob_path"] = pathname
                    clip.pop("download_url",None)
                except Exception:
                    clip.update(status="failed", error="Falha ao armazenar MP4 privado.")

            # ZIP contains only files whose private upload succeeded.
            import zipfile
            zip_file = output / "shorts_prontos.zip"
            ready = [c for c in state["clips"] if c.get("blob_path")]
            if ready:
                with zipfile.ZipFile(zip_file, 'w', compression=zipfile.ZIP_STORED) as pack:
                    for clip in ready:
                        pack.write(output / clip["name"], clip["name"])
                        subtitles = output / f"corte_{clip['number']:02d}" / "legendas.srt"
                        if subtitles.is_file():
                            pack.write(subtitles, f"legendas/short_{clip['number']:02d}.srt")
                    report = output / "relatorio.json"
                    if report.is_file():
                        pack.write(report, "relatorio.json")
                pathname=state_path.removesuffix("state.json") + "output/shorts_prontos.zip"
                try:
                    await upload(zip_file,pathname,"application/zip")
                    state["zip_name"]="shorts_prontos.zip"
                    state["zip_path"]=pathname
                except Exception:
                    state.setdefault("errors", []).append("Falha ao armazenar ZIP; baixe os MP4s individualmente.")
            success=sum(bool(clip.get("blob_path")) for clip in state["clips"])
            state["status"]="completed" if success == job.count else ("partial" if success else "failed")
            state["progress"]=int(100*success/job.count)
            state["message"]=f"{success} de {job.count} Shorts armazenados e prontos para download."
            state["stage"]=state["status"]
        if job.status in ("failed","cancelled"):
            state["status"]=job.status
            state["message"]=job.message
    except Exception as exc:
        if task and not task.done():
            job.cancel.set()
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=15)
            except Exception:
                pass  # VM deadline still bounds an unresponsive native operation.
        state.update(status="failed",stage="failed",progress=0,
                     message=f"Falha no worker ({type(exc).__name__}). Consulte o diagnóstico privado.")
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

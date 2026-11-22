"""Política de consumo do ShortForge Hobby — somente regras puras e testáveis.

O gateway NÃO deve iniciar Vercel Sandbox sem configuração explícita, limites,
chave de acesso, armazenamento e confirmação de disponibilidade da plataforma.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit
import math
import os
import re

CLIPS_PER_JOB = 5
CLIP_SECONDS = 45
OUTPUT_WIDTH = 720
SANDBOX_VCPUS = 2
SANDBOX_MEMORY_MB = 4096
SANDBOX_MAX_MINUTES = 42  # abaixo do máximo de 45 minutos do Hobby
OUTPUT_TTL_HOURS = 24
DEFAULT_MONTHLY_CAP = 3  # 3 x 42min x 2 vCPU = até 4,2h CPU (estimativa conservadora)
MONTHLY_CPU_SECONDS = 5 * 60 * 60
MONTHLY_MEMORY_GB_HOURS = 420
MONTHLY_SANDBOX_EGRESS_BYTES = 20 * 1000**3
MAX_SOURCE_HOURS = 6

YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
FACE_MODES = {"auto", "superior_esquerdo", "superior_direito",
              "inferior_esquerdo", "inferior_direito"}


class RequestRejected(ValueError):
    pass


def canonical_youtube(raw: str) -> str:
    if not isinstance(raw, str) or len(raw) > 2048:
        raise RequestRejected("Informe um link individual do YouTube.")
    p = urlsplit(raw.strip())
    if p.scheme != "https" or p.username or p.password or p.port not in (None, 443):
        raise RequestRejected("Use um endereço HTTPS do YouTube.")
    host = (p.hostname or "").lower()
    if host == "youtu.be":
        video_id = p.path.strip("/")
    elif host in ("youtube.com", "www.youtube.com", "m.youtube.com"):
        if p.path == "/watch":
            video_id = parse_qs(p.query).get("v", [""])[0]
        else:
            m = re.fullmatch(r"/(?:shorts|live)/([A-Za-z0-9_-]{11})/?", p.path)
            video_id = m.group(1) if m else ""
    else:
        raise RequestRejected("Somente vídeos individuais do YouTube são permitidos.")
    if not YOUTUBE_ID.fullmatch(video_id):
        raise RequestRejected("O link precisa identificar um vídeo individual.")
    return "https://youtu.be/" + video_id


def validate_job(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise RequestRejected("O pedido deve ser um objeto JSON.")
    source = canonical_youtube(payload.get("url", ""))
    # Limites rígidos para proteger o plano Hobby. Não aceitamos override do cliente.
    try:
        count = int(payload.get("count", CLIPS_PER_JOB))
        resolution = int(payload.get("resolution", OUTPUT_WIDTH))
        length = int(payload.get("length", CLIP_SECONDS))
    except (ValueError, TypeError):
        raise RequestRejected("Quantidade, resolução ou duração inválida.") from None
    if count != CLIPS_PER_JOB or resolution != OUTPUT_WIDTH or length != CLIP_SECONDS:
        raise RequestRejected("Nesta fase, apenas 5 Shorts de 45 segundos em 720p são permitidos.")
    facecam = payload.get("facecam", "auto")
    if facecam not in FACE_MODES:
        raise RequestRejected("Modo de facecam inválido.")
    manual_box = payload.get("manual_box")
    if manual_box not in (None, []):
        if not isinstance(manual_box, list) or len(manual_box) != 4:
            raise RequestRejected("Ajuste manual da facecam inválido.")
        if any(isinstance(x, bool) or not isinstance(x, (int, float))
               or not math.isfinite(x) for x in manual_box):
            raise RequestRejected("Coordenadas da facecam inválidas.")
        x, y, w, h = map(float, manual_box)
        if not (0 <= x < 100 and 0 <= y < 100 and w > 0 and h > 0
                and x + w <= 100 and y + h <= 100):
            raise RequestRejected("Facecam fora da tela.")
    return {
        "url": source, "count": CLIPS_PER_JOB, "length": CLIP_SECONDS,
        "resolution": OUTPUT_WIDTH, "facecam": facecam,
        "model_name": "base", "manual_box": manual_box or None,
    }


def monthly_cap() -> int:
    try:
        cap = int(os.getenv("SHORTFORGE_MAX_JOBS_MONTH", DEFAULT_MONTHLY_CAP))
    except ValueError:
        cap = DEFAULT_MONTHLY_CAP
    return min(3, max(1, cap))


def period_key(date: datetime | None = None) -> str:
    return (date or datetime.now(timezone.utc)).strftime("%Y-%m")


def expired(iso_date: str, now: datetime | None = None) -> bool:
    t = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError("Timestamp sem timezone")
    return (now or datetime.now(timezone.utc)) >= t + timedelta(hours=OUTPUT_TTL_HOURS)


def approximate_usage(cpu_seconds: float, wall_seconds: float,
                      storage_bytes: int, transfer_bytes: int) -> dict:
    """Estimativas locais, NÃO são métricas de faturamento da Vercel."""
    values = (cpu_seconds, wall_seconds, storage_bytes, transfer_bytes)
    if not all(isinstance(x, (int, float)) and math.isfinite(x) and x >= 0 for x in values):
        raise ValueError("Métricas inválidas")
    return {
        "mode": "estimated_not_billing",
        "cpu_seconds": round(cpu_seconds, 1),
        "cpu_monthly_percent": round(100 * cpu_seconds / MONTHLY_CPU_SECONDS, 2),
        "memory_gb_hours": round(wall_seconds * (SANDBOX_MEMORY_MB / 1024) / 3600, 3),
        "memory_monthly_percent": round(100 * wall_seconds *
                (SANDBOX_MEMORY_MB / 1024) / 3600 / MONTHLY_MEMORY_GB_HOURS, 2),
        "storage_bytes": int(storage_bytes),
        "storage_vs_1gb_percent": round(100 * storage_bytes / 1_000_000_000, 2),
        "transfer_bytes": int(transfer_bytes),
        "sandbox_transfer_monthly_percent": round(
            100 * transfer_bytes / MONTHLY_SANDBOX_EGRESS_BYTES, 2),
    }

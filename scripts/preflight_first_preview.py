#!/usr/bin/env python3
"""No-Sandbox, metadata-only preflight for the first authorized YouTube Preview.

Run manually on a trusted development machine. This makes no Vercel API call,
creates no Sandbox, and downloads no media. Do not use this result as proof
that the full rendering pipeline can access the video from Vercel.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
from api.policy import canonical_youtube, RequestRejected

AUTHORIZED_URL = "https://youtu.be/NZRCjPMb0AY"
MAX_SOURCE_SECONDS = 6 * 3600
# Limit *downloaded audio/selected section*, not the metadata size of a 6h source.


def validate_metadata(metadata: dict) -> dict:
    """Fail closed if the authorized source would exceed the bounded smoke."""
    if not isinstance(metadata, dict) or metadata.get("_type") in ("playlist", "multi_video"):
        raise ValueError("Metadados inválidos ou playlist.")
    original = metadata.get("webpage_url") or metadata.get("original_url")
    vid = metadata.get("id")
    if vid and vid != "NZRCjPMb0AY":
        raise ValueError("O YouTube retornou outro vídeo.")
    if original:
        try:
            if canonical_youtube(original) != AUTHORIZED_URL:
                raise ValueError("Metadados de outra origem.")
        except RequestRejected as exc:
            raise ValueError("Origem do vídeo inválida.") from exc
    if metadata.get("is_live") or metadata.get("live_status") in (
            "is_live", "is_upcoming", "post_live"):
        raise ValueError("Transmissões ao vivo não são permitidas neste teste.")
    duration = metadata.get("duration")
    if (isinstance(duration, bool) or not isinstance(duration, (int, float))
            or not math.isfinite(duration) or
            not 30 <= duration <= MAX_SOURCE_SECONDS):
        raise ValueError(
            "Vídeo fora da janela autorizada: aceitamos fontes entre "
            "30 segundos e 6 horas. Nenhum Sandbox deve ser criado.")
    # Do not reject long input because its original 1080p filesize is huge:
    # only a bounded bestaudio and the final selected 30-second section are
    # downloaded in the cloud. Their size and runtime have separate limits.
    return {"id": "NZRCjPMb0AY", "duration_seconds": round(duration, 2),
            "source_bounded": True, "media_downloaded": False,
            "sandbox_created": False}


def main() -> int:
    if len(sys.argv) != 1:
        print("Uso: python -m scripts.preflight_first_preview", file=sys.stderr)
        return 2
    command = [
        sys.executable, "-m", "yt_dlp", "--ignore-config", "--no-playlist",
        "--skip-download", "--dump-single-json", "--socket-timeout", "15",
        "--retries", "1", AUTHORIZED_URL,
    ]
    try:
        result = subprocess.run(
            command, text=True, capture_output=True, timeout=90, check=False)
        if result.returncode != 0:
            raise RuntimeError(
                "Falha ao consultar o YouTube (yt-dlp). "
                "Não iniciar Sandbox. Verifique conectividade e disponibilidade.")
        data = validate_metadata(json.loads(result.stdout))
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError,
            ValueError, RuntimeError) as error:
        print("PRÉ-VERIFICAÇÃO BLOQUEADA:", str(error), file=sys.stderr)
        return 1
    print(json.dumps(data, ensure_ascii=False, sort_keys=True))
    print("Metadados aptos ao limite de fonte; direitos autorizados pelo operador. "
          "Ainda é necessário conferir franquias, envs e deploy protegido.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

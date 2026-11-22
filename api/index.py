"""ShortClips lightweight Vercel API gateway.

Video processing must happen on an authenticated long-running worker.
No MP4 is processed or stored inside a Vercel serverless function.
"""
from http.server import BaseHTTPRequestHandler
import asyncio
import hmac
import json
import os
import re
from api import sandbox_engine
from api.policy import RequestRejected
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

MAX_BODY = 16 * 1024
MAX_RESPONSE = 512 * 1024
ROUTE = re.compile(r"/api/jobs(?:/latest|/[a-f0-9]{8,40}(?:/(?:cancel|retry))?)?$")


def config():
    origin = os.getenv("SHORTFORGE_FRONTEND_ORIGIN", "https://short-clips-tan.vercel.app").rstrip("/")
    worker = os.getenv("SHORTFORGE_WORKER_URL", "").rstrip("/")
    access_key = os.getenv("SHORTFORGE_PUBLIC_ACCESS_KEY", "")
    worker_secret = os.getenv("SHORTFORGE_WORKER_SECRET", "")
    parsed = urlsplit(worker)
    valid_url = (parsed.scheme == "https" and bool(parsed.netloc) and
                 not parsed.username and not parsed.password and
                 parsed.path in ("", "/") and not parsed.query and not parsed.fragment)
    mode = "sandbox" if sandbox_engine.enabled() else "gateway"
    ready = sandbox_engine.configured() if mode == "sandbox" else bool(origin and valid_url and access_key and worker_secret)
    return {
        "mode": mode,
        "origin": origin,
        "worker": worker if valid_url else "",
        "access_key": access_key,
        "worker_secret": worker_secret,
        "ready": ready,
    }


def requested_path(raw_path):
    """Resolve a rota original preservada pelo rewrite da Vercel.

    O deploy encaminha /api/<rota> a /api/index?sf_route=<rota>.
    Receber apenas /api/index faria /api/health passar pela autenticação
    em vez de retornar o diagnóstico público.
    """
    parsed = urlsplit(raw_path)
    if parsed.path != "/api/index":
        return parsed.path
    routes = parse_qs(parsed.query).get("sf_route", [])
    if len(routes) != 1:
        return parsed.path
    route = routes[0]
    if route in ("health","usage","cleanup","internal/finished") or ROUTE.fullmatch("/api/" + route):
        return "/api/" + route
    return parsed.path


class handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Avoid logging secrets or request bodies.
        pass

    def send_json(self, status, obj, extra=None):
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        origin = self.headers.get("Origin", "").rstrip("/")
        if origin and origin == config()["origin"]:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(raw)

    def check_auth(self, cfg):
        origin = self.headers.get("Origin", "").rstrip("/")
        if origin and origin != cfg["origin"]:
            self.send_json(403, {"error": "Origem não permitida."})
            return False
        if not cfg["ready"]:
            self.send_json(503, {"error": "Backend de processamento não configurado; geração de Shorts indisponível."})
            return False
        scheme, _, key = self.headers.get("Authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(key, cfg["access_key"]):
            self.send_json(401, {"error": "Chave de acesso inválida ou ausente."})
            return False
        return True

    def do_OPTIONS(self):
        origin = self.headers.get("Origin", "").rstrip("/")
        if not config()["origin"] or origin != config()["origin"]:
            return self.send_json(403, {"error": "Origem não permitida."})
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = requested_path(self.path)
        cfg = config()
        if path == "/api/health":
            return self.send_json(200, {
                "ok": True, "service": "BackendShortClips",
                "mode": cfg["mode"], "ready": cfg["ready"],
                "limits": {"clips":5,"seconds":45,"resolution":720,"concurrency":1},
                "reason": None if cfg["ready"] else
                    "Worker ainda não configurado; nenhuma tarefa é iniciada.",
            })
        if path == "/api/cleanup":
            expected = os.getenv("CRON_SECRET", "")
            auth = self.headers.get("Authorization", "")
            if not expected or not hmac.compare_digest(auth, "Bearer " + expected):
                return self.send_json(401, {"error":"Não autorizado."})
            if cfg["mode"] != "sandbox":
                return self.send_json(503, {"error":"Sandbox não habilitado."})
            try:
                return self.send_json(200, asyncio.run(sandbox_engine.cleanup()))
            except Exception:
                return self.send_json(502, {"error":"Falha na limpeza; tente novamente."})
        if not self.check_auth(cfg):
            return
        if cfg["mode"] == "sandbox":
            try:
                if path == "/api/usage":
                    return self.send_json(200, asyncio.run(sandbox_engine.usage()))
                if path == "/api/jobs/latest":
                    job = asyncio.run(sandbox_engine.latest_job())
                else:
                    match = re.fullmatch(r"/api/jobs/([a-f0-9]{32})",path)
                    if not match:
                        return self.send_json(404, {"error":"Rota desconhecida."})
                    job = asyncio.run(sandbox_engine.get_job(match.group(1)))
                if job is None:
                    return self.send_json(404, {"error":"Tarefa não encontrada."})
                # /latest tem envelope; /jobs/id devolve estado direto (contrato da UI local).
                return self.send_json(200, {"job":sandbox_engine.public_job(job)} if path == "/api/jobs/latest" else sandbox_engine.public_job(job))
            except Exception:
                return self.send_json(502, {"error":"Não foi possível acessar o estado dos vídeos."})
        if path.startswith("/downloads/"):
            return self.send_json(501, {"error": "Downloads exigem armazenamento externo com URLs assinadas."})
        if not ROUTE.fullmatch(path):
            return self.send_json(404, {"error": "Rota não encontrada."})
        return self.proxy("GET", cfg, path)

    def do_POST(self):
        cfg = config()
        path = requested_path(self.path)
        if path == "/api/internal/finished":
            secret = os.getenv("SHORTFORGE_WORKER_SECRET", "")
            given = self.headers.get("X-ShortForge-Worker-Secret", "")
            if not secret or not hmac.compare_digest(given, secret):
                return self.send_json(401, {"error":"Não autorizado."})
            try:
                size = int(self.headers.get("Content-Length","0"))
                if not 1 <= size <= 1024:
                    raise ValueError()
                job_id = json.loads(self.rfile.read(size)).get("id","")
                if not re.fullmatch(r"[a-f0-9]{32}",job_id):
                    raise ValueError()
                if cfg["mode"] != "sandbox":
                    return self.send_json(503, {"error":"Sandbox não habilitado."})
                result = asyncio.run(sandbox_engine.finalize(job_id))
                return self.send_json(200, result)
            except (ValueError,TypeError,AttributeError):
                return self.send_json(400, {"error":"Pedido inválido."})
            except Exception:
                return self.send_json(502, {"error":"Não foi possível finalizar o worker."})
        if not self.check_auth(cfg):
            return
        if path != "/api/jobs" and not re.fullmatch(r"/api/jobs/[a-f0-9]{8,40}/(?:cancel|retry)", path):
            return self.send_json(404, {"error": "Rota não encontrada."})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= MAX_BODY:
                raise ValueError("Tamanho do pedido inválido.")
            body = self.rfile.read(size)
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError("JSON precisa ser objeto.")
        except (ValueError, TypeError):
            return self.send_json(400, {"error": "JSON de entrada inválido."})
        if cfg["mode"] == "sandbox":
            if path == "/api/jobs":
                try:
                    job = asyncio.run(sandbox_engine.submit(payload))
                    return self.send_json(201, {"job":sandbox_engine.public_job(job)})
                except RequestRejected as exc:
                    message=str(exc)
                    status=429 if "mensal" in message else (409 if "andamento" in message or "ativo" in message else 400)
                    return self.send_json(status, {"error":message})
                except Exception:
                    return self.send_json(503, {"error":"Sandbox ou armazenamento indisponível. Nenhuma tarefa foi concluída."})
            match = re.fullmatch(r"/api/jobs/([a-f0-9]{32})/(cancel|retry)",path)
            if not match:
                return self.send_json(404, {"error":"Tarefa inválida."})
            if match.group(2) == "retry":
                return self.send_json(501, {"error":"Repetição isolada de cortes não está habilitada no worker cloud."})
            try:
                job = asyncio.run(sandbox_engine.cancel(match.group(1)))
                return self.send_json(200, {"job":sandbox_engine.public_job(job)}) if job else self.send_json(404, {"error":"Tarefa não encontrada."})
            except Exception:
                return self.send_json(502, {"error":"Falha ao cancelar a tarefa."})
        return self.proxy("POST", cfg, path, body)

    def proxy(self, method, cfg, path, body=None):
        headers = {
            "Accept": "application/json",
            "X-ShortForge-Worker-Secret": cfg["worker_secret"],
        }
        if method == "POST":
            headers["Content-Type"] = "application/json"
        request = Request(cfg["worker"] + path, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=25) as response:
                content = response.read(MAX_RESPONSE + 1)
                if len(content) > MAX_RESPONSE:
                    raise ValueError("Resposta muito grande.")
                return self.send_json(response.status, json.loads(content))
        except HTTPError as e:
            try:
                payload = json.loads(e.read(MAX_RESPONSE))
                if not isinstance(payload, dict):
                    payload = {"error": "Erro do worker."}
            except (ValueError, TypeError):
                payload = {"error": "Erro do worker."}
            return self.send_json(e.code, payload)
        except (URLError, TimeoutError, ValueError, OSError):
            return self.send_json(502, {"error": "O worker de vídeo não está respondendo."})

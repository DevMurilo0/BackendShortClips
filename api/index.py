"""ShortClips lightweight Vercel API gateway.

Video processing must happen on an authenticated long-running worker.
No MP4 is processed or stored inside a Vercel serverless function.
"""
from http.server import BaseHTTPRequestHandler
import hmac
import json
import os
import re
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
    return {
        "origin": origin,
        "worker": worker if valid_url else "",
        "access_key": access_key,
        "worker_secret": worker_secret,
        "ready": bool(origin and valid_url and access_key and worker_secret),
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
    if route == "health" or ROUTE.fullmatch("/api/" + route):
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
                "ok": True, "service": "BackendShortClips", "ready": cfg["ready"],
                "reason": None if cfg["ready"] else "Worker ainda não configurado.",
            })
        if not self.check_auth(cfg):
            return
        if path.startswith("/downloads/"):
            return self.send_json(501, {"error": "Downloads exigem armazenamento externo com URLs assinadas."})
        if not ROUTE.fullmatch(path):
            return self.send_json(404, {"error": "Rota não encontrada."})
        return self.proxy("GET", cfg, path)

    def do_POST(self):
        cfg = config()
        if not self.check_auth(cfg):
            return
        path = requested_path(self.path)
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

import importlib.util
import json
import os
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

p = Path(__file__).resolve().parents[1] / 'api' / 'index.py'
spec = importlib.util.spec_from_file_location('backendshortclips', p)
gateway = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)

ENV = {
    'SHORTFORGE_FRONTEND_ORIGIN': 'https://frontend.test',
    'SHORTFORGE_PUBLIC_ACCESS_KEY': 'client-secret',
    'SHORTFORGE_WORKER_SECRET': 'worker-secret',
    'SHORTFORGE_WORKER_URL': 'https://worker.test',
}

class Response:
    status = 201
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def read(self, *_): return b'{"job":{"id":"aabbccdd","status":"queued"}}'

class GatewayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), gateway.handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.root = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def query(self, path, method='GET', body=None, key=None, origin=None):
        headers = {}
        if key: headers['Authorization'] = 'Bearer ' + key
        if origin: headers['Origin'] = origin
        if body is not None: headers['Content-Type'] = 'application/json'
        req = Request(self.root+path, method=method, headers=headers,
                      data=json.dumps(body).encode() if body is not None else None)
        try:
            with urlopen(req, timeout=3) as r:
                payload = r.read()
                return r.status, json.loads(payload) if payload else None
        except HTTPError as e:
            return e.code, json.loads(e.read())

    def test_health_unconfigured(self):
        with patch.dict(os.environ, {}, clear=True):
            status, data = self.query('/api/health')
            self.assertEqual(status, 200)
            self.assertEqual(data['ready'], False)

    def test_no_fake_job_without_worker(self):
        with patch.dict(os.environ, {}, clear=True):
            status, data = self.query('/api/jobs', 'POST', {'url':'https://youtu.be/yWvnOWILFk0'})
            self.assertEqual(status, 503)
            self.assertIn('não configurado', data['error'])

    def test_auth_and_cors(self):
        with patch.dict(os.environ, ENV, clear=True):
            self.assertEqual(self.query('/api/jobs/latest')[0], 401)
            self.assertEqual(self.query('/api/jobs/latest', key='no')[0], 401)
            self.assertEqual(self.query('/api/jobs/latest', key='client-secret', origin='https://other.test')[0], 403)
            self.assertEqual(self.query('/api/jobs', 'OPTIONS', origin='https://frontend.test')[0], 204)

    def test_proxy(self):
        with patch.dict(os.environ, ENV, clear=True), patch.object(gateway, 'urlopen', return_value=Response()) as outgoing:
            status, data = self.query('/api/jobs','POST',{'url':'https://youtu.be/yWvnOWILFk0'},'client-secret','https://frontend.test')
            self.assertEqual(status, 201)
            self.assertEqual(data['job']['id'], 'aabbccdd')
            req = outgoing.call_args.args[0]
            self.assertEqual(req.headers['X-shortforge-worker-secret'],'worker-secret')

    def test_storage_not_misrepresented(self):
        with patch.dict(os.environ, ENV, clear=True):
            self.assertEqual(self.query('/downloads/aabbccdd/short_01.mp4',key='client-secret')[0], 501)

if __name__ == '__main__':
    unittest.main()

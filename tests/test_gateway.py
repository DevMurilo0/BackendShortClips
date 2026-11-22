import importlib.util
import json
import os
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch, AsyncMock
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
            try:
                return e.code, json.loads(e.read())
            finally:
                e.close()

    def test_health_unconfigured(self):
        with patch.dict(os.environ, {}, clear=True):
            status, data = self.query('/api/health')
            self.assertEqual(status, 200)
            self.assertEqual(data['ready'], False)

    def test_vercel_rewrite_health_is_public_and_reports_worker_missing(self):
        # A Vercel encaminha /api/health para /api/index?sf_route=health.
        with patch.dict(os.environ, {}, clear=True):
            status, data = self.query('/api/index?sf_route=health&utm_source=chatgpt')
            self.assertEqual(status, 200)
            self.assertTrue(data['ok'])
            self.assertEqual(data['service'], 'BackendShortClips')
            self.assertFalse(data['ready'])

    def test_vercel_rewrite_jobs_remain_unavailable_without_worker(self):
        with patch.dict(os.environ, {}, clear=True):
            status, data = self.query('/api/index?sf_route=jobs', 'POST',
                                      {'url':'https://youtu.be/yWvnOWILFk0'})
            self.assertEqual(status, 503)
            self.assertIn('não configurado', data['error'])

    def test_invalid_rewrite_cannot_bypass_access(self):
        with patch.dict(os.environ, ENV, clear=True):
            status, _ = self.query('/api/index?sf_route=malicious',key='client-secret')
            self.assertEqual(status, 404)

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

    def test_rewritten_post_reaches_original_worker_route(self):
        with patch.dict(os.environ, ENV, clear=True), patch.object(gateway, 'urlopen', return_value=Response()) as outgoing:
            status, data = self.query('/api/index?sf_route=jobs', 'POST',
                                      {'url':'https://youtu.be/yWvnOWILFk0'},
                                      'client-secret', 'https://frontend.test')
            self.assertEqual(status,201)
            self.assertEqual(data['job']['status'],'queued')
            self.assertEqual(outgoing.call_args.args[0].full_url, 'https://worker.test/api/jobs')

    def test_sandbox_status_auth_and_private_download_contract(self):
        env={**ENV,'SHORTFORGE_ENGINE':'sandbox','BLOB_READ_WRITE_TOKEN':'vercel_blob_rw_teststore_fake',
             'SHORTFORGE_PUBLIC_ACCESS_KEY':'x'*40,'SHORTFORGE_WORKER_SECRET':'y'*40}
        job={'id':'a'*32,'status':'completed','sandbox_name':'private-vm',
             'clips':[{'status':'ready','blob_path':'shortforge/jobs/2026-11/'+ 'a'*32+'/output/short_01.mp4'}]}
        with patch.dict(os.environ,env,clear=True),patch.object(gateway.sandbox_engine,'get_job',new_callable=AsyncMock,return_value=job):
            self.assertEqual(self.query('/api/jobs/'+ 'a'*32)[0],401)
            status,data=self.query('/api/index?sf_route=jobs%2F'+'a'*32,key='x'*40)
            self.assertEqual(status,200)
            self.assertNotIn('sandbox_name',data)
            self.assertNotIn('blob_path',data['clips'][0])
            self.assertTrue(data['clips'][0]['download_endpoint'].startswith('/api/download?'))

    def test_internal_callback_rejects_user_key_and_malformed_body(self):
        with patch.dict(os.environ,ENV,clear=True):
            self.assertEqual(self.query('/api/internal/finished','POST',{'id':'a'*32},'client-secret')[0],401)

    def test_preview_cron_cannot_clean_production_namespace(self):
        env={**ENV,'SHORTFORGE_ENGINE':'sandbox','VERCEL_ENV':'preview','CRON_SECRET':'cron-test'}
        with patch.dict(os.environ,env,clear=True),patch.object(gateway.sandbox_engine,'cleanup',new_callable=AsyncMock) as cleanup:
            status,_=self.query('/api/cleanup',key='cron-test')
            self.assertEqual(status,503)
            cleanup.assert_not_awaited()

    def test_disabled_preview_checks_auth_without_processing_or_proxy(self):
        env={**ENV,'SHORTFORGE_ENGINE':'disabled','VERCEL_ENV':'preview'}
        with patch.dict(os.environ,env,clear=True),patch.object(gateway,'urlopen') as outgoing:
            status,data=self.query('/api/health')
            self.assertEqual((status,data['mode'],data['ready']),(200,'disabled',False))
            self.assertEqual(self.query('/api/jobs/latest')[0],401)
            self.assertEqual(self.query('/api/jobs/latest',key='wrong')[0],401)
            self.assertEqual(self.query('/api/jobs/latest',key='client-secret')[0],503)
            self.assertEqual(self.query('/api/jobs','POST',{'url':'https://youtu.be/yWvnOWILFk0'},key='client-secret')[0],503)
            outgoing.assert_not_called()

    def test_unsupported_http_methods_return_json_405(self):
        with patch.dict(os.environ,ENV,clear=True):
            for method in ('PUT','DELETE','PATCH'):
                status,data=self.query('/api/health',method=method)
                self.assertEqual(status,405)
                self.assertIn('Método',data['error'])

    def test_storage_not_misrepresented(self):
        with patch.dict(os.environ, ENV, clear=True):
            self.assertEqual(self.query('/downloads/aabbccdd/short_01.mp4',key='client-secret')[0], 501)

if __name__ == '__main__':
    unittest.main()

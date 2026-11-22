"""Safe HTTP-only validation of one explicitly disabled Preview.

No deployment, Blob, worker or Sandbox SDK calls. Credentials read from ignored
local files; OIDC is sent only to the exact Preview origin, with no redirects.
"""
from datetime import datetime, timezone
import json
import argparse
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[1]
LOCAL=ROOT/'.vercel/preview-http'

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authfix", action="store_true")
    authfix=parser.parse_args().authfix
    local=ROOT/".vercel/preview-authfix" if authfix else LOCAL
    session=json.loads((local/("result.json" if authfix else "session.json")).read_text())
    if authfix:
        assert session["readyState"]=="READY" and session["exit"]==0
        session.update(preview_url="https://"+session["url"].removeprefix("https://"), deployment_id=session["id"])
    base=session['preview_url'].rstrip('/')
    parsed=urlsplit(base)
    if parsed.scheme!='https' or not parsed.hostname.endswith('.vercel.app') or parsed.path or parsed.username:
        raise RuntimeError('Unexpected deployment origin')
    token=dotenv_values(ROOT/'.env.local').get('VERCEL_OIDC_TOKEN')
    secret=(local/'access-key').read_text().strip()
    if not token or len(secret)<32: raise RuntimeError('Local test credentials unavailable')
    opener=build_opener(NoRedirect())
    checks=[]
    def request(name,path,expected,*,method='GET',auth=None,origin=None,body=None,extra=None,assertion=None):
        if not path.startswith('/') or path.startswith('//'):raise ValueError('Unsafe path')
        headers={'x-vercel-trusted-oidc-idp-token':token}
        if auth=='valid':headers['Authorization']='Bearer '+secret
        elif auth=='invalid':headers['Authorization']='Bearer incorrect-test-key'
        if origin:headers['Origin']=origin
        headers.update(extra or {})
        data=json.dumps(body).encode() if body is not None else None
        if data is not None:headers['Content-Type']='application/json'
        started=time.monotonic()
        req=Request(base+path,headers=headers,method=method,data=data)
        try:
            with opener.open(req,timeout=20) as response:
                code=response.status;raw=response.read(32768);response_headers=response.headers
        except HTTPError as error:
            code=error.code;raw=error.read(32768);response_headers=error.headers;error.close()
        if secret.encode() in raw or token.encode() in raw:
            raise RuntimeError('Credential echo detected; response withheld')
        try:payload=json.loads(raw)
        except (ValueError,UnicodeDecodeError):payload=None
        accepted=code==expected
        if assertion and accepted:accepted=bool(assertion(payload,response_headers,raw))
        result={'name':name,'method':method,'path':path,'expected':expected,'actual':code,
                'passed':accepted,'seconds':round(time.monotonic()-started,3)}
        checks.append(result)
        print(json.dumps(result,ensure_ascii=False),flush=True)
        return payload,response_headers,raw
    def cors_allowed(_p,h,_raw):return h.get('Access-Control-Allow-Origin')=='https://short-clips-tan.vercel.app'
    origin='https://short-clips-tan.vercel.app'
    state,_,_=request('health_disabled','/api/health',200,assertion=lambda p,h,r:
        p and p.get('ok') is True and p.get('ready') is False and p.get('mode')=='disabled' and h.get('Cache-Control')=='no-store')
    if not checks[-1]['passed']:
        raise RuntimeError('Disabled engine guard failed; no further checks executed')
    request('rewritten_health','/api/index?sf_route=health',200,assertion=lambda p,h,r:p and p.get('ready') is False)
    request('health_cors_allowed','/api/health',200,origin=origin,assertion=cors_allowed)
    request('public_health_no_cors_for_other_origin','/api/health',200,origin='https://blocked.invalid',assertion=lambda p,h,r:h.get('Access-Control-Allow-Origin') is None)
    request('jobs_missing_key','/api/jobs/latest',401)
    request('jobs_wrong_key','/api/jobs/latest',401,auth='invalid')
    request('jobs_valid_key_disabled','/api/jobs/latest',503,auth='valid',origin=origin,assertion=cors_allowed)
    request('status_disabled','/api/jobs/'+'a'*32,503,auth='valid')
    request('usage_disabled','/api/usage',503,auth='valid')
    request('create_missing_key','/api/jobs',401,method='POST',body={})
    request('create_valid_key_blocked','/api/jobs',503,method='POST',auth='valid',body={})
    for action in ('cancel','retry'):
        request(action+'_disabled','/api/jobs/'+'a'*32+'/'+action,503,method='POST',auth='valid',body={})
    path='/api/download?'+urlencode({'pathname':session['namespace']+'/jobs/2026-11/'+'a'*32+'/output/short_01.mp4'})
    request('download_missing_key',path,401)
    request('download_wrong_key',path,401,auth='invalid')
    request('download_valid_key_blocked',path,503,auth='valid')
    request('download_wrong_origin',path,403,auth='valid',origin='https://blocked.invalid')
    request('jobs_wrong_origin','/api/jobs/latest',403,auth='valid',origin='https://blocked.invalid')
    request('jobs_cors_preflight','/api/jobs',204,method='OPTIONS',origin=origin,assertion=cors_allowed)
    request('download_cors_preflight','/api/download',204,method='OPTIONS',origin=origin,assertion=lambda p,h,r:cors_allowed(p,h,r) and 'Authorization' in h.get('Access-Control-Allow-Headers',''))
    request('cors_preflight_wrong_origin','/api/jobs',403,method='OPTIONS',origin='https://blocked.invalid')
    request('cleanup_missing_cron_auth','/api/cleanup',401)
    request('user_key_cannot_cleanup','/api/cleanup',401,auth='valid')
    request('callback_missing_worker_auth','/api/internal/finished',401,method='POST',body={'id':'a'*32})
    if authfix:
        request('non_ascii_user', '/api/jobs/latest', 401,
                extra={'Authorization': 'Bearer é'},
                assertion=lambda p,h,r: p and 'inválida' in p.get('error',''))
        request('non_ascii_cron', '/api/cleanup', 401,
                extra={'Authorization': 'Bearer é'})
        request('non_ascii_worker', '/api/internal/finished', 401, method='POST',
                body={'id':'a'*32}, extra={'X-ShortForge-Worker-Secret':'é'})
    for method in ('PUT','PATCH','DELETE'):
        request('method_'+method,'/api/health',405,method=method,assertion=lambda p,h,r:p and h.get('Allow')=='GET, POST, OPTIONS')
    request('head_no_response_body','/api/health',405,method='HEAD',assertion=lambda p,h,r:not r)
    for path in ('/.env.local','/.vercel/project.json','/api/no-such-route','/api/sandbox_engine.py'):
        request('not_exposed_'+path,path,404)
    report={'url':base,'deployment_id':session.get('deployment_id'),'checked_at':datetime.now(timezone.utc).isoformat(),
            'engine':'disabled','ready':False,'requests':len(checks),'passed':sum(c['passed'] for c in checks),
            'failed':sum(not c['passed'] for c in checks),'checks':checks,
            'new_sandboxes':0,'blob_api_operations':0,'credential_values_logged':False,
            'protection_access':'existing Development OIDC, exact origin only, no protection changes'}
    (ROOT/'docs'/('preview-authfix-results.json' if authfix else 'preview-http-results.json')).write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    return report

if __name__=='__main__':
    result=main()
    print(json.dumps({key:result[key] for key in ('url','requests','passed','failed')}))
    if result['failed']:raise SystemExit(1)

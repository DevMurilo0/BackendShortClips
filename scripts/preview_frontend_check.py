"""Browser check using the published frontend and the real disabled Preview.

No generated job, mocked job or video. Trusted OIDC is injected only by the test
controller and only into requests to this exact Preview origin.
"""
from pathlib import Path
import json
import sys
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.path.append('/tmp/shortforge-sdk-check/lib/python3.14/site-packages')
from dotenv import dotenv_values
from playwright.sync_api import sync_playwright


def main():
    state=json.loads((ROOT/'.vercel/preview-http/session.json').read_text())
    preview=state['preview_url'].rstrip('/')
    assert urlsplit(preview).hostname.endswith('.vercel.app')
    token=dotenv_values(ROOT/'.env.local')['VERCEL_OIDC_TOKEN']
    key=(ROOT/'.vercel/preview-http/access-key').read_text().strip()
    requests=[];responses=[];errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path='/home/murilo/.cache/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell')
        page=browser.new_page(viewport={'width':1280,'height':900})
        def intercept(route):
            request=route.request
            assert request.url.startswith(preview+'/')
            requests.append({'method':request.method,'path':urlsplit(request.url).path,'origin':request.headers.get('origin')})
            route.continue_(headers={**request.headers,'x-vercel-trusted-oidc-idp-token':token})
        page.route(preview+'/**',intercept)
        page.on('response',lambda response:responses.append({'path':urlsplit(response.url).path,'status':response.status}) if response.url.startswith(preview+'/') else None)
        page.on('pageerror',lambda error:errors.append(type(error).__name__))
        page.goto('https://short-clips-tan.vercel.app',wait_until='domcontentloaded',timeout=30000)
        page.locator('#backendURL').fill(preview)
        page.locator('#backendAccessKey').fill(key)
        page.locator('#saveBackend').click()
        page.wait_for_function("document.getElementById('backendStatus').textContent.includes('não está configurado') || document.getElementById('backendStatus').textContent.includes('Conexão não estabelecida')",timeout=20000)
        notice=page.locator('#backendStatus').inner_text()
        if key in notice or token in notice:raise RuntimeError('Credential echo detected')
        passed=any(item['status']==200 for item in responses) and 'worker' in notice.lower() and page.locator('#submit').is_disabled()
        report={'frontend':'https://short-clips-tan.vercel.app','preview':preview,
                'mode':'real_frontend_to_real_disabled_preview','passed':passed,
                'notice':notice,'submit_disabled':page.locator('#submit').is_disabled(),
                'requests':requests,'responses':responses,'page_error_types':errors,
                'no_job_post':not any(item['method']=='POST' for item in requests),
                'credentials_logged':False,'protection_settings_changed':False,
                'limitations':['Backend deliberately unavailable; connection refused by UI before authenticated processing.','No active-generation or download user flow tested.','OIDC controller header required because Preview is protected.']}
        browser.close()
    (ROOT/'docs/preview-frontend-results.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps(report,ensure_ascii=False))
    if not passed or not report['no_job_post'] or errors:raise SystemExit(1)

if __name__=='__main__':
    try:main()
    except Exception as error:
        print(json.dumps({'passed':False,'error_type':type(error).__name__,'detail':'Browser check failed; private arguments withheld.'}))
        raise SystemExit(1)

"""Browser checks against live local services, without launching video jobs."""
from pathlib import Path
from urllib.parse import urlsplit
import json
import os
from playwright.sync_api import sync_playwright

url=os.getenv('SHORTFORGE_LOCAL_FRONTEND','http://localhost:5173')
report={'url':url,'viewports':[],'page_errors':[],'api_requests':[]}
with sync_playwright() as p:
    candidates=sorted((Path.home()/'.cache/ms-playwright').glob('chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell'))
    browser=p.chromium.launch(headless=True,**({'executable_path':str(candidates[-1])} if candidates else {}))
    for width in (390,1280):
        page=browser.new_page(viewport={'width':width,'height':900})
        # Stale cloud configuration must not redirect localhost processing.
        page.add_init_script("localStorage.setItem('shortforge_api_url','https://untrusted.invalid')")
        page.on('pageerror',lambda error:report['page_errors'].append(str(error)))
        page.on('request',lambda req:report['api_requests'].append({'method':req.method,'path':urlsplit(req.url).path,'origin':urlsplit(req.url).netloc}) if '/api/' in req.url else None)
        page.goto(url,wait_until='networkidle')
        assert page.locator('#url').input_value()==''
        assert page.locator('#count').input_value()=='1'
        assert page.locator('#length').input_value()=='30'
        assert not page.locator('#backendPanel').is_visible()
        assert page.locator('#rightsConfirmed').get_attribute('required') is not None
        page.locator('#url').fill('https://127.0.0.1/unauthorized')
        page.locator('#rightsConfirmed').check()
        page.locator('#submit').click()
        page.wait_for_function("document.getElementById('jobErrors').textContent.length > 0")
        notice=page.locator('#jobErrors').inner_text()
        assert 'YouTube' in notice
        assert page.locator('#submit').is_enabled()
        assert page.locator('#statusTag').inner_text()=='NÃO INICIADO'
        health=page.evaluate("fetch('/api/health').then(async r=>({status:r.status,body:await r.json()}))")
        assert health['status']==200 and health['body']['ok']
        overflow=page.evaluate('document.documentElement.scrollWidth > innerWidth')
        assert not overflow
        report['viewports'].append({'width':width,'overflow':overflow,'error_notice':notice,'submit_reenabled':True,'health':health})
        page.screenshot(path=f'/tmp/shortforge-local-{width}.png',full_page=True)
        page.close()
    browser.close()
assert not report['page_errors']
assert all(item['origin']==urlsplit(url).netloc for item in report['api_requests'])
print(json.dumps(report,ensure_ascii=False,indent=2))

"""Read-only/invalid-input local smoke; never launches media processing."""
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import json
import os

front=os.getenv('SHORTFORGE_LOCAL_FRONTEND','http://localhost:5173')
back=os.getenv('SHORTFORGE_LOCAL_BACKEND','http://localhost:8000')

def request(base,path,method='GET',data=None,headers=None):
    request=Request(base+path,method=method,data=json.dumps(data).encode() if data is not None else None,
                    headers={'Content-Type':'application/json',**(headers or {})})
    try:r=urlopen(request,timeout=10)
    except HTTPError as e:r=e
    body=r.read()
    return r.status,r.headers,body

checks=[]
for label,base,path,method,data,headers,want in [
 ('frontend',front,'/','GET',None,{},200),
 ('backend-health',back,'/api/health','GET',None,{},200),
 ('proxy-latest',front,'/api/jobs/latest','GET',None,{},200),
 ('direct-auth',back,'/api/jobs/latest','GET',None,{},401),
 ('direct-download-auth',back,'/downloads/missing/short_01.mp4','GET',None,{},401),
 ('unknown-job',front,'/api/jobs/abcdef123456','GET',None,{},404),
 ('missing-download',front,'/downloads/abcdef123456/short_01.mp4','GET',None,{},404),
 ('bad-source',front,'/api/jobs','POST',{'url':'https://127.0.0.1/','rights_confirmed':True},{'Origin':front},400),
 ('missing-rights',front,'/api/jobs','POST',{'url':'https://youtu.be/abcdefghijk','count':1,'length':30},{'Origin':front},400),
 ('foreign-origin',front,'/api/jobs','POST',{}, {'Origin':'https://untrusted.invalid'},403),
 ('cors-allowed',back,'/api/jobs','OPTIONS',None, {'Origin':front,'Access-Control-Request-Method':'POST'},204),
 ('cors-denied',back,'/api/jobs','OPTIONS',None, {'Origin':'https://untrusted.invalid'},403),
]:
 status,returned,body=request(base,path,method,data,headers)
 passed=status==want
 if label=='cors-allowed':passed=passed and returned.get('Access-Control-Allow-Origin')==front
 checks.append({'check':label,'status':status,'expected':want,'passed':passed})
print(json.dumps(checks,ensure_ascii=False,indent=2))
raise SystemExit(0 if all(c['passed'] for c in checks) else 1)

#!/usr/bin/env python3
"""Black-box verification against either isolated runtime; never targets production."""
import argparse,httpx,json,pathlib,time,asyncio
p=argparse.ArgumentParser();p.add_argument('--url',required=True);p.add_argument('--implementation',required=True);p.add_argument('--output',type=pathlib.Path,required=True);a=p.parse_args()
if not a.url.startswith('http://127.0.0.1:18'):raise SystemExit('Require isolated loopback test port')
results=[]
c=httpx.Client(base_url=a.url,timeout=10)
def check(name,method,path,status,body=None,headers=None,test=None):
 r=c.request(method,path,json=body,headers=headers or {});ok=r.status_code==status and (test(r) if test else True);results.append({'case':name,'method':method,'path':path,'expected_status':status,'actual_status':r.status_code,'passed':bool(ok)});print('PASS' if ok else 'FAIL',name,r.status_code, r.text[:140] if not ok else '');return r
origin={'Origin':'https://reports.asodya.com'}
check('CORS preflight','OPTIONS','/apps/reports/v1/catalog',200,headers={**origin,'Access-Control-Request-Method':'GET'},test=lambda r:r.headers.get('access-control-allow-origin')==origin['Origin'])
check('public proxy','GET','/apps/reports/v1/catalog',200,test=lambda r:r.json()['path']=='/catalog')
check('percent encoded path','GET','/apps/domain/v1/projects/a%2Fb?q=a%2Fb',200,test=lambda r:r.json()['path']=='/projects/a%2Fb' and r.json()['query']=='q=a%2Fb')
check('anonymous protected','GET','/apps/cortex/v1/private',403)
check('anonymous admin logs','GET','/apps/cortex/v1/logs/stream',403)
check('force auth files','GET','/apps/domain/v1/projects/a/files',403)
check('admin key proxy','POST','/apps/domain/v1/projects',200,{}, {'Authorization':'fixture-admin'})
check('invalid exchange origin','POST','/apps/api/v1/exchange',400,{'token':'invalid'},{'Origin':'https://invalid.test'})
check('missing login email','PATCH','/user/sync/v1/log-in',400,{})
r=check('password login','PATCH','/user/sync/v1/log-in',200,{'email':'fixture@example.test','password':'fixture','app':'reports'})
token=r.json().get('data');
if isinstance(token,str):
 r=check('exchange','POST','/apps/api/v1/exchange',200,{'auth_exchange_token':token,'app':'reports'},origin,test=lambda r:len(r.headers.get_list('set-cookie'))==2)
 check('artifact one use','POST','/apps/api/v1/exchange',400,{'token':token},origin)
 csrf=c.cookies.get('csrf');mutable={'X-CSRF-Token':csrf or ''}
 check('user info','GET','/user/info/v1/',200,test=lambda r:'password' not in (r.json().get('data') or {}))
 check('session proxy identity','GET','/apps/cortex/v1/private',200,test=lambda r:r.json()['headers'].get('x-uuid') is not None)
 check('regular user admin denial','GET','/apps/cortex/v1/logs/stream',403)
 check('CSRF missing','PATCH','/user/info/v1/',403,{'first_name':'X'})
 check('profile update','PATCH','/user/info/v1/',200,{'first_name':'Fixture','last_name':'Test','phone_number':None},mutable)
 r=check('create ticket','POST','/apps/support/v1/tickets',201,{'source_app':'reports','subject':'Fixture','body':'Fixture message'},mutable)
 ticket=(r.json().get('data') or {}).get('id')
 check('list tickets','GET','/apps/support/v1/tickets',200,test=lambda r:isinstance(r.json().get('data'),list))
 check('invalid ticket filter','GET','/apps/support/v1/tickets?status=invalid',400)
 if ticket:
  check('get ticket','GET',f'/apps/support/v1/tickets/{ticket}',200,test=lambda r:len(r.json()['data']['messages'])==1)
  r=check('reply ticket','POST',f'/apps/support/v1/tickets/{ticket}/messages',201,{'body':'Reply'},mutable)
  mid=(r.json().get('data') or {}).get('id')
  if mid:check('mark message read','PATCH',f'/apps/support/v1/tickets/{ticket}/messages/{mid}/read',200,headers=mutable)
  check('mark ticket read','PATCH',f'/apps/support/v1/tickets/{ticket}/read',200,headers=mutable)
 check('missing ticket','GET','/apps/support/v1/tickets/missing',404)
 check('telemetry','POST','/apps/api/v1/client-error',202,{'app_name':'reports','environment':'test','error_title':'Fixture','error_message':'Testing'},origin)
 check('telemetry untrusted origin','POST','/apps/api/v1/client-error',403,{'app_name':'reports','environment':'test','error_title':'Fixture','error_message':'Testing'},{'Origin':'https://invalid.test'})
 check('telemetry admin read','GET','/apps/api/v1/client-error',200,headers={'Authorization':'fixture-admin'})
 check('logout','POST','/user/sync/v1/log-out',200,{},mutable)
 c.cookies.clear();check('revoked session','GET','/apps/cortex/v1/private',403)
check('OAuth unsupported provider','POST','/user/sync/v1/oauth/start',400,{'provider':'invalid','app':'reports'})
r=check('OAuth start','POST','/user/sync/v1/oauth/start',200,{'provider':'google','app':'reports'})
if r.status_code==200:
 import urllib.parse
 state=urllib.parse.parse_qs(urllib.parse.urlparse(r.json()['data']['authorization_url']).query)['state'][0]
 check('OAuth callback','POST','/user/sync/v1/oauth/callback',200,{'code':'fixture','state':state})
 check('OAuth replay','POST','/user/sync/v1/oauth/callback',400,{'code':'fixture','state':state})
check('password recovery','POST','/user/sync/v1/password-recovery',200,{'email':'fixture@example.test'})
check('confirmation resend','POST','/user/sync/v1/email-confirmation-resend',200,{'email':'fixture@example.test'})
check('reset password','POST','/user/sync/v1/reset-password',200,{'access_token':'fixture','new_password':'fixture'})
check('waitlist','POST','/apps/certifications/v1/waitlist',200,{'email':'existing@example.test','plan':'free'},test=lambda r:r.json()['headers'].get('x-certifications-waitlist-registered')=='true')
check('waitlist invalid plan','POST','/apps/certifications/v1/waitlist',422,{'email':'a@b.test','plan':'paid'})
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps({'implementation':a.implementation,'results':results,'passed':sum(x['passed'] for x in results),'total':len(results)},indent=2))
raise SystemExit(0 if all(x['passed'] for x in results) else 1)

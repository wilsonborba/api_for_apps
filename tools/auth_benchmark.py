#!/usr/bin/env python3
"""Controlled auth action timings. Provider calls use local doubles; SQL uses a clone.
Setup requests are measured separately. No production accounts are created.
"""
import argparse,asyncio,csv,json,pathlib,time,uuid,statistics,httpx
p=argparse.ArgumentParser();p.add_argument('--url',required=True);p.add_argument('--implementation',required=True);p.add_argument('--output',type=pathlib.Path,required=True);p.add_argument('--requests',type=int,default=10);p.add_argument('--runs',type=int,default=3);a=p.parse_args()
if not a.url.startswith('http://127.0.0.1:18'):raise SystemExit('Isolated loopback API required')
rows=[];origin={'Origin':'https://reports.asodya.com'}
def headers():
 n=uuid.uuid4().hex;return {'X-Forwarded-For':'2001:db8:'+':'.join(n[i:i+4] for i in range(0,24,4))}
async def main():
 async with httpx.AsyncClient(base_url=a.url,timeout=20,limits=httpx.Limits(max_connections=16)) as c:
  # Create the fixture identity once, so concurrent trials do not measure a new-user race.
  r=await c.patch('/user/sync/v1/log-in',json={'access_token':'fixture-access','app':'reports'},headers=headers());assert r.status_code==200
  for run in range(a.runs):
   for concurrency in [1,4]:
    for scenario in ['password_login','signup_confirmation','oauth_start','oauth_callback','exchange','profile_update']:
     sem=asyncio.Semaphore(concurrency)
     async def one(index):
      async with sem:
       h=headers();setup=time.perf_counter_ns();token=None;state=None;session=None
       if scenario=='oauth_callback':
        r=await c.post('/user/sync/v1/oauth/start',json={'provider':'google','app':'reports'},headers=h)
        from urllib.parse import urlparse,parse_qs
        state=parse_qs(urlparse(r.json()['data']['authorization_url']).query)['state'][0]
       if scenario in ('exchange','profile_update'):
        r=await c.patch('/user/sync/v1/log-in',json={'access_token':'fixture-access','app':'reports'},headers=h);token=r.json()['data']
       if scenario=='profile_update':
        r=await c.post('/apps/api/v1/exchange',json={'token':token},headers={**h,**origin});session=dict(r.cookies.items())
       setup_ns=time.perf_counter_ns()-setup;start=time.perf_counter_ns();error='';status=0;size=0
       try:
        nonce=uuid.uuid4().hex
        if scenario=='password_login':r=await c.patch('/user/sync/v1/log-in',json={'email':nonce+'@example.test','password':'fixture','app':'reports'},headers=h)
        elif scenario=='signup_confirmation':r=await c.post('/user/sync/v1/sign-up',json={'email':'confirm-required@'+nonce+'.example.test','password':'fixture','app':'reports'},headers=h)
        elif scenario=='oauth_start':r=await c.post('/user/sync/v1/oauth/start',json={'provider':'google','app':'reports'},headers=h)
        elif scenario=='oauth_callback':r=await c.post('/user/sync/v1/oauth/callback',json={'code':'fixture','state':state},headers=h)
        elif scenario=='exchange':r=await c.post('/apps/api/v1/exchange',json={'auth_exchange_token':token},headers={**h,**origin})
        else:r=await c.patch('/user/info/v1/',json={'first_name':'Fixture','last_name':'Benchmark','phone_number':None},headers={**h,'Cookie':'sid='+session['sid']+'; csrf='+session['csrf'],'X-CSRF-Token':session['csrf']})
        status=r.status_code;size=len(r.content)
       except Exception as exc:error=type(exc).__name__
       rows.append({'implementation':a.implementation,'run':run,'scenario':scenario,'concurrency':concurrency,'request':index,'setup_duration_ns':setup_ns,'action_duration_ns':time.perf_counter_ns()-start,'status':status,'response_bytes':size,'error':error,'expected_status':201 if scenario=='signup_confirmation' else 200})
     await asyncio.gather(*(one(i) for i in range(a.requests)))
asyncio.run(main());a.output.mkdir(parents=True,exist_ok=True)
with (a.output/'requests.csv').open('w') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
failed=[r for r in rows if r['status']!=r['expected_status']]
(a.output/'metadata.json').write_text(json.dumps({'implementation':a.implementation,'runs':a.runs,'requests_per_case':a.requests,'requests':len(rows),'unexpected':len(failed),'provider':'local double; nested-session callback shape preserves existing contract','database':'separate clone of the same real-data SQLite snapshot','setup':'Prerequisites excluded from action timing and recorded separately','limits':['No real provider account writes','OAuth REST root-token mismatch remains known bug #49','Security backoff remains enabled','SQLite does not prove PostgreSQL concurrency behavior']},indent=2));print(len(rows),'auth actions;',len(failed),'unexpected responses')
raise SystemExit(1 if failed else 0)

#!/usr/bin/env python3
"""Compare gateway authorization for all downstream HTTP contracts and three roles."""
import argparse,json,pathlib,re,httpx,fnmatch
p=argparse.ArgumentParser();p.add_argument('--python-url',default='http://127.0.0.1:18108');p.add_argument('--rust-url',default='http://127.0.0.1:18109');p.add_argument('--output',type=pathlib.Path,required=True);a=p.parse_args()
if not all(u.startswith('http://127.0.0.1:18') for u in [a.python_url,a.rust_url]):raise SystemExit('Isolated targets required')
spec=json.loads(pathlib.Path('src/presentation/assets/openapi.json').read_text());settings=json.loads(pathlib.Path('src/core/defaults.json').read_text());rows=[]
def matches(table,app,m,path):return any(fnmatch.fnmatchcase(path,p) for p in settings.get(table,{}).get(app,{}).get(m.upper(),[]))
with httpx.Client(base_url=a.python_url,timeout=10) as py,httpx.Client(base_url=a.rust_url,timeout=10) as rust:
 for path,methods in spec['paths'].items():
  for method,op in methods.items():
   if op.get('tags')==['gateway'] or op.get('x-websocket'):continue
   concrete=re.sub(r'\{[^}]+\}','fixture',path);app=concrete.split('/')[2];suffix=concrete.split('/v1',1)[1]
   admin=fnmatch.fnmatchcase(suffix,'/logs*') or fnmatch.fnmatchcase(suffix,'*/logs*') or matches('ADMIN_PROTECTED_PROXY_ROUTES',app,method,suffix)
   protected=admin or matches('FORCE_AUTH_PROXY_ROUTES',app,method,suffix) or not matches('PUBLIC_PROXY_ROUTES',app,method,suffix)
   for role in ['guest','viewer','admin']:
    headers={'X-UUID':'forged-client-identity'}
    if role!='guest':headers.update({'Cookie':f'sid=fixture-{role}-session; csrf=fixture-csrf','X-CSRF-Token':'fixture-csrf'})
    expected=403 if protected and (role=='guest' or admin and role!='admin') else 200
    statuses=[];ok=True
    for client in [py,rust]:
     r=client.request(method,concrete,headers=headers,content=b'{"fixture":true}');statuses.append(r.status_code);ok=ok and r.status_code==expected
     if r.status_code==200 and method!='head':
      forwarded=r.json().get('headers',{}).get('x-uuid');ok=ok and (forwarded=='fixture-viewer' if protected else forwarded is None)
    rows.append({'path':path,'method':method,'role':role,'expected':expected,'python':statuses[0],'rust':statuses[1],'passed':ok})
a.output.write_text(json.dumps({'scope':'Gateway authorization and identity forwarding against controlled upstreams','results':rows,'passed':sum(x['passed'] for x in rows),'total':len(rows)},indent=2));print(sum(x['passed'] for x in rows),'/',len(rows),'matched authorization cases')
raise SystemExit(0 if all(x['passed'] for x in rows) else 1)

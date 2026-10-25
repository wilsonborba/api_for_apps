#!/usr/bin/env python3
"""Exercise every central downstream registration against isolated upstream doubles.
This proves gateway method/path forwarding, not each backend's business logic.
"""
import argparse,json,pathlib,re,httpx
p=argparse.ArgumentParser();p.add_argument('--url',required=True);p.add_argument('--output',type=pathlib.Path,required=True);a=p.parse_args()
if not a.url.startswith('http://127.0.0.1:18'):raise SystemExit('Require isolated target')
s=json.loads(pathlib.Path('src/presentation/assets/openapi.json').read_text());results=[]
with httpx.Client(base_url=a.url,timeout=10,headers={'Cookie':'sid=fixture-admin-session; csrf=fixture-csrf','X-CSRF-Token':'fixture-csrf'}) as c:
 for path,methods in s['paths'].items():
  for method,op in methods.items():
   if op.get('tags')==['gateway'] or op.get('x-websocket'):continue
   concrete=re.sub(r'\{[^}]+\}','fixture',path)
   try:
    r=c.request(method,concrete,content=b'{"fixture":true}');ok=r.status_code==200
    if method=='head':ok=ok and not r.content
    else:
     v=r.json();suffix=concrete.split('/v1',1)[1];ok=ok and v['path']==suffix and v['method']==method.upper()
    results.append({'path':path,'method':method,'status':r.status_code,'passed':ok})
   except Exception as e:results.append({'path':path,'method':method,'passed':False,'error':type(e).__name__})
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps({'scope':'Gateway forwarding only; backend business validation uses separate contracts','results':results,'passed':sum(x['passed'] for x in results),'total':len(results)},indent=2));print(sum(x['passed'] for x in results),'/',len(results))
raise SystemExit(0 if all(x['passed'] for x in results) else 1)

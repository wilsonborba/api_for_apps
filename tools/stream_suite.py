#!/usr/bin/env python3
"""Verify admin WebSockets/SSE, attachment bounds, and client disconnects locally."""
import asyncio,httpx,json,pathlib,argparse,inspect
import websockets
p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:18105');p.add_argument('--output',type=pathlib.Path,required=True);a=p.parse_args()
if not a.url.startswith('http://127.0.0.1:18'):raise SystemExit('Require isolated fixture')
results=[]
def record(name,ok):results.append({'case':name,'passed':bool(ok)});print('PASS' if ok else 'FAIL',name)
async def main():
 ws=a.url.replace('http:','ws:')+'/apps/cortex/v1/logs/stream'
 kw='additional_headers' if 'additional_headers' in inspect.signature(websockets.connect).parameters else 'extra_headers'
 for label,headers in [('guest',{}),('viewer',{'Cookie':'sid=fixture-viewer-session'})]:
  try:
   async with websockets.connect(ws,**{kw:headers}):record(label+' WebSocket denied',False)
  except Exception as e:record(label+' WebSocket denied','403' in str(e))
 for app in ['cortex','certifications']:
  async with websockets.connect(a.url.replace('http:','ws:')+f'/apps/{app}/v1/logs/stream',**{kw:{'Cookie':'sid=fixture-admin-session'}}) as socket:
   line=await asyncio.wait_for(socket.recv(),5);record(app+' live backend log',line.startswith('fixture backend log'))
 async with httpx.AsyncClient(base_url=a.url,timeout=5) as c:
  r=await c.get('/apps/api/v1/logs/stream');record('guest gateway SSE denied',r.status_code==403)
  async with c.stream('GET','/apps/api/v1/logs/stream',headers={'Cookie':'sid=fixture-admin-session'}) as r:
   record('admin gateway SSE type',r.status_code==200 and r.headers.get('content-type','').startswith('text/event-stream'))
   async for line in r.aiter_lines():
    if line.startswith('data:'):record('gateway log entry received',True);break
  headers={'Cookie':'sid=fixture-viewer-session; csrf=fixture-csrf','X-CSRF-Token':'fixture-csrf'}
  for size,status in [(1024,201),(3*1024*1024,201),(15*1024*1024+1,400)]:
   r=await c.post('/apps/support/v1/attachments',headers=headers,files={'file':('fixture.bin',b'x'*size,'application/octet-stream')});record(f'attachment {size} bytes',r.status_code==status)
  async with c.stream('GET','/apps/reports/v1/stream',headers={'Cookie':'sid=fixture-viewer-session'}) as r:
   async for line in r.aiter_lines():
    if line.startswith('data:'):record('HTTP proxy streams before completion',r.status_code==200);break
  r=await c.get('/apps/reports/v1/catalog');record('HTTP usable after stream cancellation',r.status_code==200)
asyncio.run(main());a.output.write_text(json.dumps({'results':results,'passed':sum(x['passed'] for x in results),'total':len(results)},indent=2));raise SystemExit(0 if all(x['passed'] for x in results) else 1)

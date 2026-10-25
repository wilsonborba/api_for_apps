"""Local deterministic upstream/provider test double. No production network access."""
import asyncio,os,json
from fastapi import FastAPI,Request,WebSocket
from fastapi.responses import Response,StreamingResponse
app=FastAPI()
@app.websocket('/logs/stream')
async def websocket_logs(ws:WebSocket):
 # Type annotation assigned below through the imported Starlette WebSocket class.
 await ws.accept()
 try:
  for i in range(100):await ws.send_text(f'fixture backend log {i}');await asyncio.sleep(.05)
 except Exception:pass
@app.post('/api_for_apps/media')
async def media_upload(request:Request):
 await request.body();return {'item':{'key':'fixture-attachment-key'}}
@app.api_route('/{path:path}',methods=['GET','POST','PUT','PATCH','DELETE','HEAD','OPTIONS'])
async def handle(path:str,request:Request):
 if path=='auth/v1/admin/users':return {'users':[{'email':'existing@example.test'}]}
 if path=='auth/v1/user':return {'id':'fixture-subject','email':'fixture@example.test','user_metadata':{'display_name':'Fixture User'}}
 if path=='auth/v1/token':return {'access_token':'fixture-access','session':{'access_token':'fixture-access'}}
 if path=='auth/v1/signup':return {'access_token':'fixture-access'}
 if path.startswith('auth/v1/'):return {}
 if path=='failure':return Response('unavailable',status_code=503)
 if path.startswith('delay/'):
  await asyncio.sleep(min(1,int(path.split('/')[1])/1000))
 if path.startswith('bytes/'):
  return Response(b'x'*min(2*1024*1024,int(path.split('/')[1])),media_type='application/octet-stream')
 if path.startswith('logs') or path=='stream':
  async def events():
   for i in range(5):yield f'data: fixture log {i}\n\n';await asyncio.sleep(.02)
  return StreamingResponse(events(),media_type='text/event-stream')
 return {'method':request.method,'path':request.scope['raw_path'].decode(),'query':request.url.query,'body':(await request.body()).decode(errors='replace'),'headers':dict(request.headers)}

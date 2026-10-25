#!/usr/bin/env python3
"""Measure isolated loopback workloads with raw requests and process-tree samples.
Each scenario has its own client pool. This prevents an existing failed hello
request from contaminating the next scenario through a stale connection.
"""
import argparse,asyncio,csv,hashlib,json,os,pathlib,platform,subprocess,time
import httpx
parser=argparse.ArgumentParser()
for name in ['url','implementation','output']:parser.add_argument('--'+name,required=True,type=pathlib.Path if name=='output' else str)
parser.add_argument('--pid',type=int,required=True);parser.add_argument('--requests',type=int,default=128);parser.add_argument('--runs',type=int,default=3);parser.add_argument('--extended',action='store_true')
a=parser.parse_args()
if not a.url.startswith(('http://127.0.0.1:18','http://localhost:18')):raise SystemExit('Only isolated loopback 18xxx targets are allowed')
a.output.mkdir(parents=True,exist_ok=True)
scenarios=[('hello','/apps/api/v1/hello_apps'),('public_catalog','/apps/reports/v1/catalog'),('protected_denied','/apps/cortex/v1/private'),('admin_proxy','/apps/domain/v1/projects'),('payload_1k','/apps/reports/v1/bytes/1024'),('payload_64k','/apps/reports/v1/bytes/65536'),('payload_1m','/apps/reports/v1/bytes/1048576'),('upstream_delay','/apps/reports/v1/delay/10'),('upstream_failure','/apps/reports/v1/failure')]
if a.extended:scenarios += [('session_proxy','/apps/cortex/v1/private'),('user_info','/user/info/v1/'),('user_fields','/user/info/v1/fields'),('support_list','/apps/support/v1/tickets'),('admin_support_list','/apps/support/v1/tickets'),('head_transfer','/apps/reports/v1/bytes/65536')]
rows=[];samples=[];warmups=[];context={}
def process_tree():
 pending=[a.pid]
 while pending:
  pid=pending.pop()
  try:
   root=pathlib.Path(f'/proc/{pid}');stat=(root/'stat').read_text().split();fds=list((root/'fd').iterdir())
   sockets=sum(str(f.readlink()).startswith('socket:') for f in fds)
   samples.append({'timestamp_ns':time.time_ns(),'pid':pid,'cpu_seconds':(int(stat[13])+int(stat[14]))/os.sysconf('SC_CLK_TCK'),'rss_bytes':int(stat[23])*os.sysconf('SC_PAGE_SIZE'),'threads':int(stat[19]),'open_fds':len(fds),'socket_fds':sockets,**context})
   pending += list(map(int,(root/'task'/str(pid)/'children').read_text().split()))
  except (OSError,ValueError):pass
async def main():
 stop=asyncio.Event()
 async def sample():
  while not stop.is_set():process_tree();await asyncio.sleep(.1)
 sampling=asyncio.create_task(sample())
 try:
  for run in range(a.runs):
   for concurrency in [1,8,32]:
    for name,path in scenarios:
     method='HEAD' if name=='head_transfer' else 'POST' if name=='admin_proxy' else 'GET'
     headers={'Authorization':'fixture-admin'} if name=='admin_proxy' else {'Cookie':'sid=fixture-admin-session'} if name=='admin_support_list' else {'Cookie':'sid=fixture-viewer-session'} if name in ('session_proxy','user_info','user_fields','support_list','head_transfer') else {}
     expected=403 if name=='protected_denied' else 503 if name=='upstream_failure' else 200
     context.update(run=run,scenario=name,concurrency=concurrency,phase='warmup')
     async with httpx.AsyncClient(base_url=a.url,timeout=10,limits=httpx.Limits(max_connections=128,max_keepalive_connections=128)) as client:
      for attempt in range(3):
       start=time.perf_counter_ns();status=0;error=''
       try:r=await client.request(method,path,headers=headers);status=r.status_code
       except httpx.HTTPError as exc:error=type(exc).__name__
       warmups.append({'run':run,'scenario':name,'concurrency':concurrency,'attempt':attempt,'status':status,'duration_ns':time.perf_counter_ns()-start,'error':error})
       if not error:break
      context['phase']='measurement';semaphore=asyncio.Semaphore(concurrency)
      async def one(index):
       async with semaphore:
        start=time.perf_counter_ns();timestamp=time.time_ns();status=0;size=0;error=''
        try:
         result=await client.request(method,path,headers=headers);status=result.status_code;size=len(result.content)
        except httpx.HTTPError as exc:error=type(exc).__name__
        rows.append({'implementation':a.implementation,'run':run,'scenario':name,'method':method,'path':path,'concurrency':concurrency,'request':index,'timestamp_ns':timestamp,'duration_ns':time.perf_counter_ns()-start,'status':status,'response_bytes':size,'error':error,'expected_status':expected,'known_baseline_bug':name=='hello' and status!=200})
      await asyncio.gather(*(one(index) for index in range(a.requests)))
 finally:stop.set();await sampling
asyncio.run(main())
for name,data in [('requests',rows),('resources',samples),('warmups',warmups)]:
 with (a.output/(name+'.csv')).open('w') as f:
  writer=csv.DictWriter(f,fieldnames=list(data[0]) if data else []);writer.writeheader();writer.writerows(data)
unexpected=[r for r in rows if r['status']!=r['expected_status'] and not r['known_baseline_bug']]
source=pathlib.Path('../api_for_apps-python-baseline') if a.implementation.startswith('python') else pathlib.Path('.')
metadata={'implementation':a.implementation,'harness_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'application_commit':subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip(),'binary_sha256':hashlib.sha256(pathlib.Path(f'/proc/{a.pid}/exe').read_bytes()).hexdigest() if a.implementation.startswith('rust') else None,'platform':platform.platform(),'cpus':os.cpu_count(),'server_pid':a.pid,'workers':4,'worker_model':'4 Gunicorn UvicornWorker processes' if a.implementation.startswith('python') else '4 Tokio workers','url':a.url,'requests_per_scenario':a.requests,'runs':a.runs,'dependency':'local deterministic upstream/provider doubles','database':'same untouched real-data SQLite snapshot','cache':'loopback Redis RESP2/RESP3 double' if a.extended else 'process-local memory fixture','clock':'perf_counter_ns','resource_sample_seconds':.1,'unexpected_response_count':len(unexpected),'limitations':['Closed-loop arrivals follow completion; no fixed offered-rate claim.','Independent client pool and one successful warm-up exchange per scenario; warm-up failures are recorded separately.','No production PostgreSQL locking or write verification.','Shared host; sequential Python/Rust trials.','Known hello bug #48 can return 500 or cause client errors and is excluded from normal success comparisons.','No production writes or stress tests.']}
(a.output/'metadata.json').write_text(json.dumps(metadata,indent=2));print(len(rows),'requests',len(samples),'resource samples;',len(unexpected),'unexpected responses',flush=True)
if unexpected:raise SystemExit('Unexpected responses: inspect raw records before accepting the comparison')

#!/usr/bin/env python3
"""Matched local-only workloads. Individual requests and /proc resource samples in CSV."""
import argparse,asyncio,csv,json,pathlib,time,statistics,random,os,platform,subprocess
import httpx,hashlib
p=argparse.ArgumentParser();p.add_argument('--url',required=True);p.add_argument('--implementation',required=True);p.add_argument('--pid',type=int,required=True);p.add_argument('--output',type=pathlib.Path,required=True);p.add_argument('--requests',type=int,default=120);p.add_argument('--runs',type=int,default=3);p.add_argument('--extended',action='store_true');a=p.parse_args()
if not a.url.startswith(('http://127.0.0.1:18','http://localhost:18')):raise SystemExit('Only isolated local 18xxx targets allowed')
a.output.mkdir(parents=True,exist_ok=True)
scenarios=[('hello','/apps/api/v1/hello_apps'),('public_catalog','/apps/reports/v1/catalog'),('protected_denied','/apps/cortex/v1/private'),('admin_proxy','/apps/domain/v1/projects'),('payload_1k','/apps/reports/v1/bytes/1024'),('payload_64k','/apps/reports/v1/bytes/65536'),('payload_1m','/apps/reports/v1/bytes/1048576'),('upstream_delay','/apps/reports/v1/delay/10'),('upstream_failure','/apps/reports/v1/failure')]
if a.extended:
 scenarios += [('session_proxy','/apps/cortex/v1/private'),('user_info','/user/info/v1/'),('user_fields','/user/info/v1/fields'),('support_list','/apps/support/v1/tickets'),('admin_support_list','/apps/support/v1/tickets'),('head_transfer','/apps/reports/v1/bytes/65536')]
# Fixture-only public paths are registered by each harness, without changing production policies.
rows=[];samples=[]
def process_tree():
 pending=[a.pid];out=[]
 while pending:
  pid=pending.pop()
  try:
   t=pathlib.Path(f'/proc/{pid}/stat').read_text().split();status=pathlib.Path(f'/proc/{pid}/status').read_text();rss=int(t[23])*os.sysconf('SC_PAGE_SIZE');fd=len(list(pathlib.Path(f'/proc/{pid}/fd').iterdir()));samples.append({'timestamp_ns':time.time_ns(),'pid':pid,'cpu_seconds':(int(t[13])+int(t[14]))/os.sysconf('SC_CLK_TCK'),'rss_bytes':rss,'threads':int(t[19]),'open_fds':fd,'socket_fds':sum(1 for link in pathlib.Path(f'/proc/{pid}/fd').iterdir() if link.is_symlink() and str(link.readlink()).startswith('socket:'))});out.append(pid);pending+=list(map(int,pathlib.Path(f'/proc/{pid}/task/{pid}/children').read_text().split()))
  except (OSError,ValueError):pass
 return out
async def main():
 stop=False
 async def sample():
  while not stop:process_tree();await asyncio.sleep(.1)
 sampling=asyncio.create_task(sample())
 try:
  async with httpx.AsyncClient(base_url=a.url,timeout=10,limits=httpx.Limits(max_connections=128,max_keepalive_connections=128)) as client:
   for run in range(a.runs):
    for concurrency in [1,8,32]:
     for name,path in scenarios:
      scenario_headers={'Authorization':'fixture-admin'} if name=='admin_proxy' else {'Cookie':'sid=fixture-admin-session'} if name=='admin_support_list' else {'Cookie':'sid=fixture-viewer-session'} if name in ('session_proxy','user_info','user_fields','support_list') else {}
      await client.request('HEAD' if name=='head_transfer' else 'GET',path,headers=scenario_headers)
      sem=asyncio.Semaphore(concurrency)
      async def one(i):
       async with sem:
        start=time.perf_counter_ns();ts=time.time_ns();status=0;size=0;error=''
        try:r=await client.request('HEAD' if name=='head_transfer' else 'GET',path,headers={'Authorization':'fixture-admin'} if name=='admin_proxy' else {'Cookie':'sid=fixture-admin-session'} if name=='admin_support_list' else {'Cookie':'sid=fixture-viewer-session'} if name in ('session_proxy','user_info','user_fields','support_list') else {});status=r.status_code;size=len(r.content)
        except Exception as e:error=type(e).__name__
        rows.append({'implementation':a.implementation,'run':run,'scenario':name,'path':path,'concurrency':concurrency,'request':i,'timestamp_ns':ts,'duration_ns':time.perf_counter_ns()-start,'status':status,'response_bytes':size,'error':error})
      await asyncio.gather(*(one(i) for i in range(a.requests)))
 finally:
  stop=True;await sampling
asyncio.run(main())
for name,data in [('requests',rows),('resources',samples)]:
 with (a.output/(name+'.csv')).open('w') as f:
  w=csv.DictWriter(f,fieldnames=list(data[0]) if data else []);w.writeheader();w.writerows(data)
meta={'implementation':a.implementation,'harness_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'application_commit':subprocess.check_output(['git','-C',str(pathlib.Path('../api_for_apps-python-baseline') if a.implementation.startswith('python') else pathlib.Path('.')),'rev-parse','HEAD'],text=True).strip(),'binary_sha256':hashlib.sha256(pathlib.Path('target/release/api-for-apps').read_bytes()).hexdigest() if a.implementation.startswith('rust') else None,'workers':4,'worker_model':'4 Gunicorn UvicornWorker processes' if a.implementation.startswith('python') else '4 Tokio workers','platform':platform.platform(),'cpus':os.cpu_count(),'url':a.url,'requests_per_scenario':a.requests,'runs':a.runs,'dependency':'local deterministic double','database':'SQLite fixture','cache':'loopback Redis RESP2/RESP3 test double' if a.extended else 'process-local memory fixture','clock':'perf_counter_ns','resource_sample_seconds':.1,'limitations':['Closed-loop clients; offered rate follows completion','No production PostgreSQL locking or driver write verification','Provider operations use doubles','CPU shared with host services; repeat matched trials','Protected-denied scenarios measure access rejection']}
(a.output/'metadata.json').write_text(json.dumps(meta,indent=2));print(len(rows),'requests',len(samples),'resource samples')

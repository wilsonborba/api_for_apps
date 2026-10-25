#!/usr/bin/env python3
"""Measure cold process startup on isolated ports, keeping production untouched."""
import argparse,subprocess,time,os,pathlib,socket,json,csv,httpx,signal
p=argparse.ArgumentParser();p.add_argument('--implementation',choices=['python','rust'],required=True);p.add_argument('--snapshot',type=pathlib.Path,required=True);p.add_argument('--output',type=pathlib.Path,required=True);p.add_argument('--runs',type=int,default=5);a=p.parse_args();root=pathlib.Path(__file__).resolve().parents[1];env=os.environ.copy();env.update({'PYTHON_BASELINE_SOURCE':str(root.parent/'api_for_apps-python-baseline'),'TEST_SQLITE_PATH':str(a.snapshot.resolve()),'FIXTURE_UPSTREAM':'http://127.0.0.1:18190','FIXTURE_REDIS_URL':'redis://127.0.0.1:18191/0','PORT':'18110','HOST':'127.0.0.1'})
cmd=[str(root.parent/'api_for_apps/.venv/bin/python'),'-m','gunicorn','tools.fixture_server:app','-k','uvicorn.workers.UvicornWorker','-w','4','-b','127.0.0.1:18110'] if a.implementation=='python' else ['bash','tools/run_rust_fixture.sh'];rows=[]
for run in range(a.runs):
 start=time.perf_counter_ns();proc=subprocess.Popen(cmd,cwd=root,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
 try:
  tcp=None
  for _ in range(2000):
   try:
    with socket.create_connection(('127.0.0.1',18110),timeout=.02):tcp=time.perf_counter_ns();break
   except OSError:
    if proc.poll() is not None:raise RuntimeError('Fixture process failed')
    time.sleep(.005)
  if tcp is None:raise RuntimeError('No startup readiness within deadline')
  with httpx.Client(base_url='http://127.0.0.1:18110',timeout=10) as client:
   before=time.perf_counter_ns();r=client.get('/apps/reports/v1/catalog');after=time.perf_counter_ns();warm=[]
   for _ in range(10):t=time.perf_counter_ns();client.get('/apps/reports/v1/catalog');warm.append((time.perf_counter_ns()-t)/1e6)
  rows.append({'implementation':a.implementation,'run':run,'tcp_ready_ms':(tcp-start)/1e6,'first_http_complete_ms':(after-start)/1e6,'first_request_ms':(after-before)/1e6,'first_status':r.status_code,'warm_request_mean_ms':sum(warm)/len(warm)})
 finally:
  os.killpg(proc.pid,signal.SIGTERM)
  try:proc.wait(timeout=10)
  except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
a.output.parent.mkdir(parents=True,exist_ok=True)
with a.output.open('w') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
print(len(rows),'cold-start trials')

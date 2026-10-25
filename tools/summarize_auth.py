#!/usr/bin/env python3
"""Summarize controlled authentication action latencies, preserving setup costs."""
import argparse,csv,json,pathlib,statistics
p=argparse.ArgumentParser();p.add_argument('--python',type=pathlib.Path,required=True);p.add_argument('--rust',type=pathlib.Path,required=True);p.add_argument('--output',type=pathlib.Path,required=True);a=p.parse_args()
def q(xs,p):
 xs=sorted(xs);k=(len(xs)-1)*p;i=int(k);return xs[i]+(xs[min(i+1,len(xs)-1)]-xs[i])*(k-i)
all_rows=[]
for name,folder in [('python',a.python),('rust',a.rust)]:
 records=list(csv.DictReader((folder/'requests.csv').open()))
 for scenario,c in sorted({(r['scenario'],int(r['concurrency'])) for r in records}):
  rs=[r for r in records if r['scenario']==scenario and int(r['concurrency'])==c];lat=[int(r['action_duration_ns'])/1e6 for r in rs];setup=[int(r['setup_duration_ns'])/1e6 for r in rs]
  all_rows.append({'implementation':name,'scenario':scenario,'concurrency':c,'observations':len(rs),'mean_client_ms':statistics.mean(lat),'median_client_ms':q(lat,.5),'p90_client_ms':q(lat,.9),'p95_client_ms':q(lat,.95),'p99_client_ms':q(lat,.99),'max_client_ms':max(lat),'stdev_client_ms':statistics.stdev(lat),'setup_median_ms':q(setup,.5),'unexpected':sum(r['status']!=r['expected_status'] for r in rs),'mean_response_bytes':statistics.mean(int(r['response_bytes']) for r in rs)})
a.output.mkdir(parents=True,exist_ok=True)
with (a.output/'auth_summary.csv').open('w') as f:w=csv.DictWriter(f,fieldnames=list(all_rows[0]));w.writeheader();w.writerows(all_rows)
(a.output/'auth_summary.json').write_text(json.dumps({'results':all_rows,'limits':['Client action latency excludes separately recorded prerequisite requests.','No throughput claim is derived from per-action durations.','Provider double supplies the legacy callback shape; root REST mismatch is tracked as bug #49.','Security backoff remains enabled.']},indent=2));print(len(all_rows),'auth scenario summaries')

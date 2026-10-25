#!/usr/bin/env python3
"""Derive run summaries and paired bootstrap intervals from raw local observations."""
import argparse,csv,json,pathlib,statistics,random,math
p=argparse.ArgumentParser();p.add_argument('--python',type=pathlib.Path,required=True);p.add_argument('--rust',type=pathlib.Path,required=True);p.add_argument('--output',type=pathlib.Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
def quantile(xs,p):
 xs=sorted(xs);k=(len(xs)-1)*p;i=int(k);return xs[i]+(xs[min(i+1,len(xs)-1)]-xs[i])*(k-i)
def load(path):
 rows=list(csv.DictReader((path/'requests.csv').open()));groups={}
 for row in rows:groups.setdefault((row['scenario'],int(row['concurrency']),int(row['run'])),[]).append(row)
 summaries=[]
 for (scenario,c,run),rs in groups.items():
  ds=[int(r['duration_ns'])/1e6 for r in rs];start=min(int(r['timestamp_ns']) for r in rs);end=max(int(r['timestamp_ns'])+int(r['duration_ns']) for r in rs);seconds=(end-start)/1e9
  summaries.append({'scenario':scenario,'concurrency':c,'run':run,'requests':len(rs),'completed_requests':sum(r['status']!='0' for r in rs),'client_errors':sum(bool(r['error']) for r in rs),'http_5xx':sum(int(r['status'])>=500 for r in rs),'duration_seconds':seconds,'throughput_rps':len(rs)/seconds,'mean_ms':statistics.mean(ds),'stdev_ms':statistics.stdev(ds) if len(ds)>1 else 0,'median_ms':quantile(ds,.5),'p90_ms':quantile(ds,.9),'p95_ms':quantile(ds,.95),'p99_ms':quantile(ds,.99),'max_ms':max(ds),'response_bytes':sum(int(r['response_bytes']) for r in rs),'transfer_bytes_per_second':sum(int(r['response_bytes']) for r in rs)/seconds})
 return summaries
py=load(a.python);rust=load(a.rust)
for name,rows in [('python_run_summaries',py),('rust_run_summaries',rust)]:
 with (a.output/(name+'.csv')).open('w') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
comparison=[];rng=random.Random(20261025)
for scenario,c in sorted({(x['scenario'],x['concurrency']) for x in py}):
 ps=sorted([x for x in py if x['scenario']==scenario and x['concurrency']==c],key=lambda x:x['run']);rs=sorted([x for x in rust if x['scenario']==scenario and x['concurrency']==c],key=lambda x:x['run'])
 for metric in ['throughput_rps','mean_ms','median_ms','p90_ms','p95_ms','p99_ms','max_ms','transfer_bytes_per_second','http_5xx','client_errors']:
  pv=[x[metric] for x in ps];rv=[x[metric] for x in rs];diff=[r-p for p,r in zip(pv,rv)];boots=[statistics.mean(rng.choices(diff,k=len(diff))) for _ in range(2000)];pm=statistics.mean(pv);rm=statistics.mean(rv)
  comparison.append({'scenario':scenario,'concurrency':c,'metric':metric,'python_mean':pm,'rust_mean':rm,'absolute_difference':rm-pm,'percentage_change':(rm/pm-1)*100 if pm else None,'paired_runs':len(diff),'difference_bootstrap_95_low':quantile(boots,.025),'difference_bootstrap_95_high':quantile(boots,.975)})
with (a.output/'comparison.csv').open('w') as f:w=csv.DictWriter(f,fieldnames=list(comparison[0]));w.writeheader();w.writerows(comparison)
report={'comparison':comparison,'limitations':[f'{len({x["run"] for x in py})} repeated trials provide limited uncertainty estimation; bootstrap intervals are descriptive, not a causal guarantee.','Loopback upstream doubles and SQLite fixtures differ from production dependencies.','Python hello failures are existing bug #48; compare successful functionality separately.','CPU/memory resources are recorded as individual PID time series; summed RSS double-counts shared pages.','Experiments run sequentially on a shared host.','No production write or stress tests performed.']}
(a.output/'comparison.json').write_text(json.dumps(report,indent=2))
lines=['# Python versus Rust controlled comparison','','Raw observations and run metadata remain beside this analysis.','', '| Scenario | Concurrency | Python p95 ms | Rust p95 ms | p95 change |','|---|---:|---:|---:|---:|']
for r in comparison:
 if r['metric']=='p95_ms':lines.append(f"| {r['scenario']} | {r['concurrency']} | {r['python_mean']:.3f} | {r['rust_mean']:.3f} | {r['percentage_change']:.1f}% |")
lines+=['','## Limits']+['- '+x for x in report['limitations']];(a.output/'comparison.md').write_text('\n'.join(lines)+'\n');print(len(comparison),'comparison measurements across',len(py)+len(rust),'scenario-runs')

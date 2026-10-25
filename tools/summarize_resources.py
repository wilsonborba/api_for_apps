#!/usr/bin/env python3
"""Summarize gateway process trees without counting external dependency doubles."""
import argparse,csv,json,pathlib,statistics
p=argparse.ArgumentParser();p.add_argument('--input',type=pathlib.Path,required=True);p.add_argument('--pid',type=int,required=True);p.add_argument('--output',type=pathlib.Path,required=True);a=p.parse_args();rows=list(csv.DictReader((a.input/'resources.csv').open()));requests=list(csv.DictReader((a.input/'requests.csv').open()));by_pid={};batches=[];current=[]
for row in rows:
 pid=int(row['pid']);by_pid.setdefault(pid,[]).append(row)
 if pid==a.pid:
  if current:batches.append(current)
  current=[]
 current.append(row)
if current:batches.append(current)
cpu=sum(float(rs[-1]['cpu_seconds'])-float(rs[0]['cpu_seconds']) for rs in by_pid.values());elapsed=(int(rows[-1]['timestamp_ns'])-int(rows[0]['timestamp_ns']))/1e9
series=[]
for batch in batches:
 series.append({'timestamp_ns':int(batch[0]['timestamp_ns']),'rss_sum_bytes':sum(int(r['rss_bytes']) for r in batch),'threads_sum':sum(int(r['threads']) for r in batch),'open_fds_sum':sum(int(r['open_fds']) for r in batch),'socket_fds_sum':sum(int(r.get('socket_fds',0)) for r in batch)})
pss=[]
for pid in by_pid:
 try:
  fields={line.split(':',1)[0]:int(line.split(':',1)[1].strip().split()[0])*1024 for line in pathlib.Path(f'/proc/{pid}/smaps_rollup').read_text().splitlines() if ':' in line}
  pss.append({'pid':pid,'pss_bytes':fields.get('Pss'),'private_clean_bytes':fields.get('Private_Clean'),'private_dirty_bytes':fields.get('Private_Dirty')})
 except (OSError,ValueError):pass
xs=[(r['timestamp_ns']-series[0]['timestamp_ns'])/1e9 for r in series];ys=[r['rss_sum_bytes'] for r in series];xm=statistics.mean(xs);ym=statistics.mean(ys);denom=sum((x-xm)**2 for x in xs);slope=sum((x-xm)*(y-ym) for x,y in zip(xs,ys))/denom if denom else 0
out={'requests':len(requests),'sampled_seconds':elapsed,'gateway_cpu_seconds':cpu,'cpu_percent_one_core_basis':cpu/elapsed*100 if elapsed else None,'cpu_microseconds_per_observed_request':cpu/len(requests)*1e6,'peak_tree_rss_sum_bytes':max(ys),'mean_tree_rss_sum_bytes':ym,'steady_tree_pss_bytes':sum(r['pss_bytes'] or 0 for r in pss) if pss else None,'rss_linear_slope_bytes_per_second':slope,'peak_threads':max(r['threads_sum'] for r in series),'peak_open_fds':max(r['open_fds_sum'] for r in series),'peak_socket_fds':max(r['socket_fds_sum'] for r in series),'pid_count':len(by_pid),'steady_pss_samples':pss,'limits':['Summed RSS double-counts shared pages; PSS is sampled after the run, not a measured peak.','CPU excludes upstream/cache/provider test doubles and the load generator.','Socket descriptors are not an exact count of established TCP connections.','Memory slope over this trial is descriptive and does not establish long-term leak behavior.']}
a.output.mkdir(parents=True,exist_ok=True);(a.output/'resource_summary.json').write_text(json.dumps(out,indent=2))
with (a.output/'resource_tree.csv').open('w') as f:w=csv.DictWriter(f,fieldnames=list(series[0]));w.writeheader();w.writerows(series)
print(json.dumps({k:out[k] for k in ['requests','gateway_cpu_seconds','peak_tree_rss_sum_bytes','steady_tree_pss_bytes']}))

#!/usr/bin/env python3
from pathlib import Path
import hashlib,json,statistics,sys
base=Path(sys.argv[1]); checks={}
def pct(v,q):
 s=sorted(v);x=(len(s)-1)*q;i=int(x);j=min(i+1,len(s)-1);return s[i]+(s[j]-s[i])*(x-i)
# Concurrency: recompute from individual joined records.
c=[json.loads(x) for x in (base/'concurrency/records.jsonl').read_text().splitlines()]
cv=[x['backend_received_to_receiver_ms'] for x in c if x.get('receiver')]
cs=json.loads((base/'concurrency/summary.json').read_text())
checks['concurrency_records_100']=len(c)==len(cv)==100
checks['concurrency_all_success']=all(x['ok'] for x in c)
checks['concurrency_p99_recomputed_matches']=abs(pct(cv,.99)-cs['latency_received_to_receiver_ms']['p99'])<1e-9
checks['concurrency_simultaneous_100_at_receiver']=cs['receiver']['max_simultaneous_active_requests']==100 and cs['barrier']['tasks_ready_before_release']==100
# Drain: recompute stats from every non-selected run summary.
d=[]; hs=set(); cores=[]
for p in sorted((base/'drain').glob('run-[0-9][0-9]')):
 s=json.loads((p/'summary.json').read_text());d.append(s['reconnect_to_queue_empty_seconds']);hs.add(hashlib.sha256((p/'run_profile.py').read_bytes()).hexdigest());cores.append('\n'.join(x for x in (p/'conditions.txt').read_text().splitlines() if not x.startswith(('run=','started_at_utc=','finished_at_utc='))))
da=json.loads((base/'drain/aggregate.json').read_text())
checks['drain_five_valid']=len(d)==5
checks['drain_same_harness_and_conditions']=len(hs)==1 and len(set(cores))==1
checks['drain_all_under_30']=all(x<30 for x in d)
checks['drain_mean_matches']=abs(statistics.fmean(d)-da['seconds']['mean'])<1e-12
checks['drain_median_matches']=abs(statistics.median(d)-da['seconds']['median'])<1e-12
checks['drain_stdev_matches']=abs(statistics.stdev(d)-da['seconds']['sample_stdev'])<1e-12
# Latency: recompute from per-event records and audit trace coverage.
l=[json.loads(x) for x in (base/'latency/records.jsonl').read_text().splitlines()];lv=[x['latency_ms'] for x in l if x.get('latency_ms') is not None];ls=json.loads((base/'latency/summary.json').read_text())
checks['latency_100_correlated']=len(l)==len(lv)==100 and len({x['path'] for x in l})==100
checks['latency_no_negative']=all(x>=0 for x in lv)
checks['latency_p99_matches']=abs(pct(lv,.99)-ls['latency_ms']['p99'])<1e-9
checks['latency_p99_under_1000']=pct(lv,.99)<1000
trace=[json.loads(x) for x in (base/'latency/agent-trace.jsonl').read_text().splitlines()]
paths={x['path'] for x in l}; trace_paths={x.get('path') for x in trace};
checks['latency_agent_trace_covers_paths']=paths <= trace_paths
checks['candidate_identity']= (base/'metadata/candidate-commit.txt').read_text().strip()=='7df4935f769a2e393a5e6a6330df605c77592e52' and (base/'metadata/candidate-tree.txt').read_text().strip()=='95455f919ec602b6cddf1440341652d99b784bd3'
checks['cleanup_and_isolation']=(base/'latency/teardown-result.json').read_text().strip()=='{"containers_remaining":0,"volumes_remaining":0,"networks_remaining":0,"temporary_root_removed":true}' and not (base/'metadata/drain-residual.txt').read_text().strip() and 'stable_container_name_image_equal=true' in (base/'metadata/main-stack-unchanged.txt').read_text() and not (base/'metadata/source-staging-after.txt').read_text().strip()
out={'checks':checks,'passed':all(checks.values()),'recomputed':{'concurrency_p99_ms':pct(cv,.99),'drain_mean_s':statistics.fmean(d),'drain_median_s':statistics.median(d),'drain_sample_stdev_s':statistics.stdev(d),'latency_p99_ms':pct(lv,.99),'latency_trace_rows':len(trace)}}
(base/'metadata/independent-verification.json').write_text(json.dumps(out,indent=2,sort_keys=True)+'\n');print(json.dumps(out,indent=2,sort_keys=True));raise SystemExit(0 if out['passed'] else 1)

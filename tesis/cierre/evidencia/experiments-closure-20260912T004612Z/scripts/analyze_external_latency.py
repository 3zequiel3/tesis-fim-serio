#!/usr/bin/env python3
import csv,json,re,statistics,sys
from datetime import datetime
from pathlib import Path
strace=Path(sys.argv[1]); db=Path(sys.argv[2]); out=Path(sys.argv[3])
pat=re.compile(r'^(\d+\.\d+)\s+close\(\d+<([^>]+)>\)\s+=\s+0\s+<(\d+\.\d+)>')
starts={}
for line in strace.read_text(errors='replace').splitlines():
 m=pat.search(line)
 if not m: continue
 name=Path(m.group(2)).name
 if name.startswith('latency-ext-') and name.endswith('.txt'):
  starts[name]=float(m.group(1))+float(m.group(3))
rows=[]
with db.open(newline='') as f:
 for r in csv.DictReader(f):
  name=Path(r['path']).name; ext=starts.get(name); recv=datetime.fromisoformat(r['received_at']).timestamp()
  rows.append({**r,'basename':name,'strace_close_end_epoch':ext,'start_source':'strace -ttt close(2) entry timestamp + syscall duration','end_source':'PostgreSQL events.received_at','latency_ms':(recv-ext)*1000 if ext is not None else None})
vals=[r['latency_ms'] for r in rows if r['latency_ms'] is not None]
def pct(xs,q):
 s=sorted(xs);x=(len(s)-1)*q;i=int(x);j=min(i+1,len(s)-1);return s[i]+(s[j]-s[i])*(x-i)
summary={'experiment':'M-2 externally anchored detection latency','definitions':{'start':'completion of close(2) for the modified file, observed externally by strace -ttt -T -yy','end':'backend PostgreSQL events.received_at for the same path/event','interval':'filesystem modification completion (a) to backend reception (c)'},'planned':100,'database_events':len(rows),'externally_correlated':len(vals),'negative_intervals':sum(v<0 for v in vals),'latency_ms':{'n':len(vals),'mean':statistics.fmean(vals) if vals else None,'median':statistics.median(vals) if vals else None,'p95':pct(vals,.95) if vals else None,'p99':pct(vals,.99) if vals else None,'min':min(vals) if vals else None,'max':max(vals) if vals else None,'sample_stdev':statistics.stdev(vals) if len(vals)>1 else None},'acceptance':{'threshold_p99_ms_strictly_less_than':1000,'complete_denominator':len(rows)==100 and len(vals)==100,'p99_under_1000_ms':bool(vals) and pct(vals,.99)<1000,'passed':len(rows)==100 and len(vals)==100 and not any(v<0 for v in vals) and pct(vals,.99)<1000},'clock_and_scope':{'strace_clock':'host CLOCK_REALTIME rendering from ptrace observer; independent of generator-owned timestamps','backend_clock':'container wall clock on same host/kernel; Docker compose uses no time namespace','topology':'single physical host, isolated Compose containers/network/volumes; Valkey plaintext','not_historical_reaggregation':True,'not_full_system_validation':True},'limits':['100 sequential modifications at 10 operations/s, not 500 historical operations','single host and shared kernel clock; no remote clock synchronization tested','strace provides independent observation of start, while end is the system PostgreSQL timestamp','no claim about encrypted Valkey transport or remote network latency']}
(out/'records.jsonl').write_text(''.join(json.dumps(r,sort_keys=True)+'\n' for r in rows)); (out/'summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n'); print(json.dumps(summary,indent=2,sort_keys=True)); raise SystemExit(0 if summary['acceptance']['passed'] else 1)

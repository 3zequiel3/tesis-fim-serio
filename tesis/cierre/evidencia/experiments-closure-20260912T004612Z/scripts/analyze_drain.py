#!/usr/bin/env python3
from pathlib import Path
import hashlib,json,statistics,sys
base=Path(sys.argv[1]); rows=[]; script_hashes=set(); condition_core=[]
for d in sorted(base.glob('run-[0-9][0-9]')):
 s=json.loads((d/'summary.json').read_text()); rc=int((d/'exit-code.txt').read_text())
 h=hashlib.sha256((d/'run_profile.py').read_bytes()).hexdigest(); script_hashes.add(h)
 core='\n'.join(x for x in (d/'conditions.txt').read_text().splitlines() if not x.startswith(('run=','started_at_utc=','finished_at_utc=')))
 condition_core.append(core)
 sec=s['reconnect_to_queue_empty_seconds']; rows.append({'run':d.name,'exit_code':rc,'completed':s['completed'],'planned':s['planned_events'],'persisted':s['persisted_events'],'queue_remaining':s['queue_remaining'],'rejected':s['rejected_events'],'duplicates':s['duplicate_event_stream_messages'],'seconds':sec,'throughput_events_s':s['throughput_events_s'],'under_30s':sec<30,'script_sha256':h})
xs=[r['seconds'] for r in rows]
summary={'experiment':'M-1 repeated Run 4 drain','valid_runs':len(rows),'all_conditions_unchanged':len(set(condition_core))==1,'unique_harness_hashes':len(script_hashes),'runs':rows,'seconds':{'n':len(xs),'mean':statistics.fmean(xs),'median':statistics.median(xs),'min':min(xs),'max':max(xs),'sample_stdev':statistics.stdev(xs) if len(xs)>1 else None},'acceptance':{'threshold_seconds_strictly_less_than':30,'runs_passing':sum(r['under_30s'] for r in rows),'runs_failing':sum(not r['under_30s'] for r in rows),'all_runs_pass':all(r['under_30s'] and r['completed'] and r['persisted']==r['planned']==3000 and r['queue_remaining']==0 and r['rejected']==0 and r['duplicates']==0 and r['exit_code']==0 for r in rows)},'limits':['single physical host','3000 events were pre-enqueued before reconnect timing','experimental rate limit 100000 events/60s instead of production default 100/60s','does not reproduce the full five-minute disconnection','descriptive five-run sample; no inferential population claim']}
(base/'aggregate.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n'); print(json.dumps(summary,indent=2,sort_keys=True))
raise SystemExit(0 if len(rows)>=5 and summary['all_conditions_unchanged'] and len(script_hashes)==1 else 1)

#!/usr/bin/env python3
"""Exercise 100 simultaneous production notifier calls against a controlled receiver."""
from __future__ import annotations
import asyncio, json, statistics, threading, time, uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

COUNT=100
HOST='127.0.0.1'; PORT=19099
OUT=Path(__file__).resolve().parents[1] / 'concurrency'
lock=threading.Lock(); records=[]; active=0; max_active=0

def pct(xs:list[float],q:float)->float:
 s=sorted(xs); r=(len(s)-1)*q; lo=int(r); hi=min(lo+1,len(s)-1); f=r-lo
 return s[lo]+(s[hi]-s[lo])*f

class Server(ThreadingHTTPServer):
 request_queue_size=256
 daemon_threads=True

class H(BaseHTTPRequestHandler):
 def do_POST(self):
  global active,max_active
  received=datetime.now(timezone.utc); recv_mono=time.monotonic_ns()
  n=int(self.headers.get('Content-Length','0')); raw=self.rfile.read(n)
  try: payload=json.loads(raw)
  except Exception: payload={}
  with lock:
   active+=1; max_active=max(max_active,active); observed_active=active
  # Controlled hold only keeps requests overlapping; reception timestamp precedes it.
  time.sleep(0.050)
  with lock:
   records.append({'event_id':payload.get('event_id'),'received_at_utc':received.isoformat(),
    'receiver_monotonic_ns':recv_mono,'active_at_reception':observed_active,
    'backend_dispatched_at':payload.get('backend_dispatched_at'),
    'source_received_at':payload.get('received_at')})
   active-=1
  body=b'{"ok":true}'
  self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
 def log_message(self,*args): pass

async def main()->int:
 from app.modules.alerts.notifier import send_n8n
 server=Server((HOST,PORT),H); th=threading.Thread(target=server.serve_forever,daemon=True); th.start()
 ready=0; ready_lock=asyncio.Lock(); all_ready=asyncio.Event(); release=asyncio.Event(); client_rows=[]
 async def one(i:int):
  nonlocal ready
  event_id=f'concurrent-{i:03d}-{uuid.uuid4()}'
  async with ready_lock:
   ready+=1
   if ready==COUNT: all_ready.set()
  await release.wait()
  start_utc=datetime.now(timezone.utc); start_ns=time.monotonic_ns()
  payload={'event_id':event_id,'alert_id':i,'notification_id':str(uuid.uuid4()),'severity':'high','path':f'/controlled/concurrent-{i:03d}.txt','received_at':start_utc.isoformat()}
  ok=await send_n8n(payload,f'http://{HOST}:{PORT}/webhook',timeout=10.0)
  end_ns=time.monotonic_ns()
  client_rows.append({'index':i,'event_id':event_id,'ok':ok,'task_start_utc':start_utc.isoformat(),'task_start_monotonic_ns':start_ns,'task_end_monotonic_ns':end_ns,'client_elapsed_ms':(end_ns-start_ns)/1e6})
 tasks=[asyncio.create_task(one(i)) for i in range(COUNT)]
 await asyncio.wait_for(all_ready.wait(),5); barrier_release_utc=datetime.now(timezone.utc); barrier_release_ns=time.monotonic_ns(); release.set()
 await asyncio.gather(*tasks)
 server.shutdown(); server.server_close(); th.join(timeout=2)
 by_id={r['event_id']:r for r in records}; joined=[]
 for c in sorted(client_rows,key=lambda x:x['index']):
  r=by_id.get(c['event_id']); row={**c,'receiver':r}
  if r:
   a=datetime.fromisoformat(c['task_start_utc']); b=datetime.fromisoformat(r['received_at_utc']); row['backend_received_to_receiver_ms']=(b-a).total_seconds()*1000
  joined.append(row)
 vals=[r['backend_received_to_receiver_ms'] for r in joined if r.get('receiver')]
 client=[r['client_elapsed_ms'] for r in joined]
 summary={'experiment':'A-3 notification concurrency','criterion':{'simultaneous_requests':100,'p99_ms_strictly_less_than':5000},
  'scope':'production send_n8n transport function to controlled local HTTP receiver; synthetic pre-persisted notification payloads',
  'not_full_system_validation':True,'barrier':{'tasks_ready_before_release':ready,'release_utc':barrier_release_utc.isoformat(),'release_monotonic_ns':barrier_release_ns},
  'receiver':{'planned':COUNT,'received':len(records),'unique_event_ids':len(by_id),'fixed_post_reception_hold_ms':50,'max_simultaneous_active_requests':max_active},
  'client':{'successful':sum(bool(r['ok']) for r in joined),'failed':sum(not bool(r['ok']) for r in joined)},
  'latency_received_to_receiver_ms':{'n':len(vals),'mean':statistics.fmean(vals),'median':statistics.median(vals),'p95':pct(vals,.95),'p99':pct(vals,.99),'min':min(vals),'max':max(vals)},
  'client_roundtrip_ms':{'n':len(client),'mean':statistics.fmean(client),'median':statistics.median(client),'p95':pct(client,.95),'p99':pct(client,.99),'min':min(client),'max':max(client)}}
 summary['acceptance']={'simultaneity_proven':ready==COUNT and max_active>1,'complete_denominator':len(records)==COUNT and len(by_id)==COUNT,'p99_under_5000_ms':summary['latency_received_to_receiver_ms']['p99']<5000,'passed':ready==COUNT and max_active>1 and len(records)==COUNT and len(by_id)==COUNT and all(r['ok'] for r in joined) and summary['latency_received_to_receiver_ms']['p99']<5000}
 (OUT/'records.jsonl').write_text(''.join(json.dumps(r,sort_keys=True)+'\n' for r in joined))
 (OUT/'summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
 print(json.dumps(summary,indent=2,sort_keys=True))
 return 0 if summary['acceptance']['passed'] else 1
if __name__=='__main__': raise SystemExit(asyncio.run(main()))

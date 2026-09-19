#!/usr/bin/env python3
from pathlib import Path
from datetime import datetime,timezone
import argparse,hashlib,json,os,time
p=argparse.ArgumentParser();p.add_argument('--dir',required=True);p.add_argument('--count',type=int,default=100);p.add_argument('--rate',type=float,default=10);p.add_argument('--manifest',required=True);a=p.parse_args()
root=Path(a.dir); rows=[]; interval=1/a.rate; start=time.monotonic()
for i in range(a.count):
 target=start+i*interval; delay=target-time.monotonic()
 if delay>0: time.sleep(delay)
 path=root/f'latency-ext-{i:03d}.txt'; data=f'changed-{i:03d}-{hashlib.sha256(str(i).encode()).hexdigest()}\n'.encode()
 before=datetime.now(timezone.utc); before_ns=time.monotonic_ns()
 fd=os.open(path,os.O_WRONLY|os.O_TRUNC|os.O_CLOEXEC); os.write(fd,data); os.fsync(fd); os.close(fd)
 after_ns=time.monotonic_ns(); after=datetime.now(timezone.utc)
 rows.append({'sequence':i+1,'basename':path.name,'agent_path':f'/watch/{path.name}','operation':'write_fsync_close','bytes':len(data),'hash_after':hashlib.sha256(data).hexdigest(),'generator_before_utc':before.isoformat(),'generator_after_utc':after.isoformat(),'generator_before_monotonic_ns':before_ns,'generator_after_monotonic_ns':after_ns})
Path(a.manifest).write_text(''.join(json.dumps(r,sort_keys=True)+'\n' for r in rows))
print(json.dumps({'planned':a.count,'completed':len(rows),'rate_operations_s':a.rate,'start_definition':'external strace close(2) completion is authoritative; generator stamps are secondary only'},sort_keys=True))

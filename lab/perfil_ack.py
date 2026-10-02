"""Measure the agent's ack-side cost per event.

Each ack removes the queue file and persists the stream cursor. Both run on the
same event loop as the retry loop that republishes, so they add to the per-event
budget of a drain.
"""
import statistics
import sys
import time
import uuid
from datetime import datetime, timezone

sys.path.insert(0, "/opt/fim-agent")

from agent.queue import EventQueue  # noqa: E402
from agent.state import AgentState, save_state  # noqa: E402

N = 200
DIR = "/var/lib/fim-agent/perfil_queue2"
SECRET = b"0" * 32


def bench(label, fn, n=N):
    s = []
    for i in range(n):
        t = time.perf_counter()
        fn(i)
        s.append((time.perf_counter() - t) * 1000)
    s.sort()
    print(f"{label:38s} media={statistics.mean(s):7.3f} ms  p50={s[len(s)//2]:7.3f}  p95={s[int(n*0.95)]:7.3f}")


q = EventQueue(DIR, master_secret=SECRET, agent_id="fim-vm")
ids = []
for i in range(N):
    ev = str(uuid.uuid4())
    ids.append(ev)
    q.enqueue({"event_id": ev, "agent_id": "fim-vm", "path": f"/srv/x/{i}.txt",
               "event_type": "file_modified", "detected_at": datetime.now(timezone.utc).isoformat(),
               "hash_detected": "a" * 64, "schema_version": 1, "action": "alert_only"})

print("=== agent ack-side cost per event ===")
bench("queue.remove (unlink)", lambda i: q.remove(ids[i]))

st = AgentState(agent_id="fim-vm")
try:
    bench("save_state (cursor persist)", lambda i: save_state(st, __import__("pathlib").Path(f"{DIR}/state.json")))
except Exception as exc:  # noqa: BLE001
    print(f"save_state unavailable: {type(exc).__name__}: {exc}")

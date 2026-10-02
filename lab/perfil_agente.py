"""Profile the agent's drain cost per event, component by component.

Runs on the monitored host against the same filesystem the queue uses, with the
agent's own modules, so the crypto and the fsync are the real ones.
"""
import os
import statistics
import sys
import time
import uuid
from datetime import datetime, timezone

sys.path.insert(0, "/opt/fim-agent")

from agent.queue import EventQueue, _atomic_write_envelope, _load_envelope  # noqa: E402
from agent.streams import sign_payload  # noqa: E402

N = 200
DIR = "/var/lib/fim-agent/perfil_queue"
SECRET = b"0" * 32


def bench(label, fn, n=N):
    samples = []
    for i in range(n):
        t = time.perf_counter()
        fn(i)
        samples.append((time.perf_counter() - t) * 1000)
    samples.sort()
    print(f"{label:42s} media={statistics.mean(samples):7.3f} ms  "
          f"p50={samples[len(samples)//2]:7.3f}  p95={samples[int(len(samples)*0.95)]:7.3f}")
    return statistics.mean(samples)


q = EventQueue(DIR, master_secret=SECRET, agent_id="fim-vm")

payloads = []
for i in range(N):
    ev = str(uuid.uuid4())
    payloads.append({
        "event_id": ev, "agent_id": "fim-vm", "path": f"/srv/fim-watch/gen_{i:05d}.txt",
        "event_type": "file_modified", "detected_at": datetime.now(timezone.utc).isoformat(),
        "hash_detected": "a" * 64, "schema_version": 1, "action": "alert_only",
    })

print("=== agent drain cost per event ===")
bench("enqueue (encrypt + fsync)", lambda i: q.enqueue(payloads[i]))
bench("bump_attempts (decrypt + encrypt + fsync)", lambda i: q.bump_attempts(payloads[i]["event_id"]))
bench("HMAC sign only", lambda i: sign_payload(SECRET, payloads[i]))

# Isolate the fsync from the crypto: same atomic write, no encryption round trip.
f = q._find_file(payloads[0]["event_id"])
env, _ = _load_envelope(f, q._key)
bench("atomic write only (encrypt + fsync)", lambda i: _atomic_write_envelope(q._key, f, env))


def plain_write(i):
    tmp = f"{DIR}/plain.tmp"
    fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(b"x" * 900)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, f"{DIR}/plain.bin")


bench("bare tmp+fsync+replace (no crypto)", plain_write)

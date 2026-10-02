"""Measure the agent's XADD round trip to Valkey over mutual TLS.

The queue work costs 1.7 ms per event but the drain runs at ~22 ms per event.
This isolates the network leg, which crosses from the monitored host to the
central server.
"""
import asyncio
import statistics
import sys
import time

sys.path.insert(0, "/opt/fim-agent")

CERTS = "/var/lib/fim-agent/certs"
URL = "valkeys://192.168.1.43:6380"
N = 200


async def main():
    import valkey.asyncio as valkey
    client = valkey.Valkey.from_url(
        URL,
        ssl_certfile=f"{CERTS}/agent-cert.pem",
        ssl_keyfile=f"{CERTS}/agent-key.pem",
        ssl_ca_certs=f"{CERTS}/ca.pem",
        decode_responses=True,
    )
    for label, coro in (
        ("PING", lambda: client.ping()),
        ("XADD to a scratch stream", lambda: client.xadd("perfil:scratch", {"data": "x" * 900}, maxlen=200)),
    ):
        samples = []
        for _ in range(N):
            t = time.perf_counter()
            await coro()
            samples.append((time.perf_counter() - t) * 1000)
        samples.sort()
        print(f"{label:30s} media={statistics.mean(samples):7.3f} ms  "
              f"p50={samples[len(samples)//2]:7.3f}  p95={samples[int(len(samples)*0.95)]:7.3f}")
    await client.aclose()

asyncio.run(main())

#!/bin/sh
# Controlled lab reset on the monitored host.
systemctl stop fim-agent
find /srv/fim-watch -mindepth 1 -delete 2>/dev/null
mkdir -p /srv/fim-watch/critico
find /var/lib/fim-agent/queue -mindepth 1 -delete 2>/dev/null
find /var/lib/fim-agent/discarded -mindepth 1 -delete 2>/dev/null
# Truncate the experiment trace while the agent is stopped, so every repetition
# produces its own trace instead of a cumulative file. Copying the cumulative
# file once per repetition made the three per-run traces byte-identical, and
# nothing in the harness noticed. Harmless when tracing is disabled.
rm -f /var/lib/fim-agent/traza_b3.jsonl
systemctl start fim-agent

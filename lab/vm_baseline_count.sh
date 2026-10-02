#!/bin/sh
# Number of baseline entries (*.bin) the agent holds. Used by the harness
# preflight: it must be 0 before any generator write (L-11/L-14).
# Must run as a transferred script (multipass re-parses inline quoting).
N=$(find /var/lib/fim-agent/baseline -maxdepth 1 -type f -name '*.bin' 2>/dev/null | wc -l | tr -d ' ')
echo "baseline_entries=$N"

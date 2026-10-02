#!/bin/sh
# Real queue/discard counters for the Battery 5 harness.
# Must run as a transferred script: multipass exec re-parses inline quoting,
# so `bash -c '... | wc -l'` silently counted the working directory instead.
q=$(ls -1 /var/lib/fim-agent/queue 2>/dev/null | wc -l)
d=$(ls -1 /var/lib/fim-agent/discarded 2>/dev/null | wc -l)
echo "$q $d"

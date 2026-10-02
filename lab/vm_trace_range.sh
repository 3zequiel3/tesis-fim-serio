#!/bin/sh
# Report the experiment trace's size and time span, so the harness can assert
# that a repetition produced its own trace instead of silently copying a stale
# cumulative file.
#
# Output: one line, "<lines> <bytes> <first_timestamp> <last_timestamp>".
# Prints "0 0 - -" when the trace is absent or empty, which the caller must
# treat as a failed repetition rather than as a missing optional artifact.
F=/var/lib/fim-agent/traza_b3.jsonl
[ -s "$F" ] || { echo "0 0 - -"; exit 0; }
LINES=$(wc -l < "$F")
BYTES=$(stat -c %s "$F")
FIRST=$(head -n 1 "$F" | sed -n 's/.*"timestamp":"\([^"]*\)".*/\1/p')
LAST=$(tail -n 1 "$F" | sed -n 's/.*"timestamp":"\([^"]*\)".*/\1/p')
echo "$LINES $BYTES ${FIRST:--} ${LAST:--}"

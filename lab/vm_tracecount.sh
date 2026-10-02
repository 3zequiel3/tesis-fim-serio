#!/bin/sh
wc -l < /var/lib/fim-agent/traza_b3.jsonl 2>/dev/null || echo 0

#!/bin/sh
echo "== /var/lib/fim-agent:"
ls -la /var/lib/fim-agent
echo "== config.yaml:"
grep -iE 'queue|spool|state|dir' /etc/fim-agent/config.yaml

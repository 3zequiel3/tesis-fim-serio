#!/bin/sh
grep -iE "trace|level|debug" /etc/fim-agent/config.yaml /etc/fim-agent/env 2>/dev/null

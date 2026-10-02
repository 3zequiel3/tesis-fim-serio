#!/bin/sh
grep -iE "valkey|url|cert|key|ca_|stream" /etc/fim-agent/config.yaml

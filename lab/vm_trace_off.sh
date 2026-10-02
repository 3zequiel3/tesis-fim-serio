#!/bin/sh
rm -f /etc/systemd/system/fim-agent.service.d/trace.conf
rmdir /etc/systemd/system/fim-agent.service.d 2>/dev/null
systemctl daemon-reload
systemctl restart fim-agent
sleep 3
systemctl show fim-agent -p Environment

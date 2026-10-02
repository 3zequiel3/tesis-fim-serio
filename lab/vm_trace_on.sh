#!/bin/sh
# Enable the agent's experiment trace: one JSONL record per kernel event, so a
# missed operation can be told apart from an operation the kernel never delivered.
mkdir -p /etc/systemd/system/fim-agent.service.d
cat > /etc/systemd/system/fim-agent.service.d/trace.conf <<CONF
[Service]
Environment=FIM_EXPERIMENT_TRACE_FILE=/var/lib/fim-agent/traza_b3.jsonl
Environment=FIM_EXPERIMENT_RUN_ID=b3-traza
CONF
systemctl daemon-reload
rm -f /var/lib/fim-agent/traza_b3.jsonl
systemctl restart fim-agent
sleep 3
systemctl show fim-agent -p Environment | head -2

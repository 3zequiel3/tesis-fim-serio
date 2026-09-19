# Real acceptance result in a state/data/resource-isolated lab

**PREPARADO — EJECUTADO — VALIDACIÓN REGISTRADA**

- US-03: real old-CURRENT to new-CURRENT/old-PREVIOUS rotation exercised; prior access and refresh accepted, foreign key rejected.
- US-16: real browser edit plus DB/audit/outbox and real agent state synchronization exercised.
- US-17: cancel without DELETE, confirmed deletion, persistence/audit/outbox, real agent synchronization, and post-delete `alert_only` effect exercised.
- US-25: real browser bulk approve, signed/versioned `baseline_update`, agent execution, ACK, encrypted-baseline effect, and audit exercised.
- US-03 canonical cookie attributes and US-25 canonical `event_ids[]` request wire are exercised.
- `rule_sync` is not claimed to ACK; reception is observed in the agent's persisted ruleset version.
- Isolation covers state, data, containers, network, PKI, baseline, and watch files. It does not isolate the physical host, Docker daemon, kernel, or image cache.
- fanotify may observe kernel events outside `/watch`; the agent's scope filter discards them. Such observation is not counted as an accepted FIM event.
- RuleForm labels are programmatically associated and exercised through accessible-name locators; no global accessibility claim is made.
- Screenshots, video and trace screencast frames are disabled or removed before packaging; sanitized textual trace/report evidence remains.

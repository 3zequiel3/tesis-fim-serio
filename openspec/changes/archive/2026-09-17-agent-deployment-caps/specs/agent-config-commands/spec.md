## ADDED Requirements

### Requirement: update_config re-runs the write preflight over the new path set

After reloading the detector and scanning newly added paths, `handle_update_config` SHALL re-run the write preflight over the new watch path set and SHALL update the shared preflight registry, so the next heartbeat reports the new classification.

This is what makes the known limitation of D36 visible rather than silent. `ReadWritePaths` is materialized at installation time through the systemd drop-in, while `update_config` changes watch paths at runtime. A path added from the interface is therefore **monitored but not remediable** until the privileged host-side configuration is re-run — drop-in regeneration plus a systemd reload. The limitation is inherent to systemd resolving its isolation in the mount namespace at service start, not an implementation defect. The preflight surfaces it within one heartbeat interval instead of letting the operator discover it when a remediation eventually fails.

The re-run SHALL NOT change whether the command is acknowledged as successful, and SHALL NOT prevent the reload from taking effect. (D36 / RN-130)

#### Scenario: A newly added path outside the drop-in is reported as non-remediable

- **WHEN** an `update_config` command adds a watch path that is not covered by the installed drop-in
- **THEN** the path is monitored, and the next heartbeat reports it as `read_only_mount`

#### Scenario: A removed path disappears from the reported status

- **WHEN** an `update_config` command removes a watch path
- **THEN** the next heartbeat no longer carries an entry for it

#### Scenario: The preflight re-run does not block the reload

- **WHEN** every path in the new set classifies as non-writable
- **THEN** the detector reload and the baseline scan still complete and the agent keeps monitoring

### Requirement: Failure to persist the configuration stops being silent

The failure to write the configuration file SHALL NOT be swallowed as a bare warning. Today the write failure is logged at warning level while the in-memory watch paths are updated anyway and the acknowledgement still reports success, so the persisted state diverges from the runtime state without any signal — and on the next restart the hot configuration reverts. The case where the configuration file does not exist is currently an outright no-op with no log line at all.

The handler SHALL log the failure at error level, SHALL record the outcome in the shared registry so the heartbeat reports whether the configuration was persisted, and SHALL log the nonexistent-file case as well.

The acknowledgement's success flag SHALL NOT change. The hot reload genuinely happened — the detector was reloaded, new paths were scanned, and the in-memory configuration was updated — and the acknowledgement contract was only just settled by the command-ack work. Turning it into a failure would change the meaning of an established acknowledgement and could trigger backend retries of a command that mostly took effect. The correct channel for "running but degraded" is the heartbeat. (D36 / RN-130)

#### Scenario: A failed configuration write is reported through the heartbeat

- **WHEN** the handler cannot write the configuration file
- **THEN** an error is logged and the next heartbeat reports that the configuration was not persisted

#### Scenario: A missing configuration file is logged

- **WHEN** the resolved configuration path does not exist
- **THEN** the condition is logged rather than skipped silently

#### Scenario: The acknowledgement still reports success

- **WHEN** the reload succeeds but the configuration write fails
- **THEN** the command acknowledgement still reports success, and the degradation is carried by the heartbeat only

#### Scenario: A successful write clears the degraded persistence state

- **WHEN** a later `update_config` writes the configuration successfully
- **THEN** the heartbeat reports the configuration as persisted again

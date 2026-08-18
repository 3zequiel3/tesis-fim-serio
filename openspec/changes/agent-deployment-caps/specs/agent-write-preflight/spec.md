## ADDED Requirements

### Requirement: Write capability per watch path is classified with a closed, non-invasive probe

The agent SHALL classify each configured watch path into exactly one of four values, in lowercase snake_case per RN-71: `writable`, `read_only_mount`, `permission_denied`, `missing`.

Classification SHALL NOT be performed by writing a probe file inside the watch path. Such a probe would be the most faithful test, but it writes into a monitored directory and would generate the agent's own fanotify events — a `file_created` plus a `file_deleted` under a watch path — on every startup and every configuration reload. Only `/var/lib/fim-agent/**` is self-excluded (RN-68), so a probe elsewhere pollutes the very event stream the system exists to produce.

Classification SHALL instead use two side-effect-free syscalls, each measuring exactly one of the two barriers:

- the read-only mount flag reported by `statvfs` for the path, which reflects the mount options as seen inside the service's own mount namespace, where `ProtectSystem=strict` operates;
- an access check for write permission, which reflects the DAC barrier. That check evaluates against the real uid and gid, and the kernel retains effective capabilities when the real uid equals the effective uid — the case for this service, which never changes uid — so it does reflect `CAP_DAC_OVERRIDE`.

Evaluation order SHALL be: `missing`, then `read_only_mount`, then `permission_denied`, then `writable`. The order is normative, not incidental: a read-only mount also makes the write access check fail, and the cause useful to the operator in that case is the mount one (a missing `ReadWritePaths` entry), not the permission one (missing capabilities). Reporting the latter would send the operator to fix what is not broken.

The check SHALL be applied to the **directory**: remediating a file requires write access on its parent directory to create the temporary file and perform the rename, not on the file itself. When a watch path names a regular file, its parent directory SHALL be evaluated.

Classification SHALL be a pure function whose probes are injectable, so that all four outcomes and the ordering rule are testable without privileges. (D36 / RN-130, RN-71)

#### Scenario: A writable path is classified writable

- **WHEN** a watch path exists on a read-write mount and write access is permitted
- **THEN** it is classified `writable`

#### Scenario: A path on a read-only mount is classified read_only_mount

- **WHEN** a watch path exists but its mount is read-only
- **THEN** it is classified `read_only_mount`, even though the write access check also fails

#### Scenario: A path denied by permissions is classified permission_denied

- **WHEN** a watch path exists on a read-write mount but write access is denied
- **THEN** it is classified `permission_denied`

#### Scenario: A nonexistent path is classified missing

- **WHEN** a configured watch path does not exist
- **THEN** it is classified `missing`

#### Scenario: A watch path naming a file is evaluated through its parent directory

- **WHEN** a watch path names a regular file
- **THEN** the classification reflects the writability of the directory containing it

### Requirement: A non-writable watch path degrades to detection-only and never stops the agent

The preflight SHALL run at startup, after the configuration is loaded and before the initial baseline scan, so that the first heartbeat already carries its result.

A non-writable watch path SHALL NOT stop the agent and SHALL NOT interrupt monitoring. It SHALL be marked detection-only, logged at warning level per path with the classification as a structured field, summarized at info level, and reported in the heartbeat. Detection is the primary function; remediation is an additional capability that may be absent without invalidating the service. An agent that refuses to start because a watch path is not writable stops detecting, which is the outcome this requirement exists to prevent.

The preflight SHALL NOT terminate the process under any classification outcome. Results SHALL be held in an explicit registry object passed to the heartbeat publisher and to the command dispatcher, not in module-level global state, so that both consumers are testable in isolation.

This also makes visible a case that is currently silent end to end: a nonexistent watch path is accepted by the baseline scan, by the detector reload and by the configuration command handler, each of which logs and continues. The `missing` classification is the first time that condition reaches the operator. (D36 / RN-130)

#### Scenario: Agent starts and monitors with a non-writable watch path

- **WHEN** the preflight classifies one of several watch paths as `read_only_mount` at startup
- **THEN** the agent completes startup, the detector monitors all configured paths including that one, and the process does not exit

#### Scenario: Each degraded path is logged individually

- **WHEN** the preflight classifies two paths as non-writable
- **THEN** a warning is logged for each, carrying the path and its classification, plus a single summary at info level

#### Scenario: A missing watch path becomes visible

- **WHEN** a configured watch path does not exist on the host
- **THEN** it is reported as `missing` rather than silently accepted

#### Scenario: All paths writable produces no degradation

- **WHEN** every watch path is classified `writable`
- **THEN** no degradation warning is emitted and every path is reported as remediation-capable

### Requirement: The heartbeat reports the per-path write status

The heartbeat payload SHALL carry a `watch_path_status` key mapping each configured watch path to its classification. Adding the key is signature-safe: the canonical JSON used for HMAC covers the whole payload with sorted keys and no per-key allowlist, on both the signing and the verifying side.

The **complete** map SHALL be sent, not only the degraded entries. Omitting the writable ones would make an absent path ambiguous — writable, or an older agent that does not report at all — and the consumer could not distinguish the two.

The agent SHALL also report whether the last configuration persistence attempt succeeded, so that a runtime configuration change that could not be written to disk is visible rather than silent. (D36 / RN-130, RN-119)

#### Scenario: Heartbeat carries the full status map

- **WHEN** the agent publishes a heartbeat with three configured watch paths
- **THEN** `watch_path_status` contains an entry for each of the three, including the writable ones

#### Scenario: Adding the key does not break the signature

- **WHEN** a heartbeat carrying `watch_path_status` is verified by the backend
- **THEN** the HMAC signature validates

#### Scenario: Configuration persistence state is reported

- **WHEN** the agent's last attempt to persist its configuration to disk failed
- **THEN** the heartbeat reports that persistence state alongside the path status map

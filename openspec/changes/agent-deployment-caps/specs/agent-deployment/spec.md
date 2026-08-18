## ADDED Requirements

### Requirement: The systemd unit grants every capability the remediation path requires

The `fim-agent.service` unit SHALL declare `CAP_SYS_ADMIN`, `CAP_DAC_READ_SEARCH`, `CAP_DAC_OVERRIDE`, `CAP_FOWNER` and `CAP_CHOWN` in **both** `AmbientCapabilities` and `CapabilityBoundingSet`. Listing a capability only as ambient is insufficient: an ambient capability survives only if it is also in the permitted set, which is bounded by `CapabilityBoundingSet`, so a capability absent from the bounding set is discarded silently.

Each added capability corresponds to a specific syscall on the remediation path: `CAP_DAC_OVERRIDE` for creating the temporary file in a `root`-owned parent directory, for the `rename` behind `os.replace`, and for the source `unlink` behind `shutil.move`; `CAP_FOWNER` for `fchmod` on a file the process does not own; `CAP_CHOWN` for `fchown` to an arbitrary uid/gid. `CAP_SYS_ADMIN` alone does NOT exempt a process from DAC permission checks, and `CAP_DAC_READ_SEARCH` grants read and search only — neither substitutes for the three added ones.

No further capability SHALL be added. `NoNewPrivileges=true` SHALL be retained: it blocks escalation through `execve` of setuid or file-capability binaries and does not interfere with capabilities set by systemd at process start. (D36 / RN-130, RN-108)

#### Scenario: All five capabilities are present in both directives

- **WHEN** the shipped unit file is inspected
- **THEN** `AmbientCapabilities` and `CapabilityBoundingSet` both list exactly `CAP_SYS_ADMIN`, `CAP_DAC_READ_SEARCH`, `CAP_DAC_OVERRIDE`, `CAP_FOWNER` and `CAP_CHOWN`

#### Scenario: The running process actually holds the capabilities

- **WHEN** the service is started on a real host and its capability sets are read from `/proc/<pid>/status`
- **THEN** the effective and ambient sets decode to the five declared capabilities

#### Scenario: NoNewPrivileges remains enabled

- **WHEN** the unit is inspected
- **THEN** `NoNewPrivileges=true` is still declared alongside the expanded capability set

### Requirement: ProtectSystem stays strict and ReadWritePaths is derived into an additive drop-in

The unit SHALL retain `ProtectSystem=strict`. `ReadWritePaths` SHALL NOT be a fixed list covering the watch paths in the base unit. Instead, `install.sh` SHALL generate a systemd drop-in at `/etc/systemd/system/fim-agent.service.d/10-watchpaths.conf` derived from the `watch_paths` declared in the agent configuration file, leaving the base unit unedited.

The drop-in SHALL be **additive**: `ReadWritePaths=` is a list-type directive whose successive assignments accumulate, and only an empty assignment resets it. The drop-in therefore SHALL NOT repeat `/var/lib/fim-agent` or `/var/log/fim-agent` and SHALL NOT emit an empty `ReadWritePaths=` line — the base unit remains the source of the agent's own directories.

The drop-in SHALL always include `/etc/fim-agent`, independently of the configured watch paths, because `update_config` persists the configuration there and that write must not depend on the operator having chosen to monitor `/etc`.

Lowering to `ProtectSystem=full` SHALL NOT be used: it would leave `/usr/bin` read-only, that is, with no possible remediation over system binaries — precisely the scenario the tool exists for. (D36 / RN-130)

#### Scenario: Drop-in is generated from the configured watch paths

- **WHEN** `install.sh` runs against a configuration declaring `/etc`, `/bin` and `/usr/bin`
- **THEN** `/etc/systemd/system/fim-agent.service.d/10-watchpaths.conf` grants read-write access to those three paths plus `/etc/fim-agent`, and the base unit file is byte-identical to the repository copy

#### Scenario: Agent-owned directories are not repeated in the drop-in

- **WHEN** the generated drop-in is inspected
- **THEN** it contains no `/var/lib/fim-agent` or `/var/log/fim-agent` entry and no empty `ReadWritePaths=` reset, and the effective merged configuration still grants read-write access to both

#### Scenario: A configured watch path is writable at runtime

- **WHEN** the service is running with the drop-in installed and a configured watch path is probed for write access inside the service's mount namespace
- **THEN** the path is writable, whereas a path outside both the drop-in and the base unit remains read-only

### Requirement: The drop-in generator rejects malformed paths instead of emitting them

Drop-in generation SHALL be performed by a Python module in the agent package exposing pure functions — reading the watch paths from the configuration file and rendering the drop-in text — with a module entrypoint invoked by `install.sh` using the agent's own interpreter. It SHALL NOT be implemented by text-munging the YAML with shell tools, because the configuration file is written by `yaml.dump` from the `update_config` handler and must be read by the same parser.

The configuration file is not static: `update_config` rewrites `watch_paths` with values arriving from the backend over the command stream. The renderer therefore SHALL treat those values as untrusted input and SHALL:

- emit **one `ReadWritePaths=` line per path**, with the path enclosed in double quotes, rather than a single space-separated line;
- **raise an error** — never silently skip — for any path that is not absolute, or that contains a newline, a double quote, a backslash, or a `..` component;
- normalize with `normpath` and NOT with `realpath`, so symlinks are not followed (same criterion as D33 / RN-127).

A rejection SHALL abort generation with a clear message and SHALL cause `install.sh` to fail, rather than installing a truncated drop-in that would leave paths uncovered without anyone noticing. (D36 / RN-130, D18 / RN-116)

#### Scenario: A relative path aborts generation

- **WHEN** the configuration declares a relative watch path such as `etc/passwd`
- **THEN** generation raises an error naming the offending path, no drop-in file is written, and `install.sh` exits non-zero

#### Scenario: A path containing a newline cannot inject a directive

- **WHEN** the configuration declares a path whose value contains a newline followed by another systemd directive
- **THEN** generation raises an error and no drop-in is produced

#### Scenario: Each path is emitted on its own quoted line

- **WHEN** the drop-in is rendered for several valid paths
- **THEN** each path appears on its own `ReadWritePaths=` line, enclosed in double quotes

#### Scenario: Symlinked watch paths are not dereferenced

- **WHEN** a configured watch path is a symlink to another directory
- **THEN** the emitted entry is the normalized configured path, not the symlink target

### Requirement: The installer orders unit, configuration and drop-in so a fresh install is coherent

`install.sh` SHALL install the unit file, then ensure the configuration file exists, then generate the drop-in, and only then run `systemctl daemon-reload` and `systemctl enable`. Generating the drop-in requires the configuration file to be present, and the reload must observe both the unit and the drop-in.

The script SHALL remain idempotent: a second run SHALL NOT overwrite an operator-edited configuration file and SHALL leave ownership and permissions in the same final state. (D36 / RN-130)

#### Scenario: Fresh install produces unit, config, drop-in and an enabled service

- **WHEN** `install.sh` runs on a host with no prior installation
- **THEN** the unit, the configuration file and the drop-in all exist before `daemon-reload` runs, and the service is enabled

#### Scenario: Re-running the installer preserves the operator's configuration

- **WHEN** `install.sh` runs a second time on a host whose configuration file was edited
- **THEN** the configuration file content is unchanged and the drop-in is regenerated from it

### Requirement: Installation does not give the service user ownership of the code it runs

`install.sh` SHALL NOT `chown` `/opt/fim-agent` or `/etc/fim-agent` to the service user. It SHALL apply: `/opt/fim-agent` owned by `root:root`; `/etc/fim-agent` owned by `root:fim-agent` mode `0750`; the agent configuration file owned by `root:fim-agent` mode `0640` so the agent reads it through its group; the environment file owned by `root:root` mode `0600`. Only `/var/lib/fim-agent` and `/var/log/fim-agent` SHALL belong to the service user, keeping the permissions RN-51 already mandates.

The protection this provides SHALL be understood precisely. The service process holds `CAP_DAC_OVERRIDE` and can therefore still write to those directories — `update_config` requires writing the configuration file. What `root` ownership removes is the other vector: a shell obtained as the `fim-agent` uid **outside** the service process holds no ambient capabilities and can no longer rewrite the code systemd will execute with `CAP_SYS_ADMIN` on the next restart. Capabilities live in the process systemd starts, not in the uid; a recursive `chown` to the service user collapses that separation into a one-step privilege escalation. (D36 / RN-130, RN-51)

#### Scenario: Agent code is root-owned after installation

- **WHEN** `install.sh` completes
- **THEN** `/opt/fim-agent` and its contents are owned by `root`, and no path under it is owned by the service user

#### Scenario: The agent can still read its configuration

- **WHEN** the service starts with the configuration file owned `root:fim-agent` mode `0640`
- **THEN** the agent loads the configuration successfully

#### Scenario: State and log directories remain owned by the service user

- **WHEN** ownership is inspected after installation
- **THEN** `/var/lib/fim-agent` and `/var/log/fim-agent` are owned by the service user with the modes RN-51 requires

### Requirement: The shipped unit can start on a clean install and fails once when misconfigured

The unit SHALL declare `EnvironmentFile=-/etc/fim-agent/env`, with the leading dash so a missing file does not prevent startup. Today the unit declares no environment source at all while the agent requires `FIM_BOOTSTRAP_SECRET` on first boot and exits on its absence, so a fresh installation cannot complete bootstrap. The bootstrap secret is single-use and is expected to be removed after first boot, which is why the file must be optional rather than required.

`install.sh` SHALL install an environment file template at `/etc/fim-agent/env` **only if it does not already exist**, with mode `0600` owned by `root:root` — systemd reads it as root before dropping privileges, so the service user needs no access to it.

Startup failures caused by configuration SHALL exit with status `78` (`EX_CONFIG`) rather than `1`: a missing bootstrap secret, a missing shared secret, and any configuration load or validation failure. The unit SHALL declare `RestartPreventExitStatus=78`. `Restart=on-failure` SHALL be retained for genuinely transient failures. A misconfigured installation therefore leaves the unit in `failed` with a single legible journal message instead of repeating the same error every `RestartSec` forever. (D36 / RN-130, RN-68)

#### Scenario: Fresh install can complete bootstrap through the environment file

- **WHEN** the operator writes the bootstrap secret into `/etc/fim-agent/env` and starts the service on a host with no certificate
- **THEN** the agent reads the secret from the environment and performs its initial bootstrap

#### Scenario: Missing environment file does not prevent startup after bootstrap

- **WHEN** the service starts on a host that already holds a valid certificate and `/etc/fim-agent/env` has been deleted
- **THEN** the service starts normally

#### Scenario: A configuration error stops the restart loop

- **WHEN** the agent is started with no bootstrap secret available and no valid certificate
- **THEN** the process exits with status `78`, systemd does not restart it, and the unit reports `failed`

#### Scenario: A transient failure still restarts

- **WHEN** the agent exits with a status other than `78`
- **THEN** systemd restarts it according to `Restart=on-failure`

#### Scenario: The installer does not overwrite an existing environment file

- **WHEN** `install.sh` runs on a host whose `/etc/fim-agent/env` already contains operator values
- **THEN** the file is left untouched

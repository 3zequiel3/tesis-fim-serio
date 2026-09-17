## ADDED Requirements

### Requirement: Automatic restore reproduces the baseline mode, uid and gid

`_auto_restore` SHALL restore the file's mode, owner and group from the baseline entry, not only its content. The baseline already records `mode` (as the octal string produced by `oct(S_IMODE(...))`), `uid` and `gid` on every entry write, and nothing has ever read them back — `chown` does not appear anywhere in the agent today.

This is a precondition for granting the write capabilities, not a completeness extra. The temporary file is created owned by the service user with a mode derived from the umask; without metadata restoration a "successful" restore of a system binary would leave it owned by the service user at a permissive mode, converting a broken feature into a privilege escalation for anyone holding that uid.

The sequence SHALL be: create the temporary file in the destination's own directory with `O_CREAT | O_WRONLY | O_EXCL` and a restrictive initial mode; write and fsync the content; apply the owner and group; apply the mode; close; then `os.replace` onto the destination.

**The owner SHALL be applied before the mode.** On Linux, changing a file's owner clears its setuid and setgid bits, and the stored mode covers the full permission word including setuid, setgid and sticky. Applying the mode first would produce a restore that reports success while silently stripping the setuid bit from a privileged binary. Both operations SHALL be performed through the open file descriptor rather than by path, which removes the time-of-check/time-of-use window on the temporary path and guarantees the file never exists at its final path with the wrong ownership, because all metadata is applied before the atomic replace.

`O_EXCL` SHALL be used so that an orphaned temporary file from a previous attempt is detected rather than truncated and reused.

The content may be selected from a snapshot while mode, uid and gid always come from the entry, since snapshots do not record them. That asymmetry is accepted and documented: the entry's metadata is the most recently observed and is the best approximation available. (D36 / RN-130, RN-30, RN-31, RN-32, RN-33)

#### Scenario: Restored file recovers its baseline mode

- **WHEN** a file whose baseline entry records a mode is auto-restored
- **THEN** the file on disk carries that mode after the restore

#### Scenario: Owner is applied before mode

- **WHEN** the restore applies the baseline metadata to the temporary file
- **THEN** the owner change is performed before the mode change

#### Scenario: A setuid binary keeps its setuid bit

- **WHEN** a setuid binary is auto-restored from a baseline entry recording the setuid bit
- **THEN** the restored file still carries the setuid bit

#### Scenario: An orphaned temporary file does not get reused

- **WHEN** a temporary restore file from a previous attempt already exists next to the destination
- **THEN** the attempt fails rather than truncating and reusing it

#### Scenario: Metadata is applied before the file reaches its final path

- **WHEN** the restore completes
- **THEN** the destination path is never observable with the temporary file's default ownership — the replace is the first moment the destination changes

### Requirement: A restore whose baseline metadata is incomplete fails instead of completing partially

When the baseline entry lacks `mode`, `uid` or `gid`, or its recorded mode cannot be parsed, the restore SHALL fail with the reason `no_baseline_metadata`, SHALL remove the temporary file, and SHALL leave the original file untouched.

The case is real rather than hypothetical: entries produced when a path is marked absent carry all three as null. Publishing a system file owned by the service user with a umask-derived mode is worse than not restoring it, because it hands that uid the ability to rewrite a privileged binary. A visible failure is preferable to a restore that degrades the host's security posture while reporting success.

Mode parsing SHALL be a pure function accepting both the prefixed form produced by `oct()` and a bare octal string, and returning no value for anything else, so that a malformed mode routes to the same failure rather than to a silent default. (D36 / RN-130, RN-30)

#### Scenario: Missing owner metadata aborts the restore

- **WHEN** the baseline entry has restorable content but a null `uid`
- **THEN** the restore fails with `no_baseline_metadata` and the file on disk is unchanged

#### Scenario: Unparseable mode aborts the restore

- **WHEN** the baseline entry records a mode that does not parse as octal
- **THEN** the restore fails with `no_baseline_metadata` and no temporary file remains

#### Scenario: The failure is distinguishable from a content problem

- **WHEN** a restore fails for missing metadata
- **THEN** the reason is `no_baseline_metadata`, distinct from `no_baseline_content` and `no_restorable_content`

### Requirement: Action failures carry a closed-vocabulary cause that distinguishes deployment from data problems

Action failure reasons SHALL come from a closed lowercase snake_case vocabulary (RN-71): `read_only_mount`, `permission_denied`, `no_baseline_content`, `no_restorable_content`, `no_baseline_metadata`, `file_not_found`, `hash_mismatch_after_restore`, `write_failed`, `move_failed`.

The first two are the point of this requirement: an operator MUST be able to tell a deployment problem — the path is not writable — from a data problem — the baseline is missing or unusable — by looking at the event. Today the reason is written only to the host-local journal and the backend sees nothing but a boolean.

Mapping from the underlying error SHALL be a pure function: a read-only filesystem error maps to `read_only_mount`; a permission or operation-not-permitted error maps to `permission_denied`; anything else maps to the site's fallback (`write_failed` for restore, `move_failed` for quarantine). The published reason SHALL be the stable literal with no interpolation of the operating system's message, which today embeds the file path into the reason string; the errno and message SHALL go to structured log fields instead.

**The action SHALL NOT consult the preflight result before attempting.** The preflight is the reporting view; the error classification at the attempt site is the truth of that attempt. Gating the action on a cached preflight would introduce a stale-state failure: a path that became writable between startup and the event would be refused without being tried. The two views may disagree transiently, which is correct, because they mean different things.

The reason SHALL travel in the published event payload alongside the existing failure flag, and SHALL NOT be written on the success path, so every consumer reads it defensively. The journal SHALL continue to receive the same reason. The manual command handlers SHALL use the same mapping and the same literals, so the event path and the command-ack path speak one vocabulary rather than two dialects. (D36 / RN-130, D35 / RN-129, RN-71)

#### Scenario: A read-only filesystem produces read_only_mount

- **WHEN** an automatic restore fails because the destination filesystem is mounted read-only
- **THEN** the published payload carries the failure flag and the reason `read_only_mount`

#### Scenario: A denied permission produces permission_denied

- **WHEN** an automatic restore fails because the process lacks write permission on the destination directory
- **THEN** the published payload carries the reason `permission_denied`

#### Scenario: A missing baseline still produces its own data-side reason

- **WHEN** an automatic restore fails because no baseline entry exists
- **THEN** the reason is `no_baseline_content`, unchanged by this requirement

#### Scenario: The reason does not leak the host path

- **WHEN** any action fails with an operating system error
- **THEN** the published reason is a bare vocabulary literal with no interpolated error message or path

#### Scenario: Success does not emit the key

- **WHEN** an automatic action completes successfully
- **THEN** the published payload contains no failure reason key at all

#### Scenario: The action is attempted even when the preflight said the path was not writable

- **WHEN** the cached preflight classified a path as non-writable but the path is writable at the moment of the event
- **THEN** the restore is attempted and succeeds

#### Scenario: Manual command handlers use the same vocabulary

- **WHEN** a manual restore command fails because the destination is on a read-only mount
- **THEN** the acknowledgement carries the same `read_only_mount` literal used on the event path

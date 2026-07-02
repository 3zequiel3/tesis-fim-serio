## MODIFIED Requirements

### Requirement: Baseline scan skips entries resolving outside the watch_path scope

During `init_scan` and `run_scan`, the baseline engine SHALL classify each candidate discovered via `rglob` by calling `p.is_symlink()` **before** `p.is_file()`, because `Path.is_file()` follows symlinks and would otherwise misclassify an in-scope symlink as a regular file. Containment is evaluated by the candidate's location, consistent with the detector scope filter (D33) and the D18/RN-116 pattern. For a candidate whose final component is a symlink located inside a `watch_path`, the engine SHALL write a symlink baseline entry (see the symlink baseline requirement) instead of following the link — it MUST NOT resolve, hash, or encrypt the symlink target's content, whether that target is inside or outside the `watch_path`. For a regular-file candidate whose `os.path.realpath()` resolves OUTSIDE the canonicalized `watch_path` (e.g. reached via a symlinked intermediate directory pointing out of scope), the engine SHALL skip it with a `warning` log instead of encrypting it into the baseline, enforcing RN-04 at baseline time. (D31 / RN-125, refined by D33 / RN-127)

#### Scenario: In-scope regular file is baselined
- **WHEN** `init_scan` finds a regular file whose `os.path.realpath()` is relative to the canonicalized `watch_path`
- **THEN** the file is hashed and written to the baseline as usual

#### Scenario: Symlink is classified before regular file and written as a symlink entry
- **WHEN** `init_scan` finds a candidate whose final component is a symlink located inside a `watch_path`
- **THEN** `is_symlink()` is checked before `is_file()`, and the engine writes a symlink baseline entry without following, hashing, or encrypting the target's content

#### Scenario: Regular file reached via an out-of-scope intermediate symlink is skipped with a warning
- **WHEN** `init_scan` finds a regular file whose `os.path.realpath()` resolves outside the canonicalized `watch_path`
- **THEN** the entry is skipped with a warning log and its content is NOT encrypted into the baseline

#### Scenario: run_scan applies the same classification and containment rules
- **WHEN** `run_scan` (rescan or newly added paths) encounters a candidate
- **THEN** it classifies `is_symlink()` before `is_file()` and applies the same skip/symlink-entry rules identically to `init_scan`

## ADDED Requirements

### Requirement: Baseline stores symlink entries with target metadata only

`BaselineEntry` SHALL gain an optional field `symlink_target: str | None = None`, with a backward-compatible default so that `from_dict` continues to parse pre-existing baseline entries that lack the field. A new `write_symlink_entry` function SHALL create a baseline entry for an in-scope symlink using `os.lstat` and `os.readlink` only: `content_b64` MUST be `None`, `hash` MUST be `sha256(target)` (the `readlink` string), and `symlink_target` MUST be set to that string. The function MUST NEVER read, hash, or encrypt the symlink target's content. Because symlinks are now recorded in the baseline at creation time, the create/delete asymmetry left by D31 is eliminated: a later deletion of the symlink is distinguishable as a real deletion rather than a spurious `file_deleted`. (D33 / RN-127)

#### Scenario: Symlink entry stores the readlink string and hashes it, not its target content
- **WHEN** `write_symlink_entry` records an in-scope symlink
- **THEN** the entry has `content_b64 = None`, `hash = sha256(os.readlink(path))`, and `symlink_target` equal to the `readlink` string, and no target content is read or encrypted

#### Scenario: Pre-existing baseline entries without symlink_target still parse
- **WHEN** `from_dict` parses a baseline entry serialized before this change (no `symlink_target` key)
- **THEN** it succeeds with `symlink_target` defaulting to `None`

#### Scenario: A symlink recorded at creation is not a spurious delete later
- **WHEN** an in-scope symlink previously written via `write_symlink_entry` is deleted
- **THEN** the baseline contains its entry, so the deletion is distinguished as a real deletion rather than a spurious `file_deleted`

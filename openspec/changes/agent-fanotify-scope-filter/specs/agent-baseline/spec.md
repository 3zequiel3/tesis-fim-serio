## ADDED Requirements

### Requirement: Baseline scan skips entries resolving outside the watch_path scope

During `init_scan` and `run_scan`, for every candidate discovered via `rglob`, the baseline engine SHALL resolve the candidate with `os.path.realpath()` and, when that real path is NOT `is_relative_to` the canonicalized `watch_path` being scanned, skip it with a `warning` log instead of encrypting it into the baseline. This prevents a symlink located inside a `watch_path` but pointing outside it (e.g. to `/root/.ssh`) from being encrypted as if it were in-scope content, enforcing RN-04 at baseline time. Containment MUST be evaluated against the canonicalized `watch_path`, consistent with the detector scope filter and with the D18/RN-116 pattern. (D31 / RN-125)

#### Scenario: In-scope file is baselined
- **WHEN** `init_scan` finds a regular file whose `os.path.realpath()` is relative to the canonicalized `watch_path`
- **THEN** the file is hashed and written to the baseline as usual

#### Scenario: Symlink escaping the watch_path is skipped with a warning
- **WHEN** `init_scan` finds a symlink inside a `watch_path` whose `os.path.realpath()` resolves outside the canonicalized `watch_path`
- **THEN** the entry is skipped with a warning log and its content is NOT encrypted into the baseline

#### Scenario: run_scan applies the same containment rule
- **WHEN** `run_scan` (rescan or newly added paths) encounters a candidate whose real path escapes the canonicalized `watch_path`
- **THEN** it is skipped with a warning, identically to `init_scan`

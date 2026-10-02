# Manifest regeneration note

`raw/services-before-teardown.jsonl` was modified after this lab wrote `SHA256SUMS`: when the lane evidence was copied into
`v10-closure-20260912T190052Z/lanes/`, the absolute home path was replaced with `[HOME]` (4 occurrences) as part of the
privacy sanitization. No other file changed. `SHA256SUMS` was regenerated on 2026-09-12 after that sanitization; the
lab results and criteria in `../CRITERIOS.md` are unchanged.

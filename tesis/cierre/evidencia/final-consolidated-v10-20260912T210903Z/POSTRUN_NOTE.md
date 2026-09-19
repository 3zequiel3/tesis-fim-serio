# Post-run adjustment of this package

The consolidation script (`freeze-and-validate-v10.sh`) wrote two files after its sanitize step and after
generating `SHA256SUMS`:

- `metadata/progress.txt` received its final `done:` line after the manifest was written, so its checksum no
  longer matched.
- `metadata/custody-verification.txt` was written after the sanitize step and contained the absolute home path.

Adjustment made on 2026-09-12 after the run finished: the home path in both files was replaced with `[HOME]`,
and `SHA256SUMS` was regenerated over the full package. No test result, exit code, coverage file, JUnit file or
custody artifact was modified. `results.json` (`overall_status: PASS`) is unchanged.

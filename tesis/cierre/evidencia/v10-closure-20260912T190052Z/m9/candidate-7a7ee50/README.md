# Component inventory of the V10 consolidated candidate

- Source: `custody/candidate-tree.tar.gz` of `final-consolidated-v10-20260912T210903Z` (commit 7a7ee5011d9234023687687ed95a7cdda9437711), extracted read-only.
- Tool: syft 1.51.1 from `anchore/syft@sha256:95fe0835e5bebc6f8b1f8acef68d47d63d594ef4c0f25c097ff853b23cbac74c` (same image as `../syft-image.txt`).
- Command: `syft scan dir:/src --exclude './**/node_modules/**' -o cyclonedx-json` and `-o spdx-json`.
- Result: CycloneDX 1.7 with 428 components; SPDX 2.3 with 425 packages. Versions come from lockfiles.
- Local inventory: not a certified SBOM and not evidence of binary reproducibility of images.

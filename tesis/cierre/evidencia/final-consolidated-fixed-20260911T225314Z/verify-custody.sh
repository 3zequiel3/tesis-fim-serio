#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
COMMIT=7df4935f769a2e393a5e6a6330df605c77592e52
TREE=95455f919ec602b6cddf1440341652d99b784bd3
BUNDLE_SHA=3b26d3301d5ad7def9ecb2723a71b73d88855e8250aa253e6657539b3a050a9c
ARCHIVE_SHA=1d3e8e731b6d802f7a0e5549a5f5ddd843dbd1a656ced735a3696311c3dc2f26
TMP=$(mktemp -d /tmp/fim-custody-verify-XXXXXX)
trap 'rm -rf "$TMP"' EXIT INT TERM
printf '%s  %s\n' "$BUNDLE_SHA" "$ROOT/custody/candidate.bundle" | sha256sum -c -
printf '%s  %s\n' "$ARCHIVE_SHA" "$ROOT/custody/candidate-tree.tar.gz" | sha256sum -c -
git bundle verify "$ROOT/custody/candidate.bundle"
git clone -q -b evidence-candidate "$ROOT/custody/candidate.bundle" "$TMP/recovered"
git -C "$TMP/recovered" checkout -q --detach "$COMMIT"
test "$(git -C "$TMP/recovered" cat-file -t "$COMMIT")" = commit
test "$(git -C "$TMP/recovered" rev-parse HEAD)" = "$COMMIT"
test "$(git -C "$TMP/recovered" rev-parse 'HEAD^{tree}')" = "$TREE"
test -z "$(git -C "$TMP/recovered" status --porcelain=v1)"
(cd "$TMP/recovered" && sha256sum -c "$ROOT/metadata/candidate-files.sha256" >/dev/null)
mkdir "$TMP/archive"
tar -xzf "$ROOT/custody/candidate-tree.tar.gz" -C "$TMP/archive"
(cd "$TMP/archive/candidate" && sha256sum -c "$ROOT/metadata/candidate-files.sha256" >/dev/null)
git -C "$TMP/recovered" archive --format=tar --prefix=candidate/ "$COMMIT" | gzip -n -9 > "$TMP/rebuilt.tar.gz"
cmp "$ROOT/custody/candidate-tree.tar.gz" "$TMP/rebuilt.tar.gz"
echo 'PASS: bundle/archive recovery, commit/tree identity, clean checkout, 813 file hashes, deterministic archive, cleanup trap'

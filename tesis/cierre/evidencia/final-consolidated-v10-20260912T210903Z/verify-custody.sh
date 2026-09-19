#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
COMMIT=7a7ee5011d9234023687687ed95a7cdda9437711
TREE=9e9e472bbdfc377674db5dec41224bcc15f48991
TMP=$(mktemp -d /tmp/fim-v10-custody-XXXXXX); trap 'rm -rf "$TMP"' EXIT INT TERM
git bundle verify "$ROOT/custody/candidate.bundle"
git clone -q -b evidence-candidate-v10 "$ROOT/custody/candidate.bundle" "$TMP/recovered"
git -C "$TMP/recovered" checkout -q --detach "$COMMIT"
test "$(git -C "$TMP/recovered" rev-parse 'HEAD^{tree}')" = "$TREE"
test -z "$(git -C "$TMP/recovered" status --porcelain=v1)"
(cd "$TMP/recovered" && sha256sum -c "$ROOT/metadata/candidate-files.sha256" >/dev/null)
mkdir "$TMP/archive"; tar -xzf "$ROOT/custody/candidate-tree.tar.gz" -C "$TMP/archive"
(cd "$TMP/archive/candidate" && sha256sum -c "$ROOT/metadata/candidate-files.sha256" >/dev/null)
git -C "$TMP/recovered" archive --format=tar --prefix=candidate/ "$COMMIT" | gzip -n -9 | cmp - "$ROOT/custody/candidate-tree.tar.gz"
echo "PASS: bundle and archive recovery, commit/tree identity, clean checkout, $(wc -l < "$ROOT/metadata/candidate-files.sha256") file hashes, deterministic archive"

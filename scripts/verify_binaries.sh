#!/bin/sh
# The binaries a release ships must be the ones sums/<variant>.sha256 publishes.
# A rebuild that differs means the pinned toolchain no longer reproduces them:
# investigate, then commit the new sums deliberately — never automatically.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VARIANT=${1:?usage: verify_binaries.sh <variant>}
SUMS="$ROOT/sums/$VARIANT.sha256"
test -f "$SUMS" || { echo "[FAIL] $SUMS is missing; build once and commit the sums" >&2; exit 2; }
cd "$ROOT/build/$VARIANT"
sha256sum -c "$SUMS"

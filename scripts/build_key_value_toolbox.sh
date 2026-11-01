#!/bin/sh
# Build the standalone Redis/Valkey extension; SQL variants remain independent.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
exec "$ROOT/key_value/scripts/build_toolbox.sh"

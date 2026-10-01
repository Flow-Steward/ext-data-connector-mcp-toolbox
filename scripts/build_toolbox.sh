#!/bin/sh
# Build Google MCP Toolbox for one variant, for every runtime target.
#
#   scripts/build_toolbox.sh <variant>      ->  build/<variant>/bin/<target>/toolbox
#
# The binary carries exactly the source and tool types the variant's prebuilt
# configurations use: they are read from Toolbox's own prebuilt YAML and mapped
# to the packages that register them, so a variant never ships drivers it cannot
# offer and never misses one it needs. Pinned source, Go image and build epoch
# make the result reproducible; scripts/verify_binaries.sh checks it.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VARIANT=${1:?usage: build_toolbox.sh <variant>}
TOOLBOX_TAG=v1.3.0
TOOLBOX_COMMIT=b0010060a939455d91e4f8ba62dc3e72b1892469
GO_IMAGE=golang:1.26.2-bookworm@sha256:47ce5636e9936b2c5cbf708925578ef386b4f8872aec74a67bd13a627d242b19
PATCH=scripts/patches/0001-flowsteward-driver-bound-query-params.patch
# Written by scripts/render_variant.py: the variant's prebuilts after the
# connector's runtime aliases (MariaDB runs on Toolbox's MySQL prebuilt).
test -f "$ROOT/build/$VARIANT/toolbox-prebuilts.txt" \
  || { echo "[FAIL] run scripts/render_variant.py $VARIANT first" >&2; exit 2; }
PREBUILTS=$(cat "$ROOT/build/$VARIANT/toolbox-prebuilts.txt")
mkdir -p "$ROOT/build/$VARIANT"

docker run --rm \
  -e TOOLBOX_TAG="$TOOLBOX_TAG" -e TOOLBOX_COMMIT="$TOOLBOX_COMMIT" -e PATCH="$PATCH" \
  -e PREBUILTS="$PREBUILTS" -e VARIANT="$VARIANT" \
  -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
  -v "$ROOT:/out" "$GO_IMAGE" sh -c '
    set -eu
    git clone --quiet --filter=blob:none --branch "$TOOLBOX_TAG" --depth 1 \
      https://github.com/googleapis/mcp-toolbox.git /src
    test "$(git -C /src rev-parse HEAD)" = "$TOOLBOX_COMMIT"
    cd /src
    git apply "/out/$PATCH"

    # Every resource type the prebuilt configurations name ...
    : > /tmp/types
    for prebuilt in $PREBUILTS; do
      file="internal/prebuiltconfigs/tools/$prebuilt.yaml"
      test -f "$file" || { echo "[FAIL] Toolbox $TOOLBOX_TAG has no prebuilt $prebuilt" >&2; exit 2; }
      sed -n "s/^type:[[:space:]]*\([a-z0-9-]*\).*/\1/p" "$file" >> /tmp/types
    done
    sort -u /tmp/types -o /tmp/types
    # ... mapped to the package that registers it.
    : > /tmp/packages
    while read -r type; do
      dir=$(grep -rlE "^const [A-Za-z]+ string = \"$type\"$" internal/sources internal/tools \
        | xargs -r -n1 dirname | sort -u)
      test "$(printf "%s\n" "$dir" | grep -c .)" = 1 \
        || { echo "[FAIL] type $type is registered by: ${dir:-nothing}" >&2; exit 2; }
      printf "github.com/googleapis/mcp-toolbox/%s\n" "$dir" >> /tmp/packages
    done < /tmp/types
    sort -u /tmp/packages -o /tmp/packages
    awk "NR==FNR { keep[\"\\\"\" \$0 \"\\\"\"] = 1; next }
         /internal\/(sources|tools)\// { if (keep[\$2]) print; next }
         { print }" /tmp/packages cmd/internal/imports.go > /tmp/imports.go
    test "$(grep -c "internal/\(sources\|tools\)/" /tmp/imports.go)" = "$(wc -l < /tmp/packages)" \
      || { echo "[FAIL] a needed package is not in cmd/internal/imports.go" >&2; exit 2; }
    mv /tmp/imports.go cmd/internal/imports.go
    echo "[PASS] $VARIANT: $(wc -l < /tmp/types) types from $(wc -l < /tmp/packages) packages for: $PREBUILTS"
    cp /tmp/packages "/out/build/$VARIANT/packages.txt"

    export SOURCE_DATE_EPOCH=1779400183
    for target in linux-amd64 linux-arm64; do
      arch=${target#linux-}
      mkdir -p "/out/build/$VARIANT/bin/$target"
      CGO_ENABLED=0 GOOS=linux GOARCH="$arch" go build -p 1 -trimpath -buildvcs=false \
        -ldflags "-s -w -buildid= -X github.com/googleapis/mcp-toolbox/cmd.buildType=flowsteward.dataset-connectors -X github.com/googleapis/mcp-toolbox/cmd.commitSha=$TOOLBOX_COMMIT" \
        -o "/out/build/$VARIANT/bin/$target/toolbox" .
      chmod 0755 "/out/build/$VARIANT/bin/$target/toolbox"
      echo "[PASS] $VARIANT $target: $(stat -c %s "/out/build/$VARIANT/bin/$target/toolbox") bytes"
    done
    chown -R "$HOST_UID:$HOST_GID" "/out/build/$VARIANT"
  '
